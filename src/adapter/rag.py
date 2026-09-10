
"""RAG 適配器模組 — 對外的薄 facade。

Public API(callers 走 `get_rag_adapter()` 拿這個 instance):
  - index_document / index_folder / index_files / trigger_auto_index
  - query_rag / query_rag_by_folder_name / query
  - delete_document_index / delete_folder_index / get_indexed_files

實際邏輯分散在四個 sub-modules(同 package):
  - rag_context.py     — 共享狀態 / config 載入 / vector store helper
  - rag_indexing.py    — indexing 三件套 + auto-index trigger
  - rag_query.py       — flat hybrid + agentic three-mode
  - rag_maintenance.py — delete + indexed-files 列表

從原本 1330 行單檔重構為 5 個 ~200-470 行檔案,2026-05-26 Phase 1-5 完成。
"""

from typing import Any, Dict, List, Optional

from llama_index.vector_stores.postgres import PGVectorStore

from src.adapter.model import RAGQueryResult
from src.adapter.rag_context import RAGContext
from src.adapter.rag_indexing import RAGIndexingService
from src.adapter.rag_maintenance import RAGMaintenanceService
from src.adapter.rag_query import RAGQueryService
from src.api.router.response import (
    DeleteFolderIndexResponse,
    FileRequest,
    IndexDocumentResponse,
    IndexFolderResponse,
)
from src.domain.rag.index_job_manager import IndexProgressTracker
from src.domain.rag.query_engine import QueryEngine
from src.log import get_adapter_logger


logger = get_adapter_logger()


