
"""Regression tests for the indexing-job keepalive heartbeat.

背景:IndexingJobManager 的 watchdog 在 600s 沒心跳就把 job 翻成 FAILED 並
cancel 掉 task,但單檔預算(_PER_FILE_TIMEOUT_DEFAULT,現預設 864000s / 10 天)
遠大於 watchdog —— 兩道防線預算差距懸殊。落在心跳盲區(semaphore 等待 /
docling OCR / context-gen 節流間隙)的慢檔案會在 per-file timeout 到期前先被
watchdog 誤殺,在較慢的機器上重現。

_ProgressKeepalive 負責在閒置時原地補心跳,讓「慢」不再被誤判成「死」;
真正 hang 住的檔案仍由 per-file 的 wait_for 兜底。
"""

import asyncio

from src.adapter.rag_indexing import _ProgressKeepalive, _keepalive_stage_label


async def test_keepalive_emits_while_idle():
    """閒置超過 interval 就要補心跳 —— 這是 watchdog 不誤殺的唯一依據。"""
    seen = []
    async with _ProgressKeepalive(lambda s, d, t: seen.append((s, d, t)), interval=0.05):
        await asyncio.sleep(0.3)

    # 尚未回報任何真實進度時,補的是初始的 "queued"(涵蓋 semaphore 等待盲區)
    assert len(seen) >= 3, f"expected repeated keepalive ticks, got {seen}"
    assert all(stage == "queued" for stage, _, _ in seen)


async def test_keepalive_repeats_last_stage_verbatim():
    """補心跳必須原樣重送 stage,不得加註 elapsed。

    micore-portal 的 IndexingStatusBadge 用 STAGE_LABEL[stage] 查中文標籤
    (fallback 為原字串)。stage 一旦被改寫成 "loading (8m20s)" 就查不到,
    badge 會從「解析文件」退化成英文 —— 偏偏發生在解析最久的時候。
    """
    seen = []
    keepalive = _ProgressKeepalive(lambda s, d, t: seen.append((s, d, t)), interval=0.05)
    async with keepalive:
        keepalive("loading", None, None)   # 一次真實進度
        await asyncio.sleep(0.2)

    assert seen[0] == ("loading", None, None)
    assert len(seen) >= 2, "keepalive should have topped up after the real tick"
    assert all(stage == "loading" for stage, _, _ in seen)


async def test_real_progress_suppresses_keepalive():
    """正常速度的檔案不該產生任何額外 tick(否則 SSE / DB 白白多寫)。"""
    seen = []
    keepalive = _ProgressKeepalive(lambda s, d, t: seen.append((s, d, t)), interval=0.5)
    async with keepalive:
        for done in range(5):
            keepalive("embedding", done, 5)
            await asyncio.sleep(0.02)      # 累計 0.1s,遠低於 interval

    assert seen == [("embedding", i, 5) for i in range(5)]


async def test_keepalive_stops_after_exit():
    """離開 context 後背景 task 必須停 —— 否則 job 結束了還在假裝活著。"""
    seen = []
    async with _ProgressKeepalive(lambda s, d, t: seen.append(s), interval=0.05):
        await asyncio.sleep(0.15)
    settled = len(seen)

    await asyncio.sleep(0.2)
    assert len(seen) == settled


async def test_callback_failure_does_not_break_indexing():
    """進度回報失敗不得影響索引本身(與既有 call site 的處理一致)。"""
    def boom(stage, done, total):
        raise RuntimeError("progress sink down")

    async with _ProgressKeepalive(boom, interval=0.05):
        await asyncio.sleep(0.15)     # 不應拋出


def test_stage_label_is_passthrough():
    """契約測試:stage 標籤原樣回傳,elapsed 不得編碼進去。"""
    assert _keepalive_stage_label("loading", 0.0) == "loading"
    assert _keepalive_stage_label("contextualizing", 9999.0) == "contextualizing"
