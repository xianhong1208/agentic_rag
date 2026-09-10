
"""IndexJob 持久化 — IndexingJobManager 的 write-through projection。

DB 是被動投影,manager 仍是 live 狀態的 source of truth。寫入 best-effort,
DB 失敗只 log warning(table 不存在也能跑)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .db import IndexJob
from db.db import Session as DBSession
from .baseDB import BaseDB
from src.log import get_db_logger

log = get_db_logger()


# 已知能寫的欄位;state_dict 內其他 key 自動 drop(forward-compat)
_PERSISTED_FIELDS = {
    "job_id", "folder_id", "status", "total_files", "processed_files",
    "current_index", "current_file_id", "current_file_name",
    "last_file_status", "last_message", "message", "error",
    "skip_existing", "started_at", "completed_at", "last_updated_at",
    "result_summary", "scope_file_ids", "file_timings",
}


class IndexJobDB(BaseDB):
    """IndexJob CRUD."""

    @classmethod
    def get_orm_class(cls) -> type:
        return IndexJob

    @classmethod
    def get_log(cls):
        return log

    @classmethod
    def ensure_table(cls) -> None:
        """建 IndexJobs table(IF NOT EXISTS,冪等)。

        M13: canonical 是 alembic migration 20260819cafe01(IndexJobs 已收進鏈,
        正常部署由啟動 auto_migrate 建好);這裡是 runtime fallback,讓 manager
        在沒跑過 Alembic 的環境也能上。
        """
        try:
            from db.db import get_engine
            cls.get_orm_class().__table__.create(get_engine(), checkfirst=True)
        except Exception as e:
            cls.get_log().warning(f"ensure_table failed (will fall back to in-memory only): {e}")

    @classmethod
    def upsert(cls, state_dict: Dict[str, Any]) -> None:
        """Upsert IndexJobState.to_dict() 到 DB(write-through,失敗只 log 不 raise)。

        Args:
            state_dict: IndexJobState.to_dict() 輸出;不認得的 key 自動 drop。
        """
        try:
            payload = {k: v for k, v in state_dict.items() if k in _PERSISTED_FIELDS}
            job_id = payload.get("job_id")
            if not job_id:
                return
            with DBSession() as session:
                existing = session.query(cls.get_orm_class()).filter_by(job_id=job_id).first()
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    obj = cls.get_orm_class()(**payload)
                    session.add(obj)
                session.commit()
        except Exception as e:
            cls.get_log().warning(f"IndexJobDB.upsert failed for job {state_dict.get('job_id')}: {e}")

    @classmethod
    def load_active(cls) -> List[Dict[str, Any]]:
        """讀取 DB 內所有 PENDING / RUNNING jobs(供 startup A4 cleanup 用)。

        Returns:
            row dicts list;DB 失敗回空 list。
        """
        try:
            with DBSession() as session:
                rows = (
                    session.query(cls.get_orm_class())
                    .filter(cls.get_orm_class().status.in_(["pending", "running"]))
                    .all()
                )
                return [
                    {col.name: getattr(row, col.name) for col in row.__table__.columns}
                    for row in rows
                ]
        except Exception as e:
            cls.get_log().warning(f"IndexJobDB.load_active failed: {e}")
            return []

    @classmethod
    def delete_for_folder(cls, folder_id: int) -> int:
        """刪除該 folder 的所有 job rows(folder 刪除時的清理,best-effort)。

        Args:
            folder_id: 被刪除的 folder id。

        Returns:
            刪掉的 row 數;DB 失敗回 0。
        """
        try:
            with DBSession() as session:
                deleted = (
                    session.query(cls.get_orm_class())
                    .filter_by(folder_id=folder_id)
                    .delete(synchronize_session=False)
                )
                session.commit()
                if deleted:
                    cls.get_log().info(
                        f"Deleted {deleted} IndexJob row(s) for folder {folder_id}"
                    )
                return deleted
        except Exception as e:
            cls.get_log().warning(f"IndexJobDB.delete_for_folder({folder_id}) failed: {e}")
            return 0

    @classmethod
    def purge_terminal_older_than(cls, days: int = 30) -> int:
        """清掉終態且超過保留期的 job rows(startup 呼叫,擋 unbounded growth)。

        timestamps 是 ISO-8601 UTC 字串,同格式下字典序 = 時間序,直接字串比較。

        Args:
            days: 保留天數;last_updated_at 早於 now-days 的終態 row 會被刪。

        Returns:
            刪掉的 row 數;DB 失敗回 0。
        """
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            orm = cls.get_orm_class()
            with DBSession() as session:
                deleted = (
                    session.query(orm)
                    .filter(orm.status.in_(
                        ["succeeded", "partial_success", "failed", "cancelled"]
                    ))
                    .filter(orm.last_updated_at < cutoff)
                    .delete(synchronize_session=False)
                )
                session.commit()
                if deleted:
                    cls.get_log().info(
                        f"Purged {deleted} terminal IndexJob row(s) older than {days}d"
                    )
                return deleted
        except Exception as e:
            cls.get_log().warning(f"IndexJobDB.purge_terminal_older_than failed: {e}")
            return 0

    @classmethod
    def get_by_id(cls, job_id) -> Optional[Dict[str, Any]]:
        """依 job_id 取單一 job row。

        Args:
            job_id: UUID 或 str。

        Returns:
            row dict 或 None(找不到 / DB 失敗)。
        """
        try:
            with DBSession() as session:
                row = session.query(cls.get_orm_class()).filter_by(job_id=job_id).first()
                if not row:
                    return None
                return {col.name: getattr(row, col.name) for col in row.__table__.columns}
        except Exception as e:
            cls.get_log().warning(f"IndexJobDB.get_by_id({job_id}) failed: {e}")
            return None
