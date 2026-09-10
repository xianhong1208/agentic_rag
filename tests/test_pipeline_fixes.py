
"""2026-09-07 管線審查修復的回歸網(C1/C2/H1/H3/H4/M3/M4)。

出處:全鏈審查(上傳→解析→CR→embed→存→reindex→delete)發現的真缺陷。
每個測試名對應審查編號,倒退 = 舊缺陷復活。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core import Document


class TestM3EmbeddingBatchMismatch:
    async def test_short_batch_raises_not_silently_truncates(self):
        from src.domain.rag.embedding.batch_exec import _embed_batch_with_retry
        embed = MagicMock()
        embed.get_text_embedding_batch.return_value = [[0.1]] * 2  # 少一筆
        with pytest.raises(ValueError, match="mismatch"):
            await _embed_batch_with_retry(embed, ["a", "b", "c"], "f.pdf", 0, 3, 3)

    async def test_exact_batch_passes(self):
        from src.domain.rag.embedding.batch_exec import _embed_batch_with_retry
        embed = MagicMock()
        embed.get_text_embedding_batch.return_value = [[0.1]] * 3
        out = await _embed_batch_with_retry(embed, ["a", "b", "c"], "f.pdf", 0, 3, 3)
        assert len(out) == 3


class TestM4EmptyDocumentFails:
    async def test_zero_chunks_raises_instead_of_indexed_zero(self):
        from src.domain.rag.hierarchical_indexer import HierarchicalIndexer
        indexer = HierarchicalIndexer(embed_model=MagicMock())
        doc = Document(text="   \n\t  ", metadata={"file_id": "f1", "file_name": "empty.txt"})
        with pytest.raises(ValueError, match="0 chunks"):
            await indexer.index_document(doc, MagicMock())


class TestH1LeafFilterInRestQuery:
    async def test_parent_nodes_filtered_out(self):
        from src.domain.rag.query_engine import QueryEngine
        with patch("src.domain.rag.query_engine.VectorStoreIndex") as VSI:
            VSI.from_vector_store.return_value = MagicMock()
            qe = QueryEngine(vector_store=MagicMock(), similarity_cutoff=0.0)

        def node(role, text, nid):
            n = MagicMock()
            n.node.metadata = {"node_role": role} if role else {}
            n.metadata = {"file_id": "f", "file_name": "x", "folder_name": None}
            n.node.node_id = nid  # 各節點唯一 id(RRF 依 node_id 去重)
            n.text = text; n.score = 0.9
            return n

        # 每次呼叫 aretrieve 回一份新 hits(RRF 路徑會分別檢索 dense+sparse)
        def _hits():
            return [node("leaf", "L1", "00000000-0000-0000-0000-000000000001"),
                    node("parent", "P-superset", "00000000-0000-0000-0000-000000000002"),
                    node(None, "legacy", "00000000-0000-0000-0000-000000000003")]
        with patch("src.domain.rag.query_engine.VectorIndexRetriever") as R:
            R.return_value.aretrieve = AsyncMock(side_effect=lambda *a, **k: _hits())
            results = await qe.aquery("q")
        texts = [r.text for r in results]
        assert "P-superset" not in texts          # parent 濾掉
        assert "L1" in texts and "legacy" in texts  # legacy 無 node_role 視為 leaf


class TestH4ForceBypass:
    async def test_endpoint_passes_force_to_adapter(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api.router import rag_indexing as ri
        app = FastAPI()
        app.include_router(ri.router)
        from src.api.dependencies.auth import extract_token
        app.dependency_overrides[extract_token] = lambda: "tok"
        app.dependency_overrides[ri.get_file_by_id] = lambda: SimpleNamespace(
            id="9e68c18e-3209-44d3-b7e9-2211b3660d66", file_name="a.pdf",
            file_path="p", folder_id=1, mime_type="x", file_size=1, content_hash="h")
        # router 掛了 authenticate_request(router-level)→ 一併 override
        from src.auth.dependencies import authenticate_request
        app.dependency_overrides[authenticate_request] = lambda: None
        adapter = MagicMock()
        _resp = {"file_id": "9e68c18e-3209-44d3-b7e9-2211b3660d66", "index_id": "i",
                 "num_chunks": 3, "status": "indexed", "indexed_at": "", "message": "ok"}
        adapter.index_document = AsyncMock(
            return_value=SimpleNamespace(model_dump=lambda: dict(_resp), num_chunks=3))
        with patch.object(ri, "get_rag_adapter", return_value=adapter):
            r = TestClient(app).post(
                "/file/9e68c18e-3209-44d3-b7e9-2211b3660d66/index?force=true", json={})
        assert r.status_code == 200
        assert adapter.index_document.await_args.kwargs["force"] is True


class TestC1ReindexIntegrity:
    async def test_delete_failure_aborts_reindex(self):
        """刪索引失敗 → endpoint 必須 500 中止,不得啟動 job(舊行為:warn 後照跑)。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api.router import rag_indexing as ri
        app = FastAPI()
        app.include_router(ri.router)
        from src.api.dependencies.auth import extract_token
        from src.auth.dependencies import authenticate_request
        app.dependency_overrides[extract_token] = lambda: "tok"
        app.dependency_overrides[authenticate_request] = lambda: None
        app.dependency_overrides[ri.get_folder_by_id] = lambda: SimpleNamespace(
            id=7, name="f", vector_table_uuid="u")
        adapter = MagicMock()
        adapter.delete_folder_index = AsyncMock(side_effect=ValueError("db down"))
        with patch.object(ri, "get_rag_adapter", return_value=adapter), \
             patch.object(ri.job_manager, "start_indexing", new=AsyncMock()) as start:
            r = TestClient(app).post("/files/7/reindex", json={})
        assert r.status_code == 500
        assert "aborted" in r.json()["detail"]
        start.assert_not_awaited()  # 索引未清成功,絕不能起 job

    def test_maintenance_drop_failure_raises(self):
        """DROP 失敗必 raise(舊行為只 log)— 防止舊向量表 + 無 FileIndex 疊寫。"""
        import inspect
        from src.adapter import rag_maintenance
        src = inspect.getsource(rag_maintenance)
        assert "raise ValueError" in src and "Failed to drop vector table" in src
        # 順序:刪 rows 在 DROP 之前(致命態防護)
        assert src.index("delete_indices_for_folder") < src.index("drop_table(")


