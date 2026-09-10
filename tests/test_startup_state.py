
"""M15 前置回歸測試 — 啟動期能力載入失敗登記表。

背景:app.py 載入 router/module 用 broad try/except,失敗只記 log → server 照常
啟動且 /health 顯示 healthy,但該端點靜默 404(能力靜默流失,排查困難)。
startup_state 把載入失敗登記起來,讓 /health/detailed 反映出「哪些能力掛了」。

純邏輯,零外部依賴。
"""

import pytest

from src.api import startup_state


@pytest.fixture(autouse=True)
def _clean():
    startup_state.clear_load_failures()
    yield
    startup_state.clear_load_failures()


def test_record_and_get():
    startup_state.record_load_failure("rag_indexing", ImportError("boom"))
    failures = startup_state.get_load_failures()
    assert "rag_indexing" in failures
    # 存例外類型名(不外洩完整訊息;細節在 log)
    assert failures["rag_indexing"] == "ImportError"


def test_get_returns_copy_not_internal():
    """回傳應是副本,呼叫端改它不影響內部狀態。"""
    startup_state.record_load_failure("m", ValueError("x"))
    got = startup_state.get_load_failures()
    got["injected"] = "y"
    assert "injected" not in startup_state.get_load_failures()


def test_clear():
    startup_state.record_load_failure("m", RuntimeError("x"))
    startup_state.clear_load_failures()
    assert startup_state.get_load_failures() == {}


def test_string_error_accepted():
    """也接受純字串原因(非例外物件)。"""
    startup_state.record_load_failure("m", "custom reason")
    assert startup_state.get_load_failures()["m"] == "custom reason"
