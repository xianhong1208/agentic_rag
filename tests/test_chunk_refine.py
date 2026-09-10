
"""BL-05 — chunk 記錄化(引用溯源)單元測試。

_refine_chunks_for_token_budget 從回 List[str] 改回 List[dict]
(``{"text", "headings", "page_no"}``),契約:
- 過大塊拆分:每段繼承源塊 meta
- 小塊合併:取 buffer 首塊 meta
- 裸字串輸入(fallback 路徑):meta 為 None
- leaf_splitter 把記錄的 headings/page_no 注入 leaf Document.metadata

tokenizer 用 1 char = 1 token 的假物件,不碰 HuggingFace。
"""

from types import SimpleNamespace

from src.domain.rag.docling_loader import (
    _chunk_provenance,
    _refine_chunks_for_token_budget,
)


class LenTokenizer:
    """1 字元 = 1 token(_count_tokens 走 encode(add_special_tokens=False))。"""

    def encode(self, text, add_special_tokens=False):
        return list(text)


def _mk_chunk(text, headings=None, page_no=None):
    """仿 docling HierarchicalChunker chunk 物件(meta.headings + doc_items.prov)。"""
    prov = [SimpleNamespace(page_no=page_no)] if page_no is not None else []
    doc_items = [SimpleNamespace(prov=prov)]
    return SimpleNamespace(
        text=text,
        meta=SimpleNamespace(headings=headings, doc_items=doc_items),
    )


TOK = LenTokenizer()


# ---- _chunk_provenance ------------------------------------------------------

class TestChunkProvenance:
    def test_bare_string_no_meta(self):
        assert _chunk_provenance("純字串") == {"headings": None, "page_no": None}

    def test_full_extraction(self):
        c = _mk_chunk("x", headings=["第一章", "1.1 節"], page_no=3)
        assert _chunk_provenance(c) == {"headings": ["第一章", "1.1 節"], "page_no": 3}

    def test_missing_fields_defensive(self):
        # meta 在但 headings 空、prov 空 → 全 None,不炸
        c = _mk_chunk("x", headings=[], page_no=None)
        assert _chunk_provenance(c) == {"headings": None, "page_no": None}

    def test_page_no_from_first_prov_only(self):
        # 多 doc_items:取第一個有 page_no 的
        c = SimpleNamespace(
            text="x",
            meta=SimpleNamespace(
                headings=None,
                doc_items=[
                    SimpleNamespace(prov=[]),
                    SimpleNamespace(prov=[SimpleNamespace(page_no=7),
                                          SimpleNamespace(page_no=8)]),
                ],
            ),
        )
        assert _chunk_provenance(c)["page_no"] == 7


# ---- _refine_chunks_for_token_budget(記錄化契約)---------------------------

class TestRefineRecords:
    def test_bare_strings_yield_none_meta(self):
        # fallback 切分路徑餵裸字串 → 記錄 meta 為 None
        out = _refine_chunks_for_token_budget(["a" * 15], TOK, max_tokens=20)
        assert out == [{"text": "a" * 15, "headings": None, "page_no": None}]

    def test_passthrough_keeps_meta(self):
        c = _mk_chunk("b" * 15, headings=["H"], page_no=2)
        out = _refine_chunks_for_token_budget([c], TOK, max_tokens=20)
        assert out == [{"text": "b" * 15, "headings": ["H"], "page_no": 2}]

    def test_oversized_split_inherits_meta(self):
        # 3 行 × 10 chars,budget 10 → 拆多段,每段都繼承源塊 meta
        text = "\n".join(["r" * 10] * 3)
        c = _mk_chunk(text, headings=["表格章"], page_no=5)
        out = _refine_chunks_for_token_budget([c], TOK, max_tokens=10)
        assert len(out) > 1
        for rec in out:
            assert rec["headings"] == ["表格章"]
            assert rec["page_no"] == 5
            assert len(rec["text"]) <= 10

    def test_merge_takes_first_chunk_meta(self):
        # 兩小塊(各 3 tokens < threshold 10)合併 → 取首塊 meta
        c1 = _mk_chunk("aaa", headings=["首章"], page_no=1)
        c2 = _mk_chunk("bbb", headings=["次章"], page_no=9)
        out = _refine_chunks_for_token_budget([c1, c2], TOK, max_tokens=20)
        assert out == [{"text": "aaa\nbbb", "headings": ["首章"], "page_no": 1}]

    def test_empty_text_skipped(self):
        out = _refine_chunks_for_token_budget(["   ", ""], TOK, max_tokens=20)
        assert out == []


# ---- leaf_splitter 注入 leaf metadata ---------------------------------------

class TestLeafSplitterProvenance:
    def _split(self, chunks):
        from llama_index.core import Document
        from src.domain.rag.leaf_splitter import LeafSplitter

        splitter = LeafSplitter(leaf_chunk_size=450, chunk_overlap=50)
        doc = Document(
            text="全文",
            metadata={"file_id": "f1", "file_name": "a.pdf",
                      "_docling_chunks": chunks},
        )
        return splitter.split_into_leaf_documents(doc)

    def test_dict_records_inject_provenance(self):
        leaves = self._split([
            {"text": "第一段內容", "headings": ["第一章"], "page_no": 2},
        ])
        assert len(leaves) == 1
        md = leaves[0].metadata
        assert md["headings"] == ["第一章"]
        assert md["page_no"] == 2
        assert md["file_id"] == "f1"  # 文件級 metadata 仍在

    def test_none_provenance_not_injected(self):
        # meta 為 None(音檔/裸字串)→ 不塞 key,不污染 node metadata
        leaves = self._split([
            {"text": "音檔轉錄段", "headings": None, "page_no": None},
            "裸字串段",
        ])
        assert len(leaves) == 2
        for leaf in leaves:
            assert "headings" not in leaf.metadata
            assert "page_no" not in leaf.metadata

    def test_empty_text_record_filtered(self):
        leaves = self._split([{"text": "  ", "headings": ["H"], "page_no": 1}])
        assert leaves == []
