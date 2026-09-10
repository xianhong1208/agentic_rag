
"""FileIndex database operations module

Provides database operations for tracking file indexing in the RAG system.
"""

from datetime import datetime, timezone
from typing import Optional

from .db import FileIndex
from db.db import Session as DBSession
from .baseDB import BaseDB
from src.log import get_db_logger

# Get logger instance
log = get_db_logger()


class FileIndexDB(BaseDB):
    """FileIndex database operations class

    Provides CRUD operations for file index tracking
    """

    @classmethod
    def get_orm_class(cls) -> type:
        """Get ORM class"""
        return FileIndex

    @classmethod
    def get_log(cls):
        """Get logger instance"""
        return log

    @classmethod
    def get_indexed_models_for_folder(cls, folder_id: int) -> list:
        """回傳該 folder 成功索引記錄使用過的 embedding model 名(distinct)。

        換模防護用:同一張向量表混兩種模型的向量,檢索會靜默劣化(維度相同
        時連 insert 都不會炸),indexing 前先比對。

        Args:
            folder_id: 目標 folder id。

        Returns:
            model name list(排除 NULL);DB 失敗回空 list(fail-open,不擋索引)。
        """
        try:
            with DBSession() as session:
                rows = (
                    session.query(FileIndex.embedding_model)
                    .filter(FileIndex.folder_id == folder_id)
                    .filter(FileIndex.status == "indexed")
                    .filter(FileIndex.embedding_model.isnot(None))
                    .distinct()
                    .all()
                )
                return [r[0] for r in rows]
        except Exception as e:
            cls.get_log().warning(
                f"get_indexed_models_for_folder({folder_id}) failed: {e}"
            )
            return []

    @classmethod
    def get_by_file(cls, file_id):
        """Get index record for a specific file

        Args:
            file_id: UUID of the file

        Returns:
            FileIndex object or None
        """
        try:
            result = cls.get(file_id=file_id)
            return result[0] if result else None
        except Exception as e:
            cls.get_log().error(f"Failed to get FileIndex by file_id {file_id}: {e}")
            raise

    @classmethod
    def get_by_folder(cls, folder_id: int):
        """Get all indexed files in a folder

        Args:
            folder_id: ID of the folder

        Returns:
            List of FileIndex objects
        """
        try:
            return cls.get(folder_id=folder_id)
        except Exception as e:
            cls.get_log().error(f"Failed to get FileIndex by folder_id {folder_id}: {e}")
            raise

    @classmethod
    def ensure_content_hash_columns(cls) -> None:
        """補 Files / FileIndices 的 content_hash 欄位(冪等 ALTER TABLE ADD COLUMN IF NOT EXISTS)。

        既有 deployment 的 table 建在這欄出現之前,CREATE TABLE IF NOT EXISTS 不會補 column,
        要靠 ALTER。失敗只 log,idempotency 檢查會把 NULL 視為「未知,需重 index」。

        ⚠️ M13: 這是 runtime 自愈的 fallback,不是 schema 的正規來源 —— canonical 是
        alembic:content_hash 已正式收進 migration 20260819cafe01(versions/
        20260819_content_hash_indexjobs.py,2026-08-19 於真實 DB 驗證 fresh/patched/
        downgrade 三場景)。正常部署由啟動 auto_migrate 建好,這裡永遠是 no-op;
        若真的補了欄位,代表 migration 沒被套用 → 發 WARNING 讓 ops 察覺 drift。
        """
        try:
            from db.db import get_engine
            from sqlalchemy import text
            eng = get_engine()
            with eng.connect() as conn:
                missing = conn.execute(text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name IN ('Files', 'FileIndices') AND column_name = 'content_hash'"
                )).scalar()
                # 兩張表都有 → 2;缺任一 → < 2
                if missing is not None and missing < 2:
                    cls.get_log().warning(
                        "content_hash 欄位缺失,由 runtime ensure 補上 —— 表示 alembic "
                        "migration 可能未套用(schema drift)。canonical schema 是 alembic,"
                        "請確認 startup auto_migrate 有跑成功。"
                    )
                conn.execute(text(
                    'ALTER TABLE "Files" ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)'
                ))
                conn.execute(text(
                    'ALTER TABLE "FileIndices" ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)'
                ))
                conn.commit()
        except Exception as e:
            cls.get_log().warning(f"content_hash columns migration skipped: {e}")

    @classmethod
    def upsert_indexed(
        cls,
        *,
        file_id,
        folder_id: int,
        index_id: str,
        vector_store_table: str,
        chunk_size: int,
        chunk_overlap: int,
        embedding_model: str,
        num_chunks: int,
        content_hash: Optional[str] = None,
    ):
        """`create(... status="indexed")` 的 idempotent 版本(處理 reindex)。

        已存在 row 時就地 update(status flip 'indexed' + 清 error_message + 更新 indexed_at);
        不存在就 create。避開直接 create() 在 reindex 時撞 UniqueViolation。
        為何不沿用 BaseDB.update:它 skip None 值,沒法主動清掉 error_message。

        Args:
            file_id: 檔案 UUID。
            folder_id: 所屬 folder id。
            index_id: LlamaIndex doc id(`file_{uuid}`)。
            vector_store_table: 對應的 pgvector table 名。
            chunk_size: 實際使用的 leaf chunk size。
            chunk_overlap: 實際使用的 chunk overlap。
            embedding_model: 實際使用的 embedding model name。
            num_chunks: 寫入的 leaf chunk 數量。
            content_hash: 索引當下的 File.content_hash(供 D3 idempotency 比對)。

        Returns:
            更新後 / 新建的 FileIndex ORM 物件。

        Raises:
            DB 層的 exception(connection / constraint 等)─ 不吞,讓 caller 決策。
        """
        try:
            with DBSession() as session:
                existing = (
                    session.query(cls.get_orm_class())
                    .filter_by(file_id=file_id)
                    .first()
                )
                if existing:
                    existing.folder_id = folder_id
                    existing.index_id = index_id
                    existing.vector_store_table = vector_store_table
                    existing.chunk_size = chunk_size
                    existing.chunk_overlap = chunk_overlap
                    existing.embedding_model = embedding_model
                    existing.num_chunks = num_chunks
                    existing.status = "indexed"
                    existing.error_message = None
                    existing.content_hash = content_hash  # D3
                    existing.indexed_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(existing)
                    session.expunge(existing)
                    cls.get_log().info(
                        f"Upserted (update) FileIndex for file_id={file_id} "
                        f"status=indexed (cleared prior error_message)"
                    )
                    return existing
            # Fall through to insert path (separate session — clean state)
            return cls.create(
                file_id=file_id,
                folder_id=folder_id,
                index_id=index_id,
                vector_store_table=vector_store_table,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                embedding_model=embedding_model,
                num_chunks=num_chunks,
                status="indexed",
                content_hash=content_hash,  # D3
            )
        except Exception as e:
            cls.get_log().error(f"upsert_indexed failed for file_id={file_id}: {e}")
            raise

    @classmethod
    def mark_failed(
        cls,
        file_id,
        error_message: str,
        folder_id: Optional[int] = None,
        embedding_model: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        """標記檔案索引失敗。

        三條路徑:
        - 已有 row → update status='failed'。
        - 沒 row + 有 folder_id → 建一筆 status='failed'(讓 /indexed-files 看得到)。
        - 沒 row + 沒 folder_id → log warning + return None(保留舊 caller 行為)。

        Args:
            file_id: 檔案 UUID。
            error_message: 寫進 FileIndex.error_message 的訊息。
            folder_id: 沒 row 時要建新 row 必須給(folder_id 是 NOT NULL)。
            embedding_model: 失敗 row 寫進去的 model name(別讓 column 預設誤導讀者)。
            chunk_size: 失敗 row 寫進去的 chunk size。
            chunk_overlap: 失敗 row 寫進去的 chunk overlap。

        Returns:
            update / create 後的 FileIndex 物件;沒 row + 沒 folder_id 時回 None。
        """
        try:
            # Get the existing index record
            index_record = cls.get_by_file(file_id)
            if not index_record:
                if folder_id is None:
                    cls.get_log().warning(f"No FileIndex found for file_id {file_id}")
                    return None

                # No prior record — create one with status="failed" so the
                # failure is visible to downstream consumers.
                cls.get_log().info(
                    f"Creating failed FileIndex record for file_id {file_id} "
                    f"(folder_id={folder_id}) — no prior record existed"
                )
                create_kwargs = {
                    "file_id": file_id,
                    "folder_id": folder_id,
                    "index_id": f"file_{file_id}",
                    "vector_store_table": "",
                    "num_chunks": 0,
                    "status": "failed",
                    "error_message": error_message,
                }
                # Only set when caller supplied — keeps backward compat with
                # callers that don't yet pass these.
                if embedding_model is not None:
                    create_kwargs["embedding_model"] = embedding_model
                if chunk_size is not None:
                    create_kwargs["chunk_size"] = chunk_size
                if chunk_overlap is not None:
                    create_kwargs["chunk_overlap"] = chunk_overlap
                return cls.create(**create_kwargs)

            # 只覆蓋 caller 顯式傳的欄位;其他保留 record_index_success 寫的值
            update_kwargs = {"status": "failed", "error_message": error_message}
            if embedding_model is not None:
                update_kwargs["embedding_model"] = embedding_model
            if chunk_size is not None:
                update_kwargs["chunk_size"] = chunk_size
            if chunk_overlap is not None:
                update_kwargs["chunk_overlap"] = chunk_overlap
            return cls.update(index_record.id, **update_kwargs)
        except Exception as e:
            cls.get_log().error(f"Failed to mark FileIndex as failed for file_id {file_id}: {e}")
            raise

    @classmethod
    def delete_by_file(cls, file_id):
        """Delete index record for a specific file

        Args:
            file_id: UUID of the file

        Returns:
            True if deleted, False if not found
        """
        try:
            result = cls.delete(file_id=file_id)
            if result:
                cls.get_log().info(f"Deleted FileIndex for file_id {file_id}")
            return result
        except Exception as e:
            cls.get_log().error(f"Failed to delete FileIndex by file_id {file_id}: {e}")
            raise

    @classmethod
    def delete_by_folder(cls, folder_id: int) -> int:
        """Delete all index records for a specific folder

        Args:
            folder_id: ID of the folder

        Returns:
            Number of records deleted
        """
        try:
            with DBSession() as session:
                deleted_count = session.query(cls.get_orm_class()).filter_by(folder_id=folder_id).delete(synchronize_session=False)
                session.commit()
                cls.get_log().info(f"Deleted {deleted_count} FileIndex records for folder_id {folder_id}")
                return deleted_count
        except Exception as e:
            cls.get_log().error(f"Failed to delete FileIndex records by folder_id {folder_id}: {e}")
            raise
