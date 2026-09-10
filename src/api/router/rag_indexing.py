
"""RAG Indexing REST API

只負責 indexing 相關操作:
- POST   /api/rag/files/{folder_id}/index                       索引整個資料夾(背景非同步)
- POST   /api/rag/file/{file_id}/index                          索引單一檔案
- POST   /api/rag/files/{folder_id}/reindex                     重新索引整個資料夾
- GET    /api/rag/indexed-files                                 查詢已索引的檔案清單
- GET    /api/rag/files/{folder_id}/index/jobs/{job_id}         查詢背景任務狀態
- GET    /api/rag/files/{folder_id}/index/jobs/{job_id}/events  SSE realtime progress stream (D1)
- DELETE /api/rag/files/{folder_id}/index/jobs/{job_id}         取消背景索引任務 (A1)
- GET    /api/rag/file/{file_id}/index/status                   查詢單檔索引狀態 (Part 3)
- DELETE /api/rag/files/{folder_id}/index                       刪除整個資料夾索引
- DELETE /api/rag/file/{file_id}/index                          刪除單檔索引

查詢 endpoint 已移到 rag_query.py。
"""

import asyncio
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from db.cached_folderdb import CachedFolderDB
from db.db import File, Folder
from src.adapter.folder import FolderAdapter
from src.adapter.rag import get_rag_adapter
from src.api.dependencies.auth import (
    extract_token,
    get_file_by_id,
    get_folder_by_id,
    get_folder_by_name,
)
from src.api.router.response import (
    ErrorDetailResponse,
    FileIndexStatusEnvelope,
    FileIndexStatusResponse,
    FileRequest,
    IndexDocumentEnvelope,
    IndexedFilesResponse,
    IndexJobCancelResponse,
    IndexJobEnvelope,
    IndexJobListResponse,
    IndexJobStatusResponse,
    IndexRequest,
)
from src.auth.dependencies import authenticate_request
from src.domain.exceptions import ConflictError, FolderNotFoundError
from src.domain.rag.index_job_manager import IndexingJobManager, JobStatus
from src.log import get_api_logger, log_err, log_op, log_warn

logger = get_api_logger()

# router-level tag 留空;每個 endpoint 自己 declare 分群(Indexing/Jobs/Status/Cleanup)
router = APIRouter(dependencies=[Depends(authenticate_request)])

# Tag constants — keep in sync with openapi_tags in app.py (順序也在那裡定義)
_TAG_INDEXING = "RAG: Indexing"
_TAG_JOBS = "RAG: Jobs"
_TAG_STATUS = "RAG: Status"
_TAG_CLEANUP = "RAG: Cleanup"

job_manager = IndexingJobManager.get_instance()


# ============================================================================
# Index operations
# ============================================================================

_INDEX_REQUEST_EXAMPLES = {
    "use_config_defaults": {
        "summary": "用 config 預設(最常見)",
        "description": "送空 body → indexing 從 `config.rag.chunking` 讀預設值。",
        "value": {},
    },
    "explicit_match_config": {
        "summary": "顯式對齊 config 當前值",
        "description": "把 config 預設複製到 request,方便只調其中一個。",
        "value": {"chunk_size": 256, "chunk_overlap": 50},
    },
    "smaller_chunks": {
        "summary": "更小的 chunk(高精準度)",
        "description": "leaf 切小,提升 retrieval 精度但會產生更多 chunk。",
        "value": {"chunk_size": 128, "chunk_overlap": 30},
    },
}


