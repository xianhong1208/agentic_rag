
"""Query Engine

Handles RAG queries with hybrid search (vector + BM25) and optional reranking.
"""

import asyncio
from typing import List, Optional, TYPE_CHECKING
import sqlalchemy.exc
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.vector_stores.postgres import PGVectorStore
from src.domain.rag.dto import RAGSearchResult, RAGChunkMetadata
from src.domain.exceptions import FolderNotFoundError
from src.log import get_api_logger

if TYPE_CHECKING:
    from src.domain.rag.reranker import Reranker

logger = get_api_logger()


class QueryEngine:
    """Handles RAG queries with hybrid search

    Responsibilities:
    - Create retriever from vector store
    - Execute hybrid search queries (vector + BM25)
    - Filter results by similarity threshold
    - Format results with metadata

    Benefits of separating this responsibility:
    - Single Responsibility Principle (SRP)
    - Easier to test query logic
    - Can swap out retrieval strategies
    - Clear interface for querying
    """

    def __init__(
        self,
        vector_store: PGVectorStore,
        top_k: int = 5,
        similarity_cutoff: float = 0.7,
        sparse_top_k: int = 10,
        hybrid_alpha: float = 0.5,
        reranker: Optional["Reranker"] = None,
        hybrid_fusion: str = "rrf",
        rrf_k: int = 60,
        text_search_config: str = "jiebacfg",
    ):
        """Initialize query engine

        Args:
            vector_store: PGVector store to query
            top_k: Number of results to return (default 5)
            similarity_cutoff: Minimum similarity score (default 0.7)
            sparse_top_k: Number of sparse (keyword) results to blend (default 10)
            hybrid_alpha: Blend weight between vector and sparse scores (0-1, default 0.5)
        """
        self._vector_store = vector_store
        self._top_k = top_k
        self._similarity_cutoff = similarity_cutoff
        self._sparse_top_k = sparse_top_k
        self._hybrid_alpha = hybrid_alpha
        self._reranker = reranker
        self._hybrid_fusion = hybrid_fusion
        self._rrf_k = rrf_k
        self._text_search_config = text_search_config

        # 防 pgvector table 已被 drop → 翻成 FolderNotFoundError,不吐 SQL error
        try:
            self._index = VectorStoreIndex.from_vector_store(vector_store)
        except sqlalchemy.exc.ProgrammingError as e:
            err = str(e).lower()
            if "does not exist" in err or "undefined" in err:
                raise FolderNotFoundError(
                    folder_name="Vector store table missing — folder may have been deleted or its index cleared."
                ) from e
            raise

        rerank_status = "enabled" if reranker else "disabled"
        logger.debug(
            f"QueryEngine initialized (top_k={top_k}, "
            f"similarity_cutoff={similarity_cutoff}, "
            f"sparse_top_k={sparse_top_k}, hybrid_alpha={hybrid_alpha}, "
            f"rerank={rerank_status})"
        )

    async def _or_query(self, query_text: str) -> str:
        """把查詢轉成 OR-of-lexemes,修 llama_index 對「無空白語言」的 sparse bug。

        llama_index sparse 把整串查詢丟給 to_tsquery;中文沒空白 → 被建成
        phrase query(token1 <-> token2 <-> …)要求整句逐字相鄰 → 幾乎必 0 命中
        斷詞、拆出 lexeme 用空白串回去(llama_index 隨後把空白換成 |)→ 變 OR
        (同查詢命中 63)。斷詞失敗則退回原字串,不擋檢索。
        """
        def _seg():
            from sqlalchemy import text as _sql
            from db.db import get_engine
            with get_engine().connect() as c:
                return c.execute(
                    _sql("SELECT array_to_string("
                         "tsvector_to_array(to_tsvector(:cfg, :q)), ' ')"),
                    {"cfg": self._text_search_config, "q": query_text}).scalar()
        try:
            seg = await asyncio.to_thread(_seg)
            return seg or query_text
        except Exception as e:  # noqa: BLE001
            logger.debug(f"sparse OR-query segmentation failed, using raw: {e}")
            return query_text

    async def _aretrieve_mode(self, query_text: str, mode: str, k: int):
        """單一 query mode 檢索(default=dense / sparse=BM25 / hybrid),只留 leaf。"""
        q = query_text
        vector_store_kwargs = {}
        if mode in ("sparse", "hybrid"):
            vector_store_kwargs["sparse_top_k"] = self._sparse_top_k
        if mode == "sparse":
            q = await self._or_query(query_text)  # 修 phrase-query bug
        if mode == "hybrid" and self._hybrid_alpha is not None:
            vector_store_kwargs["alpha"] = self._hybrid_alpha
        retriever = VectorIndexRetriever(
            index=self._index, similarity_top_k=k,
            vector_store_query_mode=mode, vector_store_kwargs=vector_store_kwargs,
        )
        nodes = await retriever.aretrieve(q)
        return [n for n in nodes if n.node.metadata.get("node_role", "leaf") == "leaf"]

    def _rrf_fuse(self, ranked_lists, k: int):
        """Reciprocal Rank Fusion:各列表名次 1/(rrf_k+rank) 相加重排。

        不需分數正規化(只看名次),讓 dense 與 BM25 都真正影響最終排序 ——
        修掉 llama_index concat 融合『dense 主導、hybrid≡vector』的問題。
        """
        scores: dict = {}
        node_map: dict = {}
        for lst in ranked_lists:
            for rank, n in enumerate(lst):
                nid = n.node.node_id
                scores[nid] = scores.get(nid, 0.0) + 1.0 / (self._rrf_k + rank + 1)
                node_map.setdefault(nid, n)
        ranked = sorted(node_map.values(),
                        key=lambda n: scores[n.node.node_id], reverse=True)
        for n in ranked:
            n.score = scores[n.node.node_id]  # 下游(rerank / 回傳)用 RRF 分數
        return ranked[:k]

    async def _retrieve_candidates(self, query_text: str, k: int):
        """回 (候選 nodes, is_rrf)。rrf → dense+sparse 分別檢索後 RRF 融合;
        concat → llama_index 原生 hybrid(舊行為)。"""
        if self._hybrid_fusion == "rrf":
            dense = await self._aretrieve_mode(query_text, "default", k)
            sparse = await self._aretrieve_mode(query_text, "sparse", k)
            return self._rrf_fuse([dense, sparse], k), True
        return await self._aretrieve_mode(query_text, "hybrid", k), False

    async def aquery(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        similarity_cutoff: Optional[float] = None
    ) -> List[RAGSearchResult]:
        """Execute a RAG query with hybrid search(真異步)

        整條路徑不佔 event loop:
        - retriever.aretrieve → 查詢 embedding(AsyncOpenAI)+ hybrid SQL(asyncpg)
        - reranker.arerank → httpx.AsyncClient

        Args:
            query_text: Search query
            top_k: Override default top_k (optional)
            similarity_cutoff: Override default cutoff (optional)

        Returns:
            List of RAGSearchResult instances
        """
        # Use provided values or defaults
        k = top_k if top_k is not None else self._top_k
        cutoff = similarity_cutoff if similarity_cutoff is not None else self._similarity_cutoff

        # When reranker is enabled, retrieve more candidates for better precision
        retrieve_k = k * 3 if self._reranker else k

        logger.debug(f"Executing query: '{query_text[:50]}...' (top_k={k}, retrieve_k={retrieve_k}, cutoff={cutoff})")

        try:
            # 混合檢索候選:RRF(dense+sparse 名次融合)或 concat(llama_index 原生)。
            # leaf-only 過濾已在 _aretrieve_mode 內完成(H1:parent 節點不計入名次)。
            nodes, is_rrf = await self._retrieve_candidates(query_text, retrieve_k)
            logger.debug(
                f"Retrieved {len(nodes)} leaf candidates "
                f"(fusion={self._hybrid_fusion}) before rerank/cutoff")

            # Rerank if enabled (cross-encoder produces more accurate scores)
            if self._reranker and nodes:
                # Reranker handles top_n and score_threshold internally
                nodes = await self._reranker.arerank(query_text, nodes, top_n=k)

            # Filter and format results
            results = []
            for node in nodes:
                # similarity cutoff 只適用於 dense 相似度分數;RRF 分數(1/(k+rank)
                # 量級 ~0.03)與 rerank 分數都不適用此門檻,故跳過。
                if not self._reranker and not is_rrf and (node.score is None or node.score < cutoff):
                    continue

                # Extract metadata
                metadata = RAGChunkMetadata(
                    node_id=node.node.node_id,
                    mcp_file_id=node.metadata.get("file_id"),
                    file_name=node.metadata.get("file_name"),
                    folder_name=node.metadata.get("folder_name"),
                    # BL-05 引用溯源(docling 路徑索引的資料才有)
                    page=node.metadata.get("page_no"),
                    headings=node.metadata.get("headings"),
                )

                # Create search result
                result = RAGSearchResult(
                    text=node.text,
                    score=float(node.score) if node.score else 0.0,
                    metadata=metadata
                )
                results.append(result)

            logger.info(
                f"Query completed: {len(results)} results above threshold {cutoff} "
                f"(from {len(nodes)} total)"
            )

            return results

        except sqlalchemy.exc.ProgrammingError as e:
            # vector_store table was dropped (e.g. after delete_folder_index) —
            # translate to FolderNotFoundError so middleware returns 404 instead of 500.
            err = str(e).lower()
            if "does not exist" in err or "undefined" in err:
                logger.warning(f"Vector store table missing during query: {e}")
                raise FolderNotFoundError(
                    folder_name="Vector store table missing — folder may have been deleted or its index cleared."
                ) from e
            logger.error(f"Query execution failed: {e}")
            raise

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise

    async def atrace(
        self,
        query_text: str,
        top_k: Optional[int] = None,
    ) -> dict:
        """檢索軌跡(診斷用)— 拆出 vector / BM25 / hybrid / rerank 各路名次與分數。

        正常查詢只跑一次 hybrid 檢索;trace 為了讓客戶看懂「為什麼這段被選中」,
        額外各跑一次純向量(mode=default)與純 BM25(mode=sparse),用 node_id
        對齊,還原三路名次。用 query mode 而非 hybrid_alpha 拆信號 — pgvector
        的 hybrid 融合不吃 alpha(實測三個 alpha 分數全同),只有換 query mode
        才能真的分出 dense / sparse。屬 playground 診斷路徑,非熱路徑,容許多跑。

        回傳 {results:[{text, metadata, final_score, reranked, rerank_score,
        hybrid_score/rank, vector_score/rank, bm25_score/rank}], reranked, candidates}。
        """
        k = top_k if top_k is not None else self._top_k
        retrieve_k = k * 3 if self._reranker else k

        async def _retrieve(mode: str):
            # 共用 _aretrieve_mode:sparse 會走 OR-query 修正(與 production 一致)
            return await self._aretrieve_mode(query_text, mode, retrieve_k)

        def _rankmap(nodes):
            return {
                n.node.node_id: (float(n.score) if n.score is not None else None, i + 1)
                for i, n in enumerate(nodes)
            }

        vector_nodes = await _retrieve("default")
        bm25_nodes = await _retrieve("sparse")
        # 先擷取原始 dense/sparse 分數 —— _rrf_fuse 會就地覆寫 node.score 為 RRF 分數
        vmap, bmap = _rankmap(vector_nodes), _rankmap(bm25_nodes)
        # 融合列對齊 production aquery:rrf → 我們的 RRF;concat → llama_index 原生 hybrid
        if self._hybrid_fusion == "rrf":
            fused_nodes = self._rrf_fuse([vector_nodes, bm25_nodes], retrieve_k)
        else:
            fused_nodes = await _retrieve("hybrid")
        hmap = _rankmap(fused_nodes)

        reranked = bool(self._reranker and fused_nodes)
        if reranked:
            final = await self._reranker.arerank(query_text, fused_nodes, top_n=k)
        else:
            final = fused_nodes[:k]

        results = []
        for node in final:
            nid = node.node.node_id
            h, v, b = hmap.get(nid), vmap.get(nid), bmap.get(nid)
            results.append({
                "text": node.text,
                "final_score": float(node.score) if node.score is not None else None,
                "reranked": reranked,
                "rerank_score": (float(node.score) if node.score is not None else None) if reranked else None,
                "hybrid_score": h[0] if h else None, "hybrid_rank": h[1] if h else None,
                "vector_score": v[0] if v else None, "vector_rank": v[1] if v else None,
                "bm25_score": b[0] if b else None, "bm25_rank": b[1] if b else None,
                "metadata": {
                    "node_id": nid,
                    "file_name": node.metadata.get("file_name"),
                    "page": node.metadata.get("page_no"),
                    "headings": node.metadata.get("headings"),
                },
            })
        return {"results": results, "reranked": reranked,
                "candidates": len(fused_nodes), "fusion": self._hybrid_fusion}

    def update_config(
        self,
        top_k: Optional[int] = None,
        similarity_cutoff: Optional[float] = None,
        sparse_top_k: Optional[int] = None,
        hybrid_alpha: Optional[float] = None,
        hybrid_fusion: Optional[str] = None,
        rrf_k: Optional[int] = None,
    ):
        """Update query configuration(含融合法熱切換,快取引擎也即時生效)

        Args:
            top_k: New top_k value (optional)
            similarity_cutoff: New cutoff value (optional)
            sparse_top_k: New sparse_top_k value (optional)
            hybrid_alpha: New hybrid blend alpha (optional)
            hybrid_fusion: "rrf" / "concat"(optional)
            rrf_k: RRF 常數 (optional)
        """
        if hybrid_fusion is not None:
            self._hybrid_fusion = hybrid_fusion
        if rrf_k is not None:
            self._rrf_k = rrf_k
        if top_k is not None:
            self._top_k = top_k
            logger.debug(f"Updated top_k to {top_k}")

        if similarity_cutoff is not None:
            self._similarity_cutoff = similarity_cutoff
            logger.debug(f"Updated similarity_cutoff to {similarity_cutoff}")

        if sparse_top_k is not None:
            self._sparse_top_k = sparse_top_k
            logger.debug(f"Updated sparse_top_k to {sparse_top_k}")

        if hybrid_alpha is not None:
            self._hybrid_alpha = hybrid_alpha
            logger.debug(f"Updated hybrid_alpha to {hybrid_alpha}")

    def get_config(self) -> dict:
        """Get current query configuration

        Returns:
            Dictionary with top_k and similarity_cutoff
        """
        return {
            'top_k': self._top_k,
            'similarity_cutoff': self._similarity_cutoff,
            'sparse_top_k': self._sparse_top_k,
            'hybrid_alpha': self._hybrid_alpha
        }
