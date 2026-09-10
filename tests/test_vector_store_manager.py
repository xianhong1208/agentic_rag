
"""M5 前置回歸測試 — VectorStoreManager 的物理表刪除 API。

背景:原本 DROP TABLE / DELETE chunk 的 raw SQL 散在 adapter(rag_maintenance /
folder),表名慣例 data_{folder_id}_{uuid} 被複製多份。M5 把它們收斂進
VectorStoreManager;這份測試先鎖住行為契約(表名、IF EXISTS / CASCADE、bind
param、錯誤吞掉不拋、cache 失效),重構才有安全網。

純 mock engine,零外部依賴(符合 ENVIRONMENTS.md 的單元測試原則)。
跑法:cd agentic_rag && uv run --no-sync pytest tests/test_vector_store_manager.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from src.domain.rag.vector_store_manager import VectorStoreManager

_VSM = "src.domain.rag.vector_store_manager"


def _mock_engine():
    """回傳 (engine, conn):engine.connect() 當 context manager 用,yield conn。"""
    conn = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    return engine, conn


# ---- physical_table_name(純函式,無需 instance)---------------------------

def test_physical_table_name_convention():
    """物理表名 = data_{folder_id}_{uuid} —— 這是全專案唯一的表名慣例來源。"""
    name = VectorStoreManager.physical_table_name(5, "abc-uuid")
    assert name == "data_5_abc-uuid"


# ---- drop_table --------------------------------------------------------------

@pytest.fixture()
def vsm():
    """建一個 VectorStoreManager,__init__ 需要 config → patch 掉。"""
    fake_cfg = MagicMock()
    fake_cfg.database.url = "postgresql://x/y"
    fake_cfg.database.port = 5432
    with patch(f"{_VSM}.Config.get_config_model", return_value=fake_cfg):
        return VectorStoreManager(embed_dim=1024)


def test_drop_table_issues_if_exists_cascade(vsm):
    """DROP 必帶 IF EXISTS(表可能不存在)+ CASCADE(連帶刪 HNSW 索引)+ commit。"""
    engine, conn = _mock_engine()
    with patch(f"{_VSM}.get_engine", return_value=engine):
        ok = vsm.drop_table(5, "abc-uuid")
    assert ok is True
    sql = str(conn.execute.call_args[0][0])
    assert 'DROP TABLE IF EXISTS "data_5_abc-uuid" CASCADE' in sql
    conn.commit.assert_called_once()


def test_drop_table_swallows_errors(vsm):
    """DDL 失敗只記 log、回 False,不得往上拋中斷刪除流程。"""
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("db down")
    with patch(f"{_VSM}.get_engine", return_value=engine):
        ok = vsm.drop_table(5, "abc-uuid")
    assert ok is False


def test_drop_table_invalidates_cache(vsm):
    """drop 後對應的 cache entry(key = {folder_id}_{uuid},無 data_ 前綴)要清掉,
    否則後續 get_or_create 會拿到指向已 DROP 表的 stale store。"""
    vsm._vector_stores["5_abc-uuid"] = MagicMock()
    engine, _ = _mock_engine()
    with patch(f"{_VSM}.get_engine", return_value=engine):
        vsm.drop_table(5, "abc-uuid")
    assert "5_abc-uuid" not in vsm._vector_stores


# ---- delete_chunks_by_file(@staticmethod)------------------------------------

def test_delete_chunks_by_file_uses_bind_param():
    """file_id 必須走 bind param(:file_id),不得 f-string 內插(注入面)。"""
    engine, conn = _mock_engine()
    conn.execute.return_value.rowcount = 3
    with patch(f"{_VSM}.get_engine", return_value=engine):
        n = VectorStoreManager.delete_chunks_by_file("data_5_abc-uuid", 42)
    assert n == 3
    args, kwargs = conn.execute.call_args
    sql = str(args[0])
    params = args[1]
    assert 'DELETE FROM "data_5_abc-uuid"' in sql
    assert ":file_id" in sql
    assert params == {"file_id": "42"}  # 以字串比對 metadata_ JSONB 值
    conn.commit.assert_called_once()


def test_delete_chunks_by_file_swallows_errors():
    """刪 chunk 失敗回 0、不拋(與現有 adapter 行為一致)。"""
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("boom")
    with patch(f"{_VSM}.get_engine", return_value=engine):
        n = VectorStoreManager.delete_chunks_by_file("data_5_abc-uuid", 42)
    assert n == 0
