
"""執行期設定編排 — admin API 背後的一站式流程。

apply:驗證 → 就地改 ConfigModel → 持久化 DB(重啟不丟)→ rebind 活物件
reset:刪 DB 覆寫 → 從 config.yaml 原值還原該欄位 → rebind
startup:main.py 啟動時把 DB 覆寫疊上剛載入的 ConfigModel(此時 adapter
        尚未建構,rebind 自然無對象 — 首次建構直接吃疊加後的值)。

併發:單把鎖序列化 admin 寫入(設定面板不是高頻路徑);讀不加鎖 —
就地 setattr 是原子的屬性替換,讀端頂多晚一拍看到。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from src.config.config_manager import Config
from src.config import runtime_overrides as ro
from db.runtime_settings_db import RuntimeSettingsDB
from src.log import get_adapter_logger

logger = get_adapter_logger()

_apply_lock = threading.Lock()


def load_overrides_on_startup() -> int:
    """啟動時把 DB 覆寫疊上 ConfigModel(main.py 於 DB ready 後呼叫)。

    無效的覆寫(白名單改過 / 型別對不上)逐條略過並 log — 一條壞資料
    不能擋服務啟動。回傳成功套用數。
    """
    overrides = RuntimeSettingsDB.load_all()
    if not overrides:
        return 0
    config_model = Config.get_config_model()
    applied = 0
    for path, value in overrides.items():
        try:
            ro.validate_and_apply(config_model, {path: value})
            applied += 1
        except ValueError as e:
            logger.warning(f"[RUNTIME] 略過無效覆寫 {path}={value!r}: {e}")
    logger.info(f"[RUNTIME] 啟動套用 {applied}/{len(overrides)} 條執行期覆寫")
    return applied


def get_settings_view() -> Dict[str, Any]:
    """設定面板的完整視圖:每條白名單路徑的生效值 / 級別 / 是否有覆寫。"""
    config_model = Config.get_config_model()
    effective = ro.get_effective(config_model)
    overridden = set(RuntimeSettingsDB.load_all().keys())
    return {
        "settings": [
            {
                "path": path,
                "value": effective.get(path),
                "level": level,
                "overridden": path in overridden,
                "secret": path in ro.SECRET_PATHS,
            }
            for path, level in ro.EDITABLE.items()
        ],
    }


def apply_settings(patch: Dict[str, Any], updated_by: Optional[str] = None
                   ) -> Tuple[Dict[str, Any], List[str]]:
    """驗證 → 就地改 config → 持久化 → rebind。全有全無(驗證期);
    持久化與 rebind 為 best-effort 順序執行,失敗原樣 raise 讓 API 回 500。
    """
    with _apply_lock:
        config_model = Config.get_config_model()
        before = ro.get_effective(config_model, mask_secrets=True)  # 舊值(secret 遮罩)
        applied, warnings = ro.validate_and_apply(config_model, patch)
        for path, value in applied.items():
            RuntimeSettingsDB.upsert(path, value, updated_by=updated_by)
            _audit(path, "set", before.get(path),
                   "•••" if path in ro.SECRET_PATHS else value, updated_by)
        _rebind(list(applied.keys()))
        logger.info(f"[RUNTIME] applied {sorted(applied)} by={updated_by}")
        return applied, warnings


def reset_setting(path: str) -> bool:
    """移除單條覆寫,還原 config.yaml 原值並 rebind。回傳是否有覆寫可刪。"""
    if path not in ro.EDITABLE:
        raise ValueError(f"不可操作的設定路徑:{path}")
    with _apply_lock:
        removed = RuntimeSettingsDB.delete(path)
        if not removed:
            return False
        # 從磁碟 config.yaml 重讀該欄位原值(不動其他 runtime 狀態)
        yaml_value = _yaml_value(path)
        config_model = Config.get_config_model()
        ro.validate_and_apply(config_model, {path: yaml_value})
        _rebind([path])
        _audit(path, "reset", None,
               "•••" if path in ro.SECRET_PATHS else yaml_value, None)
        logger.info(f"[RUNTIME] reset {path} → yaml 預設 {yaml_value!r}")
        return True


def _audit(key, action, old, new, by):
    from db.settings_audit_db import SettingsAuditDB
    SettingsAuditDB.record(key, action, old, new, by)


def audit_log(limit: int = 100):
    from db.settings_audit_db import SettingsAuditDB
    return SettingsAuditDB.recent(limit)


def _yaml_value(path: str) -> Any:
    """讀 config.yaml(磁碟原檔)裡該點路徑的值;沒有 → 該欄位 pydantic 預設。"""
    import yaml
    raw_path = Config._config_path
    try:
        if raw_path:
            with open(raw_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            node: Any = data
            for part in path.split("."):
                node = node[part]
            return node
    except Exception:
        pass
    # fallback:欄位宣告預設
    parent_path, _, field = path.rpartition(".")
    obj = Config.get_config_model()
    for part in parent_path.split("."):
        obj = getattr(obj, part)
    f = type(obj).model_fields[field]
    return f.get_default(call_default_factory=True)


def _rebind(paths: List[str]) -> List[str]:
    """adapter 已建才 rebind(未建 = 尚無活物件,首次建構吃新 config)。"""
    groups = ro.rebind_groups_for(paths)
    if not groups:
        return []
    from src.adapter.rag import peek_rag_adapter
    adapter = peek_rag_adapter()
    if adapter is None:
        logger.info(f"[RUNTIME] adapter 未建構,{groups} 待首次建構生效")
        return []
    adapter._ctx.apply_runtime_changes(groups)
    return groups
