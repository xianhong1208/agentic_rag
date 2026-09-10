
"""M6 子題 — folder 事件 hooks(MCP tool 註冊的依賴反轉)。

背景:FolderAdapter 原本直接 import fastmcp_tools.agentic_tools 的
register/unregister,與 agentic_tools → adapter.rag 構成 import 環。
改為:folder.py 只呼叫本模組的 notify_*;app.py 啟動時把 MCP 層的
register/unregister 掛進來。方向從此單向(fastmcp → adapter)。

契約(這份測試釘死的):
1. 掛載後 created/renamed/deleted 分派到對應 callback,參數原樣
2. 未掛載時 notify 不 raise(不阻斷 folder CRUD)但回 False —— wiring bug
   要在 log 大聲,不能靜默
3. callback 拋例外 → 吞掉記 log、回 False(沿用原 folder.py 的兜底語義:
   工具面同步失敗絕不阻斷業務)
4. renamed = 先卸舊再掛新;卸舊失敗仍要嘗試掛新(工具面盡量收斂到新狀態)
"""

from unittest.mock import MagicMock

import pytest

from src.adapter import folder_events as fe


@pytest.fixture(autouse=True)
def _clean_hooks():
    fe.clear_folder_tool_hooks()
    yield
    fe.clear_folder_tool_hooks()


def _install():
    reg, unreg = MagicMock(return_value=True), MagicMock()
    fe.set_folder_tool_hooks(register=reg, unregister=unreg)
    return reg, unreg


def test_created_dispatches_to_register():
    reg, unreg = _install()
    assert fe.notify_folder_created("f1", "desc", "tokA") is True
    reg.assert_called_once_with("f1", "desc", "tokA")
    unreg.assert_not_called()


def test_deleted_dispatches_to_unregister():
    reg, unreg = _install()
    assert fe.notify_folder_deleted("f1", "tokA") is True
    unreg.assert_called_once_with("f1", user_token="tokA")
    reg.assert_not_called()


def test_renamed_unregisters_old_then_registers_new():
    reg, unreg = _install()
    calls = []
    unreg.side_effect = lambda *a, **k: calls.append("unreg")
    reg.side_effect = lambda *a, **k: calls.append("reg")
    assert fe.notify_folder_renamed("old", "new", "d2", "tokA") is True
    assert calls == ["unreg", "reg"], "必須先卸舊再掛新"
    unreg.assert_called_once_with("old", user_token="tokA")
    reg.assert_called_once_with("new", "d2", "tokA")


def test_renamed_still_registers_new_when_unregister_fails():
    """卸舊炸掉不該擋住掛新 —— 工具面要盡量收斂到新狀態。"""
    reg, unreg = _install()
    unreg.side_effect = RuntimeError("boom")
    assert fe.notify_folder_renamed("old", "new", "d", "tokA") is False  # 有失敗 → False
    reg.assert_called_once_with("new", "d", "tokA")


def test_unwired_does_not_raise_returns_false():
    """未掛載(wiring bug):不 raise、回 False —— folder CRUD 不被阻斷。"""
    assert fe.notify_folder_created("f", "d", "t") is False
    assert fe.notify_folder_deleted("f", "t") is False
    assert fe.notify_folder_renamed("a", "b", "d", "t") is False


def test_callback_exception_swallowed():
    """callback 拋例外 → 吞掉回 False,不上拋(沿用原兜底語義)。"""
    reg, _ = _install()
    reg.side_effect = RuntimeError("mcp down")
    assert fe.notify_folder_created("f", "d", "t") is False


def test_deleted_callback_exception_swallowed():
    """deleted 的 unregister 炸掉:吞掉回 False,不阻斷刪除流程。"""
    _, unreg = _install()
    unreg.side_effect = RuntimeError("mcp down")
    assert fe.notify_folder_deleted("f", "t") is False


def test_renamed_register_failure_returns_false():
    """renamed:卸舊成功、掛新失敗 → 回 False(工具面未收斂到新狀態要讓 caller 知道)。"""
    reg, unreg = _install()
    reg.side_effect = RuntimeError("register down")
    assert fe.notify_folder_renamed("old", "new", "d", "t") is False
    unreg.assert_called_once()
