
"""RAG indexing service — 單檔 / 資料夾 / 指定檔案清單 / 自動索引。

從 RAGAdapter 拆出的四個方法:
- `index_document(file_record, token)` — 單檔索引(內部用 HierarchicalIndexer)
- `index_folder(folder_id, token, skip_existing)` — 整個資料夾迭代呼叫 index_document
- `index_files(file_ids, folder_id, token)` — 指定子集索引(auto-index 上傳用)
- `trigger_auto_index(file_ids, folder_id, token, auto_index)` — 非同步觸發 background job

共用 RAGContext 提供的 indexer / indexing_service / vector_store_manager。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.api.router.response import (
    FileIndexResult,
    FileRequest,
    IndexDocumentResponse,
    IndexFolderResponse,
)
from src.config.model import IndexingConfig  # M10: timeout default 單一來源
from src.domain.exceptions import (
    DomainException,
    FileIndexingError,
    RAGFileNotFoundError,
)
from src.domain.rag.hierarchical_indexer import IndexingAbortedError
from src.log import get_adapter_logger, log_err, log_op, log_warn

if TYPE_CHECKING:
    from typing import Callable

    from src.adapter.rag_context import RAGContext
    from src.domain.rag.index_job_manager import IndexProgressTracker

logger = get_adapter_logger()

# mid-stage abort probe 的 DB 存在性檢查節流間隔(秒)。
# manager 的 in-memory flag(刪檔主動通知)不節流 — 每個檢查點都看;
# DB probe 只是兜底(直接動 DB 刪檔等 manager 通知不到的情況)。
_ABORT_PROBE_INTERVAL_SECONDS = 10.0

# Keepalive tick 間隔(秒)。必須遠小於 index_job_manager._HEARTBEAT_STALE_SECONDS
# (600s),否則補的心跳趕不上 watchdog 判死。
#
# 為什麼需要這東西:watchdog 600s 沒心跳就翻 FAILED + cancel task,而 per-file
# 預算現在放到 10 天(_PER_FILE_TIMEOUT_DEFAULT)—— 落在心跳盲區的慢檔會在
# per-file timeout 到期前老早就被 watchdog 誤殺。keepalive 補心跳把這關兜住。
# 已知盲區:semaphore 等待、docling/OCR 解析、context-gen 每 10 chunk 的節流
# 間隙、單批 embedding、pgvector 寫入。與其逐一去包,不如包住整個單檔生命週期。
#
# 這裡不需要自己設「放棄策略」:真正 hang 住的檔案由 _with_timeout 的
# wait_for(per_file_timeout) 兜底,keepalive 只負責不讓「慢」被誤判成「死」。
_KEEPALIVE_INTERVAL_SECONDS = 60.0


# 索引同時上限;env RAG_INDEXING_CONCURRENCY > config.rag.indexing.max_concurrent_jobs > 4
_INDEXING_SEMAPHORE: Optional[asyncio.Semaphore] = None

# Per-file timeout default. Same env > config > default resolution.
# M10: 直接引用 IndexingConfig 的欄位 default,不再各處各寫一份 864000 字面值。
_PER_FILE_TIMEOUT_DEFAULT = IndexingConfig.model_fields["per_file_timeout_seconds"].default


async def _run_db(fn, *args, **kwargs):
    """M1: 把阻塞的同步 DB helper 丟到 worker thread 跑,不佔 event loop。

    索引 async 路徑原本直接呼叫同步 SQLAlchemy helper(baseDB 每次
    `with Session()`),query 期間卡住 loop → 高並發時 API/SSE/cancel/query 一起頓。
    baseDB 是 session-per-call(每次新建/關閉),丟到 thread 執行 thread-safe。

    ⚠️ 不要在 `except asyncio.CancelledError:` 區塊內用 —— cancel 期間 await 會再次
    拋 CancelledError。那些路徑(mark_index_failed on cancel)維持同步呼叫。
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def _resolve_indexing_concurrency() -> int:
    """env var > config > default 4(見 IndexingConfig.max_concurrent_jobs 註解)。"""
    env_val = os.getenv("RAG_INDEXING_CONCURRENCY")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            logger.warning(f"Invalid RAG_INDEXING_CONCURRENCY={env_val!r}, using config/default")

    try:
        from src.config.config_manager import Config
        cfg = Config.get_config_model()
        if cfg and cfg.rag and cfg.rag.indexing:
            return cfg.rag.indexing.max_concurrent_jobs
    except Exception as e:
        logger.warning(f"Failed to read indexing config: {e}")

    return 4


