
"""排隊上傳的 job 身分回歸測試

背景(2026-08 同事實測):folder 忙碌時上傳,回應拿到的是「別人的
job_id」,drain 後真正的 job 又換了新 id — 前端看起來就是「job 紀錄
消失/被覆蓋」。刪除後立刻重傳同檔最容易重現(撞上前 job 收尾窗口)。

修正後的契約:排隊的上傳**入佇列當下**就有自己的 PENDING job 紀錄,
job_id 從回應 → 排隊 → RUNNING → 終態全程不變;排隊期間被取消的 job
由 dequeue 自動跳過。
"""

import asyncio

import pytest
from unittest.mock import patch

from src.domain.rag.index_job_manager import IndexingJobManager, JobStatus


class SlowAdapter:
    """可控完成時機的 stub adapter。"""

    def __init__(self):
        self.release = asyncio.Event()
        self.calls: list = []

    async def index_files(self, *, file_ids, folder_id, token, chunk_size,
                          chunk_overlap, progress_tracker):
        self.calls.append(list(file_ids))
        progress_tracker.on_started(len(file_ids), False)
        await self.release.wait()
        self.release.clear()
        progress_tracker.mark_completed(
            {"total_files": len(file_ids), "successful": len(file_ids), "failed": 0})


@pytest.fixture()
def manager():
    with patch("db.indexjobdb.IndexJobDB.upsert"), \
         patch("db.indexjobdb.IndexJobDB.ensure_table"), \
         patch("db.fileindexdb.FileIndexDB.ensure_content_hash_columns"), \
         patch.object(IndexingJobManager, "_persist", lambda self, d: None):
        yield IndexingJobManager()


async def _wait_status(m, job_id, statuses, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        st = await m.get_status(job_id)
        if st and st["status"] in statuses:
            return st
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} 沒到達 {statuses}: {st}")


async def test_queued_upload_gets_own_stable_job_id(manager):
    """排隊上傳立刻有自己的 job_id,且全生命週期不變(TC-job-queue-01)"""
    ad = SlowAdapter()
    j1 = await manager.start_indexing_files(
        ad, file_ids=["f1"], folder_id=7, token="t", chunk_size=None, chunk_overlap=None)

    # folder 忙碌中再上傳 → 必須拿到「自己的」新 job_id,不是 j1 的
    j2 = await manager.start_indexing_files(
        ad, file_ids=["f2"], folder_id=7, token="t", chunk_size=None, chunk_overlap=None)
    assert j2["job_id"] != j1["job_id"], "排隊上傳不能回別人的 job_id(舊 bug)"
    assert j2["status"] == "pending" and j2["queued"] is True

    # 排隊的 job 立刻出現在列表(前端看得到「排隊中」)
    listed = {j["job_id"] for j in manager.list_jobs(folder_id=7)}
    assert j2["job_id"] in listed

    # 前一個 job 完成 → 排隊 job 以「同一個 id」啟動並完成
    ad.release.set()
    await _wait_status(manager, j1["job_id"], {"succeeded"})
    await _wait_status(manager, j2["job_id"], {"running"})
    assert ad.calls[-1] == ["f2"], "dequeue 啟動的就是排隊那批檔案"
    ad.release.set()
    await _wait_status(manager, j2["job_id"], {"succeeded"})


async def test_queued_job_started_at_reset_on_launch(manager):
    """排隊 job 的 started_at 在真正啟動時重設,不含排隊等待(TC-job-queue-03)

    舊怪癖:started_at 在 enqueue 當下就定,dequeue 啟動後不變 → 前端把
    排隊等待也算進耗時。修正後 started_at = 真正開始執行的時刻。
    """
    ad = SlowAdapter()
    j1 = await manager.start_indexing_files(
        ad, file_ids=["x"], folder_id=9, token="t", chunk_size=None, chunk_overlap=None)
    j2 = await manager.start_indexing_files(
        ad, file_ids=["y"], folder_id=9, token="t", chunk_size=None, chunk_overlap=None)
    assert j2["queued"] is True

    # 排隊當下的 started_at(= 入佇列時刻)
    queued_started_at = (await manager.get_status(j2["job_id"]))["started_at"]

    # 讓排隊等待有可測量的間隔(ISO8601 UTC 字串可直接字典序比較)
    await asyncio.sleep(0.05)

    # j1 完成 → j2 dequeue 真正啟動
    ad.release.set()
    await _wait_status(manager, j1["job_id"], {"succeeded"})
    await _wait_status(manager, j2["job_id"], {"running"})

    running_started_at = (await manager.get_status(j2["job_id"]))["started_at"]
    assert running_started_at > queued_started_at, (
        "排隊 job 啟動時 started_at 應重設為啟動時刻,不該還停在入佇列時刻"
    )
    ad.release.set()
    await _wait_status(manager, j2["job_id"], {"succeeded"})


