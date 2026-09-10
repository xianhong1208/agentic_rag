
"""整合測試 — 索引 pipeline(chunk → hierarchy → embed → pgvector 寫入 → 讀回)。

M14 前置測試網第二塊。HierarchicalIndexer.index_document 是 God-object 拆分的
核心路徑,先把「編排與寫入正確性」釘死,拆分才有網:
- leaf/parent 都寫入物理表,file_id metadata 全對
- leaves 有真向量、parents 是零向量(query 靠 node_role 過濾)
- ChunkLookup.fetch_file_full 能按 chunk 順序拼回原文
- M5 的 delete_chunks_by_file 真庫版(mock 測過契約,這裡驗真行為)
- abort 語義:embed 前中止 → 表無殘留

embedding 用注入的 FakeEmbed(H6 的注入點)— 確定性向量、零外部依賴。
這裡測的是編排/寫入,不是 embedding 品質(拆分本來也不改後者)。
"""

import hashlib
import uuid

import pytest
from llama_index.core import Document

from src.domain.rag.hierarchical_indexer import HierarchicalIndexer, IndexingAbortedError
from src.domain.rag.chunk_lookup import ChunkLookup
from src.domain.rag.vector_store_manager import VectorStoreManager

_DIM = 1024


class FakeEmbed:
    """確定性 embedding:hash(text) 展開成 1024 維單位向量。零外部依賴。"""

    def get_text_embedding_batch(self, texts, **kwargs):
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [(h[i % 32] - 128) / 128.0 for i in range(_DIM)]
            out.append(vec)
        return out


_DOC_TEXT = "\n\n".join(
    f"## 章節 {i}\n這是第 {i} 段測試內容。混合中英文 content for chunking,"
    f"確保切出多個 leaf。" + "填充句。" * 30
    for i in range(1, 7)
)


@pytest.fixture()
def vsm(itest_db):
    return VectorStoreManager(embed_dim=_DIM)


@pytest.fixture()
def indexer(itest_db):
    return HierarchicalIndexer(
        leaf_chunk_size=128,
        parent_target_tokens=512,
        chunk_overlap=20,
        context_generator=None,   # LLM 步驟關閉 — 不在本網範圍
        embed_model=FakeEmbed(),  # H6 注入點
    )


def _doc(file_id: str) -> Document:
    return Document(
        text=_DOC_TEXT,
        metadata={"file_id": file_id, "file_name": "pipeline.md"},
    )


def _table_rows(vsm, folder, where: str = "", params=None):
    from sqlalchemy import text
    from db.db import get_engine
    table = vsm.physical_table_name(folder.id, folder.vector_table_uuid)
    with get_engine().connect() as conn:
        return conn.execute(
            text(f'SELECT metadata_ FROM "{table}" {where}'), params or {}
        ).fetchall()


async def test_index_document_writes_leaves_and_parents(vsm, indexer, folder, file_row):
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)

    result = await indexer.index_document(_doc(fid), store)

    assert result["leaves"] > 1, f"應切出多個 leaf,實得 {result}"
    assert result["parents"] >= 1
    rows = _table_rows(vsm, folder)
    assert len(rows) == result["leaves"] + result["parents"], "表 rows 應 = leaves + parents"
    # file_id metadata 全對(檔案級刪除 / read 模式都靠它)
    assert all(r[0].get("file_id") == fid for r in rows)
    roles = {r[0].get("node_role") for r in rows}
    assert roles == {"leaf", "parent"}


async def test_leaves_have_real_vectors_parents_zero(vsm, indexer, folder, file_row):
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)
    await indexer.index_document(_doc(fid), store)

    from sqlalchemy import text
    from db.db import get_engine
    table = vsm.physical_table_name(folder.id, folder.vector_table_uuid)
    with get_engine().connect() as conn:
        # pgvector 沒有逐元素聚合,直接比對「與零向量的 L2 距離」
        zero = "[" + ",".join(["0"] * _DIM) + "]"
        leaf_zero = conn.execute(text(
            f'SELECT count(*) FROM "{table}" '
            f"WHERE metadata_->>'node_role' = 'leaf' AND embedding <-> :z = 0"
        ), {"z": zero}).scalar()
        parent_nonzero = conn.execute(text(
            f'SELECT count(*) FROM "{table}" '
            f"WHERE metadata_->>'node_role' = 'parent' AND embedding <-> :z > 0"
        ), {"z": zero}).scalar()
    assert leaf_zero == 0, "leaf 不得是零向量(否則檢索全失效)"
    assert parent_nonzero == 0, "parent 應為零向量(query 靠 node_role 過濾)"


