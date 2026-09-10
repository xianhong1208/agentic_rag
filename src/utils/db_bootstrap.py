
"""DB Bootstrap — 確保目標 DB 存在 + extensions 啟用

此模組由 main.py 啟動流程呼叫,**先於 Alembic migration**。
解決雞生蛋問題:CREATE DATABASE 不能在自己內部跑,必須連到 postgres 預設 DB。

流程:
1. 查 pg_database 確認目標 DB 存在(參數化查詢)
2. 不存在 → 連 postgres 預設 DB → CREATE DATABASE(dbname 過白名單 + 跳脫)
3. 連到目標 DB → CREATE EXTENSION IF NOT EXISTS (pgvector / pg_jieba)

安全設計(對齊 MCP_Center a46a4b8 的定案模式,sink 與 proven-clean 的
coreagent 一致):
- 全程 SQLAlchemy,不直接使用 psycopg2 — 憑證由 make_url 處理(含特殊
  字元),密碼永遠不從 URL 拆出、不落任何 dict/kwargs,程式碼中不存在
  憑證中間持有點(Checkmarx: Use Of Hardcoded Password / Insufficiently
  Protected Credentials)。
- CREATE DATABASE 的 identifier 不能 bind param,以 _validate_dbname
  白名單 + SQL 標準雙引號跳脫雙保險(Checkmarx: Second-Order SQL Injection)。
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

# Postgres 識別字上限 63 bytes(NAMEDATALEN-1),超過會被靜默截斷。
_MAX_IDENTIFIER_BYTES = 63

# dbname 白名單 — 啟動時對 DATABASE_URL 做 fail-fast 檢查。
# 注意這是設定健全性檢查兼縱深防禦:CREATE DATABASE 前另有 `"` 加倍跳脫。
_DBNAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$-]*")


def _validate_dbname(dbname: str) -> str:
    """驗證從 DATABASE_URL 解析出來的 dbname,不合法就 raise ValueError。"""
    if not _DBNAME_RE.fullmatch(dbname):
        raise ValueError(
            f"DATABASE_URL 的資料庫名稱不合法: {dbname!r}。"
            f"只允許字母/數字/底線/連字號/$,且須以字母或底線開頭"
        )
    if len(dbname.encode("utf-8")) > _MAX_IDENTIFIER_BYTES:
        raise ValueError(
            f"DATABASE_URL 的資料庫名稱超過 Postgres 上限 "
            f"{_MAX_IDENTIFIER_BYTES} bytes(會被靜默截斷): {dbname!r}"
        )
    return dbname


def _ensure_database_exists(db_url: str, logger) -> None:
    """目標 DB 不存在就建(冪等,含並發競態處理)。

    連 postgres 系統 DB 才能 CREATE DATABASE。make_url 安全處理帳密特殊
    字元並把目標 dbname 換成 postgres;AUTOCOMMIT 因 CREATE DATABASE 不能
    在 transaction 內執行。
    """
    target_dbname = _validate_dbname(make_url(db_url).database or "")

    admin_url = make_url(db_url).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target_dbname},
            ).scalar()
            if exists:
                logger.info(f"✅ Database '{target_dbname}' exists")
                return

            logger.warning(f"⚠️ Database '{target_dbname}' not found, creating...")
            # identifier 不能 bind param。SQL 標準跳脫:雙引號括住、內嵌 " 加倍;
            # dbname 另已過 _validate_dbname 白名單(根本不含 "),此為 defense-in-depth
            safe_name = target_dbname.replace('"', '""')
            conn.execute(text(f'CREATE DATABASE "{safe_name}"'))
            logger.info(f"✅ Database '{target_dbname}' created")
    except ProgrammingError as e:
        # 並發下另一個 process 先建好(duplicate_database)→ 視同成功
        if "already exists" in str(e).lower():
            logger.info(f"✅ Database '{target_dbname}' was created concurrently")
            return
        raise
    finally:
        admin_engine.dispose()


def _enable_extensions(db_url: str, logger) -> None:
    """在 DB 註冊 pgvector(必要)+ pg_jieba(可選,中文 BM25 用)。

    走 CREATE EXTENSION IF NOT EXISTS;OS 層 .so 須先裝(預期由 Postgres Docker image 提供)。

    Args:
        db_url: PostgreSQL 連線字串。
        logger: log 給 server 看的 logger。
    """
    engine = create_engine(db_url, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        # pgvector — 必要,沒有就完全不能用
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("✅ pgvector extension ready")
        except Exception as e:
            err = str(e).lower()
            if "could not open extension control file" in err or "control file" in err:
                logger.error(
                    f"❌ pgvector NOT installed at OS level.\n"
                    f"   檢查你 Postgres image 有沒有預裝 pgvector,或 bare-metal 安裝:\n"
                    f"     apt install postgresql-XX-pgvector\n"
                    f"   Original error: {e}"
                )
            else:
                logger.error(f"❌ pgvector setup failed: {e}")
            raise

        # pg_jieba — 可選,缺了 BM25 中文分詞降級成 simple
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_jieba"))
            logger.info("✅ pg_jieba extension ready")
        except Exception as e:
            err = str(e).lower()
            if "could not open extension control file" in err or "control file" in err:
                logger.warning(
                    f"⚠️ pg_jieba NOT installed at OS level — "
                    f"BM25 will fall back to default tokenizer (English-only,中文檢索效能會差).\n"
                    f"   檢查 Postgres image 是否含 pg_jieba。\n"
                    f"   或修改 config.yaml retrieval.text_search_config 為 'english' / 'simple'"
                )
            else:
                logger.warning(f"⚠️ pg_jieba registration failed: {e}")

    engine.dispose()


def ensure_hnsw_for_table(engine, table_name: str, logger=None) -> bool:
    """對單一 PGVector 表確保 HNSW index 存在(冪等,微秒級若已存在)

    用途:新 folder 第一次寫 chunks 後立刻補 HNSW,不用等下次重啟。

    Args:
        engine: SQLAlchemy engine 連到目標 DB(避免每次重建 engine)
        table_name: PGVector 表名,例如 'data_2_b09d9acf-d049-...'
        logger: 可選

    Returns:
        True 如果建了新 index,False 如果已存在
    """
    idx_name = table_name + "_hnsw_idx"
    sql = text(f'''
        CREATE INDEX IF NOT EXISTS "{idx_name}"
        ON "{table_name}"
        USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=64)
    ''')
    try:
        with engine.begin() as conn:
            # 先看 index 是否已存在(更便宜的 check)
            exists = conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :idx LIMIT 1"
            ), {"idx": idx_name}).first()
            if exists:
                return False
            conn.execute(sql)
        if logger:
            logger.debug(f"✅ HNSW index created on {table_name}")
        return True
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ HNSW index create failed for {table_name}: {e}")
        return False


def _ensure_hnsw_indexes(db_url: str, logger) -> None:
    """為所有 PGVector data_* 表建 HNSW index(冪等,自動修補 LlamaIndex 的 quoting bug)。

    LlamaIndex 自建 HNSW 對 UUID hyphen 沒做 identifier quoting → 靜默失敗;
    我們自己跑 IF NOT EXISTS 補。沒 HNSW search 1k+ chunks 後線性惡化。

    Args:
        db_url: PostgreSQL 連線字串。
        logger: log 給 server 看的 logger。
    """
    engine = create_engine(db_url, isolation_level="AUTOCOMMIT")
    sql = text("""
        DO $$
        DECLARE
          t TEXT;
          cnt INT := 0;
          new_cnt INT := 0;
        BEGIN
          FOR t IN
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename LIKE 'data\\_%' ESCAPE '\\'
          LOOP
            cnt := cnt + 1;
            -- 看這張表是不是已經有 HNSW index
            IF NOT EXISTS (
              SELECT 1 FROM pg_indexes
              WHERE tablename = t
                AND indexdef ILIKE '%USING hnsw%'
            ) THEN
              EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON %I USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)',
                t || '_hnsw_idx',
                t
              );
              new_cnt := new_cnt + 1;
            END IF;
          END LOOP;
          RAISE NOTICE 'HNSW sweep done: % vector tables, % newly indexed', cnt, new_cnt;
        END $$;
    """)
    try:
        with engine.connect() as conn:
            conn.execute(sql)
        logger.info("✅ HNSW index sweep complete (all PGVector tables checked)")
    except Exception as e:
        # 不致命 — 沒 HNSW 也能跑,只是 search 慢
        logger.warning(
            f"⚠️ HNSW index sweep failed: {e}. "
            "search will fall back to sequential scan (slower)."
        )
    finally:
        engine.dispose()


def check_vector_dims(db_url: str, expected_dim: int, logger) -> list:
    """啟動時掃所有 data_* 向量表,回報維度與 config 不符的表。

    pgvector 的維度在 CREATE TABLE 時凍結(存在 atttypmod),之後改 config
    不會改表 — 不符的表在 insert 時才會炸「expected N dimensions」。這裡
    提前到啟動就大聲報,並指出解法(reindex 該 folder)。

    Args:
        db_url: PostgreSQL 連線字串。
        expected_dim: config 的 rag.embedding.dimension。
        logger: server logger。

    Returns:
        [(table_name, actual_dim), ...] 不符清單;掃描失敗回空 list(不擋啟動)。
    """
    mismatched = []
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(r"""
                SELECT c.relname, a.atttypmod
                FROM pg_class c
                JOIN pg_attribute a ON a.attrelid = c.oid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND a.attname = 'embedding'
                  AND c.relkind = 'r'
                  AND c.relname LIKE 'data\_%' ESCAPE '\'
            """)).fetchall()
        for table_name, dim in rows:
            if dim is not None and dim > 0 and dim != expected_dim:
                mismatched.append((table_name, dim))
        if mismatched:
            for table_name, dim in mismatched:
                logger.error(
                    f"❌ Vector dim mismatch: table \"{table_name}\" was created with "
                    f"vector({dim}) but config dimension is {expected_dim}. "
                    f"Indexing into this folder WILL fail — reindex the folder "
                    f"(POST /api/rag/files/{{folder_id}}/reindex) to rebuild the table."
                )
        else:
            logger.info(
                f"✅ Vector dim check passed: {len(rows)} table(s) all match "
                f"dimension {expected_dim}"
            )
    except Exception as e:
        logger.warning(f"⚠️ Vector dim check skipped (non-fatal): {e}")
    finally:
        engine.dispose()
    return mismatched


def ensure_database_ready(db_url: str, logger) -> None:
    """確保 DB 存在 + extensions 啟用 + HNSW indexes 補齊(idempotent — 跑幾次都安全)

    完整的 declarative provisioning:
      Step 1: DB 不在 → 建
      Step 2: pgvector / pg_jieba extension 不在 → 啟用
      Step 3: PGVector data_* 表沒 HNSW index → 補建

    這個函式涵蓋「換 DB / 換機器 / Docker volume 重置 / 第一次部署」所有場景。
    跑幾次都安全(IF NOT EXISTS 保證冪等)。

    Args:
        db_url: SQLAlchemy DB URL,例如 postgresql://user:pwd@host/dbname
        logger: server logger 實例

    Raises:
        sqlalchemy.exc.OperationalError: 連 postgres 系統 DB 都失敗(密碼錯/服務沒起)
        sqlalchemy.exc.ProgrammingError: 無 CREATEDB 權限等
        Exception: pgvector extension 建立失敗(必要,沒有就完全不能用)
    """
    logger.info(f"🔍 Bootstrapping database '{make_url(db_url).database}'...")

    # Step 1: ensure DB exists(SQLAlchemy 全程,見模組 docstring 安全設計)
    _ensure_database_exists(db_url, logger)

    # Step 2: ensure extensions
    _enable_extensions(db_url, logger)

    # Step 3: ensure HNSW indexes on all existing PGVector tables
    # (LlamaIndex 自己建會炸於 UUID hyphen 的 quoting bug,所以我們承擔這責任)
    _ensure_hnsw_indexes(db_url, logger)