def _resolve_per_file_timeout() -> int:
    """解析單檔 indexing timeout 秒數。

    優先序:env RAG_PER_FILE_TIMEOUT_SECONDS > config.rag.indexing.per_file_timeout_seconds
    > _PER_FILE_TIMEOUT_DEFAULT(864000s / 10 天)。

    Returns:
        上限秒數;0 或負值 = 不設上限(緊急 bypass 用)。
    """
    env_val = os.getenv("RAG_PER_FILE_TIMEOUT_SECONDS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            logger.warning(f"Invalid RAG_PER_FILE_TIMEOUT_SECONDS={env_val!r}, using config/default")
    try:
        from src.config.config_manager import Config
        cfg = Config.get_config_model()
        if cfg and cfg.rag and cfg.rag.indexing:
            return cfg.rag.indexing.per_file_timeout_seconds
    except Exception as e:
        logger.warning(f"Failed to read per_file_timeout from config: {e}")
    return _PER_FILE_TIMEOUT_DEFAULT


def _get_indexing_semaphore() -> asyncio.Semaphore:
    """Lazy-init 因為 Semaphore 要在 event loop 起來後才能建。"""
    global _INDEXING_SEMAPHORE
    if _INDEXING_SEMAPHORE is None:
        limit = _resolve_indexing_concurrency()
        _INDEXING_SEMAPHORE = asyncio.Semaphore(limit)
        logger.info(f"[INIT] Indexing semaphore initialized (max_concurrent={limit})")
    return _INDEXING_SEMAPHORE


def _make_timing_entry(
    file_id, file_name: str, status: str, t0: float, stages: Dict[str, float],
    chunks: Optional[int] = None,
) -> Dict[str, Any]:
    """組一筆 IndexJobState.file_timings entry。

    Args:
        file_id: 檔案 UUID。
        file_name: 顯示用檔名。
        status: success / failed / timeout / skipped。
        t0: per-file try block 進入時的 perf_counter()。
        stages: load_ms / index_ms 等已完成 stage 的耗時;沒跑完的留空 → entry 內 None。
        chunks: 此檔切出的 leaf chunk 數(成功才有;skipped/failed 為 None)。
            持久化的 chunk 紀錄——job 結束後仍可稽核「每檔切了幾塊」。

    Returns:
        {file_id, file_name, status, total_ms, load_ms, index_ms, chunks} dict。
    """
    return {
        "file_id": str(file_id),
        "file_name": file_name,
        "status": status,
        "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        "load_ms": stages.get("load_ms"),
        "index_ms": stages.get("index_ms"),
        # 階段耗時明細(StageTimer):{"loading": ms, "contextualizing": ms,
        # "embedding": ms, "writing": ms} — 回答「每個階段花了多久」
        "stage_ms": stages.get("stage_ms"),
        "chunks": chunks,
    }


async def _with_timeout(coro, timeout_seconds: int, filename: str):
    """在硬時間預算下跑 per-file indexing coroutine。

    Args:
        coro: 要 await 的 coroutine(通常是 self.index_document(...))。
        timeout_seconds: 上限秒數;<=0 不設限。
        filename: 純錯誤訊息標籤,timeout 時帶在 TimeoutError 內。

    Returns:
        coro 的 return 值。

    Raises:
        TimeoutError: 超時,帶 filename + 秒數。
    """
    if timeout_seconds and timeout_seconds > 0:
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"indexing exceeded {timeout_seconds}s for file '{filename}'"
            )
    return await coro


def _keepalive_stage_label(stage: str, elapsed_seconds: float) -> str:
    """決定 keepalive 補發心跳時,回報給 job state / SSE 的 stage 標籤。

    **原樣回傳,不要在這裡加 elapsed。** 這條規則是查過下游才定的:

    micore-portal 的 ``IndexingStatusBadge.tsx`` 拿 stage 去查一張中文對照表
    ``STAGE_LABEL = {loading: '解析文件', contextualizing: '上下文生成',
    embedding: '向量化', writing: '寫入'}``,寫法是
    ``STAGE_LABEL[stage] ?? stage``。加了 elapsed 會讓 key 查不到 —— 有
    fallback 所以不會爆,但 badge 會從「解析文件」退化成英文原字串
    ``loading (8m20s)``,而且偏偏發生在解析很久、使用者最需要看懂的時候。

    elapsed 要曝光的話請放 ``message`` / ``last_message``:那兩個欄位本來就是
    自由文字,也已經在 SSE 契約裡,不受對照表約束。

    Args:
        stage: 最後一次真實進度回報的 stage。
        elapsed_seconds: 距離最後一次真實進度已經過了幾秒(目前僅供未來擴充,
            不影響回傳值 —— 見上方為什麼不能編碼進 stage)。

    Returns:
        要回報的 stage 標籤(即傳入的 stage 本身)。
    """
    return stage


class _ProgressKeepalive:
    """把 ``_progress_cb`` 包成「至少每 interval 秒發一次心跳」的版本。

    自己就是一個 callable,签名與原本的 ``_progress_cb(stage, done, total)``
    相同,可以直接頂替傳進 indexer;差別是它會記住最後一次進度,並在背景
    task 裡於閒置超過 interval 時原地補發,藉此刷新 job 的 last_updated_at。

    真實進度會重置閒置計時,所以正常跑的檔案不會有任何額外的 tick。
    """

    def __init__(self, progress_cb, interval: float = _KEEPALIVE_INTERVAL_SECONDS):
        self._cb = progress_cb
        self._interval = interval
        # 尚未進入任何 stage 前就先有值 — semaphore 等待期間補的心跳用得到
        self._last_args = ("queued", None, None)
        self._last_emit = time.monotonic()
        self._task: Optional[asyncio.Task] = None

    def __call__(self, stage: str, done: Optional[int], total: Optional[int]) -> None:
        """Drop-in replacement for ``_progress_cb`` — 記下最後進度再轉發。"""
        self._last_args = (stage, done, total)
        self._emit(stage, done, total)

    def _emit(self, stage: str, done: Optional[int], total: Optional[int]) -> None:
        self._last_emit = time.monotonic()
        if self._cb is None:
            return
        try:
            self._cb(stage, done, total)
        except Exception:
            pass  # 進度回報失敗不影響 indexing(與既有 call site 一致)

    async def _loop(self) -> None:
        while True:
            idle = self._interval - (time.monotonic() - self._last_emit)
            if idle > 0:
                await asyncio.sleep(idle)
                continue
            stage, done, total = self._last_args
            elapsed = time.monotonic() - self._last_emit
            self._emit(_keepalive_stage_label(stage, elapsed), done, total)

    async def __aenter__(self) -> "_ProgressKeepalive":
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_exc) -> bool:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        return False