async def test_fetch_file_full_reassembles_content(vsm, indexer, folder, file_row):
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)
    await indexer.index_document(_doc(fid), store)

    full = ChunkLookup.fetch_file_full(vector_store=store, file_id=fid)
    assert full["chunk_count"] > 1
    assert not full["truncated"]
    # 首尾章節都在,且順序正確(chunk 依 index 排序拼接)
    assert "章節 1" in full["text"] and "章節 6" in full["text"]
    assert full["text"].index("章節 1") < full["text"].index("章節 6")


async def test_delete_chunks_by_file_real_db(vsm, indexer, folder, file_row):
    """M5 收斂的 delete_chunks_by_file:mock 版鎖了契約,這裡驗真庫行為。"""
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)
    result = await indexer.index_document(_doc(fid), store)
    total = result["leaves"] + result["parents"]

    table = vsm.physical_table_name(folder.id, folder.vector_table_uuid)
    deleted = VectorStoreManager.delete_chunks_by_file(table, fid)
    assert deleted == total, f"應刪掉該檔全部 {total} 個 node,實刪 {deleted}"
    assert _table_rows(vsm, folder) == []


async def test_abort_before_embed_leaves_no_residue(vsm, indexer, folder, file_row):
    """should_abort 在 embed 前觸發 → IndexingAbortedError,表無殘留寫入。"""
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)

    with pytest.raises(IndexingAbortedError):
        await indexer.index_document(_doc(fid), store, should_abort=lambda: True)

    # abort 早於 vector_store.add → PGVectorStore 懶建的物理表根本不會出現。
    # 「表不存在」= 最強的無殘留證明;若表在(其他路徑建過),再驗內容為空。
    from sqlalchemy.exc import ProgrammingError
    try:
        rows = _table_rows(vsm, folder, "WHERE metadata_->>'file_id' = :fid", {"fid": fid})
        assert rows == [], "abort 於寫入前 — 不得留任何 chunk"
    except ProgrammingError:
        pass  # UndefinedTable — 連表都沒建,零殘留


# ---------------------------------------------------------------------------
# E2E 可追溯性(BL-05 驗收的儲存面):真實檔案 → docling 切割(帶溯源)→
# 入庫 → 每條記錄可反查
# ---------------------------------------------------------------------------

