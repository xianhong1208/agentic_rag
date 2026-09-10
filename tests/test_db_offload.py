
"""M1 前置回歸測試 — 阻塞 DB helper 的 event-loop offload。

背景:索引 async 路徑原本直接呼叫同步 SQLAlchemy helper(baseDB 每次
`with Session()`),query 期間卡住 event loop → 高並發時 API/SSE/cancel/query
一起頓。_run_db 把這類阻塞呼叫丟到 worker thread,不佔 loop。

這份測試鎖住核心契約:_run_db 真的在「非事件迴圈執行緒」上跑那個函式,
且結果/例外原樣傳遞。純邏輯,零外部依賴。
"""

import asyncio
import threading

import pytest

from src.adapter.rag_indexing import _run_db


async def test_run_db_executes_off_loop_thread():
    """_run_db 必須在別的執行緒跑 —— 這是「不佔 event loop」的唯一依據。"""
    loop_thread = threading.get_ident()
    seen = {}

    def _blocking():
        seen["thread"] = threading.get_ident()
        return "ok"

    result = await _run_db(_blocking)
    assert result == "ok"
    assert seen["thread"] != loop_thread, "DB helper 仍在 event loop 執行緒上跑(沒 offload)"


async def test_run_db_passes_args_and_returns():
    """位置 + 關鍵字參數原樣帶過去,回傳值原樣拿回來。"""
    def _add(a, b, *, c=0):
        return a + b + c

    assert await _run_db(_add, 2, 3, c=5) == 10


async def test_run_db_propagates_exception():
    """helper 拋的例外要原樣往上傳(呼叫端才接得到、走既有錯誤處理)。"""
    def _boom():
        raise ValueError("db exploded")

    with pytest.raises(ValueError, match="db exploded"):
        await _run_db(_boom)
