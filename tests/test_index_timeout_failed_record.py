
"""逾時失敗必須留下 FileIndex failed 記錄的回歸測試

2026-08-13 實測(慢機台 + 200 頁 PDF):單檔超過 per_file_timeout →
_with_timeout 的 asyncio.wait_for 取消 index_document,注入的是
CancelledError(BaseException,非 Exception)→ index_document 內層的
except Exception 接不到 → 它的 mark_index_failed 不會執行。而批次迴圈的
except 當時也沒補寫 → 逾時檔在 DB 完全沒有 FileIndex 記錄 → 前端 indexed
清單沒它、active job 已終態也沒它 → 檔案列完全沒有狀態 tag。

契約:批次索引(index_files / index_folder)的 per-file except 一律
persist 一筆 failed FileIndex 記錄,前端才顯示得出「失敗」。
"""

import asyncio

import pytest

from src.adapter.rag_indexing import _with_timeout


async def test_with_timeout_raises_TimeoutError_and_cancels_inner():
    """_with_timeout 逾時:取消內層 + 拋 TimeoutError(重現 cancel 語意)"""
    cancelled = {"v": False}

    async def slow():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled["v"] = True
            raise

    with pytest.raises(TimeoutError):
        await _with_timeout(slow(), timeout_seconds=1, filename="big.pdf")
    # 讓被取消的 coroutine 收尾
    await asyncio.sleep(0.05)
    assert cancelled["v"], "逾時應真的 cancel 內層 coroutine"


def test_cancellederror_is_not_caught_by_except_exception():
    """核心陷阱的守門:CancelledError 是 BaseException,except Exception 接不到。

    這是整個 bug 的根源 — 若哪天 Python 改變此繼承關係,或有人把 index_document
    的 except 改成 except BaseException,本測試提醒重新評估兜底邏輯。
    """
    assert issubclass(asyncio.CancelledError, BaseException)
    assert not issubclass(asyncio.CancelledError, Exception)

    caught_by_exception = False
    try:
        raise asyncio.CancelledError()
    except Exception:  # noqa: BLE001 - 故意示範接不到
        caught_by_exception = True
    except asyncio.CancelledError:
        pass
    assert caught_by_exception is False


def test_timeout_status_label_is_timeout():
    """逾時的 timing entry status 標為 'timeout'(與一般 failed 區分,利於排錯)"""
    from src.adapter.rag_indexing import _make_timing_entry
    import time

    e = _make_timing_entry("fid", "big.pdf", "timeout", time.perf_counter(), {})
    assert e["status"] == "timeout"
