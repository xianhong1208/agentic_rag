
"""Agentic 三模式查詢 handlers — search / list / read 的實際邏輯(domain 層)。

M6: 從 src/fastmcp_tools/tool_handlers.py **逐字搬入** domain。原本檢索編排住在
MCP 交付層,adapter(rag_query.query_agentic)反向 import 上去 → 層次環
(fastmcp → adapter → fastmcp)。這些 handler 只依賴 db / domain / log,本就
不含任何 fastmcp 依賴,正確歸屬是 domain;tool_handlers.py 保留為 re-export
shim 向下相容。logger 沿用 mcptools sink 不換 — 搬家不改任何日誌行為。

mode 設計理念:
- search:預設模式,走 hybrid retrieval + auto-merge + 可選 expand_context
- list:純 metadata 查詢,不走檢索,回傳 file_id + estimated_tokens
- read:給定 file_id,順序拼接所有 leaf chunks 回傳整份內容

每個 handler 都接受已驗證的 token + folder,不再做 ACL(由 folder_acl.py 負責)。
回傳 dict (JSON-serializable),由 caller 包成 MCP content block。

Logging 慣例:
- 每個 mode 進入時打一條 [<MODE>_START] 含關鍵參數
- 中間決策點(empty/short query / file 不屬於 folder / merge 觸發等)記詳細上下文
- 結束時打一條 [<MODE>_DONE] 含結果統計,方便排查 RAG 質量問題
"""

from __future__ import annotations

import time
from collections import Counter
from typing import List

from db.filedb import FileDB
from db.fileindexdb import FileIndexDB
from src.domain.rag.auto_merging import AutoMergingRetriever, MergedResult
from src.domain.rag.chunk_lookup import ChunkLookup
from src.log import get_mcptools_logger, log_err, log_op_debug, log_warn

logger = get_mcptools_logger()


# ============================================================================
# SEARCH MODE
# ============================================================================

async def handle_search(
    *,
    query: str,
    folder,
    retriever: AutoMergingRetriever,
    top_k: int,
    similarity_cutoff: float,
    expand_context: bool,
) -> dict:
    """mode='search' — 主力 hybrid + auto-merge(async:整段檢索不佔 event loop)"""
    start = time.perf_counter()

    # 入口 log:記下完整參數,方便重現查詢
    log_op_debug(
        logger,
        "SEARCH_START",
        folder_id=folder.id,
        msg=(
            f"folder='{folder.name}' query='{query[:50]}{'...' if len(query) > 50 else ''}' "
            f"top_k={top_k} cutoff={similarity_cutoff} expand_context={expand_context}"
        ),
    )

    # ---- Validation ----
    if not query or len(query.strip()) < 2:
        log_warn(
            logger,
            "SEARCH_INVALID_QUERY",
            folder_id=folder.id,
            msg=f"query too short (len={len(query.strip()) if query else 0})",
        )
        return {
            "mode": "search",
            "error": "Query too short (min 2 characters)",
            "results": [],
        }

    # ---- Execute retrieval ----
    try:
        results: List[MergedResult] = await retriever.aquery(
            query_text=query,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            expand_context=expand_context,
        )
    except Exception as exc:
        log_err(
            logger,
            "SEARCH_RETRIEVER_FAIL",
            exc,
            folder_id=folder.id,
            msg=f"query='{query[:30]}'",
        )
        raise

    # ---- Aggregate stats for logging ----
    role_counts = Counter(r.node_role for r in results)
    file_counts = Counter(r.file_name for r in results)
    scores = [r.score for r in results]
    score_stats = (
        f"min={min(scores):.3f} max={max(scores):.3f} avg={sum(scores)/len(scores):.3f}"
        if scores
        else "n/a"
    )

    # 計算 merge 統計(parent 多少 / expanded 多少 / 純 leaf 多少)
    merged_leaves_total = sum(
        len(r.merged_from_leaves) for r in results if r.node_role == "parent"
    )

    response = {
        "mode": "search",
        "query": query,
        "folder": folder.name,
        "total_results": len(results),
        "results": [
            {
                "node_id": r.node_id,
                "file_id": r.file_id,
                "file_name": r.file_name,
                "score": round(r.score, 4),
                "node_role": r.node_role,
                "chunk_index_range": r.chunk_index_range,
                "text": r.text,
                # BL-05 引用溯源:有才帶(舊索引資料無此 metadata → 不出現)
                **({"page": r.page} if r.page is not None else {}),
                **({"headings": r.headings} if r.headings else {}),
                **(
                    {"merged_from_leaves": len(r.merged_from_leaves)}
                    if r.node_role == "parent"
                    else {}
                ),
            }
            for r in results
        ],
    }

    # ---- Hint reasoning + log it ----
    hint_reason = "normal"
    if not results:
        response["_hint"] = (
            "No results above similarity_cutoff. Try: lower cutoff, broaden query, "
            "or use mode='list' to see what's available."
        )
        hint_reason = "no_results"
    elif len(results) < top_k:
        response["_hint"] = (
            f"Only {len(results)} results above threshold. "
            "Consider lowering similarity_cutoff or using mode='read' on most relevant file."
        )
        hint_reason = "below_top_k"
    else:
        response["_hint"] = (
            "If results seem fragmented, try mode='read' with a relevant file_id "
            "to load full document content."
        )

    elapsed_ms = (time.perf_counter() - start) * 1000

    # 完整退出 log:results 分佈 / score 統計 / 命中檔案數 / 耗時
    log_op_debug(
        logger,
        "SEARCH_DONE",
        folder_id=folder.id,
        msg=(
            f"results={len(results)} "
            f"roles={{leaf:{role_counts.get('leaf', 0)},"
            f"parent:{role_counts.get('parent', 0)}(merged_from_{merged_leaves_total}),"
            f"expanded:{role_counts.get('expanded', 0)}}} "
            f"unique_files={len(file_counts)} "
            f"scores=[{score_stats}] "
            f"hint={hint_reason} "
            f"elapsed={elapsed_ms:.0f}ms"
        ),
    )

    # 命中檔案明細(DEBUG 級別,需要時開來看)
    if file_counts:
        logger.debug(
            f"[SEARCH_FILES] fid={folder.id} | "
            + ", ".join(f"'{name}':{cnt}" for name, cnt in file_counts.most_common())
        )

    return response


