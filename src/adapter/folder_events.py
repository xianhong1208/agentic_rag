
"""Folder 事件 hooks — MCP tool 註冊的依賴反轉(M6 子題)。

背景:每個 folder 在 MCP 上有一個專屬查詢工具,folder 的建立/改名/刪除必須
同步掛/換/卸該工具。原本 FolderAdapter 直接 import fastmcp_tools.agentic_tools
的 register/unregister,而 agentic_tools 又 import adapter.rag → import 環
(adapter ↔ fastmcp 交付層互相依賴)。

改為依賴反轉:
- folder.py 只呼叫本模組的 notify_*(不認識 fastmcp)
- app.py 啟動時(它本來就同時認識兩邊)呼叫 set_folder_tool_hooks() 把
  MCP 層的 register/unregister 掛進來
- 方向從此單向:fastmcp → adapter ✅

語義(沿用原 folder.py 的兜底):工具面同步失敗**絕不阻斷** folder CRUD ——
callback 拋例外只記 warning、回 False。未掛載(wiring bug)記 ERROR 大聲提示
但同樣不 raise:寧可工具面暫缺,不能讓建/刪 folder 失敗。
"""

from __future__ import annotations

from typing import Callable, Optional

from src.log import get_adapter_logger

logger = get_adapter_logger()

# app.py 啟動時掛載;None = 未 wiring(啟動流程 bug,notify 時記 ERROR)
_register_tool: Optional[Callable] = None    # (folder_name, description, user_token) -> bool
_unregister_tool: Optional[Callable] = None  # (folder_name, *, user_token) -> None


def set_folder_tool_hooks(*, register: Callable, unregister: Callable) -> None:
    """app.py 啟動時掛載 MCP 層的 register/unregister(必須早於任何 folder CRUD)。"""
    global _register_tool, _unregister_tool
    _register_tool = register
    _unregister_tool = unregister
    logger.info("[INIT] Folder tool hooks wired (register/unregister)")


def clear_folder_tool_hooks() -> None:
    """卸載 hooks(測試隔離用;正常執行期不呼叫)。"""
    global _register_tool, _unregister_tool
    _register_tool = None
    _unregister_tool = None


def _unwired(action: str) -> bool:
    # ERROR 級:這是啟動 wiring bug(set_folder_tool_hooks 沒被呼叫),
    # 不是執行期抖動 —— 大聲讓 ops 看到,但不 raise、不阻斷 folder CRUD。
    logger.error(
        f"folder_events.{action}: tool hooks NOT wired — MCP tool 面不會同步。"
        f"app.py 啟動時應先呼叫 set_folder_tool_hooks()"
    )
    return False


def notify_folder_created(folder_name: str, description: Optional[str], user_token: str) -> bool:
    """folder 建立後掛專屬 MCP tool。失敗不拋,回 False。"""
    if _register_tool is None:
        return _unwired("created")
    try:
        _register_tool(folder_name, description, user_token)
        return True
    except Exception as e:
        logger.warning(f"Failed to register MCP tool for folder {folder_name}: {e}")
        return False


def notify_folder_deleted(folder_name: str, user_token: str) -> bool:
    """folder 刪除前卸其 MCP tool。失敗不拋,回 False。"""
    if _unregister_tool is None:
        return _unwired("deleted")
    try:
        _unregister_tool(folder_name, user_token=user_token)
        return True
    except Exception as e:
        logger.warning(f"Failed to unregister MCP tool for folder {folder_name}: {e}")
        return False


def notify_folder_renamed(
    old_name: str, new_name: str, description: Optional[str], user_token: str
) -> bool:
    """folder 改名/改描述後刷新 MCP tool:先卸舊、再掛新。

    卸舊失敗仍會嘗試掛新 —— 工具面盡量收斂到新狀態。任一步失敗回 False。
    """
    if _register_tool is None or _unregister_tool is None:
        return _unwired("renamed")
    ok = True
    try:
        _unregister_tool(old_name, user_token=user_token)
    except Exception as e:
        logger.warning(f"Failed to unregister old MCP tool '{old_name}': {e}")
        ok = False
    try:
        _register_tool(new_name, description, user_token)
    except Exception as e:
        logger.warning(f"Failed to register MCP tool for folder {new_name}: {e}")
        ok = False
    return ok