async def test_e2e_traceability_real_md_to_store_and_back(
    vsm, indexer, folder, file_row, tmp_path
):
    """檔案輸入 → 切割 → 儲存 → 反查,全鏈斷言:

    1. 真 md(含章節)經真 docling chunker 切成記錄(headings 溯源)
    2. leaf_splitter 注入 metadata → index_document 入庫
    3. 每條 leaf 行:file_id / chunk_index / parent_node_id 齊全,md 行帶 headings
    4. 反查三向:node_id → fetch_node 取回該塊;parent 的 children_node_ids
       全部指向存在的 leaf;file_id → fetch_file_full 重組全文含哨兵
    """
    from docling.document_converter import DocumentConverter
    from docling.chunking import HierarchicalChunker
    from llama_index.core import Document as LIDocument

    from src.domain.rag.docling_loader import _refine_chunks_for_token_budget
    from src.domain.rag.leaf_splitter import LeafSplitter

    # -- 1. 真實檔案 → docling → chunk 記錄(與生產 docling_convert_once 同鏈)
    md = tmp_path / "trace.md"
    md.write_text(
        "# 追溯章\n\n哨兵內容SENTINEL 第一段。" + "內文填充。" * 40
        + "\n\n## 次章\n\n次章內容。" + "更多填充。" * 40,
        encoding="utf-8",
    )

    class _LenTok:
        def encode(self, text, add_special_tokens=False):
            return list(text)

    doc = DocumentConverter().convert(str(md)).document
    records = _refine_chunks_for_token_budget(
        list(HierarchicalChunker().chunk(doc)), _LenTok(), 200)
    assert any(r["headings"] for r in records), "docling 記錄應帶 headings"

    # -- 2. 生產切分鏈:leaf_splitter(_docling_chunks)→ index_document
    file_id = str(file_row.id)
    li_doc = LIDocument(
        text=doc.export_to_markdown(),
        metadata={"file_id": file_id, "file_name": "trace.md",
                  "_docling_chunks": records},
    )
    leaves = LeafSplitter(leaf_chunk_size=128, chunk_overlap=20)\
        .split_into_leaf_documents(li_doc)
    assert any("headings" in d.metadata for d in leaves)
    # ⚠️ split_into_leaf_documents 會 pop 掉 _docling_chunks(生產語義:
    # 一份 Document 只切一次)— 上面的中途斷言消耗了它,補回去再餵 indexer
    li_doc.metadata["_docling_chunks"] = records

    vector_store = vsm.get_or_create(folder.id, folder.vector_table_uuid)
    stats = await indexer.index_document(li_doc, vector_store)
    assert stats["leaves"] >= 2 and stats["parents"] >= 1

    # -- 3. 儲存記錄逐條斷言
    rows = _table_rows(vsm, folder)
    metas = [r[0] for r in rows]
    leaf_metas = [m for m in metas if m.get("node_role") == "leaf"]
    parent_metas = [m for m in metas if m.get("node_role") == "parent"]
    assert leaf_metas and parent_metas
    for m in leaf_metas:
        assert m.get("file_id") == file_id
        assert isinstance(m.get("chunk_index"), int)
        assert m.get("parent_node_id")  # 每條 leaf 都掛得到 parent
    assert any(m.get("headings") for m in leaf_metas), "溯源 headings 應入庫"

    # -- 4a. node_id 反查單塊
    from src.domain.rag.chunk_lookup import ChunkLookup
    from sqlalchemy import text as sql_text
    from db.db import get_engine
    table = vsm.physical_table_name(folder.id, folder.vector_table_uuid)
    with get_engine().connect() as conn:
        node_ids = [r[0] for r in conn.execute(sql_text(
            f'SELECT node_id FROM "{table}"')).fetchall()]
    for nid in node_ids:
        node = ChunkLookup.fetch_node(vector_store, nid)
        assert node is not None, f"node_id={nid} 反查不到"

    # -- 4b. parent ↔ children 雙向連結完整
    leaf_ids = {r[1] for r in _id_role_rows(vsm, folder) if r[0] == "leaf"}
    for pm in parent_metas:
        for child in pm.get("children_node_ids", []):
            assert child in leaf_ids, "parent 指向不存在的 leaf"

    # -- 4c. file_id 重組全文
    full = ChunkLookup.fetch_file_full(vector_store, file_id)
    assert "哨兵內容SENTINEL" in full["text"]


def _id_role_rows(vsm, folder):
    from sqlalchemy import text as sql_text
    from db.db import get_engine
    table = vsm.physical_table_name(folder.id, folder.vector_table_uuid)
    with get_engine().connect() as conn:
        return conn.execute(sql_text(
            f"SELECT metadata_->>'node_role', node_id FROM \"{table}\"")).fetchall()


async def test_reindex_same_file_purges_stale_chunks(vsm, indexer, folder, file_row):
    """C2 回歸:同一檔重跑 index_document,總 row 數不得倍增(寫入前冪等清舊)。

    情境:上次寫入成功但收尾失敗(timeout cancel / record 失敗 / gate 3)→
    檔案標 failed → 使用者重跑。舊行為:node id 每次 uuid4 重生 + PGVector
    不去重 → 第二份完整向量疊進同表。
    """
    store = vsm.get_or_create(folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))
    fid = str(file_row.id)

    r1 = await indexer.index_document(_doc(fid), store)
    n1 = len(_table_rows(vsm, folder))
    assert n1 == r1["leaves"] + r1["parents"]

    r2 = await indexer.index_document(_doc(fid), store)  # 模擬重跑
    n2 = len(_table_rows(vsm, folder))
    assert n2 == r2["leaves"] + r2["parents"], f"重跑後應等於單份({n2} vs {r2})"
    assert n2 == n1  # 不倍增
