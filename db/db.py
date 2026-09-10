
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, BigInteger, Index, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
import uuid

# 使用新的配置系統
from src.config.config_manager import Config

# Lazy initialization: do NOT create engine at import time. This allows the application to
# load configuration (Config.set_config) before any DB connection is attempted.
_engine = None
Session = sessionmaker()
Base = declarative_base()


class Folder(Base):
    """資料夾模型"""
    __tablename__ = 'Folders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    file_count = Column(Integer, default=0)
    total_size = Column(BigInteger, default=0)
    # user_token 儲存擁有此 folder 的 token（用於權限過濾）
    # 注意：不使用 FK，因為 token 由遠端 Token Server 管理
    user_token = Column(String(256), nullable=True)
    vector_table_uuid = Column(PostgresUUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


    def __repr__(self):
        return f"<Folder(id={self.id}, name='{self.name}')>"


class File(Base):
    """文件記錄的數據庫模型"""
    __tablename__ = 'Files'

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    folder_id = Column(Integer, ForeignKey('Folders.id'), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100))
    description = Column(Text)
    tags = Column(JSONB, nullable=False, default=list, server_default='[]')
    # 上傳時算的 sha256;索引時跟 FileIndex.content_hash 比對,沒變就跳過重 embed
    content_hash = Column(String(64), nullable=True)
    upload_time = Column(DateTime, default=func.now())
    updated_time = Column(DateTime, default=func.now(), onupdate=func.now())


    __table_args__ = (
        Index('idx_files_folder_id', 'folder_id'),
        Index('idx_files_upload_time', 'upload_time', postgresql_using='btree', postgresql_ops={'upload_time': 'DESC'}),
        Index('idx_files_folder_name', 'folder_id', 'file_name'),
    )

    def __repr__(self):
        return f"<FileRecord(id={self.id}, file_name='{self.file_name}', folder_id={self.folder_id}, size={self.file_size})>"


class FileIndex(Base):
    """Tracks which files have been indexed in LlamaIndex vector stores"""
    __tablename__ = 'FileIndices'

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(PostgresUUID(as_uuid=True), ForeignKey('Files.id'), nullable=False, unique=True)
    folder_id = Column(Integer, ForeignKey('Folders.id'), nullable=False)

    # LlamaIndex document ID (used to delete from vector store)
    index_id = Column(String(255), nullable=False)

    # Vector store table name (format: {folder_id}_{vector_table_uuid})
    vector_store_table = Column(String(255), nullable=True)

    # Indexing metadata
    chunk_size = Column(Integer, default=256)
    chunk_overlap = Column(Integer, default=50)
    # 應用層永遠傳 model name 進來;NULL = 未知,不偽裝 legacy 預設值
    embedding_model = Column(String(100), nullable=True)
    num_chunks = Column(Integer, default=0)

    # Status
    status = Column(String(50), default="indexed")  # indexed, failed, deleted
    error_message = Column(Text, nullable=True)

    # 索引當下的 File.content_hash 快照;match → 後續 reindex 直接 short-circuit
    content_hash = Column(String(64), nullable=True)

    # Timestamps
    indexed_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


    __table_args__ = (
        Index('idx_fileindices_folder_id', 'folder_id'),
        Index('idx_fileindices_file_id', 'file_id'),
        Index('idx_fileindices_status', 'status'),
    )

    def __repr__(self):
        return f"<FileIndex(id={self.id}, file_id={self.file_id}, status='{self.status}')>"


class RuntimeSetting(Base):
    """執行期設定覆寫(admin 面板熱改;疊在 config.yaml 之上)。

    key = 點路徑(如 "rag.rerank.score_threshold"),value = JSONB 包一層
    {"value": ...}(JSONB 頂層存裸 scalar 各驅動行為不一,包一層最穩)。
    重啟時 main.py 讀回疊上 ConfigModel — config.yaml 永遠是「出廠預設」,
    這張表是「現場調整」,分層清楚可個別 reset。
    """
    __tablename__ = 'RuntimeSettings'

    key = Column(String(255), primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(64), nullable=True)  # 遮罩後的 token 前綴,稽核用


class SettingsAudit(Base):
    """設定變更稽核記錄(append-only)。RuntimeSetting 只存當前值;這張表
    保留每次變更的歷史,供合規稽核「誰在何時把什麼改成什麼」。"""
    __tablename__ = 'SettingsAudit'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), nullable=False)
    action = Column(String(16), nullable=False)  # set / reset
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    changed_by = Column(String(64), nullable=True)  # 遮罩 token / "console"
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index('idx_settings_audit_at', 'changed_at'),)