# ============================================================================
# LIST MODE
# ============================================================================

def handle_list(*, folder) -> dict:
    """mode='list' — 列出資料夾內所有檔案 + 索引狀態 + token 估算"""
    start = time.perf_counter()

    log_op_debug(
        logger,
        "LIST_START",
        folder_id=folder.id,
        msg=f"folder='{folder.name}'",
    )

    files = FileDB.get(folder_id=folder.id)

    # 撈索引狀態 + chunk count
    indexed_map = {}
    chunk_count_map = {}
    try:
        index_records = FileIndexDB.get_by_folder(folder.id)
        for r in index_records:
            indexed_map[str(r.file_id)] = r.status
            chunk_count_map[str(r.file_id)] = r.num_chunks
    except Exception as e:
        log_warn(
            logger,
            "LIST_INDEX_LOOKUP_FAIL",
            folder_id=folder.id,
            msg=f"fallback to 'not_indexed' for all files: {e}",
        )

    # 統計索引狀態分佈(對 agent / debug 都有幫助)
    status_counts = Counter()
    total_chunks = 0
    file_list = []
    for f in files:
        chunk_count = chunk_count_map.get(str(f.id), 0)
        status = indexed_map.get(str(f.id), "not_indexed")
        status_counts[status] += 1
        total_chunks += chunk_count

        # 粗估:每個 leaf chunk 約 200 tokens(對齊 leaf_chunk_size 256)
        # 這個估算給 agent 看,用來判斷「能不能 read 整份」,不需要精確
        estimated_tokens = chunk_count * 200 if chunk_count > 0 else None
        file_list.append({
            "file_id": str(f.id),
            "file_name": f.file_name,
            "size_kb": round(f.file_size / 1024, 1) if f.file_size else 0,
            "upload_time": f.upload_time.isoformat() if f.upload_time else None,
            "indexed_status": status,
            "chunk_count": chunk_count,
            "estimated_tokens": estimated_tokens,
        })

    response = {
        "mode": "list",
        "folder": folder.name,
        "description": folder.description,
        "total_files": len(file_list),
        "files": file_list,
        "_hint": (
            "Files with estimated_tokens < 30000 can be loaded fully via mode='read'. "
            "For others, use mode='search' to find relevant sections."
        ),
    }

    elapsed_ms = (time.perf_counter() - start) * 1000

    # 退出 log:檔案數 + 狀態分佈 + 總 chunk 數 + 耗時
    status_str = ",".join(f"{k}:{v}" for k, v in status_counts.items()) or "empty"
    log_op_debug(
        logger,
        "LIST_DONE",
        folder_id=folder.id,
        msg=(
            f"files={len(file_list)} status={{{status_str}}} "
            f"total_chunks={total_chunks} elapsed={elapsed_ms:.0f}ms"
        ),
    )

    return response


