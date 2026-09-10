
"""Vector Store Manager

Manages the lifecycle and caching of PGVector stores for different folders.
Each folder gets its own isolated vector store identified by vector_table_uuid.
"""

from typing import Dict, Optional
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import make_url, text
from db.db import get_engine
from src.log import get_api_logger
from src.config.config_manager import Config

logger = get_api_logger()


class VectorStoreManager:
    """Manages vector store lifecycle and caching

    Responsibilities:
    - Create PGVector stores for folders using vector_table_uuid
    - Cache vector stores to avoid redundant connections
    - Ensure proper table naming format: data_{vector_table_uuid}
    - Configure hybrid search (vector + BM25)

    Benefits of separating this responsibility:
    - Single Responsibility Principle (SRP)
    - Easier to test vector store logic in isolation
    - Can be reused by other components
    - Clear interface for vector store management
    """

    def __init__(self, embed_dim: int, text_search_config: str = "jiebacfg", hybrid_search: bool = True):
        """Initialize vector store manager

        Args:
            embed_dim: Embedding dimension (must match model output)
            text_search_config: PostgreSQL text search config for BM25 tokenization
                                (e.g., 'jiebacfg' for Chinese, 'english' for English)
            hybrid_search: Enable BM25 + vector hybrid search (default True)
        """
        self._embed_dim = embed_dim
        self._text_search_config = text_search_config
        self._hybrid_search = hybrid_search
        self._vector_stores: Dict[str, PGVectorStore] = {}

        # Get database URL from config
        config = Config.get_config_model()
        if config is None or config.database is None:
            raise RuntimeError("Database configuration is not loaded")

        self._db_url = config.database.url
        self._db_port = config.database.port

        logger.info(f"VectorStoreManager initialized (embed_dim={embed_dim}, text_search_config={text_search_config}, hybrid_search={hybrid_search})")

    def get_or_create(
        self,
        folder_id: int,
        vector_table_uuid: str
    ) -> PGVectorStore:
        """Get existing vector store or create new one

        Args:
            folder_id: Folder ID
            vector_table_uuid: UUID for vector table name (from Folder.vector_table_uuid)

        Returns:
            PGVectorStore instance

        This method implements the cache-aside pattern:
        1. Check if vector store exists in cache
        2. If not, create new one and cache it
        3. Return vector store
        """
        # Use vector_table_uuid as table name (format: data_{folder_id}_{uuid})
        table_name = f"{folder_id}_{vector_table_uuid}"

        # Check cache
        if table_name in self._vector_stores:
            logger.debug(f"Vector store cache HIT: {table_name}")
            return self._vector_stores[table_name]

        # Cache miss - create new vector store
        logger.debug(f"Vector store cache MISS: {table_name}, creating new one")

        try:
            vector_store = self._create_vector_store(table_name)
            self._vector_stores[table_name] = vector_store

            logger.info(
                f"Vector store created successfully: {table_name} "
                f"(folder_id={folder_id}, embed_dim={self._embed_dim})"
            )

            return vector_store

        except Exception as e:
            logger.error(f"Failed to create vector store for {table_name}: {e}")
            raise

    def _create_vector_store(self, table_name: str) -> PGVectorStore:
        """Create a new PGVector store with hybrid search enabled

        Args:
            table_name: PGVector table name

        Returns:
            Configured PGVectorStore instance

        Private method - only called by get_or_create()
        """
        # Parse connection string
        url = make_url(self._db_url)

        # Determine connection parameters with sensible fallbacks
        port = url.port or self._db_port or 5432

        # HNSW index 不透過 LlamaIndex 建 — LlamaIndex 內部 SQL 沒處理 UUID hyphen 的
        # identifier quoting,會炸:
        #     CREATE INDEX IF NOT EXISTS data_2_b09d9acf-d049-...
        #                                              ^ syntax error
        # 改由 src/utils/db_bootstrap.py:_ensure_hnsw_indexes() 在 server boot 時
        # 統一掃所有 data_* 表補 HNSW(冪等),覆蓋既有表跟未來新增 folder 的表。
        vector_store = PGVectorStore.from_params(
            database=url.database,
            host=url.host,
            password=url.password,
            port=int(port),
            user=url.username,
            table_name=table_name,
            embed_dim=self._embed_dim,
            hybrid_search=self._hybrid_search,
            text_search_config=self._text_search_config,
        )

        logger.debug(
            f"PGVector store created: table={table_name}, "
            f"hybrid_search={self._hybrid_search}, embed_dim={self._embed_dim} "
            f"(HNSW auto-managed at boot via db_bootstrap._ensure_hnsw_indexes)"
        )

        return vector_store

    def clear_cache(self):
        """Clear all cached vector stores

        Useful for testing or when memory needs to be freed.
        """
        count = len(self._vector_stores)
        self._vector_stores.clear()
        logger.info(f"Vector store cache cleared ({count} entries removed)")

    def update_embed_dim(self, embed_dim: int) -> None:
        """執行期換 embedding 維度(admin 熱改)— 換值 + 清 store cache。

        cache 內的 PGVectorStore 凍著舊維度,必須一起清;既有 folder 的
        物理表維度不會跟著變(pgvector 建表後固定),要重建索引才對齊。
        """
        if embed_dim == self._embed_dim:
            return
        old = self._embed_dim
        self._embed_dim = embed_dim
        self.clear_cache()
        logger.info(f"[RUNTIME] embed_dim {old} → {embed_dim} (store cache cleared)")

    def get_cache_stats(self) -> dict:
        """Get cache statistics

        Returns:
            Dictionary with cache metrics
        """
        return {
            'cached_stores': len(self._vector_stores),
            'table_names': list(self._vector_stores.keys()),
            'embed_dim': self._embed_dim
        }

    # ------------------------------------------------------------------
    # M5: 物理表刪除 —— 從 adapter 收斂進來(vector store 的職責)。
    # 表名慣例、DROP/DELETE 的 raw SQL 原本散在 rag_maintenance / folder,
    # 各寫一份;統一在這裡,adapter 只呼叫方法。
    # ------------------------------------------------------------------
    @staticmethod
    def physical_table_name(folder_id: int, vector_table_uuid) -> str:
        """某 folder 的 pgvector 物理表名(全專案唯一慣例來源)。

        llama_index PGVectorStore 會在其 internal table_name 前加 data_ 前綴,
        實際落庫的表就是 data_{folder_id}_{uuid}。
        """
        return f"data_{folder_id}_{vector_table_uuid}"

    @staticmethod
    def drop_table_by_name(table_name: str) -> bool:
        """DROP 一張 pgvector 物理表(CASCADE 連帶刪 HNSW 索引/約束)。無 cache 副作用。

        給沒有 VSM instance 的呼叫端(如 folder.py 刪整個 folder)用;有 instance 的
        請用 drop_table()(會一併清 cache)。IF EXISTS:表可能不存在。失敗只記
        log、回 False,不拋 —— 刪除流程不因單一 DDL 失敗而中斷。表名為 int + 服務器
        UUID 拼成,非用戶輸入,無注入面。
        """
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
                conn.commit()
            logger.info(f"Dropped vector table: {table_name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to drop vector table {table_name}: {e}")
            return False

    def drop_table(self, folder_id: int, vector_table_uuid) -> bool:
        """DROP 某 folder 的 pgvector 表並清掉對應 cache(有 instance 時用這支)。"""
        # cache key 無 data_ 前綴(見 get_or_create),清掉避免 stale store 指向已 DROP 表
        self._vector_stores.pop(f"{folder_id}_{vector_table_uuid}", None)
        return self.drop_table_by_name(self.physical_table_name(folder_id, vector_table_uuid))

    @staticmethod
    def delete_chunks_by_file(table_name: str, file_id) -> int:
        """從某 folder 的 pgvector 表刪掉某檔的所有 chunk(比對 metadata_ JSONB)。

        file_id 走 bind param(:file_id)防注入;table_name 為服務器產生的表名。
        回刪除筆數;失敗回 0、不拋。
        """
        try:
            engine = get_engine()
            with engine.connect() as conn:
                result = conn.execute(
                    text(f'DELETE FROM "{table_name}" WHERE metadata_->>\'file_id\' = :file_id'),
                    {"file_id": str(file_id)},
                )
                conn.commit()
                return result.rowcount or 0
        except Exception as e:
            # 表不存在 = 沒 chunk 可刪(首次索引的 C2 寫入前 purge 會踩到)—
            # 正常結果,降級為 debug 免洗版面;其餘錯誤照舊 warning。
            if "does not exist" in str(e).lower() or "undefinedtable" in type(e).__name__.lower():
                logger.debug(f"delete_chunks: table {table_name} absent (nothing to delete)")
            else:
                logger.warning(
                    f"Failed to delete chunks for file {file_id} from {table_name}: {e}"
                )
            return 0
