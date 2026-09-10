
"""RAG Query REST API

只負責檢索查詢:
- POST /api/rag/query                查詢已索引的內容(走 hybrid + rerank)

Indexing endpoints 已移到 rag_indexing.py。
注意:此 endpoint 走的是 RAGAdapter.query_rag(flat-style 平面 hybrid 檢索),
      若要使用 Auto-Merging + 上下文展開,請走 MCP 工具(Agentic_{folder_name}),
      或在後續版本擴充此 endpoint 加 mode 參數。

預設值:四個 retrieval 參數(top_k / similarity_cutoff / sparse_top_k /
hybrid_alpha)若未提供,會即時讀取 `config.yaml` 的 `rag.retrieval.*`,
跟 server 整體 config 保持一致。
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from db.cached_folderdb import CachedFolderDB
from src.adapter.rag import get_rag_adapter
from src.api.dependencies.auth import extract_token
from src.api.router.response import ErrorDetailResponse, QueryRequest, QueryResponse
from src.auth.dependencies import authenticate_request
from src.config.config_manager import Config
from src.domain.exceptions import FolderNotFoundError
from src.log import get_api_logger, log_err, log_op, log_warn


_QUERY_REQUEST_EXAMPLES = {
    "minimal": {
        "summary": "最小用法(用 config 預設)",
        "description": "只填必填欄位。4 個 retrieval 參數從 `config.rag.retrieval.default_*` 讀。",
        "value": {
            "query": "這份文件的核心結論是什麼?",
            "folder_name": "my-folder",
        },
    },
    "explicit_match_config": {
        "summary": "顯式對齊 config 當前值",
        "description": "把 config 預設複製進 body,方便只調某一個 retrieval 參數。",
        "value": {
            "query": "這份文件的核心結論是什麼?",
            "folder_name": "my-folder",
            "top_k": 10,
            "similarity_cutoff": 0.25,
            "sparse_top_k": 12,
            "hybrid_alpha": 0.75,
        },
    },
    "vector_heavy": {
        "summary": "純向量檢索(關掉 BM25)",
        "description": "hybrid_alpha=1.0 → 完全用向量分數,忽略關鍵字。適合語意接近但用詞不同的查詢。",
        "value": {
            "query": "What is the main conclusion?",
            "folder_name": "my-folder",
            "hybrid_alpha": 1.0,
        },
    },
    "keyword_heavy": {
        "summary": "純關鍵字檢索(關掉向量)",
        "description": "hybrid_alpha=0.0 → 完全用 BM25。適合查精確字詞(如型號、人名)。",
        "value": {
            "query": "AMD AI 395",
            "folder_name": "my-folder",
            "hybrid_alpha": 0.0,
            "sparse_top_k": 30,
        },
    },
}

logger = get_api_logger()

router = APIRouter(tags=["RAG: Query"], dependencies=[Depends(authenticate_request)])


# Hard fallback if config can't be loaded at all — same values as the Pydantic
# defaults shipped before this commit, so behavior degrades gracefully.
_FALLBACK_RETRIEVAL_DEFAULTS = {
    "top_k": 5,
    "similarity_cutoff": 0.4,
    "sparse_top_k": 12,
    "hybrid_alpha": 0.75,
}


def _resolve_retrieval_defaults() -> dict:
    """從 config.yaml 即時讀 retrieval 預設值。

    Returns:
        含 top_k / similarity_cutoff / sparse_top_k / hybrid_alpha 的 dict;
        config 缺欄位時 fall back 到模組內常數 _FALLBACK_RETRIEVAL_DEFAULTS。
    """
    out = dict(_FALLBACK_RETRIEVAL_DEFAULTS)
    try:
        cfg = Config.get_config_model()
        ret = getattr(getattr(cfg, "rag", None), "retrieval", None)
        if ret is None:
            return out
        if getattr(ret, "default_top_k", None) is not None:
            out["top_k"] = ret.default_top_k
        if getattr(ret, "default_similarity_cutoff", None) is not None:
            out["similarity_cutoff"] = ret.default_similarity_cutoff
        if getattr(ret, "default_sparse_top_k", None) is not None:
            out["sparse_top_k"] = ret.default_sparse_top_k
        if getattr(ret, "default_hybrid_alpha", None) is not None:
            out["hybrid_alpha"] = ret.default_hybrid_alpha
    except Exception as e:
        logger.warning(f"Failed to read rag.retrieval defaults from config (using fallback): {e}")
    return out


# Response = {data: {query, results[], total_results, retrieval_time_ms}, message}
# results 走 hybrid (vector + BM25) + 可選 rerank;score 為 reranker enabled 時的 rerank score
@router.post(
    "/query",
    response_model=QueryResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder_name 不存在或無權限"},
        422: {"model": ErrorDetailResponse, "description": "request body 驗證失敗"},
        500: {"model": ErrorDetailResponse},
    },
)
async def query_rag(
    request: Request,
    query_request: QueryRequest = Body(..., openapi_examples=_QUERY_REQUEST_EXAMPLES),
    token: str = Depends(extract_token),
):
    """以資料夾名稱 + 自然語言查詢 — hybrid retrieval + rerank

    Args:
        query_request: query / folder_name / top_k / similarity_cutoff /
                       sparse_top_k / hybrid_alpha — 缺項用 config 預設
        token: User token (auto-extracted from Authorization header)

    Returns:
        {data: {query, results[], total_results}, message}
    """
    try:
        # Resolve config-driven defaults for any missing retrieval params so
        # API behavior tracks config.yaml instead of stale Pydantic literals.
        defaults = _resolve_retrieval_defaults()
        top_k = query_request.top_k if query_request.top_k is not None else defaults["top_k"]
        similarity_cutoff = (
            query_request.similarity_cutoff
            if query_request.similarity_cutoff is not None
            else defaults["similarity_cutoff"]
        )
        sparse_top_k = (
            query_request.sparse_top_k
            if query_request.sparse_top_k is not None
            else defaults["sparse_top_k"]
        )
        hybrid_alpha = (
            query_request.hybrid_alpha
            if query_request.hybrid_alpha is not None
            else defaults["hybrid_alpha"]
        )

        log_op(
            logger, "API_QUERY", token=token,
            msg=(
                f"folder={query_request.folder_name} "
                f"query='{query_request.query[:50]}' "
                f"top_k={top_k} cutoff={similarity_cutoff} "
                f"sparse={sparse_top_k} alpha={hybrid_alpha}"
            ),
        )

        folder = CachedFolderDB.get_by_name_and_token(query_request.folder_name, token)
        if not folder:
            raise FolderNotFoundError(folder_name=query_request.folder_name)

        import time as _time
        _t0 = _time.perf_counter()
        result = await get_rag_adapter().query_rag(
            query=query_request.query,
            folder_id=folder.id,
            token=token,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            sparse_top_k=sparse_top_k,
            hybrid_alpha=hybrid_alpha,
        )
        _latency_ms = int((_time.perf_counter() - _t0) * 1000)

        # 查詢遙測(best-effort;供 Control Center 分析熱門/零結果/延遲)
        try:
            from db.query_log_db import QueryLogDB
            from src.log import mask_token
            QueryLogDB.record(
                query=query_request.query, folder_id=folder.id,
                result_count=result.total_results, latency_ms=_latency_ms,
                token_prefix=mask_token(token) if token else None)
        except Exception as _e:  # noqa: BLE001
            logger.debug(f"query log skipped: {_e}")

        return {
            "data": result.model_dump(),
            "message": f"Query returned {result.total_results} results",
        }

    except FolderNotFoundError as e:
        log_warn(logger, "API_QUERY_404", token=token, msg=f"folder={query_request.folder_name}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log_err(logger, "API_QUERY_FAIL", e, token=token)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