# ============================================================================
# READ MODE
# ============================================================================

async def handle_read(
    *,
    file_id: str,
    folder,
    vector_store,
    max_tokens: int = 30000,
) -> dict:
    """mode='read' handler ─ 把整份檔案內容載入回傳(嚴控用法)。

    驗證 file 必須屬於當前 folder(防 cross-folder 越權);實作上限 max_tokens。

    Args:
        file_id: 要讀的檔案 UUID。
        folder: 已通過權限驗證的 Folder ORM。
        vector_store: PGVectorStore(從 ctx 拿,供 chunk lookup)。
        max_tokens: 內容上限,超過時截斷並標 truncated=True。

    Returns:
        dict ``{content, truncated, file_name, ...}``。
    """
    start = time.perf_counter()

    log_op_debug(
        logger,
        "READ_START",
        folder_id=folder.id,
        file_id=file_id,
        msg=f"folder='{folder.name}' max_tokens={max_tokens}",
    )

    # ---- Input validation ----
    if not file_id:
        log_warn(
            logger,
            "READ_MISSING_FILE_ID",
            folder_id=folder.id,
            msg="read mode requires file_id parameter",
        )
        return {"mode": "read", "error": "file_id is required for read mode"}

    # ---- File existence + folder ownership ----
    file_records = FileDB.get_by_ids([file_id])
    file_record = file_records.get(file_id) if file_records else None
    if not file_record:
        log_warn(
            logger,
            "READ_FILE_NOT_FOUND",
            folder_id=folder.id,
            file_id=file_id,
            msg="no file record in DB",
        )
        return {"mode": "read", "error": f"File {file_id} not found"}

    if file_record.folder_id != folder.id:
        # 故意保護:不洩漏這個 file 屬於哪個 folder,避免 enumeration attack
        log_warn(
            logger,
            "READ_CROSS_FOLDER",
            folder_id=folder.id,
            file_id=file_id,
            msg=f"file actually belongs to folder_id={file_record.folder_id}, denied",
        )
        return {
            "mode": "read",
            "error": f"File does not belong to folder '{folder.name}'",
        }

    # ---- Fetch full content from PGVector ----
    try:
        # sync SQL 撈全檔可到數百 ms(大檔數百 chunks)— 丟 thread pool 不佔 loop
        import asyncio
        full = await asyncio.to_thread(
            ChunkLookup.fetch_file_full,
            vector_store=vector_store,
            file_id=file_id,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        log_err(
            logger,
            "READ_FETCH_FAIL",
            exc,
            folder_id=folder.id,
            file_id=file_id,
        )
        raise

    response = {
        "mode": "read",
        "folder": folder.name,
        "file_id": file_id,
        "file_name": file_record.file_name,
        "content": full["text"],
        "tokens_estimated": full["tokens_estimated"],
        "truncated": full["truncated"],
        "chunk_count": full["chunk_count"],
        "_hint": (
            "Truncated content — consider mode='search' for specific sections."
            if full["truncated"]
            else "Full content loaded."
        ),
    }

    elapsed_ms = (time.perf_counter() - start) * 1000

    # 退出 log:檔案內容統計
    truncated_marker = " ⚠️TRUNCATED" if full["truncated"] else ""
    log_op_debug(
        logger,
        "READ_DONE",
        folder_id=folder.id,
        file_id=file_id,
        msg=(
            f"file_name='{file_record.file_name}' "
            f"chunks={full['chunk_count']} tokens={full['tokens_estimated']}"
            f"{truncated_marker} elapsed={elapsed_ms:.0f}ms"
        ),
    )

    return response
