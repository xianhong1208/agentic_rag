
"""Leaf Splitter — Document → leaf-sized chunks(M14 自 HierarchicalIndexer 拆出)。

兩條路徑(與拆出前完全一致,逐字搬移):
- Docling pre-parsed(metadata._docling_chunks)直接採用
- fallback:結構切分(表格 [TABLE_START] 保留)+ 同一套 token budget refine
"""

from __future__ import annotations

import re
from typing import List, Optional

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from src.log import get_api_logger
from src.domain.rag.document_loader import clean_text

logger = get_api_logger()

# 結尾為「空 code fence」的殘塊偵測:docling 對無法擷取內容的 code block / 圖片
# 會產出「[描述]\n\n```」這種只有標題/占位描述、正文為空的 chunk(實例見
# reports 診斷:『代碼區塊占位符』『占位符區塊,表示缺少實際內容』重複 10~12 次)。
# 這種 chunk 進 index 只會污染檢索(rerank 還會因標題字面命中把它評高分)。
_TRAILING_EMPTY_FENCE = re.compile(r"\n\s*```[a-zA-Z0-9_+-]*\s*$")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)
_STRUCT_CHARS = re.compile(r"[\s`#|>*_~\-→▪●·•]+")


def _is_low_value_chunk(text: str) -> bool:
    """判斷是否為無檢索價值的殘塊(空 code fence 占位符 / 純結構符)。

    規則(保守,寧可少殺):
    - 去零寬字元後,若『結尾是空 code fence』且『去掉該 fence 後的實質字元 < 40』
      → 判為 docling 空塊/占位符殘塊。
    - 去所有結構符後完全沒有實質字元 → 空塊。
    正常內容(有正文、或雖短但不以空 fence 結尾)一律保留。
    """
    t = (text or "").translate(_ZERO_WIDTH).strip()
    if not t:
        return True
    ended_empty_fence = bool(_TRAILING_EMPTY_FENCE.search(t))
    stripped = _TRAILING_EMPTY_FENCE.sub("", t).strip()
    body = _STRUCT_CHARS.sub("", stripped)
    if len(body) == 0:
        return True
    if ended_empty_fence and len(body) < 40:
        return True
    return False


class LeafSplitter:
    """切分器(HierarchicalIndexer 組合使用;邏輯自其 _structure_aware_split /
    _split_into_leaf_documents 逐字搬入)。"""

    def __init__(
        self,
        leaf_chunk_size: int,
        chunk_overlap: int,
        embedding_model_name: Optional[str] = None,
        has_context_generator: bool = False,
    ):
        self._leaf_chunk_size = leaf_chunk_size
        self._embedding_model_name = embedding_model_name
        self._has_context_generator = has_context_generator
        self._text_splitter = SentenceSplitter(
            chunk_size=leaf_chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def structure_aware_split(self, text: str) -> List[str]:
        """跟前一版 flat RAG 一致 — 表格保留,文字走 SentenceSplitter"""
        table_pattern = re.compile(
            r'\[TABLE_START\]\s*(.*?)\s*\[TABLE_END\]',
            re.DOTALL,
        )
        chunks = []
        last_end = 0
        for match in table_pattern.finditer(text):
            text_before = text[last_end:match.start()].strip()
            if text_before:
                chunks.extend(self._text_splitter.split_text(text_before))
            table_md = match.group(1).strip()
            if table_md:
                chunks.append(table_md)
            last_end = match.end()
        text_after = text[last_end:].strip()
        if text_after:
            chunks.extend(self._text_splitter.split_text(text_after))
        if not chunks:
            chunks = self._text_splitter.split_text(text)
        return [c for c in chunks if c.strip()]

    def split_into_leaf_documents(self, document: Document) -> List[Document]:
        """產出 leaf-sized Document list(Docling 解析優先,fallback SentenceSplitter)。

        Docling chunks 可能含 NUL (\\x00) 等控制字元(PDF 字型表 / ICC profile 來源),
        PostgreSQL 不接受,所以最後強制清洗。

        fallback 路徑(.txt/.csv/SimpleDirectoryReader)的結構切分後,
        會再過 docling 路徑同一套 `_refine_chunks_for_token_budget`:
        同一顆 embedding tokenizer 量 budget、表格 [TABLE_START] 巨塊
        token-bounded 切分 + 表頭重複、小塊 merge — 兩條路徑保證一致。

        Args:
            document: 已 load 的完整 Document(metadata 內可能藏 `_docling_chunks`)。

        Returns:
            leaf Document list,空 chunks 已過濾、控制字元已清。
        """
        pre_parsed = document.metadata.pop("_docling_chunks", None)
        if pre_parsed:
            chunk_texts = pre_parsed
        else:
            chunk_texts = self.structure_aware_split(clean_text(document.text))
            # 統一 token budget 保證(與 DocumentLoader 的 docling 路徑同公式)
            try:
                from src.domain.rag.docling_loader import (
                    get_hf_tokenizer,
                    _refine_chunks_for_token_budget,
                )
                hf_tok = get_hf_tokenizer(self._embedding_model_name)
                budget = min(
                    self._leaf_chunk_size, 380 if self._has_context_generator else 450
                )
                chunk_texts = _refine_chunks_for_token_budget(chunk_texts, hf_tok, budget)
            except Exception as e:
                # tokenizer 不可得時降級為結構切分結果(舊行為),不擋索引
                logger.warning(
                    f"Token-budget refine unavailable for fallback split "
                    f"(degrading to structure-only): {e}"
                )

        leaf_docs: List[Document] = []
        seen_texts: set = set()  # 同一文件內去重(占位符殘塊常重複 10+ 次)
        dropped_lowvalue = 0
        dropped_dup = 0
        for item in chunk_texts:
            # BL-05: chunk 可為記錄 dict({"text","headings","page_no"},docling
            # 路徑帶引用溯源)或裸字串(audio / 舊資料)— 兩者皆收
            if isinstance(item, dict):
                text = item.get("text", "")
                provenance = {
                    k: item[k] for k in ("headings", "page_no")
                    if item.get(k) is not None
                }
            else:
                text, provenance = item, {}
            # 強制清洗 — 不論來源都要過,Docling pre-parsed 路徑特別容易帶 NUL
            text = clean_text(text)
            if not text.strip():
                continue
            # 品質守門:丟掉空 code fence 占位符 / 純結構殘塊(污染檢索)
            if _is_low_value_chunk(text):
                dropped_lowvalue += 1
                continue
            # 同文件去重:占位符殘塊常一字不差重複多次,只留一顆
            key = text.strip()
            if key in seen_texts:
                dropped_dup += 1
                continue
            seen_texts.add(key)
            leaf_docs.append(Document(
                text=text,
                metadata={
                    **{k: v for k, v in document.metadata.items() if v is not None},
                    **provenance,  # per-chunk 引用欄位(hierarchy 會原樣併進 leaf node)
                },
            ))
        if dropped_lowvalue or dropped_dup:
            logger.info(
                f"[LEAF_QUALITY] kept {len(leaf_docs)} leaf chunks; "
                f"dropped {dropped_lowvalue} low-value + {dropped_dup} duplicate")
        return leaf_docs
