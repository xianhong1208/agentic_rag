
"""Background indexing job manager

Provides utilities to run folder indexing in background tasks and track progress.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from cachetools import TTLCache

from src.config.model import IndexingConfig  # M10: timeout default 單一來源
from src.domain.exceptions import ConflictError
from src.log import get_api_logger

logger = get_api_logger()


class JobStatus(str, Enum):
    """Index job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"   # some files indexed, some failed
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal statuses that release the per-folder lock and allow cleanup
_TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.PARTIAL_SUCCESS,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


@dataclass
class _PendingFileBatch:
    """A file-indexing request that arrived while the folder was busy.

    每個 batch 在入佇列時就擁有**自己的 job 紀錄**(PENDING 狀態、穩定的
    job_id)— 上傳回應與 /index/jobs 列表從第一刻就看得到它。前一個 job
    結束時,_cleanup_job_slot 依序啟動佇列中下一個仍為 PENDING 的 job
    (被取消的自動跳過),job_id 全程不變。

    (舊設計:busy 時回傳「別人的 job_id」,drain 再生全新 id 的合併 job —
    前端永遠學不到新 id,看起來就是「job 紀錄消失/被覆蓋」。)
    """

    job_id: str
    adapter: Any
    file_ids: List[str]
    folder_id: int
    token: str
    chunk_size: Optional[int]
    chunk_overlap: Optional[int]


@dataclass
class IndexJobState:
    """Runtime state for a background indexing job."""

    job_id: str
    folder_id: int
    status: JobStatus = JobStatus.PENDING
    total_files: int = 0
    processed_files: int = 0
    current_index: int = 0
    current_file_id: Optional[str] = None
    current_file_name: Optional[str] = None
    last_file_status: Optional[str] = None
    last_message: Optional[str] = None
    message: str = "Waiting to start"
    error: Optional[str] = None
    skip_existing: bool = True
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None
    # 此 job 處理的 file_ids;只有 file-scoped jobs 填,folder-wide 留空
    scope_file_ids: List[str] = field(default_factory=list)
    # A3 heartbeat watchdog: refreshed on every _update_job_state call.
    last_updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # per-file timing: {file_id, file_name, status, total_ms, load_ms, index_ms, chunks}
    file_timings: List[Dict[str, Any]] = field(default_factory=list)
    # chunk 級進度(僅 current file)。in-memory + SSE 即時視圖,不落 DB —
    # 檔案完成即被 reset;重啟後 job 會被翻 failed,殘值無意義。
    # stage: loading(docling 解析)/ contextualizing(LLM 前綴)/ embedding / writing(pgvector 寫入)
    current_file_stage: Optional[str] = None
    current_file_chunks_done: Optional[int] = None
    current_file_chunks_total: Optional[int] = None
    # ETA(秒)— 同 chunk 進度:in-memory + SSE 即時視圖,不落 DB。
    # current_file_eta_seconds:目前 stage 按實測速率外推的剩餘秒數
    #   (stage 剛切換 / 尚無速率樣本時為 None,前端顯示「估算中」)
    # eta_seconds:整個 job 的粗估 = 已完成檔平均耗時 × 剩餘檔數 − 當前檔已耗時
    #   (第一個檔完成前為 None)
    current_file_eta_seconds: Optional[int] = None
    eta_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable copy of the job state."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