async def test_stale_cleanup_reentry_does_not_drain_queue(manager):
    """非持有者的遲到 cleanup 不得 drain 佇列 / 搶佔 folder lock(TC-job-queue-04)

    情境:H4 watchdog 強制回收 job1 的 lock 並 dequeue job2 後,job1 那個
    wedged thread 終於跑完、finally 第二次呼叫 _cleanup_job_slot(job1)。
    此時 job1 已非 lock 持有者 —— 若 drain 段無所有權守衛,它會把佇列中的
    job3 也啟動並搶佔 lock → job2 與 job3 並發同寫一張表。
    """
    ad = SlowAdapter()
    j1 = await manager.start_indexing_files(
        ad, file_ids=["a"], folder_id=11, token="t", chunk_size=None, chunk_overlap=None)
    j2 = await manager.start_indexing_files(
        ad, file_ids=["b"], folder_id=11, token="t", chunk_size=None, chunk_overlap=None)
    assert j2["queued"] is True
    # 等 j1 真正開跑(create_task 後需出讓點,calls 才會記到 ["a"])
    await _wait_status(manager, j1["job_id"], {"running"})

    # 模擬「已被 reclaim 的 job」遲到重入:呼叫者已不是 lock 持有者
    manager._cleanup_job_slot("stale-ghost-job-id", 11)

    # lock 仍屬 j1、j2 仍安靜排隊、沒有任何新 job 被啟動
    assert manager._active_folders.get(11) == j1["job_id"], "非持有者不得動 folder lock"
    assert ad.calls == [["a"]], "非持有者的 cleanup 不得啟動排隊 job"
    assert (await manager.get_status(j2["job_id"]))["status"] == "pending"

    # 守衛不得破壞正常鏈:j1 完成 → j2 照常以同 id dequeue 執行
    ad.release.set()
    await _wait_status(manager, j1["job_id"], {"succeeded"})
    await _wait_status(manager, j2["job_id"], {"running"})
    ad.release.set()
    await _wait_status(manager, j2["job_id"], {"succeeded"})


async def test_cancelled_queued_job_is_skipped_at_dequeue(manager):
    """排隊期間被取消的 job,dequeue 自動跳過、輪到下一個(TC-job-queue-02)"""
    ad = SlowAdapter()
    j1 = await manager.start_indexing_files(
        ad, file_ids=["a"], folder_id=8, token="t", chunk_size=None, chunk_overlap=None)
    j2 = await manager.start_indexing_files(
        ad, file_ids=["b"], folder_id=8, token="t", chunk_size=None, chunk_overlap=None)
    j3 = await manager.start_indexing_files(
        ad, file_ids=["c"], folder_id=8, token="t", chunk_size=None, chunk_overlap=None)

    # 排隊中取消 j2(對應「上傳後馬上刪檔」)
    assert await manager.cancel_job(j2["job_id"]) is True
    st2 = await manager.get_status(j2["job_id"])
    assert st2["status"] == "cancelled"

    # j1 完成 → 跳過 j2,直接啟動 j3(同 id)
    ad.release.set()
    await _wait_status(manager, j1["job_id"], {"succeeded"})
    await _wait_status(manager, j3["job_id"], {"running"})
    assert ad.calls[-1] == ["c"]
    ad.release.set()
    await _wait_status(manager, j3["job_id"], {"succeeded"})
    # j2 維持 cancelled,沒有被 dequeue 復活
    assert (await manager.get_status(j2["job_id"]))["status"] == "cancelled"