# Resource = IndexJob;Response = {data: IndexJobStatusResponse, message}(背景 job,立刻回 job_id)
@router.post(
    "/files/{folder_id}/index",
    tags=[_TAG_INDEXING],
    response_model=IndexJobEnvelope,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        409: {"model": ErrorDetailResponse, "description": "該 folder 已有 in-flight indexing job (#28 folder lock)"},
        500: {"model": ErrorDetailResponse},
    },
)
async def index_folder_endpoint(
    folder_id: int,
    index_request: IndexRequest = Body(..., openapi_examples=_INDEX_REQUEST_EXAMPLES),
    skip_existing: bool = True,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """背景索引整個資料夾的所有檔案"""
    try:
        log_op(logger, "API_INDEX_FOLDER", folder_id=folder_id, token=token,
               msg=f"skip_existing={skip_existing}")

        folder_list = await FolderAdapter.get_folder(id=folder_id, user_token=token)
        if not folder_list:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")

        job_state = await job_manager.start_indexing(
            get_rag_adapter(),
            folder_id=folder_id,
            token=token,
            chunk_size=index_request.chunk_size,
            chunk_overlap=index_request.chunk_overlap,
            skip_existing=skip_existing,
        )

        job_response = IndexJobStatusResponse.model_validate(job_state)
        return {"data": job_response.model_dump(), "message": "Indexing job started"}

    except FolderNotFoundError as e:
        log_warn(logger, "API_INDEX_FOLDER_404", folder_id=folder_id, token=token, msg=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        log_warn(logger, "API_INDEX_FOLDER_409", folder_id=folder_id, token=token, msg=e.message)
        raise HTTPException(status_code=409, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_INDEX_FOLDER_FAIL", e, folder_id=folder_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to start indexing: {str(e)}")


# Resource = FileIndex;Response = {data: IndexDocumentResponse, message}(同步,等真正索引完才返回)
@router.post(
    "/file/{file_id}/index",
    tags=[_TAG_INDEXING],
    response_model=IndexDocumentEnvelope,
    responses={
        404: {"model": ErrorDetailResponse, "description": "file 不存在或無權限"},
        500: {"model": ErrorDetailResponse, "description": "索引失敗(Docling / embedding 等)"},
    },
)
async def index_single_file_endpoint(
    file_id: UUID,
    index_request: IndexRequest = Body(..., openapi_examples=_INDEX_REQUEST_EXAMPLES),
    force: bool = False,
    token: str = Depends(extract_token),
    file: File = Depends(get_file_by_id),
):
    """同步索引單一檔案。

    force=true 跳過 content_hash 冪等短路,強制重跑整條管線(設定變更後
    的單檔重建;寫入前會先清該檔舊向量,不會殘留重複)。
    """
    try:
        log_op(logger, "API_INDEX_FILE", file_id=file_id, token=token,
               msg=f"chunk_size={index_request.chunk_size} force={force}")

        file_request = FileRequest(
            id=file.id,
            file_name=file.file_name,
            file_path=file.file_path,
            folder_id=file.folder_id,
            mime_type=file.mime_type,
            file_size=file.file_size,
            content_hash=getattr(file, "content_hash", None),  # D3 idempotency
        )

        result = await get_rag_adapter().index_document(
            file_record=file_request,
            token=token,
            chunk_size=index_request.chunk_size,
            chunk_overlap=index_request.chunk_overlap,
            force=force,
        )

        return {
            "data": result.model_dump(),
            "message": f"File indexed successfully with {result.num_chunks} chunks",
        }
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_INDEX_FILE_FAIL", e, file_id=file_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to index file: {str(e)}")


# Resource = IndexJob;Response = {data: IndexJobStatusResponse, message}(先刪 folder 索引再啟動新 job)
@router.post(
    "/files/{folder_id}/reindex",
    tags=[_TAG_INDEXING],
    response_model=IndexJobEnvelope,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        409: {"model": ErrorDetailResponse, "description": "該 folder 已有 in-flight job"},
        500: {"model": ErrorDetailResponse},
    },
)
async def reindex_folder_endpoint(
    folder_id: int,
    reindex_request: IndexRequest = Body(..., openapi_examples=_INDEX_REQUEST_EXAMPLES),
    skip_existing: bool = False,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """先刪除舊索引,再背景重新索引整個資料夾"""
    try:
        logger.info(
            f"API: Reindexing folder_id={folder_id} chunk_size={reindex_request.chunk_size} "
            f"chunk_overlap={reindex_request.chunk_overlap}"
        )

        # C1 修:刪舊索引失敗**必須中止** — 舊行為(warn 後照跑)會讓 reindex
        # 在索引未清的情況下啟動,content_hash 短路使其成為靜默 no-op。
        try:
            delete_result = await get_rag_adapter().delete_folder_index(
                folder_id=folder_id, token=token
            )
            logger.info(f"Deleted {delete_result.successful} file indices before reindexing")
        except Exception as e:
            log_err(logger, "API_REINDEX_DELETE_FAIL", e, folder_id=folder_id)
            raise HTTPException(
                status_code=500,
                detail=f"Reindex aborted: failed to clear existing index ({e}). "
                       "Nothing was rebuilt — retry when the cause is resolved.",
            )

        # H5 緩解:刪除→啟動之間的 folder lock 空窗可能被 auto-index 搶走
        # (start_indexing 是拒絕語義)。此刻索引已清,409 放棄會留下空索引 —
        # 重試幾次拿鎖,拿不到才回 409(訊息明確指示重按)。
        job_state = None
        for attempt in range(3):
            try:
                job_state = await job_manager.start_indexing(
                    get_rag_adapter(),
                    folder_id=folder_id,
                    token=token,
                    chunk_size=reindex_request.chunk_size,
                    chunk_overlap=reindex_request.chunk_overlap,
                    skip_existing=skip_existing,
                )
                break
            except ConflictError:
                if attempt == 2:
                    raise HTTPException(
                        status_code=409,
                        detail="Index cleared but folder busy (another job grabbed the lock). "
                               "Existing index has been deleted — start indexing again once the folder is free.",
                    )
                await asyncio.sleep(1.5)

        job_response = IndexJobStatusResponse.model_validate(job_state)
        return {"data": job_response.model_dump(), "message": "Reindexing job started"}

    except ConflictError as e:
        log_warn(logger, "API_REINDEX_409", folder_id=folder_id, token=token, msg=e.message)
        raise HTTPException(status_code=409, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_REINDEX_FAIL", e, folder_id=folder_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to reindex folder: {str(e)}")


# ============================================================================
# Read-only status
# ============================================================================

# Resource = List[FileIndex];Response = {data: [IndexedFileEntry...], message}
@router.get(
    "/indexed-files",
    tags=[_TAG_STATUS],
    response_model=IndexedFilesResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def get_indexed_files(
    folder_id: int,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """列出指定資料夾內已索引的所有檔案"""
    try:
        logger.info(f"API: Getting indexed files for folder_id={folder_id}")
        result = await get_rag_adapter().get_indexed_files(folder_id=folder_id)
        return {"data": result, "message": f"Found {len(result)} indexed files"}
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_GET_INDEXED_FAIL", e, folder_id=folder_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to get indexed files: {str(e)}")


# Resource = IndexJob;Response = {data: IndexJobStatusResponse, message}
@router.get(
    "/files/{folder_id}/index/jobs/{job_id}",
    tags=[_TAG_JOBS],
    response_model=IndexJobEnvelope,
    responses={
        404: {"model": ErrorDetailResponse, "description": "job_id 不存在或不屬於該 folder"},
        500: {"model": ErrorDetailResponse},
    },
)
async def get_index_job_status(
    folder_id: int,
    job_id: str,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """查詢背景索引任務狀態"""
    try:
        status = await job_manager.get_status(job_id)

        if not status or status.get("folder_id") != folder_id:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

        job_response = IndexJobStatusResponse.model_validate(status)
        return {"data": job_response.model_dump(), "message": "Indexing job status retrieved"}

    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_JOB_STATUS_FAIL", e, folder_id=folder_id)
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


# Response = {counts: {status: count}, jobs: [IndexJobStatusResponse...]}
@router.get(
    "/index/jobs",
    tags=[_TAG_JOBS],
    response_model=IndexJobListResponse,
    responses={
        400: {"model": ErrorDetailResponse, "description": "status query param 不是合法值"},
        500: {"model": ErrorDetailResponse},
    },
)
async def list_index_jobs(
    status: Optional[str] = None,
    folder_id: Optional[int] = None,
    token: str = Depends(extract_token),
):
    """列出 indexing jobs + 各狀態 count(只回 token 擁有的 folders 的 jobs)。

    Query params:
      - status: pending / running / succeeded / partial_success / failed / cancelled
                (可選,只回該狀態)
      - folder_id: 只回該 folder 的 jobs(可選;不屬於此 token 時 404)

    Returns:
      {
        "counts": {"pending": N, "running": N, "succeeded": N, "partial_success": N,
                   "failed": N, "cancelled": N, "total": N},
        "jobs": [ {job_id, folder_id, status, progress, ...}, ... ]
      }
    """
    try:
        status_filter = None
        if status:
            try:
                status_filter = JobStatus(status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status '{status}'. Use one of: "
                           f"{[s.value for s in JobStatus]}",
                )

        # 所有權過濾 — 不濾的話任何合法 token 都看得到全站 jobs(檔名/錯誤/耗時)
        if folder_id is not None:
            folder = CachedFolderDB.get_by_id(folder_id)
            if not folder or folder.user_token != token:
                raise HTTPException(status_code=404, detail=f"Folder not found: {folder_id}")
            scoped = job_manager.list_jobs(folder_id=folder_id)
        else:
            # use_cache=False:folder 建立走 FolderDB.create,不會失效
            # folders:user:{token} 快取(TTL 180s)— 吃快取的話,新建 folder
            # 的 jobs 會被這裡隱形最多 3 分鐘。直查 DB(有 user_token index,便宜)
            allowed_ids = {
                f.id for f in CachedFolderDB.get_by_user_token(token, use_cache=False)
            }
            scoped = [
                j for j in job_manager.list_jobs()
                if j.get("folder_id") in allowed_ids
            ]

        # counts 也要限縮到本人的 jobs(維持原語義:不受 status filter 影響)
        counts = {s.value: 0 for s in JobStatus}
        for j in scoped:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        counts["total"] = len(scoped)

        jobs = (
            [j for j in scoped if j["status"] == status_filter.value]
            if status_filter is not None else scoped
        )
        return {"counts": counts, "jobs": jobs}
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_JOBS_LIST_FAIL", e)
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


# Statuses that mean "nothing more will happen on this job"
_TERMINAL_JOB_STATUSES = {
    "succeeded", "partial_success", "failed", "cancelled",
}


# Stream;非 JSON ─ 每個 event 是一個 IndexJobStatusResponse 序列化。Content-Type: text/event-stream
@router.get(
    "/files/{folder_id}/index/jobs/{job_id}/events",
    tags=[_TAG_JOBS],
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-Sent Events stream; each `data: {...}` 是完整 IndexJobStatusResponse JSON,到 terminal status 自動斷",
        },
        404: {"model": ErrorDetailResponse, "description": "job_id 不存在"},
    },
)
async def stream_index_job_events(
    folder_id: int,
    job_id: str,
    request: Request,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """SSE stream:推送 job 狀態變化(取代 polling)。

    每次 status / progress / 每檔完成 / timing 寫入都會推一個 `data: {full state JSON}` event。
    Job 達 terminal status 後 stream 自動關。閒置 15s 推 `:ping` 防 proxy 斷線。

    Args:
        folder_id: job 所屬 folder。
        job_id: 要訂閱的 job id。
        request: FastAPI Request(用來偵測 client 斷線)。
        token: 使用者 token(權限驗證)。
        folder: get_folder_by_id Depend 注入。

    Returns:
        StreamingResponse, Content-Type: text/event-stream。
    """
    # M9: 先 subscribe 再讀快照。反過來(舊寫法)會有空窗:讀完快照、還沒 subscribe
    # 之前 job 若轉終態,terminal 事件發給「還沒存在的訂閱者」而遺失 → 快照顯示非終態、
    # stream 之後只每 15s 送 ping,對一個已結束的 job 永遠掛著。先 subscribe 就不漏。
    queue = job_manager.subscribe(job_id)
    initial = await job_manager.get_status(job_id)
    if not initial or initial.get("folder_id") != folder_id:
        job_manager.unsubscribe(job_id, queue)
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    async def event_stream():
        try:
            # 1. 先送當前快照,client 一連上就渲染正確狀態,不必先 polling
            yield f"data: {json.dumps(initial)}\n\n"
            if initial.get("status") in _TERMINAL_JOB_STATUSES:
                return

            # 2. 消費 subscribe(早於快照)之後的所有更新;terminal 不會漏
            while True:
                # client 斷線就停;不然會對死掉的 socket emit 到天荒地老
                if await request.is_disconnected():
                    return
                try:
                    state = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(state)}\n\n"
                if state.get("status") in _TERMINAL_JOB_STATUSES:
                    return
        finally:
            job_manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        # Disable common buffering interceptors so events flush promptly.
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# Response = {data: {cancelled: bool, job_id: str}, message}
@router.delete(
    "/files/{folder_id}/index/jobs/{job_id}",
    tags=[_TAG_JOBS],
    response_model=IndexJobCancelResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "job_id 不存在或不屬於該 folder"},
        500: {"model": ErrorDetailResponse},
    },
)
async def cancel_index_job(
    folder_id: int,
    job_id: str,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """取消執行中的背景索引任務 (A1)"""
    try:
        status = await job_manager.get_status(job_id)
        if not status or status.get("folder_id") != folder_id:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        cancelled = await job_manager.cancel_job(job_id)
        if not cancelled:
            return {
                "data": {"cancelled": False, "job_id": job_id},
                "message": "Job already finished — nothing to cancel",
            }
        return {
            "data": {"cancelled": True, "job_id": job_id},
            "message": "Job cancelled",
        }
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_CANCEL_JOB_FAIL", e, folder_id=folder_id)
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


# Response = {data: FileIndexStatusResponse, message} ─ status ∈ indexed / indexing / queued / failed / not_indexed
@router.get(
    "/file/{file_id}/index/status",
    tags=[_TAG_STATUS],
    response_model=FileIndexStatusEnvelope,
    responses={
        404: {"model": ErrorDetailResponse, "description": "file 不存在或無權限"},
        500: {"model": ErrorDetailResponse},
    },
)
async def get_file_index_status(
    file_id: UUID,
    token: str = Depends(extract_token),
    file: File = Depends(get_file_by_id),
):
    """查單一檔案的索引狀態。

    Args:
        file_id: 檔案 UUID。
        token: 使用者 token(權限驗證)。
        file: get_file_by_id Depend 注入。

    Returns:
        envelope: ``{data: FileIndexStatusResponse, message}``;
        status ∈ ``indexed`` / ``indexing`` / ``queued`` / ``failed`` / ``not_indexed``。
    """
    try:
        from db.fileindexdb import FileIndexDB

        record = FileIndexDB.get_by_file(file_id)
        if record and getattr(record, "status", None) == "indexed":
            payload = FileIndexStatusResponse(
                file_id=str(file_id),
                file_name=file.file_name,
                status="indexed",
                num_chunks=getattr(record, "num_chunks", None),
                indexed_at=record.indexed_at.isoformat() if getattr(record, "indexed_at", None) else None,
                job_id=None,
                progress=None,
                error=None,
            )
            return {"data": payload.model_dump(), "message": "File is indexed"}
        if record and getattr(record, "status", None) == "failed":
            payload = FileIndexStatusResponse(
                file_id=str(file_id),
                file_name=file.file_name,
                status="failed",
                num_chunks=None,
                indexed_at=None,
                job_id=None,
                progress=None,
                error=getattr(record, "error_message", None),
            )
            return {"data": payload.model_dump(), "message": "Indexing previously failed"}

        # Not in DB (or not in a terminal state) — check live running jobs
        file_id_str = str(file_id)
        for job in job_manager.list_jobs(status_filter=JobStatus.RUNNING):
            if job.get("current_file_id") == file_id_str:
                payload = FileIndexStatusResponse(
                    file_id=file_id_str,
                    file_name=file.file_name,
                    status="indexing",
                    num_chunks=None,
                    indexed_at=None,
                    job_id=job["job_id"],
                    progress={
                        "current_index": job.get("current_index", 0),
                        "total_files": job.get("total_files", 0),
                    },
                    error=None,
                )
                return {
                    "data": payload.model_dump(),
                    "message": "File is currently being indexed",
                }
            if file_id_str in (job.get("scope_file_ids") or []):
                payload = FileIndexStatusResponse(
                    file_id=file_id_str,
                    file_name=file.file_name,
                    status="queued",
                    num_chunks=None,
                    indexed_at=None,
                    job_id=job["job_id"],
                    progress={
                        "current_index": job.get("current_index", 0),
                        "total_files": job.get("total_files", 0),
                    },
                    error=None,
                )
                return {
                    "data": payload.model_dump(),
                    "message": "File is queued for indexing",
                }

        payload = FileIndexStatusResponse(
            file_id=file_id_str,
            file_name=file.file_name,
            status="not_indexed",
            num_chunks=None,
            indexed_at=None,
            job_id=None,
            progress=None,
            error=None,
        )
        return {"data": payload.model_dump(), "message": "File has not been indexed"}

    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_FILE_STATUS_FAIL", e, file_id=file_id)
        raise HTTPException(status_code=500, detail=f"Failed to get file status: {str(e)}")


# ============================================================================
# Deletion
# ============================================================================

# Resource = folder 全部 FileIndex + vector store table;Response = DeleteFolderIndexResponse
@router.delete(
    "/files/{folder_id}/index",
    tags=[_TAG_CLEANUP],
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def delete_folder_index_endpoint(
    folder_id: int,
    token: str = Depends(extract_token),
    folder: Folder = Depends(get_folder_by_id),
):
    """刪除整個資料夾的索引(保留 folder 與 files 本身)"""
    try:
        logger.info(f"API: Deleting folder index for folder_id={folder_id}")
        result = await get_rag_adapter().delete_folder_index(folder_id=folder_id, token=token)

        if result.total_files == 0:
            return {"data": result, "message": "No indexed files found in folder"}

        return {"data": result, "message": result.message}

    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_DELETE_FOLDER_IDX_FAIL", e, folder_id=folder_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to delete folder index: {str(e)}")


# Response = {data: {file_id, file_name, deleted: bool}, message}
@router.delete(
    "/file/{file_id}/index",
    tags=[_TAG_CLEANUP],
    responses={
        404: {"model": ErrorDetailResponse, "description": "file 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def delete_single_file_index_endpoint(
    file_id: UUID,
    token: str = Depends(extract_token),
    file: File = Depends(get_file_by_id),
):
    """刪除單檔的索引"""
    try:
        logger.info(f"API: Deleting index for single file_id={file_id}")
        success = await get_rag_adapter().delete_document_index(file_id=file_id, token=token)

        if not success:
            return {
                "data": {"file_id": str(file_id), "deleted": False},
                "message": "No index found for this file",
            }

        return {
            "data": {
                "file_id": str(file_id),
                "file_name": file.file_name,
                "deleted": True,
            },
            "message": f"Successfully deleted index for file: {file.file_name}",
        }

    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_DELETE_FILE_IDX_FAIL", e, file_id=file_id, token=token)
        raise HTTPException(status_code=500, detail=f"Failed to delete file index: {str(e)}")