class IndexProgressTracker:
    """Callback helper used by RAGAdapter while indexing."""

    def __init__(self, manager: "IndexingJobManager", job_id: str):
        self._manager = manager
        self._job_id = job_id

    def on_started(self, total_files: int, skip_existing: bool):
        self._manager._update_job_state(
            self._job_id,
            total_files=total_files,
            skip_existing=skip_existing,
            message="Indexing started" if total_files else "Preparing indexing",
            status=JobStatus.RUNNING,
            processed_files=0,
            current_index=0,
            current_file_id=None,
            current_file_name=None,
        )

    def on_file_started(
        self,
        current_index: int,
        file_id: str,
        file_name: str,
    ):
        self._manager._note_file_started(self._job_id)
        self._manager._update_job_state(
            self._job_id,
            current_index=current_index,
            current_file_id=file_id,
            current_file_name=file_name,
            message=f"Indexing file {current_index}: {file_name}",
            current_file_stage=None,
            current_file_chunks_done=None,
            current_file_chunks_total=None,
            current_file_eta_seconds=None,
        )

    def on_chunk_progress(
        self,
        stage: str,
        done: Optional[int],
        total: Optional[int],
    ):
        """chunk 級進度(indexer 節流後呼叫:context-gen 每 10 chunk、embedding 每批)。

        Args:
            stage: loading / contextualizing / embedding / writing。
            done: 該 stage 已完成 chunk 數。
            total: 此檔 chunk 總數。
        """
        # ETA 計算與進度更新一起做(stage 速率外推 + job 級粗估)
        self._manager._update_chunk_progress(self._job_id, stage, done, total)

    def on_file_completed(
        self,
        processed_files: int,
        status: str,
        message: str,
    ):
        self._manager._update_job_state(
            self._job_id,
            processed_files=processed_files,
            last_file_status=status,
            last_message=message,
            current_file_stage=None,
            current_file_chunks_done=None,
            current_file_chunks_total=None,
            current_file_eta_seconds=None,
        )

    def record_file_timing(self, entry: Dict[str, Any]) -> None:
        """把一筆 per-file timing 追加到 job state(每檔完成後 indexing service 呼叫)。

        list 是 result_summary 的一部分,讓消費端排序「哪檔最慢」不必 parse log。

        Args:
            entry: ``{file_id, file_name, status, total_ms, load_ms, index_ms}``。
        """
        with self._manager._lock:
            state = self._manager._jobs.get(self._job_id)
            if not state:
                return
            # 同 _update_job_state 的終態閘:terminal 後遲到的 timing 不再寫入
            if state.status in _TERMINAL_STATUSES:
                return
            state.file_timings.append(entry)
            # 剛完成一檔 = job ETA 的最佳更新時點(檔與檔之間,current elapsed=None)
            state.eta_seconds = self._manager._compute_job_eta_locked(
                state, current_file_elapsed=None
            )
            state.last_updated_at = datetime.now(timezone.utc).isoformat()
            snapshot = state.to_dict()
        # file_timings is a write-heavy field; persist outside the lock
        self._manager._persist(snapshot)

    def mark_completed(self, summary: Dict[str, Any]):
        # 終態:全成功→SUCCEEDED;部份失敗→PARTIAL_SUCCESS;0 成功 ≥1 失敗→FAILED
        successful = summary.get("successful", 0) or 0
        failed = summary.get("failed", 0) or 0
        if failed > 0 and successful == 0:
            status = JobStatus.FAILED
        elif failed > 0:
            status = JobStatus.PARTIAL_SUCCESS
        else:
            status = JobStatus.SUCCEEDED

        self._manager._update_job_state(
            self._job_id,
            status=status,
            message=summary.get("message", "Indexing completed"),
            processed_files=summary.get("total_files", 0),
            current_index=summary.get("total_files", 0),
            current_file_id=None,
            current_file_name=None,
            result_summary=summary,
            completed_at=datetime.now(timezone.utc).isoformat(),
            eta_seconds=0,
            current_file_eta_seconds=None,
        )

    def mark_failed(self, error: str):
        self._manager._update_job_state(
            self._job_id,
            status=JobStatus.FAILED,
            error=error,
            message="Indexing failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


class IndexingJobManager:
    """Singleton manager coordinating background indexing jobs."""

    _instance: Optional["IndexingJobManager"] = None

    # Job state retention — completed jobs stay queryable for 24h then evict.
    # Caps total entries at 10k to bound memory if many indexing jobs fire.
    _JOB_TTL_SECONDS = 86400
    _JOB_MAX_ENTRIES = 10000

    # A3 watchdog tunables — scan every 60s, stale after 10min without heartbeat
    #
    # ⚠️ 不變式:這個門檻**不是**單檔耗時上限,那是 per-file 的
    # wait_for(_PER_FILE_TIMEOUT_DEFAULT,現預設 864000s / 10 天)在管的。
    # 這裡只負責偵測「job 真的死了」。注意兩者差距懸殊(600s vs 10 天,1440 倍):
    # 合法但慢的檔案落在心跳盲區(semaphore 等待 / docling OCR / context-gen
    # 節流間隙)時,會在 per-file 預算用完前先被這裡誤殺並 cancel 掉。
    # 現在由 rag_indexing._ProgressKeepalive 每 60s 補心跳覆蓋所有盲區;
    # 調小這個值、或新增不經 progress_cb 的長阻塞路徑前,先確認 keepalive 有蓋到。
    _WATCHDOG_INTERVAL_SECONDS = 60
    _HEARTBEAT_STALE_SECONDS = 600
    # H4: folder lock 的正常唯一出口是 _cleanup_job_slot(task finally)。task 若卡在
    # 無法中斷的阻塞呼叫(docling/GPU 真 hang、驅動卡死),finally 永不執行 → folder
    # 永久鎖死,該 folder 之後所有索引 409 直到 process 重啟。這是最後兜底:job 已
    # 終態、但持鎖 task 過了這個寬限期仍沒退出,就強制回收 lock(接受「垂死 thread
    # 之後若醒來寫入」的殘寫風險 —— 大聲記 error)。設 1h:遠大於任何合法阻塞呼叫
    # (embedding 批次 / insert)的耗時,只會咬到真正 wedged 的 task。
    _LOCK_RECLAIM_GRACE_SECONDS = 3600

    # D2 fallback job-level cap — only used if config can't be read at all.
    # 與 IndexingConfig.job_timeout_seconds 的 default 對齊(10 天)。
    # Normal resolution: env RAG_JOB_TIMEOUT_SECONDS > config.rag.indexing.job_timeout_seconds > this.
    # M10: 引用 IndexingConfig 欄位 default,不再各處各寫一份 864000 字面值。
    _JOB_TIMEOUT_FALLBACK = IndexingConfig.model_fields["job_timeout_seconds"].default

    # cancel_job 等 task 真正退出的上限。to_thread 內的阻塞呼叫(embedding 批次/
    # bulk insert)無法中斷,只能等它跑完這一步;30s 蓋得住單批最壞情況。
    _CANCEL_WAIT_SECONDS = 30

    def __init__(self):
        # TTLCache avoids the unbounded-dict memory leak from earlier impl;
        # GET also returns None for expired keys, matching the old dict.get() contract.
        self._jobs: "TTLCache[str, IndexJobState]" = TTLCache(
            maxsize=self._JOB_MAX_ENTRIES,
            ttl=self._JOB_TTL_SECONDS,
        )
        self._lock = Lock()
        # #28 folder-level lock — at most one running job per folder
        self._active_folders: Dict[int, str] = {}
        # Per-folder queue of file-indexing batches that arrived during a
        # running job. Drained by _cleanup_job_slot when the running job
        # terminates, spawning a single merged follow-up job. Lets users
        # batch-upload many files without hitting "Folder already has a
        # running indexing job" and silently losing 9/10 files.
        self._pending_file_batches: Dict[int, List[_PendingFileBatch]] = {}
        # A1 cancellation — track the asyncio.Task for each running job
        self._task_handles: Dict[str, asyncio.Task] = {}
        # ETA 計算的內部追蹤(不進 state,避免 API 噪音):
        # {job_id: {"file_start": ts, "stage": str, "stage_start": ts, "baseline": int}}
        self._progress_track: Dict[str, Dict[str, Any]] = {}
        # per-file abort flags — 檔案刪除時由 FileAdapter.delete_file 標記,
        # adapter 的 mid-stage probe 消費(消費即清除)。TTL 兜底:pending 檔
        # 由 gate 1 的 DB probe 擋下、不會來消費 flag,靠過期回收避免累積。
        self._file_abort_flags: "TTLCache[str, bool]" = TTLCache(
            maxsize=4096, ttl=self._JOB_TTL_SECONDS,
        )
        # A3 watchdog handle (idempotent start)
        self._watchdog_task: Optional[asyncio.Task] = None
        # M8: 主 event loop 參照,供 worker thread 的進度回報 thread-safe 地喚醒 SSE。
        # 在 start_watchdog(必在 loop thread 內)捕獲。
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # fire-and-forget 背景 task(drain 等)的強引用 — asyncio 只留 weak ref,
        # 沒有這個 set,queued job 可能在執行前被 GC 掉
        self._bg_tasks: Set[asyncio.Task] = set()
        # DB persist 專用單工 executor:upsert 是 sync SQLAlchemy(SELECT+commit),
        # 直接在 event loop 上跑會在每個進度 tick 卡住整個 server(API/SSE/cancel)。
        # 單 worker 保證寫入順序(亂序會讓舊 snapshot 蓋掉新的)。
        self._persist_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="idxjob-persist",
        )
        # D1 (SSE) — per-job event subscribers. Each value is the list of live
        # asyncio.Queue subscribers waiting for state updates of that job.
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        # ensure the IndexJobs table exists; persistence is best-effort
        # (a DB failure here does not break the in-memory manager).
        try:
            from db.indexjobdb import IndexJobDB
            IndexJobDB.ensure_table()
        except Exception as e:
            logger.warning(f"IndexJobs table init skipped (will run in-memory only): {e}")
        # 借用 manager bootstrap 順便補 content_hash 欄位
        try:
            from db.fileindexdb import FileIndexDB
            FileIndexDB.ensure_content_hash_columns()
        except Exception as e:
            logger.warning(f"content_hash columns migration skipped: {e}")

    @classmethod
    def get_instance(cls) -> "IndexingJobManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _resolve_job_timeout(cls) -> int:
        """解析整 job timeout 秒數。

        優先序:env RAG_JOB_TIMEOUT_SECONDS > config.rag.indexing.job_timeout_seconds > fallback。

        Returns:
            上限秒數;<=0 不設限。
        """
        import os
        env_val = os.getenv("RAG_JOB_TIMEOUT_SECONDS")
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                logger.warning(
                    f"Invalid RAG_JOB_TIMEOUT_SECONDS={env_val!r}, using config/default"
                )
        try:
            from src.config.config_manager import Config
            cfg = Config.get_config_model()
            if cfg and cfg.rag and cfg.rag.indexing:
                return cfg.rag.indexing.job_timeout_seconds
        except Exception as e:
            logger.warning(f"Failed to read job_timeout_seconds from config: {e}")
        return cls._JOB_TIMEOUT_FALLBACK

    async def start_indexing(
        self,
        adapter,
        *,
        folder_id: int,
        token: str,
        chunk_size: Optional[int],
        chunk_overlap: Optional[int],
        skip_existing: bool,
    ) -> Dict[str, Any]:
        """Schedule folder indexing in the background."""
        job_id = str(uuid.uuid4())
        state = IndexJobState(job_id=job_id, folder_id=folder_id, skip_existing=skip_existing)

        # reject if this folder already has a live job
        with self._lock:
            if folder_id in self._active_folders:
                existing = self._active_folders[folder_id]
                raise ConflictError(
                    message=f"Folder {folder_id} already has a running indexing job: {existing}",
                    resource=f"indexing_job:{folder_id}",
                )
            self._jobs[job_id] = state
            self._active_folders[folder_id] = job_id

        # initial persist so the job is queryable from DB immediately
        self._persist(state.to_dict())

        tracker = IndexProgressTracker(self, job_id)

        job_timeout = self._resolve_job_timeout()

        async def _run_folder():
            try:
                core = adapter.index_folder(
                    folder_id=folder_id,
                    token=token,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    skip_existing=skip_existing,
                    progress_tracker=tracker,
                )
                # job-level hard timeout. <=0 disables the cap.
                if job_timeout and job_timeout > 0:
                    await asyncio.wait_for(core, timeout=job_timeout)
                else:
                    await core
            except asyncio.CancelledError:
                logger.info(f"Indexing job {job_id} cancelled")
                raise
            except asyncio.TimeoutError:
                logger.error(
                    f"Indexing job {job_id} exceeded job_timeout={job_timeout}s — marking failed"
                )
                tracker.mark_failed(f"Job exceeded {job_timeout}s job-level timeout")
            except Exception as exc:
                logger.error(
                    f"Indexing job {job_id} for folder {folder_id} failed: {exc}"
                )
                tracker.mark_failed(str(exc))
            finally:
                self._cleanup_job_slot(job_id, folder_id)

        # asyncio task,不開 thread — index_folder 本身就 async,而且把它丟到 thread pool
        # 加 asyncio.run 會吃掉一個 worker thread 整個 indexing 過程,32 個並發 job 就把
        # pool 卡死(包括 STT/OCR 的 run_in_threadpool 都 block)。
        task = asyncio.create_task(_run_folder())
        with self._lock:
            self._task_handles[job_id] = task

        logger.info(
            f"Scheduled indexing job {job_id} for folder {folder_id} (skip_existing={skip_existing})"
        )

        return state.to_dict()

    async def start_indexing_files(
        self,
        adapter,
        *,
        file_ids: list,
        folder_id: int,
        token: str,
        chunk_size: Optional[int],
        chunk_overlap: Optional[int],
    ) -> Dict[str, Any]:
        """Schedule indexing of specific files in the background.

        Used for auto-indexing on file upload. Only indexes the specified files,
        not the entire folder.

        Args:
            adapter: RAGAdapter instance
            file_ids: List of file IDs (UUID strings) to index
            folder_id: Target folder ID
            token: User token
            chunk_size: Chunk size (None = use default)
            chunk_overlap: Chunk overlap (None = use default)

        Returns:
            Job state dictionary
        """
        job_id = str(uuid.uuid4())
        state = IndexJobState(job_id=job_id, folder_id=folder_id, skip_existing=False)
        # Part 3 — record planned scope so per-file status endpoint can detect "queued"
        state.scope_file_ids = [str(fid) for fid in file_ids]

        # folder lock applies to file-scoped jobs too — but unlike start_indexing
        # (which rejects), we queue the batch and let it drain after the current
        # job finishes. This is the upload-N-files-in-a-row case: file 1 starts
        # a job, file 2…10 used to fail with AUTO_INDEX_FAIL. Now they queue.
        #
        # ⚠️ 排隊的上傳也**立刻**擁有自己的 job 紀錄(PENDING、穩定 job_id)。
        # 舊設計回「別人的 job_id」+ drain 生新 id:前端拿到的 id 可能瞬間
        # terminal(如「刪除後馬上重傳」撞上前 job 收尾),真正的 follow-up
        # job 又換了 id — 使用者看到的就是「job 紀錄消失/被覆蓋」。
        with self._lock:
            if folder_id in self._active_folders:
                existing = self._active_folders[folder_id]
                state.message = f"Queued behind job {existing}"
                self._jobs[job_id] = state
                self._pending_file_batches.setdefault(folder_id, []).append(
                    _PendingFileBatch(
                        job_id=job_id,
                        adapter=adapter,
                        file_ids=[str(fid) for fid in file_ids],
                        folder_id=folder_id,
                        token=token,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                )
                pending_total = sum(
                    len(b.file_ids) for b in self._pending_file_batches[folder_id]
                )
                queued = True
            else:
                self._jobs[job_id] = state
                self._active_folders[folder_id] = job_id
                queued = False

        if queued:
            self._persist(state.to_dict())
            logger.info(
                f"Folder {folder_id} busy with job {existing}; queued job {job_id} "
                f"({len(file_ids)} file(s), total pending: {pending_total})"
            )
            # 舊契約的 "queued": True 保留給呼叫端顯示;job_id 就是自己的,
            # 之後 RUNNING → terminal 全程同一個 id
            return {**state.to_dict(), "queued": True}

        self._launch_file_job(
            state, adapter,
            file_ids=[str(fid) for fid in file_ids],
            folder_id=folder_id, token=token,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )
        return state.to_dict()

    def _launch_file_job(
        self,
        state: IndexJobState,
        adapter,
        *,
        file_ids: List[str],
        folder_id: int,
        token: str,
        chunk_size: Optional[int],
        chunk_overlap: Optional[int],
    ) -> None:
        """啟動一個 file-scoped job(caller 必須已把 folder lock 給這個 job)。

        start_indexing_files 的即時路徑與 _cleanup_job_slot 的 dequeue 路徑共用,
        保證兩條路徑啟動的 job 行為完全一致(timeout / cancel / cleanup / drain)。
        必須在 event loop 內呼叫(create_task)。
        """
        job_id = state.job_id
        # started_at = 真正開始執行的時刻,不是入佇列時刻。排隊 job 在 enqueue
        # 時就建了 state(started_at=當時),真正啟動可能是幾分鐘後 dequeue ——
        # 這裡重設,前端顯示的耗時才不會把排隊等待也算進去。即時路徑重設約等於
        # no-op(state 剛建好)。watchdog 用 last_updated_at 判活、ETA 用 per-file
        # 均值,兩者都不看 started_at,重設無副作用。
        state.started_at = datetime.now(timezone.utc).isoformat()
        self._persist(state.to_dict())
        tracker = IndexProgressTracker(self, job_id)
        job_timeout = self._resolve_job_timeout()

        async def _run_files():
            try:
                core = adapter.index_files(
                    file_ids=file_ids,
                    folder_id=folder_id,
                    token=token,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    progress_tracker=tracker,
                )
                # job-level hard timeout. <=0 disables the cap.
                if job_timeout and job_timeout > 0:
                    await asyncio.wait_for(core, timeout=job_timeout)
                else:
                    await core
            except asyncio.CancelledError:
                logger.info(f"File indexing job {job_id} cancelled")
                raise
            except asyncio.TimeoutError:
                logger.error(
                    f"File indexing job {job_id} exceeded job_timeout={job_timeout}s — marking failed"
                )
                tracker.mark_failed(f"Job exceeded {job_timeout}s job-level timeout")
            except Exception as exc:
                logger.error(
                    f"File indexing job {job_id} for folder {folder_id} failed: {exc}"
                )
                tracker.mark_failed(str(exc))
            finally:
                self._cleanup_job_slot(job_id, folder_id)

        task = asyncio.create_task(_run_files())
        with self._lock:
            self._task_handles[job_id] = task

        logger.info(
            f"Scheduled file indexing job {job_id} for folder {folder_id} with {len(file_ids)} files"
        )

    def _cleanup_job_slot(self, job_id: str, folder_id: int):
        """Job 結束後釋放 task_handle + folder lock 槽位(冪等);drain pending queue。

        ⚠️ 這裡是 folder lock 的**唯一**釋放點(task 真正退出時才跑到)。
        _update_job_state 翻終態不放鎖 — task 可能還卡在 to_thread 的阻塞呼叫,
        提早放鎖會讓新 job 跟殘存寫入同寫一張表。

        After releasing the lock, dequeue the next still-PENDING batch for this
        folder and launch **its pre-created job (same job_id)** — 排隊中被
        cancel 的 job 自動跳過。一次只出一個(folder lock 天然序列化),
        該 job 結束時它自己的 cleanup 會再出下一個,鏈式消化整條佇列。

        Args:
            job_id: 要清的 job。
            folder_id: 對應 folder。
        """
        next_batch: Optional[_PendingFileBatch] = None
        with self._lock:
            self._task_handles.pop(job_id, None)
            self._progress_track.pop(job_id, None)
            # 所有權守衛:只有「目前確實持有 folder lock 的 job」才能釋放鎖、
            # drain 佇列、把鎖交給下一個 job。H4 watchdog 強制回收後,原 wedged
            # task 可能之後才醒來跑 finally 重入這裡 —— 它已非持有者,若無此
            # 守衛會把佇列中的下一個 job 也啟動並搶佔鎖,兩個 job 併發同寫
            # 一張表(破壞 #28「每 folder 最多一個 running job」不變式)。
            # 非持有者只清自己的 task_handle / progress_track(冪等、無害)。
            owned = self._active_folders.get(folder_id) == job_id
            if owned:
                self._active_folders.pop(folder_id, None)

                queue = self._pending_file_batches.get(folder_id)
                while queue:
                    cand = queue.pop(0)
                    cand_state = self._jobs.get(cand.job_id)
                    if cand_state is not None and cand_state.status == JobStatus.PENDING:
                        next_batch = cand
                        break
                    # 排隊期間被 cancel(CANCELLED)或 TTL 蒸發 → 跳過,繼續找下一個
                    logger.info(
                        f"Folder {folder_id}: skipping dequeued job {cand.job_id} "
                        f"(status={getattr(cand_state, 'status', 'evicted')})"
                    )
                if not queue:
                    self._pending_file_batches.pop(folder_id, None)
                if next_batch is not None:
                    # 在鎖內就把 folder lock 交給下一個 job — create_task 前的空窗
                    # 不能讓新來的 start_indexing 搶走槽位
                    self._active_folders[folder_id] = next_batch.job_id
            else:
                logger.warning(
                    f"Folder {folder_id}: cleanup from non-owner job {job_id} "
                    f"(current owner: {self._active_folders.get(folder_id)}) — "
                    f"skipping lock release / queue drain (late reentry after reclaim?)"
                )

        if next_batch is not None:
            state = self._jobs.get(next_batch.job_id)
            logger.info(
                f"Folder {folder_id}: dequeuing job {next_batch.job_id} "
                f"({len(next_batch.file_ids)} file(s))"
            )
            try:
                self._update_job_state(next_batch.job_id, message="Dequeued — starting")
                self._launch_file_job(
                    state, next_batch.adapter,
                    file_ids=next_batch.file_ids,
                    folder_id=folder_id, token=next_batch.token,
                    chunk_size=next_batch.chunk_size,
                    chunk_overlap=next_batch.chunk_overlap,
                )
            except RuntimeError:
                # No running loop (e.g. cleanup ran from a non-async context).
                # 釋放剛佔的槽位並把 job 標 FAILED,不留永久 PENDING 幽靈。
                with self._lock:
                    if self._active_folders.get(folder_id) == next_batch.job_id:
                        self._active_folders.pop(folder_id, None)
                self._update_job_state(
                    next_batch.job_id,
                    status=JobStatus.FAILED,
                    error="could not schedule dequeued job (no asyncio loop)",
                )
                logger.error(
                    f"Folder {folder_id}: could not schedule dequeued job "
                    f"{next_batch.job_id} (no asyncio loop)."
                )

    async def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return current status for a job."""
        with self._lock:
            state = self._jobs.get(job_id)
            return state.to_dict() if state else None

    def list_jobs(
        self,
        status_filter: Optional[JobStatus] = None,
        folder_id: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        """List jobs in the in-memory cache.

        Args:
            status_filter: 只回特定狀態(RUNNING / PENDING / SUCCEEDED / FAILED / CANCELLED)
            folder_id: 只回特定 folder 的 jobs
        """
        with self._lock:
            jobs = []
            for state in self._jobs.values():
                if status_filter is not None and state.status != status_filter:
                    continue
                if folder_id is not None and state.folder_id != folder_id:
                    continue
                jobs.append(state.to_dict())
            return jobs

    def active_file_stages(self) -> Dict[str, Dict[str, Any]]:
        """回 {file_id: {stage, done, total, eta}} — 目前正在索引的檔案在哪個階段。

        給 admin 檔案清單即時顯示「解析中 / 生成上下文 / 向量化 / 寫入」用。
        只含 RUNNING job 正在處理的當前檔;in-memory,不落 DB。
        """
        out: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for state in self._jobs.values():
                if state.status != JobStatus.RUNNING or not state.current_file_id:
                    continue
                out[str(state.current_file_id)] = {
                    "stage": state.current_file_stage,
                    "done": state.current_file_chunks_done,
                    "total": state.current_file_chunks_total,
                    "eta": state.current_file_eta_seconds,
                }
        return out

    def count_by_status(self) -> Dict[str, int]:
        """Return {pending: N, running: N, succeeded: N, failed: N, cancelled: N, total: N}。

        TTLCache 會自動清掉過期 entries,所以 succeeded/failed 數字是「最近 TTL
        窗口」內的，不是 all-time。
        """
        counts = {s.value: 0 for s in JobStatus}
        with self._lock:
            for state in self._jobs.values():
                counts[state.status.value] += 1
            counts["total"] = sum(counts.values())
        return counts

    async def cancel_jobs_for_folder(self, folder_id: int) -> list[str]:
        """取消該 folder 的所有 PENDING/RUNNING jobs。

        刪 folder / 刪 index 等破壞性操作前先呼叫,避免 in-flight job 寫到一個被拆掉的 state。

        Args:
            folder_id: 要清的 folder id。

        Returns:
            被 cancel 的 job_id list;空 list 代表本來就沒在跑。
        """
        with self._lock:
            # 先丟棄排隊中的批次 — 不丟的話,被 cancel 的 job 在 _cleanup_job_slot
            # 會把它們 drain 成新 job,正好跟破壞性操作(DROP TABLE)對撞
            dropped = self._pending_file_batches.pop(folder_id, None)
            targets = [
                state.job_id
                for state in self._jobs.values()
                if state.folder_id == folder_id
                and state.status in (JobStatus.PENDING, JobStatus.RUNNING)
            ]
        if dropped:
            n_files = sum(len(b.file_ids) for b in dropped)
            logger.info(
                f"Dropped {n_files} queued file(s) for folder {folder_id} "
                f"(destructive operation pending)"
            )
        cancelled = []
        for job_id in targets:
            try:
                if await self.cancel_job(job_id):
                    cancelled.append(job_id)
            except Exception as e:
                logger.warning(f"cancel_jobs_for_folder: cancel of {job_id} failed: {e}")
        if cancelled:
            logger.info(
                f"Cancelled {len(cancelled)} running job(s) for folder {folder_id}: {cancelled}"
            )
        return cancelled

    def purge_jobs_for_folder(self, folder_id: int) -> int:
        """把該 folder 的所有 job 記錄從 in-memory cache + DB 徹底移除。

        folder 刪除時呼叫(先 cancel_jobs_for_folder 再 purge)。沒有這步,
        孤兒 job 會一直留在 /index/jobs 列表,前端順著它的 folder_id 輪詢
        已不存在的 folder → FOLDER_NOT_FOUND 無限刷 log。

        Args:
            folder_id: 被刪除的 folder id。

        Returns:
            從 in-memory cache 移除的 job 數。
        """
        with self._lock:
            doomed = [
                job_id for job_id, state in self._jobs.items()
                if state.folder_id == folder_id
            ]
            for job_id in doomed:
                self._jobs.pop(job_id, None)
                self._task_handles.pop(job_id, None)
                self._progress_track.pop(job_id, None)
            self._pending_file_batches.pop(folder_id, None)
            if self._active_folders.get(folder_id) in doomed:
                self._active_folders.pop(folder_id, None)
        # DB 側同步清掉(best-effort;失敗只 log,不擋 folder 刪除流程)
        try:
            from db.indexjobdb import IndexJobDB
            IndexJobDB.delete_for_folder(folder_id)
        except Exception as e:
            logger.warning(f"IndexJob DB purge for folder {folder_id} failed: {e}")
        if doomed:
            logger.info(f"Purged {len(doomed)} job record(s) for deleted folder {folder_id}")
        return len(doomed)

    async def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """取消一個執行中或排隊中的 job。

        Args:
            job_id: 要 cancel 的 job 識別字。
            reason: 寫進 job state 的取消原因(前端 job 狀態會顯示)。

        Returns:
            True 表示成功 cancel;False = 找不到或已 terminal。

        注意:此方法會等 task **真正結束**(上限 _CANCEL_WAIT_SECONDS)才返回。
        to_thread 裡的阻塞呼叫不會被 cancel() 中斷;不等的話 caller(刪 folder →
        DROP TABLE)會跟殘存的 insert 競速,PGVectorStore.add 還會把被 DROP 的表
        自動建回來,留下無主孤兒表。
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if not state or state.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return False
            task = self._task_handles.get(job_id)
        if task and not task.done():
            task.cancel()
        self._update_job_state(
            job_id,
            status=JobStatus.CANCELLED,
            message=reason,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._CANCEL_WAIT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Job {job_id} task still running {self._CANCEL_WAIT_SECONDS}s after "
                    f"cancel (blocking call in flight); caller proceeds at its own risk"
                )
            except asyncio.CancelledError:
                pass  # task 以 CancelledError 收場 = 正常取消完成
            except Exception:
                pass  # task 自己的例外已在 _run_* 內處理過,這裡只關心「停了沒」
        return True

    async def abort_indexing_for_file(
        self, file_id: str, folder_id: Optional[int] = None,
    ) -> Optional[str]:
        """檔案被刪除時呼叫:盡快中止該檔的 in-flight indexing。

        兩段式策略:
        - 單檔 job(scope 恰好只有這檔)→ 直接 cancel 整個 job(preemptive,
          task.cancel() 在下個 await 點立即生效)。
        - 多檔 / folder-wide job → 只設 per-file abort flag,由 adapter 的
          mid-stage probe(cooperative)在下個檢查點中止該檔,其他檔不受影響。
        還沒輪到的 pending 檔不用管 — adapter 的 gate 1 會用 DB probe 擋下。

        Args:
            file_id: 被刪除的檔案 UUID(str)。
            folder_id: 已知時傳入,縮小掃描範圍。

        Returns:
            ``"cancelled_job:<job_id>"`` / ``"flagged"`` / None(沒有相關 job)。
        """
        fid = str(file_id)
        with self._lock:
            target: Optional[IndexJobState] = None
            for state in self._jobs.values():
                if state.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                    continue
                if folder_id is not None and state.folder_id != folder_id:
                    continue
                if state.current_file_id == fid or fid in state.scope_file_ids:
                    target = state
                    break
        if target is None:
            return None

        if target.scope_file_ids == [fid]:
            if await self.cancel_job(
                target.job_id, reason="Cancelled: file deleted during indexing",
            ):
                logger.info(
                    f"Cancelled single-file indexing job {target.job_id} — "
                    f"file {fid} was deleted"
                )
                return f"cancelled_job:{target.job_id}"

        with self._lock:
            self._file_abort_flags[fid] = True
        logger.info(
            f"Flagged file {fid} for indexing abort (job {target.job_id}); "
            f"mid-stage probe will stop it at the next checkpoint"
        )
        return "flagged"

    def is_file_abort_requested(self, file_id: str) -> bool:
        """adapter 的 mid-stage probe 用:此檔是否被要求中止。"""
        with self._lock:
            return str(file_id) in self._file_abort_flags

    def clear_file_abort(self, file_id: str) -> None:
        """flag 已被消費(該檔 indexing 已中止)後清除。"""
        with self._lock:
            self._file_abort_flags.pop(str(file_id), None)

    async def _watchdog_loop(self):
        """背景輪詢:每 60s 掃 RUNNING jobs,>10min 無心跳就翻成 FAILED。"""
        while True:
            await asyncio.sleep(self._WATCHDOG_INTERVAL_SECONDS)
            try:
                now = datetime.now(timezone.utc)
                with self._lock:
                    stale = []
                    for state in list(self._jobs.values()):
                        if state.status != JobStatus.RUNNING:
                            continue
                        try:
                            last = datetime.fromisoformat(state.last_updated_at)
                        except ValueError:
                            continue
                        if (now - last).total_seconds() > self._HEARTBEAT_STALE_SECONDS:
                            stale.append(state.job_id)
                for job_id in stale:
                    logger.warning(
                        f"Heartbeat lost for job {job_id} — marking failed"
                    )
                    self._update_job_state(
                        job_id,
                        status=JobStatus.FAILED,
                        error="Heartbeat lost (>10min without update)",
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    # 翻 FAILED 只是帳面;還要真的 cancel task(終態閘擋回寫)。
                    # folder lock 不在這裡放 — 它由 _cleanup_job_slot 在 task 真正
                    # 退出時釋放,所以就算 task 卡在無法中斷的阻塞呼叫裡,新 job
                    # 也進不來,不會兩個 job 同寫一張表。
                    with self._lock:
                        task = self._task_handles.get(job_id)
                    if task and not task.done():
                        task.cancel()
                        logger.warning(f"Cancelled stale task for job {job_id}")

                # H4: 兜底回收「已終態、但持鎖 task 仍未退出」而卡死的 folder lock。
                # 正常路徑 lock 由 _cleanup_job_slot(task finally)釋放;task 卡在
                # 無法中斷的阻塞呼叫時 finally 永不跑,folder 會永久鎖死。
                reclaim: List[tuple] = []
                with self._lock:
                    for folder_id, holder in list(self._active_folders.items()):
                        state = self._jobs.get(holder)
                        task = self._task_handles.get(holder)
                        if state is None:
                            # holder 已被 TTL 逐出卻仍持鎖 → 早該回收
                            reclaim.append((folder_id, holder, "holder evicted from cache"))
                            continue
                        if state.status not in _TERMINAL_STATUSES:
                            continue  # 運行中 / 排隊中,不動
                        if task is None or task.done():
                            continue  # task 已退出,_cleanup 會/已釋放鎖,不強制
                        try:
                            done_at = (
                                datetime.fromisoformat(state.completed_at)
                                if state.completed_at else None
                            )
                        except ValueError:
                            done_at = None
                        if done_at and (now - done_at).total_seconds() > self._LOCK_RECLAIM_GRACE_SECONDS:
                            reclaim.append((folder_id, holder, "terminal task wedged past grace"))
                for folder_id, holder, why in reclaim:
                    logger.error(
                        f"Force-reclaiming folder lock {folder_id} from job {holder} "
                        f"({why}); wedged task may still be alive — residual-write risk"
                    )
                    self._cleanup_job_slot(holder, folder_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Watchdog tick failed (will retry next interval)")

    def start_watchdog(self):
        """啟動 watchdog 背景任務(冪等,重複呼叫只啟動一次)。"""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._loop = asyncio.get_running_loop()  # M8: 捕獲主 loop 供跨執行緒喚醒
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            f"Job watchdog started (interval={self._WATCHDOG_INTERVAL_SECONDS}s, "
            f"stale_after={self._HEARTBEAT_STALE_SECONDS}s)"
        )

    def mark_all_running_as_restart_failed(self) -> int:
        """把 DB 內遺留的 PENDING/RUNNING jobs 全翻成 FAILED(reason=server_restart)。

        重啟時呼叫:之前 process 死掉留下的孤兒 job 沒人在跑,直接收掉。冪等,可多次呼叫。

        Returns:
            被翻成 failed 的 job 數量。
        """
        flipped = 0
        # 1. Load DB jobs that were left mid-flight by a previous process
        try:
            from db.indexjobdb import IndexJobDB
            for row in IndexJobDB.load_active():
                job_id = str(row.get("job_id"))
                with self._lock:
                    if job_id in self._jobs:
                        # already in memory — _update_job_state below will handle it
                        continue
                    state = IndexJobState(
                        job_id=job_id,
                        folder_id=row.get("folder_id"),
                        status=JobStatus(row.get("status", "running")),
                        total_files=row.get("total_files") or 0,
                        processed_files=row.get("processed_files") or 0,
                        current_index=row.get("current_index") or 0,
                        current_file_id=row.get("current_file_id"),
                        current_file_name=row.get("current_file_name"),
                        last_file_status=row.get("last_file_status"),
                        last_message=row.get("last_message"),
                        message=row.get("message") or "",
                        error=row.get("error"),
                        skip_existing=row.get("skip_existing", True),
                        started_at=row.get("started_at") or datetime.now(timezone.utc).isoformat(),
                        completed_at=row.get("completed_at"),
                        last_updated_at=row.get("last_updated_at") or datetime.now(timezone.utc).isoformat(),
                        result_summary=row.get("result_summary"),
                        scope_file_ids=row.get("scope_file_ids") or [],
                        file_timings=row.get("file_timings") or [],
                    )
                    self._jobs[job_id] = state
        except Exception as e:
            logger.warning(f"A4 DB scan skipped (will only process in-memory jobs): {e}")

        # 2. Flip everything still PENDING/RUNNING in the cache
        with self._lock:
            job_ids = [
                state.job_id
                for state in self._jobs.values()
                if state.status in (JobStatus.PENDING, JobStatus.RUNNING)
            ]
        for job_id in job_ids:
            self._update_job_state(
                job_id,
                status=JobStatus.FAILED,
                error="server_restart",
                message="Job marked failed due to server restart",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            flipped += 1
        if flipped:
            logger.info(f"Marked {flipped} stale running jobs as failed (server_restart)")
        return flipped

    # ------------------------------------------------------------------
    # ETA — chunk 進度旁的「還剩多久」
    # ------------------------------------------------------------------

    def _note_file_started(self, job_id: str) -> None:
        """記錄當前檔開始時間;stage 追蹤歸零(per-file)。"""
        with self._lock:
            self._progress_track[job_id] = {"file_start": time.time()}

    @staticmethod
    def _compute_job_eta_locked(state: IndexJobState, current_file_elapsed: Optional[float]) -> Optional[int]:
        """整個 job 的粗估剩餘秒數。caller 必須持有 self._lock。

        估法:已完成檔(不含 skipped)的平均耗時 × 剩餘檔數,再扣掉當前檔
        已經跑掉的時間(有的話)。刻意粗糙但誠實:第一個檔完成前回 None,
        不編數字。

        Args:
            state: job state(讀 file_timings / total_files / processed_files)。
            current_file_elapsed: 當前檔已耗秒數;檔與檔之間傳 None。

        Returns:
            預估剩餘秒數(≥0)或 None(樣本不足)。
        """
        durations_ms = [
            t.get("total_ms") for t in state.file_timings
            if t.get("status") != "skipped" and t.get("total_ms")
        ]
        if not durations_ms:
            return None
        avg_s = (sum(durations_ms) / len(durations_ms)) / 1000.0
        remaining = max(state.total_files - state.processed_files, 0)
        if remaining <= 0:
            return 0
        eta = remaining * avg_s
        if current_file_elapsed is not None:
            # 當前檔包含在 remaining 內,扣掉它已跑的部分(不讓 ETA 倒灌成負)
            eta -= min(current_file_elapsed, avg_s)
        return int(max(eta, 0))

    def _update_chunk_progress(
        self,
        job_id: str,
        stage: str,
        done: Optional[int],
        total: Optional[int],
    ) -> None:
        """chunk 進度 + 兩級 ETA 一起更新(tracker.on_chunk_progress 的實作)。

        stage ETA:同 stage 內用 (done − baseline)/elapsed 估速率再外推;
        stage 剛切換或 elapsed < 1s(樣本太少,估出來會亂跳)時為 None。
        """
        now = time.time()
        stage_eta: Optional[int] = None
        job_eta: Optional[int] = None
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            track = self._progress_track.setdefault(job_id, {"file_start": now})
            if track.get("stage") != stage:
                # stage 切換:重置速率基準(不同 stage 速率完全不同,不可混用)
                track["stage"] = stage
                track["stage_start"] = now
                track["baseline"] = done or 0
            elif done is not None and total:
                elapsed = now - track["stage_start"]
                progressed = done - track.get("baseline", 0)
                if elapsed >= 1.0 and progressed > 0:
                    rate = progressed / elapsed
                    stage_eta = int(max(total - done, 0) / rate)
            job_eta = self._compute_job_eta_locked(
                state, current_file_elapsed=now - track.get("file_start", now)
            )
        self._update_job_state(
            job_id,
            current_file_stage=stage,
            current_file_chunks_done=done,
            current_file_chunks_total=total,
            current_file_eta_seconds=stage_eta,
            eta_seconds=job_eta,
        )

    def _update_job_state(self, job_id: str, **updates):
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                logger.warning(f"Attempted to update unknown job_id={job_id}")
                return

            # 終態單向閘:job 一旦 SUCCEEDED/FAILED/CANCELLED/PARTIAL,任何遲到的
            # 更新一律拒絕。沒有這個閘,watchdog 翻 FAILED 後原 task 跑完會把狀態
            # 翻回 SUCCEEDED;cancel_job 設 CANCELLED 後垂死 task 的 mark_failed
            # 也會蓋掉取消原因。
            if state.status in _TERMINAL_STATUSES:
                logger.debug(
                    f"Ignoring update to terminal job {job_id} "
                    f"(status={state.status.value}, attempted={updates.get('status')})"
                )
                return

            for key, value in updates.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            # every state change is a heartbeat
            state.last_updated_at = datetime.now(timezone.utc).isoformat()
            # H3: 重新寫入 = 續 TTL。TTLCache 的 ttl 從「寫入」起算、GET 不續命,
            # 而 job_timeout 可達 10 天 >> _JOB_TTL_SECONDS(24h)。不在每次心跳
            # 重寫,長 job 會在跑到 24h 時被逐出 _jobs → 後續更新變 "unknown
            # job_id"、進度靜默丟失、watchdog 看不到它、GPU 仍被佔到 10 天。
            # 心跳(keepalive 每 60s)重寫後 RUNNING job 永不因 TTL 過期;翻終態
            # 後走上面的閘早退、不再重寫,24h 後正常回收。重寫同 key 不增 size,
            # 不會誤逐其他 entry。
            self._jobs[job_id] = state
            if updates.get("status") in _TERMINAL_STATUSES and state.completed_at is None:
                state.completed_at = datetime.now(timezone.utc).isoformat()

            # ⚠️ folder lock 不在這裡釋放 — 唯一出口是 _cleanup_job_slot(task 真正
            # 退出時)。status 翻終態 ≠ task 已停:watchdog/cancel 從外部翻狀態時,
            # task 可能還卡在 to_thread 的阻塞呼叫(embedding/insert)裡,thread 無法
            # 中斷。在這裡提早放鎖,新 job 會跟殘存寫入同寫一張表。
            # 正常完成路徑 lock 只多held 幾微秒(task finally 馬上跑 cleanup)。

            # write-through persist (snapshot inside the lock to avoid races)
            snapshot = state.to_dict()
        self._persist(snapshot)

    def _persist(self, state_dict: Dict[str, Any]) -> None:
        """best-effort write-through to IndexJobs table. Never raises.

        upsert 是 sync SQLAlchemy,丟到單工 executor 跑 — 進度 tick 很頻繁
        (context-gen 每 10 chunk、embedding 每批),在 event loop 上直接跑
        會把 API/SSE/cancel 全卡住。manager 記憶體才是 source of truth,
        DB 是被動投影,晚幾十 ms 落盤無妨;單 worker 保證 upsert 順序。
        """
        try:
            self._persist_executor.submit(self._persist_sync, state_dict)
        except Exception as e:
            logger.warning(f"IndexJob persist scheduling failed (continuing in-memory): {e}")
        # SSE 直接吃 in-memory snapshot(canonical),不等 DB 落盤
        self._notify_subscribers(state_dict.get("job_id"), state_dict)

    @staticmethod
    def _persist_sync(state_dict: Dict[str, Any]) -> None:
        """executor worker:實際的 DB upsert(IndexJobDB 自吞例外,只 log)。"""
        try:
            from db.indexjobdb import IndexJobDB
            IndexJobDB.upsert(state_dict)
        except Exception as e:
            logger.warning(f"IndexJob persist failed (continuing in-memory): {e}")

    # ------------------------------------------------------------------
    # D1 (T2.2) — SSE subscriber fan-out
    # ------------------------------------------------------------------

    def subscribe(self, job_id: str) -> asyncio.Queue:
        """訂閱某個 job 的狀態變化(供 SSE endpoint 用)。

        Args:
            job_id: 要訂閱的 job。

        Returns:
            一個 bounded asyncio.Queue;每次 state 變動會 put 整份 state dict。
            **caller 結束時務必呼叫 unsubscribe(),否則 manager 會 leak reference。**
        """
        # Bounded so a slow consumer cannot OOM the server. 100 updates is
        # plenty for any sane job (we emit ~3-5 events per file processed).
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        """移除訂閱者 queue。冪等。

        Args:
            job_id: 對應的 job。
            q: subscribe() 之前回傳的同一個 queue。
        """
        with self._lock:
            subs = self._subscribers.get(job_id)
            if not subs:
                return
            try:
                subs.remove(q)
            except ValueError:
                pass
            if not subs:
                self._subscribers.pop(job_id, None)

    def _notify_subscribers(self, job_id: Optional[str], state_dict: Dict[str, Any]) -> None:
        """把最新 state 推給所有 subscribers(best-effort,slow consumer drop 不報錯)。

        Args:
            job_id: 要通知的 job;None → 直接 return。
            state_dict: 完整 state dict(同 get_status 回傳)。
        """
        if not job_id:
            return
        with self._lock:
            subs = list(self._subscribers.get(job_id, ()))
            loop = self._loop
        if not subs:
            return

        def _deliver():
            for q in subs:
                try:
                    q.put_nowait(state_dict)
                except asyncio.QueueFull:
                    pass
                except Exception as e:
                    logger.warning(f"SSE notify dropped for job {job_id}: {e}")

        # M8: asyncio.Queue 非 thread-safe;put_nowait 內部的 consumer 喚醒走
        # call_soon(非 threadsafe)。此方法會被 docling worker thread(to_thread
        # 的頁級進度回報)呼叫,直接 put 可能導致 SSE 喚醒遺失。若不在 loop thread,
        # 就把投遞排回 loop 上執行。
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        if on_loop:
            _deliver()
        elif loop is not None:
            loop.call_soon_threadsafe(_deliver)
        else:
            _deliver()  # 極端 fallback(loop 未捕獲);不比原行為差
