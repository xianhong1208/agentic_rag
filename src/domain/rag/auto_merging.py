
"""Auto-Merging Retriever — 命中多 leaf 同 parent 自動 merge 回 parent

核心邏輯:
1. 用 hybrid retrieval(vector + BM25)+ rerank 撈 top-k LEAF nodes
   (查詢時用 metadata filter 限制 node_role=leaf,parent 不參與檢索)
2. 統計命中 leaves 的 parent 分布
3. 若某 parent 的 children 命中比例達到 merge_threshold 則升級回 parent
4. 對沒被升級的 leaves,可選地展開鄰居(expand_context)

設計取捨:
- 沒用 LlamaIndex 內建 AutoMergingRetriever,因為它依賴 docstore(in-memory),
  而我們是 PGVector + JSONB metadata 路線。寫成自己的 50 行邏輯反而更清楚。
- merge 後仍保留原始 leaf 的 score(用「該 parent 命中 children 的最高分」),
  這樣 final ranking 還是有意義的。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.postgres import PGVectorStore

from src.log import get_api_logger

logger = get_api_logger()


@dataclass
class MergedResult:
    """Auto-merge 後的單一結果

    可能是:
    - 原始 leaf(沒觸發 merge)
    - 升級後的 parent(觸發 merge)
    - leaf + 展開鄰居(expand_context=True)
    """
    text: str
    score: float
    file_id: str
    file_name: str
    node_id: str
    node_role: str                    # leaf / parent / expanded
    chunk_index_range: List[int]      # parent: [start, end];leaf: [i, i]
    merged_from_leaves: List[str] = field(default_factory=list)  # parent merge 時記錄
    # BL-05 引用溯源(來自 leaf node metadata;parent merge 取最高分命中 leaf 的)
    page: Optional[int] = None
    headings: Optional[List[str]] = None


class AutoMergingRetriever:
    """命中後智慧合併的 retriever

    Usage:
        retriever = AutoMergingRetriever(
            vector_store=...,
            reranker=...,
            merge_threshold=0.5,
            expand_context_neighbors=2,
        )
        results = await retriever.aquery(query_text="問題", top_k=6, expand_context=True)
    """

    def __init__(
        self,
        vector_store: PGVectorStore,
        reranker=None,
        merge_threshold: float = 0.5,
        expand_context_neighbors: int = 2,
        sparse_top_k: int = 12,
        hybrid_alpha: float = 0.75,
    ):
        from llama_index.core import VectorStoreIndex
        from llama_index.core.retrievers import VectorIndexRetriever

        self._vector_store = vector_store
        self._reranker = reranker
        self._merge_threshold = merge_threshold
        self._expand_context_neighbors = expand_context_neighbors
        self._sparse_top_k = sparse_top_k
        self._hybrid_alpha = hybrid_alpha
        self._index = VectorStoreIndex.from_vector_store(vector_store)
        self._VectorIndexRetriever = VectorIndexRetriever

        logger.info(
            f"AutoMergingRetriever ready (merge_threshold={merge_threshold}, "
            f"expand_neighbors={expand_context_neighbors})"
        )

    async def aquery(
        self,
        query_text: str,
        top_k: int = 6,
        similarity_cutoff: float = 0.4,
        expand_context: bool = True,
    ) -> List[MergedResult]:
        """執行 hybrid retrieval + auto-merge(真異步 + 批次 DB 查詢)。

        流程:hybrid retrieve 只撈 leaves → rerank → 統計 parent 命中 → 達閾值的 parent 取代 leaves;
        沒 merge 的 leaves 可選展開鄰居。

        DB 互動全批次化(原 N+1 → 最多 3 次 round trip):
        parent 計數 1 次、parent 內容 1 次、鄰居窗口 1 次,全走 async engine。

        Args:
            query_text: 查詢字串。
            top_k: 回傳前 K 個結果(rerank 後)。
            similarity_cutoff: 相似度閾值;reranker 啟用時無效。
            expand_context: True → 為沒 merge 的 leaves 展開鄰居。

        Returns:
            List[MergedResult]。
        """
        from src.domain.rag.chunk_lookup import ChunkLookup

        retrieve_k = top_k * 3 if self._reranker else top_k

        retriever = self._VectorIndexRetriever(
            index=self._index,
            similarity_top_k=retrieve_k,
            vector_store_query_mode="hybrid",
            vector_store_kwargs={
                "sparse_top_k": self._sparse_top_k,
                "alpha": self._hybrid_alpha,
            },
        )

        nodes = await retriever.aretrieve(query_text)
        # 過濾:只取 leaf nodes(parent 也在同表,但不參與檢索 ranking)
        # 之所以兩者同表卻能分開:索引時 parent 沒有 embedding,vector retrieval 不會選到;
        # BM25 階段可能偶爾選到 parent,這裡顯式過濾保險。
        # 向下相容:沒有 node_role 的 legacy chunks(舊版 flat 索引)視為 leaf,
        # 讓使用者不必為了升級被迫重新索引(但這些 chunks 不會觸發 auto-merge,
        # 因為沒有 parent_node_id)。
        leaf_nodes = [
            n for n in nodes
            if n.node.metadata.get("node_role", "leaf") == "leaf"
        ]

        logger.debug(f"Retrieved {len(nodes)} nodes, {len(leaf_nodes)} are leaves")

        if self._reranker and leaf_nodes:
            leaf_nodes = await self._reranker.arerank(query_text, leaf_nodes, top_n=top_k)

        if not self._reranker:
            leaf_nodes = [n for n in leaf_nodes if n.score and n.score >= similarity_cutoff]

        if not leaf_nodes:
            return []

        # ---------- Auto-merge 決策(parent 計數:N 次查詢 → 1 次批次)----------
        parent_hits: Dict[str, List[NodeWithScore]] = defaultdict(list)
        for ln in leaf_nodes:
            pid = ln.node.metadata.get("parent_node_id")
            if pid:
                parent_hits[pid].append(ln)

        children_counts = await ChunkLookup.aget_parent_children_counts(
            self._vector_store, list(parent_hits.keys())
        )

        parents_to_merge: List[str] = []
        for pid, hit_leaves in parent_hits.items():
            total_children = children_counts.get(pid, 0)
            if total_children == 0:
                continue
            hit_ratio = len(hit_leaves) / total_children
            if hit_ratio >= self._merge_threshold and len(hit_leaves) >= 2:
                parents_to_merge.append(pid)
                logger.debug(
                    f"Will merge parent {pid[:8]}: "
                    f"{len(hit_leaves)}/{total_children} children hit ({hit_ratio:.0%})"
                )

        # ---------- 批次預取(原本在迴圈內逐筆查,N+1 的主體)----------
        # parent 內容:1 次批次
        parent_nodes_map = await ChunkLookup.afetch_nodes(
            self._vector_store, parents_to_merge
        )
        # 鄰居窗口:先算出會走 expand 分支的 leaves(pid 沒被 merge、首見),1 次批次
        window_by_leaf: Dict[str, dict] = {}
        if expand_context and self._expand_context_neighbors > 0:
            expand_targets = []
            seen_ids: set = set()
            for ln in leaf_nodes:
                pid = ln.node.metadata.get("parent_node_id")
                if pid in parents_to_merge or ln.node.id_ in seen_ids:
                    continue
                seen_ids.add(ln.node.id_)
                fid = ln.node.metadata.get("file_id")
                ci = ln.node.metadata.get("chunk_index")
                if fid is not None and ci is not None:
                    expand_targets.append((ln.node.id_, fid, ci))
            if expand_targets:
                windows = await ChunkLookup.afetch_neighbor_windows(
                    self._vector_store,
                    [(fid, ci) for _, fid, ci in expand_targets],
                    n=self._expand_context_neighbors,
                )
                window_by_leaf = {
                    leaf_id: w
                    for (leaf_id, _, _), w in zip(expand_targets, windows)
                }

        # ---------- 構建最終結果 ----------
        results: List[MergedResult] = []
        merged_parent_ids: set = set()
        used_leaf_ids: set = set()

        def _provenance(node) -> dict:
            """leaf metadata 的 page_no/headings → MergedResult 引用欄位(BL-05)。"""
            md = node.metadata
            return {"page": md.get("page_no"), "headings": md.get("headings")}

        for ln in leaf_nodes:
            pid = ln.node.metadata.get("parent_node_id")

            if pid in parents_to_merge and pid not in merged_parent_ids:
                parent_node = parent_nodes_map.get(pid)
                if parent_node:
                    merged_leaves = [hl.node.id_ for hl in parent_hits[pid]]
                    used_leaf_ids.update(merged_leaves)
                    best_hit = max(parent_hits[pid], key=lambda hl: hl.score or 0.0)
                    results.append(MergedResult(
                        text=parent_node.text,
                        score=best_hit.score or 0.0,
                        file_id=parent_node.metadata.get("file_id", ""),
                        file_name=parent_node.metadata.get("file_name", ""),
                        node_id=pid,
                        node_role="parent",
                        chunk_index_range=parent_node.metadata.get("children_index_range", []),
                        merged_from_leaves=merged_leaves,
                        **_provenance(best_hit.node),
                    ))
                    merged_parent_ids.add(pid)
                continue

            if pid in merged_parent_ids:
                continue

            if ln.node.id_ in used_leaf_ids:
                continue
            used_leaf_ids.add(ln.node.id_)

            if expand_context and self._expand_context_neighbors > 0:
                # 批次預取的窗口;缺 file_id/chunk_index 的 leaf 不在 map 裡,
                # fallback 為原 leaf 內容(與舊逐筆版 _expand_neighbors 行為一致)
                center = ln.node.metadata.get("chunk_index")
                expanded = window_by_leaf.get(
                    ln.node.id_,
                    {"text": ln.node.text, "index_range": [center, center]},
                )
                results.append(MergedResult(
                    text=expanded["text"],
                    score=ln.score or 0.0,
                    file_id=ln.node.metadata.get("file_id", ""),
                    file_name=ln.node.metadata.get("file_name", ""),
                    node_id=ln.node.id_,
                    node_role="expanded",
                    chunk_index_range=expanded["index_range"],
                    **_provenance(ln.node),
                ))
            else:
                results.append(MergedResult(
                    text=ln.node.text,
                    score=ln.score or 0.0,
                    file_id=ln.node.metadata.get("file_id", ""),
                    file_name=ln.node.metadata.get("file_name", ""),
                    node_id=ln.node.id_,
                    node_role="leaf",
                    chunk_index_range=[
                        ln.node.metadata.get("chunk_index", -1),
                        ln.node.metadata.get("chunk_index", -1),
                    ],
                    **_provenance(ln.node),
                ))

        results.sort(key=lambda r: r.score, reverse=True)

        logger.info(
            f"AutoMerge query done: {len(leaf_nodes)} leaves to "
            f"{len(results)} results ({len(merged_parent_ids)} merged to parent)"
        )
        return results

    # 舊的逐筆 DB helpers(_get_parent_children_count / _fetch_parent /
    # _expand_neighbors)已移除 — aquery 內改用 ChunkLookup 的批次 async 版,
    # 一次 search 的 DB round trip 從 N+1 收斂為最多 3 次。