class RAGIndexingService:
    """處理單檔 / 資料夾 / 子集 indexing 跟 auto-index trigger 的 service。"""

    def __init__(self, ctx: "RAGContext"):
        self._ctx = ctx

    # ------------------------------------------------------------------
    # File-existence gates (#24)
    # ------------------------------------------------------------------

    def _file_still_exists(self, file_id) -> bool:
        """檢查 file_id 還在不在 Files table(mid-job existence gate)。

        當使用者在背景索引途中刪檔,讓我們提前 abort,免得繼續燒 Docling/embed,
        最後又因 FK violation 才炸。Fail-open:probe 自己失敗時不 abort。

        Args:
            file_id: 檔案 UUID。

        Returns:
            True = 還在;False = 已刪。Probe 出錯時也回 True(fail-open)。
        """
        try:
            records = self._ctx.indexing_service.get_files_by_ids([str(file_id)])
        except Exception as e:
            logger.warning(
                f"[FILE_EXISTS_PROBE] fid={file_id} | probe failed, "
                f"assuming file still exists: {e}"
            )
            return True
        return str(file_id) in records

    def _make_should_abort(self, file_id) -> "Callable[[], bool]":
        """建立單檔的 mid-stage abort probe(gate 之外的 stage 內檢查點用)。

        兩層訊號,回傳 True 即該檔中止:
        ① IndexingJobManager 的 per-file abort flag — 刪檔主動通知,in-memory
           查詢零成本,每個檢查點都看(消費即清除)。
        ② `_file_still_exists` DB probe — 兜底,每 _ABORT_PROBE_INTERVAL_SECONDS
           節流一次,涵蓋 manager 通知不到的刪法。
        保證不 raise(indexer 端不再包 try);判定過一次 abort 後結果黏住,
        後續呼叫直接回 True 不再打 DB。
        """
        fid = str(file_id)
        state = {"aborted": False, "last_probe": time.monotonic()}

        def _should_abort() -> bool:
            if state["aborted"]:
                return True
            try:
                from src.domain.rag.index_job_manager import IndexingJobManager
                manager = IndexingJobManager.get_instance()
                if manager.is_file_abort_requested(fid):
                    manager.clear_file_abort(fid)
                    state["aborted"] = True
                    return True
            except Exception as e:  # pragma: no cover - 防禦性
                logger.debug(f"[ABORT_PROBE] fid={fid} | manager flag check failed: {e}")
            now = time.monotonic()
            if now - state["last_probe"] >= _ABORT_PROBE_INTERVAL_SECONDS:
                state["last_probe"] = now
                if not self._file_still_exists(fid):  # probe 自身 fail-open
                    state["aborted"] = True
            return state["aborted"]

        return _should_abort

    # ------------------------------------------------------------------
    # Single-document indexing
    # ------------------------------------------------------------------

    async def index_document(
        self,
        file_record: FileRequest,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        folder_id_override: Optional[int] = None,
        force: bool = False,
        _timings_out: Optional[Dict[str, float]] = None,
        _progress_cb=None,
    ) -> IndexDocumentResponse:
        """將文件索引到向量存儲。

        Args:
            file_record: File information
            token: Client API token
            chunk_size: Chunk size (characters). 為 None 用 config 預設值
            chunk_overlap: Chunk overlap size. 為 None 用 config 預設值
            force: True = 跳過 content_hash 冪等短路,強制重跑整條管線 —
                設定變更(contextual retrieval / embedding / chunking)後
                單檔重建用。寫入前的 stale-chunk purge 保證不留舊向量。
            _timings_out: T1.4 internal — if provided, populated with
                ``{"load_ms": float, "index_ms": float}`` for per-file audit.
            _progress_cb: chunk 級進度回呼 ``(stage, done, total)``,由背景 job
                的 IndexProgressTracker.on_chunk_progress 供給;None 靜默。

        Raises:
            FileIndexingError: indexing 失敗
        """
        file_id = file_record.id
        ctx = self._ctx

        # progress_cb 為 None 代表沒有背景 job 在追這次索引(同步單檔 API),
        # 沒有 job state 要保活,就不必多開一條 keepalive task。
        if _progress_cb is None:
            async with _get_indexing_semaphore():
                return await self._index_document_locked(
                    file_record=file_record,
                    token=token,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    folder_id_override=folder_id_override,
                    _timings_out=_timings_out,
                    _progress_cb=None,
                )

        # keepalive 包在 semaphore **外面**:等 semaphore 也是心跳盲區
        # (semaphore 跨 job 共用,別的 job 佔著時本 job 完全不動),
        # 包在裡面的話等待期間照樣會被 watchdog 誤判。
        async with _ProgressKeepalive(_progress_cb) as keepalive:
            # StageTimer 掛最外層觀察每個 stage 的 wall-clock 耗時
            # (loading/contextualizing/embedding/writing);keepalive 補發的
            # 同 stage 心跳不觸發切換,不影響計時。結果進 file_timings.stage_ms
            from src.domain.rag.stage_timer import StageTimer
            timer = StageTimer(inner=keepalive)
            try:
                # 限制同時跑的 indexing 任務數 — 上傳 N 個檔案不會一起搶 GPU/OCR session
                async with _get_indexing_semaphore():
                    return await self._index_document_locked(
                        file_record=file_record,
                        token=token,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        folder_id_override=folder_id_override,
                        force=force,
                        _timings_out=_timings_out,
                        _progress_cb=timer,
                    )
            finally:
                # 成功/失敗/timeout 都要收斂計時 — 失敗檔的階段耗時對排錯更重要
                if _timings_out is not None:
                    stage_ms = timer.finish()
                    if stage_ms:
                        _timings_out["stage_ms"] = stage_ms

    async def _index_document_locked(
        self,
        file_record: FileRequest,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        folder_id_override: Optional[int] = None,
        force: bool = False,
        _timings_out: Optional[Dict[str, float]] = None,
        _progress_cb=None,
    ) -> IndexDocumentResponse:
        """Index core — caller (index_document) 持有 semaphore 才能進。"""
        file_id = file_record.id
        ctx = self._ctx
        # Pre-bind folder_id so the except handler can pass it to
        # mark_index_failed even if a validation error fires before it is parsed.
        folder_id: Optional[int] = None

        try:
            # ---- Validate file_record ----
            if not file_record:
                raise ValueError("file_record cannot be None")
            if not file_record.file_path:
                raise ValueError("file_path cannot be empty")
            if not file_record.file_name:
                raise ValueError("file_name cannot be empty")

            # ---- folder_id 整型驗證 ----
            try:
                raw_folder_id = (
                    folder_id_override
                    if folder_id_override is not None
                    else file_record.folder_id
                )
                if raw_folder_id in (None, "None", ""):
                    raise ValueError(
                        f"folder_id is missing for file: {file_record.file_name}"
                    )
                folder_id = int(raw_folder_id)
            except (ValueError, TypeError) as ve:
                raise ValueError(
                    f"Invalid folder_id: '{raw_folder_id}' "
                    f"(type: {type(raw_folder_id).__name__}). Error: {ve}"
                )

            # Gate 1: file 中途被刪 → 提前 abort,省下 Docling/embed/ctx-gen
            if not await _run_db(self._file_still_exists, file_id):
                log_warn(
                    logger, "INDEX_ABORT",
                    folder_id=folder_id, file_id=file_id, token=token,
                    msg=f"file {file_id} was deleted during indexing — aborting (gate 1)",
                )
                raise RAGFileNotFoundError(file_id=str(file_id))

            # idempotency: content_hash 沒變直接 return,不重跑 embed
            # (force=True 旁路 — 單檔強制重建的唯一途徑,H4)
            current_hash = getattr(file_record, "content_hash", None)
            if current_hash and not force:
                existing_idx = await _run_db(ctx.indexing_service.get_index_for_file, file_id)
                if (
                    existing_idx
                    and getattr(existing_idx, "status", None) == "indexed"
                    and getattr(existing_idx, "content_hash", None) == current_hash
                ):
                    log_op(
                        logger, "INDEX_SKIP_IDEMPOTENT",
                        folder_id=existing_idx.folder_id, file_id=file_id, token=token,
                        msg=(
                            f"content_hash unchanged — reusing existing FileIndex "
                            f"({existing_idx.num_chunks} chunks)"
                        ),
                    )
                    return IndexDocumentResponse(
                        file_id=str(file_id),
                        index_id=existing_idx.index_id,
                        num_chunks=existing_idx.num_chunks or 0,
                        status="already_indexed_same_content",
                        indexed_at=(
                            existing_idx.indexed_at.isoformat()
                            if existing_idx.indexed_at else ""
                        ),
                        message="Skipped: content_hash unchanged from prior index",
                    )

            # ---- chunk size 參數 ----
            # Hierarchical chunking — chunk size 在 ctx 階段已從 hierarchy_sizes 取出固定。
            # 這裡保留參數簽名向下相容(IndexJobManager 會傳 chunk_size/chunk_overlap),
            # 但實際以 ctx.leaf_chunk_size / ctx.chunk_overlap 為準。
            # 若呼叫方明確傳入,記錄到 DB 時會使用其值(僅用於審計,不影響實際分塊)。
            try:
                if chunk_size is None or chunk_size == "":
                    chunk_size = ctx.leaf_chunk_size
                else:
                    chunk_size = int(chunk_size)
                if chunk_overlap is None or chunk_overlap == "":
                    chunk_overlap = ctx.chunk_overlap
                else:
                    chunk_overlap = int(chunk_overlap)
            except (ValueError, TypeError) as ve:
                raise ValueError(
                    f"Invalid chunk parameters. chunk_size={chunk_size}, "
                    f"chunk_overlap={chunk_overlap}. Error: {ve}"
                )

            # ---- Get vector store(driven by folder ownership)----
            folder = await _run_db(ctx.indexing_service.get_folder, folder_id, token)
            vector_store = ctx.get_vector_store(folder_id, token, folder=folder)
            vector_store_table = f"data_{folder_id}_{folder.vector_table_uuid}"

            # ---- 換模防護 ----
            # 此 folder 既有成功索引若出自別的 embedding model,拒絕混寫:
            # 維度相同時(如 bge-m3 → e5 都是 1024)insert 不會炸,但兩個
            # 向量空間互不相容,檢索會靜默劣化成接近隨機。唯一正解是 reindex。
            from db.fileindexdb import FileIndexDB
            prior_models = await _run_db(FileIndexDB.get_indexed_models_for_folder, folder_id)
            stale_models = [m for m in prior_models if m != ctx.model_name]
            if stale_models:
                raise ValueError(
                    f"Folder {folder_id} has indexes built with embedding model "
                    f"{stale_models} but current config uses '{ctx.model_name}'. "
                    f"Mixing embedding spaces silently corrupts retrieval — "
                    f"reindex the folder (POST /api/rag/files/{folder_id}/reindex) "
                    f"to switch models."
                )

            log_op(
                logger, "INDEX_START",
                folder_id=folder_id, file_id=file_id, token=token,
                msg=(
                    f"table={vector_store_table} "
                    f"leaf_size={ctx.leaf_chunk_size} "
                    f"parent_target={ctx.parent_target_tokens}"
                ),
            )

            # ---- Load document ----
            # Docling parsing + RapidOCR 是 sync CPU-bound,直接 call 會卡住整個
            # event loop(實測 11MB 圖文 PDF 走 OCR ~32s)。丟 thread pool 讓
            # 上傳 / 查詢 request 在 indexing 進行中還能繼續服務。
            logger.debug(
                f"[INDEX_LOAD] fid={folder_id} file={file_id} | "
                f"path={file_record.file_path} name={file_record.file_name}"
            )
            # 大檔的 docling/OCR 可到數百秒,是 chunk 進度的最大盲區——
            # 先報 loading stage,讓 job 狀態在解析期間不會呆在無 stage 狀態
            if _progress_cb:
                try:
                    _progress_cb("loading", None, None)
                except Exception:
                    pass  # 進度回報失敗不影響 indexing
            load_t0 = time.perf_counter()
            document = await asyncio.to_thread(
                ctx.indexer.load_document_from_file,
                file_path=file_record.file_path,
                file_id=str(file_id),
                file_name=file_record.file_name,
                # 頁級解析進度(PDF/OCR):badge 顯示「解析文件 done/total」
                # + ETA;keepalive 包裝過的 cb,順便刷心跳
                progress_cb=_progress_cb,
                metadata={
                    "folder_id": folder_id,
                    "folder_name": folder.name,
                    "mime_type": file_record.mime_type,
                    "file_size": file_record.file_size,
                },
            )
            if _timings_out is not None:
                _timings_out["load_ms"] = round((time.perf_counter() - load_t0) * 1000, 1)
            logger.debug(
                f"[INDEX_LOAD] fid={folder_id} file={file_id} | "
                f"text_len={len(document.text) if document.text else 0}"
            )

            # ---- Gate 2 (#24): re-check after Docling load, before the
            # expensive context-gen + embedding stages. ----
            if not await _run_db(self._file_still_exists, file_id):
                log_warn(
                    logger, "INDEX_ABORT",
                    folder_id=folder_id, file_id=file_id, token=token,
                    msg=f"file {file_id} was deleted during indexing — aborting (gate 2)",
                )
                raise RAGFileNotFoundError(file_id=str(file_id))

            # ---- Index hierarchically — 回傳 {"leaves": N, "parents": M} ----
            idx_t0 = time.perf_counter()
            try:
                index_stats = await ctx.indexer.index_document(
                    document=document,
                    vector_store=vector_store,
                    progress_cb=_progress_cb,
                    should_abort=self._make_should_abort(file_id),
                )
            except IndexingAbortedError as abort_exc:
                # stage 內檢查點(contextualizing / embedding / writing)發現
                # 檔案途中被刪 — 走與 gate 相同的 abort 路徑
                log_warn(
                    logger, "INDEX_ABORT",
                    folder_id=folder_id, file_id=file_id, token=token,
                    msg=f"{abort_exc} — aborting (mid-stage probe)",
                )
                raise RAGFileNotFoundError(file_id=str(file_id))
            if _timings_out is not None:
                _timings_out["index_ms"] = round((time.perf_counter() - idx_t0) * 1000, 1)
            num_leaves = index_stats.get("leaves", 0)
            num_parents = index_stats.get("parents", 0)

            log_op(
                logger, "INDEX_DONE",
                folder_id=folder_id, file_id=file_id, token=token,
                msg=f"{num_leaves} leaves + {num_parents} parents",
            )

            # ---- Gate 3 (#24): last chance — if the file is gone now, the
            # FileIndex FK insert below would blow up anyway. Abort cleanly. ----
            if not await _run_db(self._file_still_exists, file_id):
                # H2 修:此刻向量**已經寫進表了**(index_document 內含 add)。
                # 只 raise 不清 → 孤兒 chunks 永留(無 FileIndex、無 File row,
                # delete_chunks_by_file 再也不會被叫到),已刪檔內容持續被檢索
                # 命中。abort 前清掉剛寫入的 chunks。
                try:
                    from src.domain.rag.vector_store_manager import VectorStoreManager
                    removed = await _run_db(
                        VectorStoreManager.delete_chunks_by_file,
                        vector_store_table, str(file_id),
                    )
                    log_warn(
                        logger, "INDEX_ABORT_PURGE",
                        folder_id=folder_id, file_id=file_id, token=token,
                        msg=f"purged {removed} freshly-written chunk(s) of deleted file",
                    )
                except Exception as purge_err:
                    log_err(logger, "INDEX_ABORT_PURGE_FAIL", purge_err,
                            folder_id=folder_id, file_id=file_id, token=token)
                log_warn(
                    logger, "INDEX_ABORT",
                    folder_id=folder_id, file_id=file_id, token=token,
                    msg=f"file {file_id} was deleted during indexing — aborting (gate 3)",
                )
                raise RAGFileNotFoundError(file_id=str(file_id))

            # ---- Record index metadata ----
            # chunk_size 寫入 leaf size,num_chunks 記錄 leaves(實際被檢索的單位)
            index_record = await _run_db(
                ctx.indexing_service.record_index_success,
                file_id=file_id,
                folder_id=folder_id,
                index_id=f"file_{file_id}",
                vector_store_table=vector_store_table,
                chunk_size=ctx.leaf_chunk_size,
                chunk_overlap=ctx.chunk_overlap,
                embedding_model=ctx.model_name,
                num_chunks=num_leaves,
                content_hash=getattr(file_record, "content_hash", None),  # D3
            )

            # ---- Invalidate caches ----
            await _run_db(ctx.indexing_service.invalidate_folder_caches, folder_id)
            ctx.invalidate_query_engine_cache(folder_id)

            return IndexDocumentResponse(
                file_id=str(file_id),
                index_id=index_record.index_id,
                num_chunks=num_leaves,
                status="indexed",
                indexed_at=index_record.indexed_at.isoformat(),
                message=f"Indexed hierarchically: {num_leaves} leaves + {num_parents} parents",
            )

        except DomainException:
            raise
        except Exception as e:
            log_err(
                logger, "INDEX_FAIL", e,
                folder_id=folder_id, file_id=file_id, token=token,
            )
            try:
                # 傳 folder_id + 真實 model/size → 失敗 row 反映真實 config,而非 column 預設
                ctx.indexing_service.mark_index_failed(
                    file_id,
                    str(e),
                    folder_id=folder_id,
                    embedding_model=ctx.model_name,
                    chunk_size=ctx.leaf_chunk_size,
                    chunk_overlap=ctx.chunk_overlap,
                )
            except Exception:
                pass
            raise FileIndexingError(file_id=str(file_id), reason=str(e))

    # ------------------------------------------------------------------
    # Folder-wide indexing
    # ------------------------------------------------------------------

    async def index_folder(
        self,
        folder_id: int,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        skip_existing: bool = True,
        progress_tracker: Optional["IndexProgressTracker"] = None,
    ) -> IndexFolderResponse:
        """將資料夾中所有文件索引到向量存儲。"""
        ctx = self._ctx

        try:
            # Validate folder access upfront
            await _run_db(ctx.indexing_service.get_folder, folder_id, token)

            files = await _run_db(ctx.indexing_service.list_files, folder_id)
            total_files = len(files)

            if progress_tracker:
                progress_tracker.on_started(total_files, skip_existing)

            if not files:
                log_op(
                    logger, "INDEX_FOLDER",
                    folder_id=folder_id, token=token, msg="no files found",
                )
                response = IndexFolderResponse(
                    folder_id=folder_id, total_files=0, successful=0,
                    failed=0, skipped=0, results=[],
                    message="No files found in folder",
                )
                if progress_tracker:
                    progress_tracker.mark_completed(response.model_dump())
                return response

            log_op(
                logger, "INDEX_FOLDER_START",
                folder_id=folder_id, token=token,
                msg=f"{len(files)} files, skip_existing={skip_existing}",
            )

            successful = 0
            failed = 0
            skipped = 0
            results: List[FileIndexResult] = []
            processed_count = 0
            per_file_timeout = _resolve_per_file_timeout()  # bounds each file

            for file_record in files:
                file_id = file_record.id
                filename = file_record.file_name

                if progress_tracker:
                    progress_tracker.on_file_started(
                        current_index=processed_count + 1,
                        file_id=str(file_id),
                        file_name=filename,
                    )

                stage_timings: Dict[str, float] = {}
                file_t0 = time.perf_counter()
                try:
                    if skip_existing:
                        existing_index = await _run_db(ctx.indexing_service.get_index_for_file, file_id)
                        # H3 修:只有 status=indexed 才算「已索引」— failed/deleted
                        # 的 row 不能擋重試,否則失敗檔用 /index 永遠救不回
                        if existing_index and getattr(existing_index, "status", None) == "indexed":
                            log_warn(
                                logger, "INDEX_SKIP",
                                folder_id=folder_id, file_id=file_id, token=token,
                                msg=f"already indexed: {filename}",
                            )
                            skipped += 1
                            processed_count += 1
                            results.append(FileIndexResult(
                                file_id=str(file_id), filename=filename,
                                status="skipped",
                                message="File is already indexed",
                                num_chunks=None,
                            ))
                            if progress_tracker:
                                progress_tracker.on_file_completed(
                                    processed_files=processed_count,
                                    status="skipped",
                                    message="File is already indexed",
                                )
                                progress_tracker.record_file_timing(_make_timing_entry(
                                    file_id, filename, "skipped",
                                    file_t0, stage_timings,
                                ))
                            continue

                    result = await _with_timeout(
                        self.index_document(
                            file_record=file_record,
                            token=token,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            folder_id_override=folder_id,
                            _timings_out=stage_timings,
                            _progress_cb=(
                                progress_tracker.on_chunk_progress
                                if progress_tracker else None
                            ),
                        ),
                        per_file_timeout,
                        filename,
                    )

                    successful += 1
                    processed_count += 1
                    results.append(FileIndexResult(
                        file_id=str(file_id), filename=filename,
                        status="success",
                        message=result.message,
                        num_chunks=result.num_chunks,
                    ))
                    log_op(
                        logger, "INDEX_FILE_DONE",
                        folder_id=folder_id, file_id=file_id, token=token,
                        msg=f"{result.num_chunks} chunks | {filename}",
                    )
                    if progress_tracker:
                        progress_tracker.on_file_completed(
                            processed_files=processed_count,
                            status="success",
                            message=result.message,
                        )
                        progress_tracker.record_file_timing(_make_timing_entry(
                            file_id, filename, "success", file_t0, stage_timings,
                            chunks=result.num_chunks,
                        ))

                except Exception as e:
                    failed += 1
                    error_message = str(e)
                    processed_count += 1
                    status_label = "timeout" if isinstance(e, TimeoutError) else "failed"
                    results.append(FileIndexResult(
                        file_id=str(file_id), filename=filename,
                        status="failed",
                        message=error_message,
                        num_chunks=None,
                    ))
                    log_err(
                        logger, "INDEX_FILE_FAIL", e,
                        folder_id=folder_id, file_id=file_id, token=token,
                    )
                    # 持久化 failed 記錄 — 前端才顯示得出「失敗」tag。
                    # ⚠️ timeout 走 asyncio.wait_for 的 cancel,注入的是
                    # CancelledError(BaseException,非 Exception),index_document
                    # 內層的 except Exception 接不到 → 它的 mark_index_failed 不會跑,
                    # 逾時檔就完全沒有 FileIndex 記錄 → 前端無 tag。這裡兜底補寫。
                    # 非逾時失敗 index_document 已寫過,upsert 重寫同一筆無害。
                    try:
                        ctx.indexing_service.mark_index_failed(
                            file_id,
                            error_message,
                            folder_id=folder_id,
                            embedding_model=ctx.model_name,
                            chunk_size=ctx.leaf_chunk_size,
                            chunk_overlap=ctx.chunk_overlap,
                        )
                    except Exception as _mf_err:
                        # M3: 兜底補寫失敗別靜默 —— DB 斷線/衝突會讓前端缺 tag
                        # 且無跡可循,與這段「確保失敗被記錄」的目的矛盾。
                        logger.warning(
                            f"mark_index_failed fallback also failed for "
                            f"file {file_id}: {_mf_err}"
                        )
                    if progress_tracker:
                        progress_tracker.on_file_completed(
                            processed_files=processed_count,
                            status="failed",
                            message=error_message,
                        )
                        progress_tracker.record_file_timing(_make_timing_entry(
                            file_id, filename, status_label, file_t0, stage_timings,
                        ))

                except asyncio.CancelledError:
                    # M2: job 級逾時/cancel 經 wait_for 注入 CancelledError(BaseException,
                    # 上面的 except Exception 接不到)。in-flight 檔會既非 indexed 也非
                    # failed 而在前端憑空消失。補寫 failed 記錄後 re-raise 保留取消語義。
                    # mark_index_failed 是 sync,cancel 期間呼叫安全。
                    try:
                        ctx.indexing_service.mark_index_failed(
                            file_id,
                            "aborted: job cancelled or job-level timeout",
                            folder_id=folder_id,
                            embedding_model=ctx.model_name,
                            chunk_size=ctx.leaf_chunk_size,
                            chunk_overlap=ctx.chunk_overlap,
                        )
                    except Exception as _mf_err:
                        logger.warning(
                            f"mark_index_failed on cancel failed for file {file_id}: {_mf_err}"
                        )
                    raise

            summary_message = (
                f"Folder indexing completed: {successful} successful, "
                f"{failed} failed, {skipped} skipped"
            )
            log_op(
                logger, "INDEX_FOLDER_DONE",
                folder_id=folder_id, token=token, msg=summary_message,
            )

            await _run_db(ctx.indexing_service.invalidate_folder_caches, folder_id)

            response = IndexFolderResponse(
                folder_id=folder_id,
                total_files=total_files,
                successful=successful,
                failed=failed,
                skipped=skipped,
                results=results,
                message=summary_message,
            )
            if progress_tracker:
                progress_tracker.mark_completed(response.model_dump())
            return response

        except DomainException as domain_exc:
            if progress_tracker:
                progress_tracker.mark_failed(str(domain_exc))
            raise
        except Exception as e:
            log_err(logger, "INDEX_FOLDER_FAIL", e, folder_id=folder_id, token=token)
            if progress_tracker:
                progress_tracker.mark_failed(str(e))
            raise ValueError(f"Failed to index folder: {str(e)}")

    # ------------------------------------------------------------------
    # Subset indexing (auto-index after upload)
    # ------------------------------------------------------------------

    async def index_files(
        self,
        file_ids: List[str],
        folder_id: int,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        progress_tracker: Optional["IndexProgressTracker"] = None,
    ) -> IndexFolderResponse:
        """索引指定的 file_id 子集(供上傳後 auto-index)。

        跟 index_folder 類似但只處理 file_ids 內的;**不 skip 已索引**,因為呼叫端是
        為了重做或補做剛 upload 的檔案。

        Args:
            file_ids: 要索引的 UUID 字串 list。
            folder_id: 所屬 folder id。
            token: 使用者 token(權限驗證)。
            chunk_size: 覆寫 chunk size;None = 用 ctx.leaf_chunk_size。
            chunk_overlap: 覆寫 chunk overlap;None = 用 ctx.chunk_overlap。
            progress_tracker: 背景 job 進度回報用;None = 同步呼叫。

        Returns:
            IndexFolderResponse(每檔 success/failed 細節 + 統計)。
        """
        ctx = self._ctx

        try:
            await _run_db(ctx.indexing_service.get_folder, folder_id, token)

            files = await _run_db(ctx.indexing_service.list_files, folder_id)
            files_to_index = [f for f in files if str(f.id) in file_ids]
            total_files = len(files_to_index)

            if progress_tracker:
                progress_tracker.on_started(total_files, skip_existing=False)

            if not files_to_index:
                log_op(
                    logger, "INDEX_FILES",
                    folder_id=folder_id, token=token,
                    msg="no matching files found",
                )
                response = IndexFolderResponse(
                    folder_id=folder_id, total_files=0, successful=0,
                    failed=0, skipped=0, results=[],
                    message="No files found to index",
                )
                if progress_tracker:
                    progress_tracker.mark_completed(response.model_dump())
                return response

            log_op(
                logger, "INDEX_FILES_START",
                folder_id=folder_id, token=token,
                msg=f"{len(files_to_index)} files",
            )

            successful = 0
            failed = 0
            skipped = 0
            results: List[FileIndexResult] = []
            processed_count = 0
            per_file_timeout = _resolve_per_file_timeout()  # bounds each file

            for file_record in files_to_index:
                file_id = file_record.id
                filename = file_record.file_name

                if progress_tracker:
                    progress_tracker.on_file_started(
                        current_index=processed_count + 1,
                        file_id=str(file_id),
                        file_name=filename,
                    )

                stage_timings: Dict[str, float] = {}
                file_t0 = time.perf_counter()
                try:
                    result = await _with_timeout(
                        self.index_document(
                            file_record=file_record,
                            token=token,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            folder_id_override=folder_id,
                            _timings_out=stage_timings,
                            _progress_cb=(
                                progress_tracker.on_chunk_progress
                                if progress_tracker else None
                            ),
                        ),
                        per_file_timeout,
                        filename,
                    )
                    successful += 1
                    processed_count += 1
                    results.append(FileIndexResult(
                        file_id=str(file_id), filename=filename,
                        status="success",
                        message=result.message,
                        num_chunks=result.num_chunks,
                    ))
                    log_op(
                        logger, "INDEX_FILE_DONE",
                        folder_id=folder_id, file_id=file_id, token=token,
                        msg=f"{result.num_chunks} chunks | {filename}",
                    )
                    if progress_tracker:
                        progress_tracker.on_file_completed(
                            processed_files=processed_count,
                            status="success",
                            message=result.message,
                        )
                        progress_tracker.record_file_timing(_make_timing_entry(
                            file_id, filename, "success", file_t0, stage_timings,
                            chunks=result.num_chunks,
                        ))

                except Exception as e:
                    failed += 1
                    error_message = str(e)
                    processed_count += 1
                    status_label = "timeout" if isinstance(e, TimeoutError) else "failed"
                    results.append(FileIndexResult(
                        file_id=str(file_id), filename=filename,
                        status="failed",
                        message=error_message,
                        num_chunks=None,
                    ))
                    log_err(
                        logger, "INDEX_FILE_FAIL", e,
                        folder_id=folder_id, file_id=file_id, token=token,
                    )
                    # 持久化 failed 記錄 — 前端才顯示得出「失敗」tag。
                    # ⚠️ timeout 走 asyncio.wait_for 的 cancel,注入的是
                    # CancelledError(BaseException,非 Exception),index_document
                    # 內層的 except Exception 接不到 → 它的 mark_index_failed 不會跑,
                    # 逾時檔就完全沒有 FileIndex 記錄 → 前端無 tag。這裡兜底補寫。
                    # 非逾時失敗 index_document 已寫過,upsert 重寫同一筆無害。
                    try:
                        ctx.indexing_service.mark_index_failed(
                            file_id,
                            error_message,
                            folder_id=folder_id,
                            embedding_model=ctx.model_name,
                            chunk_size=ctx.leaf_chunk_size,
                            chunk_overlap=ctx.chunk_overlap,
                        )
                    except Exception as _mf_err:
                        # M3: 兜底補寫失敗別靜默 —— DB 斷線/衝突會讓前端缺 tag
                        # 且無跡可循,與這段「確保失敗被記錄」的目的矛盾。
                        logger.warning(
                            f"mark_index_failed fallback also failed for "
                            f"file {file_id}: {_mf_err}"
                        )
                    if progress_tracker:
                        progress_tracker.on_file_completed(
                            processed_files=processed_count,
                            status="failed",
                            message=error_message,
                        )
                        progress_tracker.record_file_timing(_make_timing_entry(
                            file_id, filename, status_label, file_t0, stage_timings,
                        ))

                except asyncio.CancelledError:
                    # M2: job 級逾時/cancel 經 wait_for 注入 CancelledError(BaseException,
                    # 上面的 except Exception 接不到)。in-flight 檔會既非 indexed 也非
                    # failed 而在前端憑空消失。補寫 failed 記錄後 re-raise 保留取消語義。
                    # mark_index_failed 是 sync,cancel 期間呼叫安全。
                    try:
                        ctx.indexing_service.mark_index_failed(
                            file_id,
                            "aborted: job cancelled or job-level timeout",
                            folder_id=folder_id,
                            embedding_model=ctx.model_name,
                            chunk_size=ctx.leaf_chunk_size,
                            chunk_overlap=ctx.chunk_overlap,
                        )
                    except Exception as _mf_err:
                        logger.warning(
                            f"mark_index_failed on cancel failed for file {file_id}: {_mf_err}"
                        )
                    raise

            summary_message = (
                f"File indexing completed: {successful} successful, {failed} failed"
            )
            log_op(
                logger, "INDEX_FILES_DONE",
                folder_id=folder_id, token=token, msg=summary_message,
            )

            await _run_db(ctx.indexing_service.invalidate_folder_caches, folder_id)

            response = IndexFolderResponse(
                folder_id=folder_id,
                total_files=total_files,
                successful=successful,
                failed=failed,
                skipped=skipped,
                results=results,
                message=summary_message,
            )
            if progress_tracker:
                progress_tracker.mark_completed(response.model_dump())
            return response

        except DomainException as domain_exc:
            if progress_tracker:
                progress_tracker.mark_failed(str(domain_exc))
            raise
        except Exception as e:
            error_msg = f"Failed to index files: {str(e)}"
            logger.error(error_msg)
            if progress_tracker:
                progress_tracker.mark_failed(error_msg)
            raise ValueError(error_msg)

    # ------------------------------------------------------------------
    # Auto-index trigger (background job)
    # ------------------------------------------------------------------

    async def trigger_auto_index(
        self,
        file_ids: List[str],
        folder_id: int,
        token: str,
        auto_index: bool = True,
    ) -> Dict[str, Any]:
        """上傳成功後觸發背景 auto-index job。

        Args:
            file_ids: 剛上傳的檔案 UUID list。
            folder_id: 所屬 folder。
            token: 使用者 token。
            auto_index: False 或 file_ids 為空 → 直接 return 不啟動。

        Returns:
            IndexingMetadata-shape dict:
            ``{auto_index_enabled, job_id?, status?, total_files?, message}``。
        """
        try:
            from src.domain.rag.index_job_manager import IndexingJobManager

            if not auto_index or not file_ids:
                return {
                    "auto_index_enabled": False,
                    "message": (
                        "Auto-indexing disabled or no files to index. "
                        "Call /api/rag/files/{folder_id}/index to index manually"
                    ),
                }

            # 用 ctx 自身的 leaf size / overlap(於 RAGContext.from_config 設定)
            chunk_size = self._ctx.leaf_chunk_size
            chunk_overlap = self._ctx.chunk_overlap

            job_manager = IndexingJobManager.get_instance()
            # IndexingJobManager 透過 adapter 介面呼叫 .index_files(),this service
            # exposes that method directly,所以可以把自己當 adapter 傳進去。
            job_state = await job_manager.start_indexing_files(
                self,
                file_ids=file_ids,
                folder_id=folder_id,
                token=token,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

            log_op(
                logger, "AUTO_INDEX",
                folder_id=folder_id, token=token,
                msg=f"{len(file_ids)} files, job_id={job_state['job_id']}",
            )

            return {
                "auto_index_enabled": True,
                "job_id": job_state["job_id"],
                "status": job_state["status"],
                "total_files": len(file_ids),
                "message": f"Indexing started in background for {len(file_ids)} file(s)",
            }

        except Exception as e:
            log_err(logger, "AUTO_INDEX_FAIL", e, folder_id=folder_id, token=token)
            return {
                "auto_index_enabled": True,
                "message": (
                    f"Warning: Auto-indexing failed to start: {str(e)}. "
                    f"File uploaded successfully. You can index manually later."
                ),
            }
