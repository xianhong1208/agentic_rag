
"""整合測試基座 — 真實 PostgreSQL(一次性庫,自建自毀)。

原則(對齊 docs/testing/ENVIRONMENTS.md):
- 單元測試(tests/test_*.py)零外部依賴,這裡是**整合層**:需要真 DB。
- **opt-in**:必須設 RAG_RUN_DB_ITESTS=1 才會跑,否則整組 skip。刻意不用
  「探測到 DB 就跑」— 那會讓任何碰巧有同憑證 postgres 的機器(如 CI agent)
  被擅自建庫/刪庫。跑法:RAG_RUN_DB_ITESTS=1 uv run --no-sync pytest tests/integration
- 設了 env 但 DB 不可達 → 一樣 skip(不紅)。
- 絕不碰現有庫:每次建全新 agentic_rag_itest,跑 alembic 全鏈建 schema
  (順帶每輪都重驗 migration 鏈),測畢 DROP。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

_ITEST_DB = "agentic_rag_itest"
_REPO = Path(__file__).resolve().parents[2]
_TMP_CONFIG = _REPO / "config" / "_itest_config.yaml"


def _base_url():
    """從 config/config.yaml 取連線資訊(dbname 之外的部分)。"""
    text = (_REPO / "config" / "config.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("url:"):
            return make_url(line.split(":", 1)[1].strip().strip('"'))
    raise RuntimeError("config.yaml 沒有 database url")


def _admin_conn():
    """連 postgres 管理庫(短 timeout;失敗 → skip 整組整合測試)。"""
    import psycopg2
    u = _base_url()
    return psycopg2.connect(
        host=u.host or "localhost", port=u.port or 5432,
        user=u.username, password=u.password,
        dbname="postgres", connect_timeout=2,
    )


def _db_available() -> bool:
    try:
        conn = _admin_conn()
        conn.close()
        return True
    except Exception:
        return False


if os.getenv("RAG_RUN_DB_ITESTS") != "1":
    pytest.skip(
        "整合測試需顯式 opt-in:RAG_RUN_DB_ITESTS=1(防止在碰巧有 postgres 的機器上擅自建庫)",
        allow_module_level=True,
    )

if not _db_available():
    pytest.skip(
        "PostgreSQL 不可達 — 跳過整合測試(單元測試不受影響)",
        allow_module_level=True,
    )


@pytest.fixture(scope="session")
def itest_db():
    """一次性整合測試庫:建庫 → alembic 全鏈 → yield → DROP。"""
    # 1. 重建全新庫
    conn = _admin_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS {_ITEST_DB}')
        cur.execute(f'CREATE DATABASE {_ITEST_DB}')
    conn.close()

    # 1b. 裝 extension(pgvector 寫入 + jiebacfg hybrid search 需要)
    import psycopg2
    u = _base_url()
    econn = psycopg2.connect(
        host=u.host or "localhost", port=u.port or 5432,
        user=u.username, password=u.password,
        dbname=_ITEST_DB, connect_timeout=2,
    )
    econn.autocommit = True
    with econn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_jieba")  # jiebacfg 全文檢索
        except Exception:
            pass  # 沒裝 pg_jieba 的實例:hybrid 相關測試自行 skip
    econn.close()

    # 2. 臨時 config(config 路徑安全檢查要求在 repo 內)指向一次性庫
    src = (_REPO / "config" / "config.yaml").read_text(encoding="utf-8")
    u = _base_url()
    old_db = u.database
    _TMP_CONFIG.write_text(src.replace(f"/{old_db}", f"/{_ITEST_DB}"), encoding="utf-8")

    from src.config.config_manager import Config
    Config.set_config(str(_TMP_CONFIG))

    # 3. alembic 全鏈建 schema(每輪整合測試都重驗 migration 鏈)
    from db.migrate import DatabaseMigrator
    assert DatabaseMigrator().upgrade("head"), "alembic 全鏈套用失敗"

    # 4. 綁 Session factory(get_engine 內部才做 Session.configure(bind=...);
    #    migrator 用自己的 engine,不觸發這步)
    from db.db import get_engine
    get_engine()

    yield _ITEST_DB

    # 4. 清理:先斷 SQLAlchemy 連線池,才 DROP 得掉
    try:
        import db.db as dbdb
        if getattr(dbdb, "_engine", None) is not None:
            dbdb._engine.dispose()
    except Exception:
        pass
    conn = _admin_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS {_ITEST_DB} WITH (FORCE)')
    conn.close()
    _TMP_CONFIG.unlink(missing_ok=True)


# ---- 共用資料 fixture(FileIndex 有 FK:先 Folder 再 File)---------------------

@pytest.fixture()
def folder(itest_db):
    """每案一個乾淨 folder(名稱唯一,避免案間互擾)。"""
    import uuid as _uuid
    from db.folderdb import FolderDB
    return FolderDB.create(
        name=f"itest-{_uuid.uuid4().hex[:8]}",
        description="integration test folder",
        user_token="itest-token",
    )


@pytest.fixture()
def file_row(itest_db, folder):
    import uuid as _uuid
    from db.filedb import FileDB
    return FileDB.create(
        folder_id=folder.id,
        file_name="doc.pdf",
        file_path=f"/tmp/itest/{_uuid.uuid4().hex}",
        file_size=1234,
        mime_type="application/pdf",
    )
