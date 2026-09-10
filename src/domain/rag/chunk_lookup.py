
"""ChunkLookup — 直接 SQL 查詢 PGVector 表的 metadata,bypass LlamaIndex retrieval

為什麼需要這層:
- LlamaIndex 的 retriever 是「query → embedding → 相似度排序」,
  不適合「給定 node_id 取單一節點」或「給定 file_id 取一段 chunk_index 區間」這類精確查詢。
- PGVector 表結構(LlamaIndex 自動建立):
    data_{folder_id}_{uuid}:
        id           bigserial primary key
        text         text
        metadata_    jsonb        (!! 注意底線後綴 — LlamaIndex 慣例 !!)
        node_id      varchar
        embedding    vector(N)
- 用 JSONB operator (->>) 查 metadata 比走 LlamaIndex 抽象層快 10-100 倍。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import bindparam, text as sql_text

from src.log import get_api_logger

logger = get_api_logger()


class ChunkLookup:
    """無狀態工具類 — 全部是 staticmethod"""

    @staticmethod
    def _get_table_name(vector_store: PGVectorStore) -> str:
        """取得 PGVectorStore 對應的 SQL table 名(含 `data_` 前綴)。

        對不同 LlamaIndex 版本的內部屬性做容錯抽取。

        Args:
            vector_store: PGVectorStore instance。

        Returns:
            完整 table 名,例如 `data_5_<uuid>`;抽不到 raise ValueError。
        """
        # 主路徑:vector_store.table_name(較新版本)
        name = getattr(vector_store, "table_name", None)
        if name:
            return name if name.startswith("data_") else f"data_{name}"

        # 備援:從 _table_class 取
        table_class = getattr(vector_store, "_table_class", None)
        if table_class is not None:
            return table_class.__tablename__

        raise RuntimeError(
            "Cannot determine PGVector table name — LlamaIndex internal API changed?"
        )

    @staticmethod
    def _get_engine(vector_store: PGVectorStore):
        """取得 SQLAlchemy engine — 統一走 db.db.get_engine() 避開雙軌 pool。

        舊版自建 cache 沒 health check;DB 重啟後 cached engine 壞掉到 server restart。
        現在 PGVectorStore 已 lazy-init 的就用它,否則走主 engine。

        Args:
            vector_store: PGVectorStore instance。

        Returns:
            SQLAlchemy engine。
        """
        # 優先用 LlamaIndex 已建好的(避免雙寫不一致)
        existing = getattr(vector_store, "_engine", None)
        if existing is not None:
            return existing

        # PGVector 跟 metadata 表共用同一個 DB,直接用主 engine
        from db.db import get_engine
        return get_engine()

    # ----------------------------------------------------------------------
    # Async batched API — 查詢熱路徑用
    # 一次 search 會需要 N 個 parent 計數 + M 個鄰居窗口;逐筆查是 N+1
    # (10-30 次串行 round trip)。這裡全部批次成單一查詢,並走 async engine
    # 不佔 event loop。sync 版保留給非熱路徑(read mode / 舊呼叫端)。
    # ----------------------------------------------------------------------

    @staticmethod
    async def aget_parent_children_counts(
        vector_store: PGVectorStore, parent_ids: List[str],
    ) -> Dict[str, int]:
        """批次讀多個 parent 的 chunk_count(單一查詢)。

        Args:
            vector_store: 目標 folder 的 PGVectorStore。
            parent_ids: parent node_id list。

        Returns:
            {parent_id: chunk_count};查不到的 id 不在 dict 裡。DB 失敗回空 dict
            (fail-open:caller 視為 count=0 → 不觸發 merge,檢索仍有結果)。
        """
        if not parent_ids:
            return {}
        table = ChunkLookup._get_table_name(vector_store)
        from db.db import get_async_engine

        query = sql_text(f"""
            SELECT node_id, (metadata_->>'chunk_count')::int AS cnt
            FROM "{table}"
            WHERE node_id IN :ids
              AND metadata_->>'node_role' = 'parent'
        """).bindparams(bindparam("ids", expanding=True))
        try:
            async with get_async_engine().connect() as conn:
                rows = (await conn.execute(query, {"ids": list(parent_ids)})).fetchall()
            return {r[0]: int(r[1]) for r in rows if r[1] is not None}
        except Exception as e:
            logger.warning(f"aget_parent_children_counts failed ({len(parent_ids)} ids): {e}")
            return {}

    @staticmethod
    async def afetch_nodes(
        vector_store: PGVectorStore, node_ids: List[str],
    ) -> Dict[str, TextNode]:
        """批次撈多個 node 的完整內容(單一查詢)。

        Returns:
            {node_id: TextNode};查不到的不在 dict。DB 失敗回空 dict。
        """
        if not node_ids:
            return {}
        table = ChunkLookup._get_table_name(vector_store)
        from db.db import get_async_engine

        query = sql_text(f"""
            SELECT node_id, text, metadata_
            FROM "{table}"
            WHERE node_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))
        try:
            async with get_async_engine().connect() as conn:
                rows = (await conn.execute(query, {"ids": list(node_ids)})).fetchall()
            return {
                r[0]: TextNode(id_=r[0], text=r[1], metadata=r[2] or {})
                for r in rows
            }
        except Exception as e:
            logger.warning(f"afetch_nodes failed ({len(node_ids)} ids): {e}")
            return {}

    @staticmethod
    async def afetch_neighbor_windows(
        vector_store: PGVectorStore,
        requests: List[Tuple[str, int]],
        n: int,
    ) -> List[dict]:
        """批次撈多個 (file_id, center_chunk_index±n) 鄰居窗口(單一查詢)。

        SQL 用 OR-chain 的參數化區間條件(每窗 3 個 bind param,top_k≤10 → 條件
        數有限);Python 端再按窗口切分。窗口可能互相重疊,各窗獨立取自己的列。

        Args:
            vector_store: 目標 folder 的 PGVectorStore。
            requests: [(file_id, center_chunk_index), ...],順序保留。
            n: 左右各展開的鄰居數。

        Returns:
            與 requests 等長的 dict list,格式同 fetch_neighbor_window。
        """
        empty = lambda c: {"text": "", "index_range": [c, c], "chunks": []}  # noqa: E731
        if not requests:
            return []
        table = ChunkLookup._get_table_name(vector_store)
        from db.db import get_async_engine

        conditions = []
        params: Dict[str, object] = {}
        for i, (file_id, center) in enumerate(requests):
            conditions.append(
                f"(metadata_->>'file_id' = :fid_{i} "
                f"AND (metadata_->>'chunk_index')::int BETWEEN :s_{i} AND :e_{i})"
            )
            params[f"fid_{i}"] = str(file_id)
            params[f"s_{i}"] = max(center - n, 0)
            params[f"e_{i}"] = center + n

        query = sql_text(f"""
            SELECT
                metadata_->>'file_id' AS fid,
                text,
                (metadata_->>'chunk_index')::int AS idx
            FROM "{table}"
            WHERE COALESCE(metadata_->>'node_role', 'leaf') = 'leaf'
              AND ({" OR ".join(conditions)})
            ORDER BY fid, idx ASC
        """)
        try:
            async with get_async_engine().connect() as conn:
                rows = (await conn.execute(query, params)).fetchall()
        except Exception as e:
            logger.warning(f"afetch_neighbor_windows failed ({len(requests)} windows): {e}")
            return [empty(c) for _, c in requests]

        # 按 file_id 分桶後,各窗自取區間(窗口重疊時同列可進多窗)
        by_file: Dict[str, List[Tuple[int, str]]] = {}
        for fid, txt, idx in rows:
            by_file.setdefault(fid, []).append((idx, txt))

        results = []
        for file_id, center in requests:
            start, end = max(center - n, 0), center + n
            hits = [
                {"chunk_index": idx, "text": txt}
                for idx, txt in by_file.get(str(file_id), [])
                if start <= idx <= end
            ]
            if not hits:
                results.append(empty(center))
                continue
            results.append({
                "text": "\n\n".join(h["text"] for h in hits),
                "index_range": [hits[0]["chunk_index"], hits[-1]["chunk_index"]],
                "chunks": hits,
            })
        return results

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    @staticmethod
    def get_parent_children_count(vector_store: PGVectorStore, parent_id: str) -> int:
        """從 parent node 的 metadata 讀 chunk_count(由 hierarchy.build_hierarchy 寫入)"""
        table = ChunkLookup._get_table_name(vector_store)
        engine = ChunkLookup._get_engine(vector_store)

        query = sql_text(f"""
            SELECT (metadata_->>'chunk_count')::int AS cnt
            FROM "{table}"
            WHERE node_id = :node_id
              AND metadata_->>'node_role' = 'parent'
            LIMIT 1
        """)
        try:
            with engine.connect() as conn:
                row = conn.execute(query, {"node_id": parent_id}).first()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.warning(f"get_parent_children_count failed for {parent_id[:8]}: {e}")
            return 0

    @staticmethod
    def fetch_node(vector_store: PGVectorStore, node_id: str) -> Optional[TextNode]:
        """撈單一 node(leaf 或 parent)的完整內容"""
        table = ChunkLookup._get_table_name(vector_store)
        engine = ChunkLookup._get_engine(vector_store)

        query = sql_text(f"""
            SELECT node_id, text, metadata_
            FROM "{table}"
            WHERE node_id = :node_id
            LIMIT 1
        """)
        try:
            with engine.connect() as conn:
                row = conn.execute(query, {"node_id": node_id}).first()
                if not row:
                    return None
                return TextNode(
                    id_=row[0],
                    text=row[1],
                    metadata=row[2] or {},
                )
        except Exception as e:
            logger.warning(f"fetch_node failed for {node_id[:8]}: {e}")
            return None

    @staticmethod
    def fetch_neighbor_window(
        vector_store: PGVectorStore,
        file_id: str,
        center_chunk_index: int,
        n: int,
    ) -> dict:
        """撈 (file_id, chunk_index ± n) 的 leaf chunks,順序拼接

        Returns:
            {
                "text": "拼接後的擴展段落",
                "index_range": [start, end],
                "chunks": [{"chunk_index": i, "text": "..."}, ...]
            }
        """
        table = ChunkLookup._get_table_name(vector_store)
        engine = ChunkLookup._get_engine(vector_store)

        start = max(center_chunk_index - n, 0)
        end = center_chunk_index + n

        # 向下相容:legacy chunks(舊版 flat 索引)沒有 node_role,視為 leaf 也撈
        query = sql_text(f"""
            SELECT
                node_id,
                text,
                (metadata_->>'chunk_index')::int AS idx
            FROM "{table}"
            WHERE metadata_->>'file_id' = :file_id
              AND COALESCE(metadata_->>'node_role', 'leaf') = 'leaf'
              AND (metadata_->>'chunk_index')::int BETWEEN :start AND :end
            ORDER BY idx ASC
        """)
        try:
            with engine.connect() as conn:
                rows = conn.execute(query, {
                    "file_id": str(file_id),
                    "start": start,
                    "end": end,
                }).fetchall()

            if not rows:
                return {"text": "", "index_range": [center_chunk_index, center_chunk_index], "chunks": []}

            chunks = [{"chunk_index": r[2], "text": r[1]} for r in rows]
            joined = "\n\n".join(c["text"] for c in chunks)
            return {
                "text": joined,
                "index_range": [chunks[0]["chunk_index"], chunks[-1]["chunk_index"]],
                "chunks": chunks,
            }
        except Exception as e:
            logger.warning(f"fetch_neighbor_window failed for file={file_id} center={center_chunk_index}: {e}")
            return {"text": "", "index_range": [center_chunk_index, center_chunk_index], "chunks": []}

    @staticmethod
    def fetch_file_full(vector_store: PGVectorStore, file_id: str, max_tokens: int = 30000) -> dict:
        """撈整份檔案的所有 leaf chunks,順序拼成全文(供 mode='read' 用)

        Returns:
            {
                "text": "完整文字",
                "tokens_estimated": int,
                "truncated": bool,
                "chunk_count": int,
            }
        """
        table = ChunkLookup._get_table_name(vector_store)
        engine = ChunkLookup._get_engine(vector_store)

        # 向下相容:legacy chunks 視為 leaf
        query = sql_text(f"""
            SELECT
                text,
                (metadata_->>'chunk_index')::int AS idx
            FROM "{table}"
            WHERE metadata_->>'file_id' = :file_id
              AND COALESCE(metadata_->>'node_role', 'leaf') = 'leaf'
            ORDER BY idx ASC
        """)
        try:
            with engine.connect() as conn:
                rows = conn.execute(query, {"file_id": str(file_id)}).fetchall()

            if not rows:
                return {"text": "", "tokens_estimated": 0, "truncated": False, "chunk_count": 0}

            from src.domain.rag.hierarchy import estimate_tokens

            joined_parts = []
            running_tokens = 0
            truncated = False
            for r in rows:
                t = r[0]
                t_tokens = estimate_tokens(t)
                if running_tokens + t_tokens > max_tokens:
                    truncated = True
                    break
                joined_parts.append(t)
                running_tokens += t_tokens

            return {
                "text": "\n\n".join(joined_parts),
                "tokens_estimated": running_tokens,
                "truncated": truncated,
                "chunk_count": len(joined_parts),
            }
        except Exception as e:
            logger.warning(f"fetch_file_full failed for file={file_id}: {e}")
            return {"text": "", "tokens_estimated": 0, "truncated": False, "chunk_count": 0}
