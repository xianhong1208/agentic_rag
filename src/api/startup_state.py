
"""啟動期能力載入狀態(M15)。

app.py 載入 router / MCP tools / module 時用 broad try/except,失敗只記 log,
server 仍會啟動 → 該端點靜默 404,/health 卻顯示 healthy。這裡登記載入失敗,
讓 /health/detailed 反映「哪些能力掛了」,能力流失不再無聲。

模組級單例(startup 一次性寫入,之後唯讀),零外部依賴。
"""

from typing import Dict

_LOAD_FAILURES: Dict[str, str] = {}


def record_load_failure(name: str, error) -> None:
    """登記一個載入失敗。error 可為例外物件(存類型名,不外洩完整訊息)或字串。"""
    _LOAD_FAILURES[name] = (
        type(error).__name__ if isinstance(error, BaseException) else str(error)
    )


def get_load_failures() -> Dict[str, str]:
    """回傳載入失敗的副本(name -> 原因)。空 dict = 全部載入成功。"""
    return dict(_LOAD_FAILURES)


def clear_load_failures() -> None:
    """清空(測試用;正常執行期不呼叫)。"""
    _LOAD_FAILURES.clear()