class RAGAdapter:
    """LlamaIndex 基礎的 RAG 適配器

    提供文件索引、查詢和管理功能,使用 PostgreSQL pgvector 進行向量存儲。

    狀態管理委派給 RAGContext(`self._ctx`):embedding provider / indexer /
    vector store manager / reranker / 各種 size 設定全部歸 ctx 管,RAGAdapter
    只負責協調 indexing / query / maintenance 三類 use case。

    為了 backwards compat,所有 `self._xxx` 私有屬性仍可用 — 透過 @property
    delegate 到 ctx。phases 2-4 把方法搬出去後,這些 alias 會逐步移除。
    """

    def __init__(self):
        """初始化 RAG 適配器 — 委派給 RAGContext.from_config()"""
        self._ctx: RAGContext = RAGContext.from_config()
        # Sub-services receive shared ctx, expose narrower SRP-aligned interfaces.
        self._indexing = RAGIndexingService(self._ctx)
        self._query_svc = RAGQueryService(self._ctx)
        self._maintenance = RAGMaintenanceService(self._ctx)

    # ------------------------------------------------------------------
    # Backwards-compat property aliases — 讓 phase 1 之後本檔內既有 method body
    # 可以繼續 self._xxx 不必同步改。phase 2-4 把方法搬到 sub-services 後,
    # service 內直接 self._ctx.xxx,這層 alias 屆時可刪。
    # ------------------------------------------------------------------

    @property
    def _embedding_provider(self):
        return self._ctx.embedding_provider

    @property
    def _embed_dim(self) -> int:
        return self._ctx.embed_dim

    @property
    def _model_name(self) -> str:
        return self._ctx.model_name

    @property
    def _chunker_tokenizer_name(self) -> Optional[str]:
        return self._ctx.chunker_tokenizer_name

    @property
    def _leaf_chunk_size(self) -> int:
        return self._ctx.leaf_chunk_size

    @property
    def _parent_target_tokens(self) -> int:
        return self._ctx.parent_target_tokens

    @property
    def _chunk_overlap(self) -> int:
        return self._ctx.chunk_overlap

    @property
    def _vector_store_manager(self):
        return self._ctx.vector_store_manager

    @property
    def _indexer(self):
        return self._ctx.indexer

    @property
    def _document_indexer(self):
        # 舊別名 — phase 2 搬走後可刪
        return self._ctx.indexer

    @property
    def _indexing_service(self):
        return self._ctx.indexing_service

    @property
    def _auto_merging_enabled(self) -> bool:
        return self._ctx.auto_merging_enabled

    @property
    def _merge_threshold(self) -> float:
        return self._ctx.merge_threshold

    @property
    def _expand_neighbors(self) -> int:
        return self._ctx.expand_neighbors

    @property
    def _reranker(self):
        return self._ctx.reranker

    @property
    def _query_engines(self) -> Dict[str, QueryEngine]:
        # mutable dict — 改變會傳回 ctx,因為這是 reference
        return self._ctx.query_engines

    # ------------------------------------------------------------------
    # Runtime helpers — delegate to RAGContext
    # ------------------------------------------------------------------

    def _invalidate_query_engine_cache(self, folder_id: int) -> None:
        """Remove cached QueryEngine for a folder (call after index changes)."""
        self._ctx.invalidate_query_engine_cache(folder_id)

    def _get_vector_store(
        self, folder_id: int, token: str, folder: Optional[Any] = None
    ) -> PGVectorStore:
        """獲取或創建指定 folder/token 的向量存儲(委派給 RAGContext)。"""
        return self._ctx.get_vector_store(folder_id, token, folder)

    async def index_document(
        self,
        file_record: FileRequest,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        folder_id_override: Optional[int] = None,
    ) -> IndexDocumentResponse:
        """委派給 RAGIndexingService — 單檔索引。"""
        return await self._indexing.index_document(
            file_record=file_record,
            token=token,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            folder_id_override=folder_id_override,
        )

    async def index_folder(
        self,
        folder_id: int,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        skip_existing: bool = True,
        progress_tracker: Optional["IndexProgressTracker"] = None,
    ) -> IndexFolderResponse:
        """委派給 RAGIndexingService — 整個資料夾索引。"""
        return await self._indexing.index_folder(
            folder_id=folder_id,
            token=token,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            skip_existing=skip_existing,
            progress_tracker=progress_tracker,
        )

    async def index_files(
        self,
        file_ids: List[str],
        folder_id: int,
        token: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        progress_tracker: Optional["IndexProgressTracker"] = None,
    ) -> IndexFolderResponse:
        """委派給 RAGIndexingService — 指定檔案清單索引(auto-index 上傳用)。"""
        return await self._indexing.index_files(
            file_ids=file_ids,
            folder_id=folder_id,
            token=token,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            progress_tracker=progress_tracker,
        )

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
        """委派給 RAGQueryService — flat hybrid query with result cache。"""
        return await self._query_svc.query_rag(
            query=query,
            folder_id=folder_id,
            token=token,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            use_cache=use_cache,
            sparse_top_k=sparse_top_k,
            hybrid_alpha=hybrid_alpha,
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
        """委派給 RAGQueryService — 檢索軌跡拆解(診斷用,不走 cache)。"""
        return await self._query_svc.query_trace(
            query=query,
            folder_id=folder_id,
            token=token,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            sparse_top_k=sparse_top_k,
            hybrid_alpha=hybrid_alpha,
        )

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
        """委派給 RAGQueryService — query by folder name(帶身份驗證)。"""
        return await self._query_svc.query_rag_by_folder_name(
            query=query,
            folder_name=folder_name,
            token=token,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            sparse_top_k=sparse_top_k,
            hybrid_alpha=hybrid_alpha,
        )

    async def query(
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
        """委派給 RAGQueryService — MCP agentic three-mode(search / list / read)。"""
        return await self._query_svc.query_agentic(
            folder_name=folder_name,
            mode=mode,
            query=query,
            file_id=file_id,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            expand_context=expand_context,
            token=token,
        )

    async def delete_document_index(self, file_id: int, token: str) -> bool:
        """委派給 RAGMaintenanceService — 從向量存儲中刪除文件索引。"""
        return await self._maintenance.delete_document_index(file_id, token)

    async def trigger_auto_index(
        self,
        file_ids: List[str],
        folder_id: int,
        token: str,
        auto_index: bool = True,
    ) -> Dict[str, Any]:
        """委派給 RAGIndexingService — 觸發背景 auto-index job。"""
        return await self._indexing.trigger_auto_index(
            file_ids=file_ids,
            folder_id=folder_id,
            token=token,
            auto_index=auto_index,
        )

    async def delete_folder_index(
        self,
        folder_id: int,
        token: str,
    ) -> DeleteFolderIndexResponse:
        """委派給 RAGMaintenanceService — 刪除資料夾全部索引(保留 folder 跟 files)。"""
        return await self._maintenance.delete_folder_index(folder_id, token)

    async def get_indexed_files(
        self,
        folder_id: int,
    ) -> List[Dict[str, Any]]:
        """委派給 RAGMaintenanceService — 列出已索引檔案。"""
        return await self._maintenance.get_indexed_files(folder_id)

## Lazy initialization of rag adapter
# Don't instantiate at module level - config must be loaded first!
_rag_adapter_instance = None

def get_rag_adapter() -> RAGAdapter:
    """Get or create the singleton RAGAdapter instance

    Uses lazy initialization to ensure Config is loaded before instantiation.
    """
    global _rag_adapter_instance
    if _rag_adapter_instance is None:
        _rag_adapter_instance = RAGAdapter()
    return _rag_adapter_instance


def peek_rag_adapter() -> "RAGAdapter | None":
    """已建才回,**不觸發**建構(admin 熱改用:adapter 還沒 lazy-init 時
    只改 ConfigModel 即可 — 之後首次建構自然吃到新值,rebind 沒對象)。"""
    return _rag_adapter_instance