class TestH4ForceRealPath:
    """回歸(2026-09-07 用戶 log):force 只加在外層簽名、hash 檢查在
    _index_document_locked → NameError 讓整夾檔案全標 failed。
    此測試**真的執行**到 hash 檢查行,scope 斷裂會當場炸。"""

    def _svc(self):
        from src.adapter.rag_indexing import RAGIndexingService
        ctx = MagicMock()
        return RAGIndexingService(ctx), ctx

    def _file(self):
        return SimpleNamespace(
            id="9e68c18e-3209-44d3-b7e9-2211b3660d66", file_name="a.pdf",
            file_path="p", folder_id=1, mime_type="x", file_size=1,
            content_hash="same-hash")

    async def test_hash_shortcircuit_line_executes_without_nameerror(self):
        svc, ctx = self._svc()
        existing = SimpleNamespace(status="indexed", content_hash="same-hash",
                                   folder_id=1, num_chunks=5,
                                   index_id="i", indexed_at=None)
        async def fake_run_db(fn, *a, **k):
            name = getattr(fn, "__name__", "")
            if name == "_file_still_exists" or "still_exists" in name:
                return True
            return existing  # get_index_for_file
        with patch("src.adapter.rag_indexing._run_db", side_effect=fake_run_db):
            r = await svc._index_document_locked(file_record=self._file(), token="t")
        assert r.status == "already_indexed_same_content"

    async def test_force_bypasses_shortcircuit(self):
        svc, ctx = self._svc()
        existing = SimpleNamespace(status="indexed", content_hash="same-hash",
                                   folder_id=1, num_chunks=5,
                                   index_id="i", indexed_at=None)
        calls = {"n": 0}
        async def fake_run_db(fn, *a, **k):
            calls["n"] += 1
            name = getattr(fn, "__name__", "")
            if "still_exists" in name:
                return True
            if calls["n"] <= 3:
                return existing
            raise RuntimeError("proceeded-past-shortcircuit")  # 走過短路即達成目的
        with patch("src.adapter.rag_indexing._run_db", side_effect=fake_run_db):
            with pytest.raises(Exception):
                await svc._index_document_locked(
                    file_record=self._file(), token="t", force=True)
        # force=True 不得回 already_indexed(上面若短路會 return 而非 raise)
