
"""Document Loader — 檔案 → llama_index Document 的三路載入(M14 自 HierarchicalIndexer 拆出)。

三條路徑(與拆出前完全一致,逐字搬移):
1. 純文字家族(.txt/.json/.csv/...):read_text_robust 編碼容錯直讀,不經 docling
2. docling 支援格式:docling_convert_once(音檔先裁靜音、後過 Whisper 幻覺過濾)
3. fallback:SimpleDirectoryReader

⚠️ import 時序(M12):本模組頂部 import audio_defense — whisper 反幻覺 patch
在 import 時套用,必須先於 docling get_converter()。原鏈 adapter →
hierarchical_indexer → audio_defense;拆分後 hierarchical_indexer 頂部 import
本模組,鏈變 … → hierarchical_indexer → document_loader → audio_defense,
時序保證不變。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from llama_index.core import Document, SimpleDirectoryReader

from src.log import get_api_logger
from src.domain.rag.docling_loader import (
    is_docling_supported,
    docling_convert_once,
)
from src.domain.rag.asr_provider import AsrProvider, create_asr_provider
from src.domain.rag.audio_defense import (
    _AUDIO_TRIM_EXTENSIONS,
    _filter_whisper_hallucinations,
    _trim_audio_leading_silence,
)
from src.storage.file_storage import FileStorage

logger = get_api_logger()


def clean_text(text: str) -> str:
    """清掉 NUL 與控制字元(PostgreSQL 不接受;PDF 字型表 / ICC profile 常見來源)。"""
    if not text:
        return text
    cleaned = text.replace('\x00', '')
    cleaned = ''.join(
        char for char in cleaned
        if char in ('\n', '\t', '\r') or ord(char) >= 32
    )
    return cleaned


class DocumentLoader:
    """檔案載入器(HierarchicalIndexer 組合使用;邏輯自其 load_document_from_file 逐字搬入)。"""

    def __init__(
        self,
        leaf_chunk_size: int,
        embedding_model_name: Optional[str] = None,
        has_context_generator: bool = False,
        asr_provider: Optional[AsrProvider] = None,
        asr_enabled: bool = True,
    ):
        self._leaf_chunk_size = leaf_chunk_size
        self._embedding_model_name = embedding_model_name
        # 只影響 docling_max_tokens 公式(contextual prefix 佔 token 預算)
        self._has_context_generator = has_context_generator
        # BL-07: 音檔轉錄走注入的 provider(H6 同模式);未注入 → default
        # docling-whisper(available() 沿用舊 auto-discover 語義,零行為變化)
        self._asr_provider = asr_provider or create_asr_provider(None)
        self._asr_enabled = asr_enabled

    def load(
        self,
        file_path: str,
        file_id: str,
        file_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[Callable[[str, Optional[int], Optional[int]], None]] = None,
    ) -> Document:
        """跟前一版 flat RAG 的 load_document_from_file 行為一致 — 沿用既定流程

        progress_cb: 頁級解析進度 ``("loading", done, total)``(PDF/OCR 用,
        可選)— 大掃描檔終於能顯示「解析文件 12/161」而不是乾等。
        """
        # 純文字家族:直讀(read_text_robust 容錯編碼),不經 docling
        text_extensions = {
            '.txt', '.text', '.json', '.csv',
            '.yaml', '.yml', '.xml', '.conf', '.log',
        }
        file_extension = Path(file_name).suffix.lower()

        # DB 存的是 `storage/...` 相對字串。直接 open() 會吃 cwd,跟 save_file
        # 的 _PROJECT_ROOT-anchored 寫入對不上 → ENOENT。一律走 FileStorage 解析。
        resolved_path = str(FileStorage.resolve_path(file_path))

        base_metadata: Dict[str, Any] = {
            "file_id": str(file_id),
            "file_name": file_name,
            "file_path": file_path,  # 保留 DB 相對字串,給 metadata 消費者
        }
        if metadata:
            base_metadata.update({k: v for k, v in metadata.items() if v is not None})

        doc_id = f"file_{file_id}"

        if file_extension in text_extensions:
            # 編碼容錯:UTF-16(Windows 記事本「Unicode」)/ Big5 的 txt·csv
            # 實務常見,寫死 utf-8 會 UnicodeDecodeError 直接索引失敗。
            # 無法辨識時 read_text_robust 會 raise 帶處置指引的 ValueError
            # (進 FileIndex.error_message),不靜默索引亂碼。
            from src.utils.text_io import read_text_robust
            content = clean_text(read_text_robust(resolved_path, file_name))
            return Document(text=content, metadata=base_metadata, doc_id=doc_id)

        # BL-07: 音檔走注入的 AsrProvider(trim → transcribe → 幻覺過濾)。
        # config 選定的 provider 就是**唯一**語音來源:不可服務(權重/端點
        # 未就緒)→ 明確報錯讓檔案標 failed(帶可行動訊息),絕不靜默改走
        # 別的模型或不轉錄。只有 rag.asr.enabled=false 才是「明確不轉錄」。
        if file_extension in _AUDIO_TRIM_EXTENSIONS and self._asr_enabled:
            if not self._asr_provider.available():
                raise RuntimeError(
                    f"rag.asr provider 不可用(權重/端點未就緒),{file_name} 無法轉錄 — "
                    "檢查 assets/ 權重或 rag.asr 設定;確定不轉錄音檔請設 rag.asr.enabled=false"
                )
            return self._load_audio(
                resolved_path=resolved_path,
                file_name=file_name,
                base_metadata=base_metadata,
                doc_id=doc_id,
                progress_cb=progress_cb,
            )

        if is_docling_supported(file_name):
            docling_max_tokens = min(
                self._leaf_chunk_size, 380 if self._has_context_generator else 450
            )
            full_text, chunk_texts = docling_convert_once(
                file_path=resolved_path,
                file_name=file_name,
                max_tokens=docling_max_tokens,
                tokenizer=self._embedding_model_name,
                progress_cb=progress_cb,
            )
            content = clean_text(full_text)
            if not content.strip():
                raise ValueError(f"Empty content extracted from {file_name}")

            doc = Document(text=content, metadata=base_metadata, doc_id=doc_id)
            doc.metadata["_docling_chunks"] = chunk_texts
            return doc

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = Path(temp_dir) / file_name
            shutil.copy2(resolved_path, temp_file_path)
            return self._load_via_simple_reader(
                temp_dir, file_name, base_metadata, doc_id)

    def _load_via_simple_reader(self, temp_dir, file_name, base_metadata, doc_id) -> Document:
        reader = SimpleDirectoryReader(
            input_dir=temp_dir,
            filename_as_id=True,
            recursive=False,
        )
        docs = reader.load_data()
        if not docs:
            raise ValueError(f"No content extracted from {file_name}")
        original = docs[0]
        cleaned = clean_text(original.text)
        merged_meta = {**original.metadata, **base_metadata}
        return Document(text=cleaned, metadata=merged_meta, doc_id=doc_id)

    def _load_audio(
        self, *, resolved_path: str, file_name: str,
        base_metadata: Dict[str, Any], doc_id: str,
        progress_cb: Optional[Callable[[str, Optional[int], Optional[int]], None]] = None,
    ) -> Document:
        """音檔:前導靜音裁切 → AsrProvider 轉錄 → Whisper 幻覺過濾 → Document。

        裁切/過濾是模型無關的前後處理(audio_defense),刻意留在 provider 外層 —
        換任何 provider 都保留這兩道防禦。語義與拆出前逐點一致(BL-07 零行為)。
        """
        docling_max_tokens = min(
            self._leaf_chunk_size, 380 if self._has_context_generator else 450
        )

        # 1. Trim leading silence(失敗 fallback 原檔,不擋轉錄)
        effective_path = resolved_path
        trimmed_temp: Optional[str] = None
        try:
            trimmed_temp = _trim_audio_leading_silence(resolved_path, file_name)
            if trimmed_temp:
                effective_path = trimmed_temp
        except Exception as e:
            logger.warning(f"Audio trim failed for {file_name}, using original: {e}")
            trimmed_temp = None

        try:
            # 2. Transcribe(provider 失敗原樣 raise → 既有失敗路徑寫 failed tag)
            result = self._asr_provider.transcribe(
                audio_path=effective_path,
                file_name=file_name,
                max_tokens=docling_max_tokens,
                tokenizer=self._embedding_model_name,
                progress_cb=progress_cb,
            )
            full_text = result.text
            chunk_texts = result.chunks

            # 3. Strip known Whisper hallucinations
            full_text, n_full = _filter_whisper_hallucinations(full_text)
            n_chunks = 0
            if chunk_texts is not None:
                cleaned_chunks = []
                for c in chunk_texts:
                    cleaned, n = _filter_whisper_hallucinations(c)
                    cleaned_chunks.append(cleaned)
                    n_chunks += n
                chunk_texts = cleaned_chunks
            if n_full or n_chunks:
                logger.info(
                    f"Filtered Whisper hallucinations from {file_name}: "
                    f"{n_full} matches in full text, {n_chunks} across chunks"
                )

            content = clean_text(full_text)
            if not content.strip():
                raise ValueError(f"Empty content extracted from {file_name}")

            doc = Document(text=content, metadata=base_metadata, doc_id=doc_id)
            if chunk_texts is not None:
                # docling provider 有預切 chunks;雲端 None → leaf_splitter 純文字路徑
                doc.metadata["_docling_chunks"] = chunk_texts
            return doc
        finally:
            if trimmed_temp:
                Path(trimmed_temp).unlink(missing_ok=True)