class IndexJob(Base):
    """背景索引 job 持久化。IndexingJobManager write-through,讓 job state 跨 restart 還在。

    timestamps 用 ISO 字串(對齊 IndexJobState 序列化),避開 timezone 漂移。
    """
    __tablename__ = 'IndexJobs'

    job_id = Column(PostgresUUID(as_uuid=True), primary_key=True)
    folder_id = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    current_index = Column(Integer, default=0)
    current_file_id = Column(String(255), nullable=True)
    current_file_name = Column(String(255), nullable=True)
    last_file_status = Column(String(64), nullable=True)
    last_message = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    skip_existing = Column(Boolean, default=True)
    started_at = Column(String(64), nullable=True)
    completed_at = Column(String(64), nullable=True)
    last_updated_at = Column(String(64), nullable=True)
    result_summary = Column(JSONB, nullable=True)
    scope_file_ids = Column(JSONB, nullable=False, default=list, server_default='[]')
    file_timings = Column(JSONB, nullable=False, default=list, server_default='[]')

    __table_args__ = (
        Index('idx_indexjobs_folder_id', 'folder_id'),
        Index('idx_indexjobs_status', 'status'),
        Index('idx_indexjobs_last_updated', 'last_updated_at'),
    )

    def __repr__(self):
        return f"<IndexJob(job_id={self.job_id}, folder_id={self.folder_id}, status='{self.status}')>"


class QueryLog(Base):
    """檢索查詢記錄 — 供 Control Center 分析(查詢量 / 熱門查詢 / 零結果 / 延遲)。

    每次檢索 best-effort 記一筆(失敗不擋查詢)。query 存原字串供熱門/零結果
    分析;token 只存遮罩前綴(稽核,不存完整 token)。屬營運遙測,非權限資料。
    """
    __tablename__ = 'QueryLogs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, nullable=True)
    query = Column(Text, nullable=False)
    result_count = Column(Integer, default=0)
    latency_ms = Column(Integer, nullable=True)
    token_prefix = Column(String(64), nullable=True)  # 遮罩後前綴
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_querylogs_folder', 'folder_id'),
        Index('idx_querylogs_created', 'created_at'),
    )


def _resolve_db_url(db_conf) -> str:
    """回傳完整連線 URL。

    坑修(2026-09-07):create_engine / create_async_engine 只吃 URL、
    忽略 config 分開的 `database.port` 欄位 → URL 沒寫 port 時預設連 5432,
    使用者設了 port 欄位卻連錯實例(症狀:連到別台 → password failed)。
    此 helper 在 URL 未帶 port 且 config 有 port 時,把 port 注入 URL,
    讓三處連線(sync/async/vector store)一致。
    """
    from sqlalchemy import make_url
    url = make_url(db_conf.url)
    port = getattr(db_conf, "port", None)
    if url.port is None and port:
        url = url.set(port=int(port))
    return url.render_as_string(hide_password=False)


def get_engine():
    """返回已配置的 SQLAlchemy engine，若尚未建立則根據 Config 建立。

    注意：在呼叫此函式前應先呼叫 Config.set_config(...) 以載入配置。
    """
    global _engine
    if _engine is None:
        # 僅使用 Pydantic model 取得 database 設定，若未載入 model 則拋出錯誤
        db_conf = Config.get_database_config()
        if not db_conf:
            raise RuntimeError("Database configuration is missing in Pydantic ConfigModel.")
        db_uri = _resolve_db_url(db_conf)
        # 預設 False:echo=True 會把每條 SQL 印進 log,量大且可能含資料值。
        # 要 debug SQL 時在 config 顯式設 echo: true。
        echo_flag = getattr(db_conf, 'echo', False)
        _engine = create_engine(
            db_uri,
            echo=echo_flag,
        )
        # 將 engine 綁定到 Session factory
        Session.configure(bind=_engine)
    return _engine


_async_engine = None


def get_async_engine():
    """返回共用的 SQLAlchemy async engine(asyncpg driver),lazy 建立。

    查詢熱路徑(ChunkLookup 批次查詢)用 — event loop 上不佔 loop 的 DB I/O。
    與 get_engine() 讀同一份 config;driver 由 postgresql:// 改寫為
    postgresql+asyncpg://。pool 沿用 config 的 pool_size / max_overflow,
    與 sync 主 engine 各自獨立計數(容量規劃見 config 註解)。
    """
    global _async_engine
    if _async_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        db_conf = Config.get_database_config()
        if not db_conf:
            raise RuntimeError("Database configuration is missing in Pydantic ConfigModel.")
        async_uri = _resolve_db_url(db_conf).replace(
            "postgresql://", "postgresql+asyncpg://", 1)
        _async_engine = create_async_engine(
            async_uri,
            echo=getattr(db_conf, 'echo', False),
            pool_size=getattr(db_conf, 'pool_size', 5),
            max_overflow=getattr(db_conf, 'max_overflow', 10),
            pool_recycle=getattr(db_conf, 'pool_recycle', 3600),
        )
    return _async_engine


def init_db(create_tables: bool = True):
    """初始化資料庫連線,選擇性建立資料表。

    Args:
        create_tables: True → 跑 Base.metadata.create_all(對既有 schema 冪等)。

    Returns:
        已配置好的 SQLAlchemy engine。
    """
    engine = get_engine()
    if create_tables:
        Base.metadata.create_all(engine)
    return engine
