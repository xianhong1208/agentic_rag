
"""RAG query service — flat hybrid (REST) 和 agentic (MCP) 兩套查詢介面。

從 RAGAdapter 拆出的三個方法:
- `query_rag(query, folder_id, token, ...)` — REST 用,flat hybrid + result cache
- `query_rag_by_folder_name(query, folder_name, token, ...)` — REST,by folder name
- `query(folder_name, mode, ...)` — agentic / MCP 用,三 mode(search / list / read)+ auto-merge

共用 RAGContext 的 reranker / vector_store_manager / query_engines cache。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.adapter.model import RAGQueryResult
from src.config.config_manager import Config
from src.domain.exceptions import (
    DomainException,
    QueryExecutionError,
)
from src.domain.rag.auto_merging import AutoMergingRetriever
from src.domain.rag.query_engine import QueryEngine
from src.infrastructure.cache.cache_service import CacheKeys, CacheService, CacheTTL
from src.log import get_adapter_logger, log_err, log_op

if TYPE_CHECKING:
    from src.adapter.rag_context import RAGContext

logger = get_adapter_logger()


def _fusion_config() -> tuple:
    """讀 config.rag.retrieval → (hybrid_fusion, rrf_k, text_search_config)。

    缺設定時 fall back rrf/60/jiebacfg(新預設);config 讀不到也不擋查詢。
    """
    try:
        ret = getattr(getattr(Config.get_config_model(), "rag", None), "retrieval", None)
        return (getattr(ret, "hybrid_fusion", "rrf") or "rrf",
                int(getattr(ret, "rrf_k", 60) or 60),
                getattr(ret, "text_search_config", "jiebacfg") or "jiebacfg")
    except Exception:
        return "rrf", 60, "jiebacfg"

# 全域查詢併發閘(REST + MCP 共用)— 上限 config rag.retrieval.max_concurrent_queries。
# 查詢已真異步(不佔 event loop),這裡管的是「同時打 DB / embedding / rerank
# 服務的查詢數」;超過上限的排隊等待,不丟棄。lazy 建立(需在 event loop 內)。
_query_semaphore: Optional[asyncio.Semaphore] = None


def _get_query_semaphore() -> asyncio.Semaphore:
    global _query_semaphore
    if _query_semaphore is None:
        try:
            limit = Config.get_config_model().rag.retrieval.max_concurrent_queries
        except Exception:
            limit = 8
        _query_semaphore = asyncio.Semaphore(limit)
        logger.info(f"Query concurrency gate initialized (max_concurrent_queries={limit})")
    return _query_semaphore


class RAGQueryService:
    """處理 REST flat hybrid query 跟 agentic MCP query 的 service。"""

    def __init__(self, ctx: "RAGContext"):
        self._ctx = ctx

    # ------------------------------------------------------------------
    # REST: flat hybrid query (with result cache)
    # ------------------------------------------------------------------

    async def query_rag(
        self,
        query: str,
        folder_id: int,
        token: str,
        top_k: int = 5,
        similarity_cutoff: float = 0.7,
        use_cache: bool = True,
        sparse_top_k: Optional[int] = None,
        hybrid_alpha: Optional[float] = None,
    ) -> RAGQueryResult:
        """混合檢索(vector + BM25)+ 可選 rerank,帶結果 cache。

        Performance: cache hit < 1ms;cache miss 100-800ms(依索引大小);cache TTL 5 分鐘。

        Args:
            query: 查詢字串。
            folder_id: 要查的 folder。
            token: 使用者 token(權限驗證)。
            top_k: 返回前 K 個結果(reranker enabled 時為 rerank 後的 top)。
            similarity_cutoff: 相似度閾值;reranker enabled 時此值會被忽略。
            use_cache: 是否走結果 cache(False = 強制 retrieval)。
            sparse_top_k: BM25 候選數量;None = 用 config 預設。
            hybrid_alpha: 向量 vs BM25 權重(0=純 BM25, 1=純向量);None = 用 config 預設。

        Returns:
            RAGQueryResult(query / results / total_results / retrieval_time_ms)。
        """
        ctx = self._ctx

        try:
            folder = ctx.indexing_service.get_folder(folder_id, token)

            # ---- Result cache check ----
            cache_key = None
            cache = CacheService.get_instance()

            if use_cache:
                fingerprint_parts = [
                    query,
                    str(top_k),
                    f"{similarity_cutoff}",
                    str(sparse_top_k) if sparse_top_k is not None else "default_sparse_top_k",
                    f"{hybrid_alpha}" if hybrid_alpha is not None else "default_hybrid_alpha",
                    f"rerank:{ctx.reranker._model}" if ctx.reranker else "no_rerank",
                ]
                query_fingerprint = hashlib.sha256(
                    "|".join(fingerprint_parts).encode("utf-8")
                ).hexdigest()
                cache_key = CacheKeys.rag_query(folder_id, query_fingerprint)
                cached_result = cache.get(cache_key)

                if cached_result is not None:
                    logger.debug(f"RAG query cache HIT: {cache_key}")
                    return cached_result

                logger.debug(f"RAG query cache MISS: {cache_key}")

            # ---- Vector store + cached QueryEngine ----
            vector_store = ctx.get_vector_store(folder_id, token)

            fusion, rrf_k, tsc = _fusion_config()
            engine_key = f"{folder_id}"
            query_engine = ctx.query_engines.get(engine_key)
            if query_engine is None:
                query_engine = QueryEngine(
                    vector_store=vector_store,
                    top_k=top_k,
                    similarity_cutoff=similarity_cutoff,
                    sparse_top_k=sparse_top_k,
                    hybrid_alpha=hybrid_alpha,
                    reranker=ctx.reranker,
                    hybrid_fusion=fusion,
                    rrf_k=rrf_k,
                    text_search_config=tsc,
                )
                ctx.query_engines[engine_key] = query_engine
            else:
                query_engine.update_config(
                    top_k=top_k,
                    similarity_cutoff=similarity_cutoff,
                    sparse_top_k=sparse_top_k,
                    hybrid_alpha=hybrid_alpha,
                    hybrid_fusion=fusion,
                    rrf_k=rrf_k,
                )

            async with _get_query_semaphore():
                search_results = await query_engine.aquery(query)

            # Backfill folder_name if missing (backward compat)
            for res in search_results:
                if res.metadata.folder_name is None:
                    res.metadata.folder_name = folder.name

            log_op(
                logger, "QUERY_DONE",
                folder_id=folder_id, token=token,
                msg=f"{len(search_results)} results above threshold={similarity_cutoff}",
            )

            result = RAGQueryResult(
                query=query,
                results=search_results,
                total_results=len(search_results),
            )

            if use_cache and cache_key:
                cache.set(cache_key, result, ttl=CacheTTL.QUERY_RESULT)
                logger.debug(f"Cached query result: {cache_key}")

            return result

        except DomainException:
            raise
        except Exception as e:
            log_err(logger, "QUERY_FAIL", e, folder_id=folder_id, token=token)
            raise QueryExecutionError(
                query=query, reason=str(e), folder_id=folder_id
            )

    async def query_trace(
        self,
        query: str,
        folder_id: int,
        token: str,
        top_k: int = 5,
        similarity_cutoff: float = 0.7,
        sparse_top_k: Optional[int] = None,
        hybrid_alpha: Optional[float] = None,
    ) -> dict:
        """檢索軌跡(診斷)— 不走 cache,拆解 vector / BM25 / hybrid / rerank 名次。

        供 Control Center 查詢測試台的「檢索軌跡」用:讓客戶看懂每個命中片段
        在三路檢索各排第幾、rerank 如何改變順序。回 dict(見 QueryEngine.atrace)。
        """
        ctx = self._ctx
        folder = ctx.indexing_service.get_folder(folder_id, token)
        vector_store = ctx.get_vector_store(folder_id, token)
        fusion, rrf_k, tsc = _fusion_config()
        engine = QueryEngine(
            vector_store=vector_store,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            sparse_top_k=sparse_top_k,
            hybrid_alpha=hybrid_alpha,
            reranker=ctx.reranker,
            hybrid_fusion=fusion,
            rrf_k=rrf_k,
            text_search_config=tsc,
        )
        async with _get_query_semaphore():
            trace = await engine.atrace(query, top_k=top_k)
        for r in trace["results"]:
            if not r["metadata"].get("file_name"):
                r["metadata"]["file_name"] = None
            r["metadata"]["folder_name"] = folder.name
        return trace

    async def query_rag_by_folder_name(
        self,
        query: str,
        folder_name: str,
        token: str,
        top_k: int = 5,
        similarity_cutoff: float = 0.7,
        sparse_top_k: Optional[int] = None,
        hybrid_alpha: Optional[float] = None,
    ) -> RAGQueryResult:
        """使用資料夾名稱查詢(帶身份驗證,delegate 給 query_rag)。"""
        try:
            folder = self._ctx.indexing_service.get_folder_by_name(folder_name, token)
            log_op(
                logger, "QUERY_BY_NAME",
                folder_id=folder.id, token=token,
                msg=f"folder_name={folder_name}",
            )
            return await self.query_rag(
                query=query,
                folder_id=folder.id,
                token=token,
                top_k=top_k,
                similarity_cutoff=similarity_cutoff,
                sparse_top_k=sparse_top_k,
                hybrid_alpha=hybrid_alpha,
            )
        except DomainException:
            raise
        except Exception as e:
            log_err(logger, "QUERY_BY_NAME_FAIL", e, token=token)
            raise ValueError(f"Failed to query RAG by folder name: {str(e)}")

    # ------------------------------------------------------------------
    # Agentic / MCP: three-mode (search / list / read)
    # ------------------------------------------------------------------

    async def query_agentic(
        self,
        *,
        folder_name: str,
        mode: str,
        query: str,
        file_id: Optional[str],
        top_k: int,
        similarity_cutoff: float,
        expand_context: bool,
        token: str,
    ) -> Dict[str, Any]:
        """MCP 查詢入口 — 三 mode(search / list / read)統一介面。

        Returns:
            JSON-serializable dict — 由 agentic_tools 包成 MCP content block。
        """
        # M6: 三模式編排與 folder ACL 已下沉 domain — adapter 不再反向 import
        # fastmcp 交付層(舊環:fastmcp → adapter → fastmcp)。
        from src.domain.rag.agentic_handlers import handle_list, handle_read, handle_search
        from src.domain.rag.folder_acl import verify_folder_access

        ctx = self._ctx
        # ACL — 確認 token 有權存取此 folder
        folder = verify_folder_access(token=token, folder_name=folder_name)

        if mode == "list":
            return handle_list(folder=folder)

        # search / read 都需要 vector_store
        vector_store = ctx.vector_store_manager.get_or_create(
            folder_id=folder.id,
            vector_table_uuid=str(folder.vector_table_uuid),
        )

        if mode == "read":
            async with _get_query_semaphore():
                return await handle_read(
                    file_id=file_id,
                    folder=folder,
                    vector_store=vector_store,
                )

        if mode == "search":
            # 構建一次性 retriever(輕量,不快取 — folder 切換頻繁時更靈活)
            config = Config.get_config_model().rag.retrieval
            retriever = AutoMergingRetriever(
                vector_store=vector_store,
                reranker=ctx.reranker,
                merge_threshold=(
                    ctx.merge_threshold if ctx.auto_merging_enabled else 1.1
                ),
                expand_context_neighbors=ctx.expand_neighbors,
                sparse_top_k=config.default_sparse_top_k,
                hybrid_alpha=config.default_hybrid_alpha,
            )
            async with _get_query_semaphore():
                return await handle_search(
                    query=query,
                    folder=folder,
                    retriever=retriever,
                    top_k=top_k,
                    similarity_cutoff=similarity_cutoff,
                    expand_context=expand_context,
                )

        return {"error": f"Unknown mode: {mode}. Use search / list / read."}
