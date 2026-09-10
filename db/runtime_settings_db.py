
"""RuntimeSettings 持久化 — admin 面板熱改設定的覆寫層。

config.yaml = 出廠預設(唯讀);這張表 = 現場調整(點路徑 key → 值)。
啟動時 main.py 讀回疊上 ConfigModel;之後每次 admin 改動 write-through。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .db import RuntimeSetting
from db.db import Session as DBSession
from .baseDB import BaseDB
from src.log import get_db_logger

log = get_db_logger()


class RuntimeSettingsDB(BaseDB):
    """RuntimeSettings CRUD(key = 設定點路徑,value = {"value": ...})。"""

    @classmethod
    def get_orm_class(cls) -> type:
        return RuntimeSetting

    @classmethod
    def get_log(cls):
        return log

    @classmethod
    def ensure_table(cls) -> None:
        """建表(IF NOT EXISTS,冪等)— bootstrap create_all 外的 runtime 保險。"""
        try:
            from db.db import get_engine
            cls.get_orm_class().__table__.create(get_engine(), checkfirst=True)
        except Exception as e:
            cls.get_log().warning(f"RuntimeSettings ensure_table failed: {e}")

    @classmethod
    def load_all(cls) -> Dict[str, Any]:
        """全部覆寫:{點路徑: 值}。表不存在/DB 掛 → 空 dict(不擋啟動)。"""
        try:
            with DBSession() as session:
                rows = session.query(RuntimeSetting).all()
                return {r.key: (r.value or {}).get("value") for r in rows}
        except Exception as e:
            log.warning(f"RuntimeSettings load_all failed (using yaml defaults only): {e}")
            return {}

    @classmethod
    def upsert(cls, key: str, value: Any, updated_by: Optional[str] = None) -> None:
        with DBSession() as session:
            row = session.get(RuntimeSetting, key)
            if row is None:
                session.add(RuntimeSetting(
                    key=key, value={"value": value}, updated_by=updated_by))
            else:
                row.value = {"value": value}
                row.updated_by = updated_by
            session.commit()

    @classmethod
    def delete(cls, key: str) -> bool:
        """移除單一覆寫(回歸 yaml 預設)。回傳是否真的有刪到。"""
        with DBSession() as session:
            row = session.get(RuntimeSetting, key)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
