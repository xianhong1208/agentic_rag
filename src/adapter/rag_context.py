
"""Shared dependencies + cached state for RAG operations.

RAGAdapter 拆分前是 1330 行單檔(violates SRP)。Phase 1 把所有 __init__ 期間建立
的「共用狀態」抽到這個 RAGContext dataclass — embedding provider / indexer /
vector store manager / reranker / config-derived sizes / mutable caches。

之後 indexing / query / maintenance 三個 sub-service 都會接 RAGContext 作為
依賴,擺脫互相耦合到 RAGAdapter 的私有屬性。

設計取捨:
- 用 `dataclass` 而不是 plain class — 強制宣告所有 fields,IDE 補全友善
- `from_config()` classmethod 是唯一的 factory,封裝所有 fallback / error handling
- `query_engines` 是 mutable cache,放在 ctx 上讓 sub-services 共享
- `get_vector_store` 跟 `invalidate_query_engine_cache` 是 ctx 自己的 helper —
  雖然不是「資料」,但都依賴 ctx 內部的 manager + cache,放這裡比 sub-services
  各自 own 一份更清楚。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from llama_index.core import Settings
from llama_index.vector_stores.postgres import PGVectorStore

from src.config.config_manager import Config
from src.domain.exceptions import RAGOperationError
from src.domain.rag.embedding import (
    EmbeddingProviderFactory,
    OpenAIEmbeddingProvider,
)
from src.domain.rag.hierarchical_indexer import HierarchicalIndexer
from src.domain.rag.index_service import IndexingService
from src.domain.rag.vector_store_manager import VectorStoreManager
from src.log import get_adapter_logger, log_err, mask_token

if TYPE_CHECKING:
    from src.domain.rag.query_engine import QueryEngine
    from src.domain.rag.reranker import Reranker

logger = get_adapter_logger()


@dataclass
class RAGContext:
    """RAGAdapter 跟 sub-services 共享的所有 dependencies + caches。

    由 `from_config()` 構造一次,之後 indexing / query / maintenance services
    都接這個 ctx,不再各自管理初始化。
    """

    embedding_provider: Any
    embed_dim: int
    model_name: str
    chunker_tokenizer_name: Optional[str]

    leaf_chunk_size: int
    parent_target_tokens: int
    chunk_overlap: int

    vector_store_manager: VectorStoreManager
    indexer: HierarchicalIndexer
    indexing_service: IndexingService

    auto_merging_enabled: bool
    merge_threshold: float
    expand_neighbors: int

    reranker: Optional["Reranker"] = None

    query_engines: Dict[str, "QueryEngine"] = field(default_factory=dict)

    @classmethod
    def from_config(cls) -> "RAGContext":
        """從 Config singleton 建構整個 RAG 運行時狀態。

        失敗時 fallback 到 OpenAI default — 確保 RAG adapter 在 config 異常時
        仍能勉強啟動,而不是 crash 整個 server。
        """
        rag_config = None
        try:
            config_model = Config.get_config_model()
            rag_config = config_model.rag
        except Exception as e:
            logger.error(f"Failed to load RAG configuration: {e}")

        provider_info = cls._load_embedding_provider(rag_config)

        leaf_size, parent_target, overlap = cls._load_chunking_sizes(rag_config)
        Settings.chunk_size = leaf_size
        Settings.chunk_overlap = overlap

        text_search_config = "jiebacfg"
        hybrid_search = True
        try:
            if rag_config and rag_config.retrieval:
                text_search_config = getattr(
                    rag_config.retrieval, "text_search_config", "jiebacfg"
                )
                hybrid_search = getattr(rag_config.retrieval, "hybrid_search", True)
        except Exception:
            pass

        vector_store_manager = VectorStoreManager(
            embed_dim=provider_info["embed_dim"],
            text_search_config=text_search_config,
            hybrid_search=hybrid_search,
        )
        logger.info("[INIT] VectorStoreManager initialized")

        context_generator = None
        try:
            if rag_config:
                from src.domain.rag.context_generator import ContextGenerator
                context_generator = ContextGenerator.from_config(rag_config)
        except Exception as e:
            logger.warning(f"Contextual Retrieval initialization failed: {e}")

        # BL-06/07: ASR provider 依 config 選(未設 → default docling-whisper)
        from src.domain.rag.asr_provider import create_asr_provider
        asr_cfg = getattr(rag_config, "asr", None) if rag_config else None
        indexer = HierarchicalIndexer(
            leaf_chunk_size=leaf_size,
            parent_target_tokens=parent_target,
            chunk_overlap=overlap,
            context_generator=context_generator,
            embedding_model_name=provider_info["chunker_tokenizer_name"],
            embed_model=provider_info.get("embed_model"),  # H6: 注入,不讀全域
            asr_provider=create_asr_provider(asr_cfg),
            asr_enabled=(asr_cfg.enabled if asr_cfg else True),
        )
        logger.info("[INIT] HierarchicalIndexer initialized")

        am_cfg = getattr(rag_config, "retrieval", None) if rag_config else None
        am_cfg = getattr(am_cfg, "auto_merging", None) if am_cfg else None
        auto_merging_enabled = bool(getattr(am_cfg, "enabled", True)) if am_cfg else True
        merge_threshold = float(getattr(am_cfg, "merge_threshold", 0.5)) if am_cfg else 0.5
        expand_neighbors = (
            int(getattr(rag_config.retrieval, "expand_context_neighbors", 2))
            if rag_config and rag_config.retrieval else 2
        )

        indexing_service = IndexingService()
        logger.info("[INIT] IndexingService initialized")

        reranker = None
        try:
            if rag_config:
                rerank_config = getattr(rag_config, "rerank", None)
                if rerank_config and rerank_config.enabled:
                    from src.domain.rag.reranker import Reranker
                    reranker = Reranker.from_config(rerank_config)
                    if reranker:
                        logger.info("[INIT] Reranker initialized")
        except Exception as e:
            logger.warning(f"Reranker initialization failed: {e}")

        return cls(
            embedding_provider=provider_info["provider"],
            embed_dim=provider_info["embed_dim"],
            model_name=provider_info["model_name"],
            chunker_tokenizer_name=provider_info["chunker_tokenizer_name"],
            leaf_chunk_size=leaf_size,
            parent_target_tokens=parent_target,
            chunk_overlap=overlap,
            vector_store_manager=vector_store_manager,
            indexer=indexer,
            indexing_service=indexing_service,
            auto_merging_enabled=auto_merging_enabled,
            merge_threshold=merge_threshold,
            expand_neighbors=expand_neighbors,
            reranker=reranker,
        )

    @staticmethod
    def _load_embedding_provider(rag_config) -> Dict[str, Any]:
        """嘗試從 config 建 provider,失敗 fallback OpenAI default。"""
        if rag_config and rag_config.enabled:
            embedding_config = rag_config.embedding
            logger.info(
                f"Loading RAG configuration: provider={embedding_config.provider}, "
                f"model={embedding_config.model}, dimension={embedding_config.dimension}"
            )
            try:
                provider = EmbeddingProviderFactory.create_from_config(embedding_config)
                embed_model = provider.get_embed_model()
                # e5 系需要 query/passage 前綴(config 設定);bge 留空 = 不包裝零開銷
                q_pre = getattr(embedding_config, "query_prefix", "") or ""
                p_pre = getattr(embedding_config, "passage_prefix", "") or ""
                if q_pre or p_pre:
                    from src.domain.rag.embedding.prefixed import PrefixedEmbedding
                    embed_model = PrefixedEmbedding(
                        embed_model, query_prefix=q_pre, passage_prefix=p_pre)
                    logger.info(
                        f"Embedding prefixes enabled: query='{q_pre}' passage='{p_pre}'")
                Settings.embed_model = embed_model
                # chunker tokenizer = embedding 模型的 HF tokenizer(算 chunk token 數用)。
                # vllm / ollama 服務的也是 HF 模型名(如 BAAI/bge-m3),一樣可解析到
                # assets/hf_tokenizers;只有 openai / azure 的專有模型名不是 HF repo。
                # (修:原本只認 huggingface,vllm 拿到 None → tokenizer 靠 fallback 猜)
                chunker_tok = (
                    provider.get_model_name()
                    if provider.get_provider_name() in ("huggingface", "vllm", "ollama")
                    else None
                )
                logger.info(
                    f"Embedding provider initialized successfully: "
                    f"{provider.get_provider_name()} - {provider.get_model_name()} "
                    f"(dimension={provider.get_dimension()})"
                )
                return {
                    "provider": provider,
                    "embed_dim": provider.get_dimension(),
                    "model_name": provider.get_model_name(),
                    "chunker_tokenizer_name": chunker_tok,
                    # H6: 把最終 embed_model(含 PrefixedEmbedding 包裝)一起帶出,
                    # 注入 HierarchicalIndexer,讓 indexer 不必讀全域 Settings.embed_model
                    "embed_model": embed_model,
                }
            except Exception as e:
                logger.error(f"Failed to create embedding provider: {e}")
                logger.warning("Falling back to default OpenAI configuration")

        if not rag_config or not rag_config.enabled:
            logger.warning("RAG configuration not found, using defaults")
        return RAGContext._setup_default_provider()

    @staticmethod
    def _setup_default_provider() -> Dict[str, Any]:
        """OpenAI text-embedding-3-small fallback。"""
        try:
            provider = OpenAIEmbeddingProvider(
                model_name="text-embedding-3-small",
                dimension=1536,
            )
            Settings.embed_model = provider.get_embed_model()
            Settings.chunk_size = 512
            Settings.chunk_overlap = 50
            logger.info("Default OpenAI configuration loaded successfully")
            return {
                "provider": provider,
                "embed_dim": provider.get_dimension(),
                "model_name": provider.get_model_name(),
                "chunker_tokenizer_name": None,
                "embed_model": provider.get_embed_model(),  # H6: 見上
            }
        except Exception as e:
            logger.error(f"Failed to setup default configuration: {e}")
            raise RuntimeError("Unable to initialize embedding provider")

    @staticmethod
    def _load_chunking_sizes(rag_config) -> tuple[int, int, int]:
        """Returns (leaf_size, parent_target, chunk_overlap)。"""
        if not rag_config or not rag_config.enabled:
            return 256, 1024, 50
        chunking_config = rag_config.chunking
        sizes = getattr(chunking_config, "hierarchy_sizes", None) or [1024, 256]
        if len(sizes) < 2:
            sizes = [1024, 256]
        parent_target = sizes[0]
        leaf_size = sizes[-1]
        overlap = getattr(chunking_config, "chunk_overlap", 50)
        logger.info(
            f"Hierarchical chunking: leaf_size={leaf_size}, "
            f"parent_target={parent_target}, overlap={overlap}"
        )
        return leaf_size, parent_target, overlap

    def get_vector_store(
        self,
        folder_id: int,
        token: str,
        folder: Optional[Any] = None,
    ) -> PGVectorStore:
        """獲取或創建指定 folder/token 的向量存儲。

        Raises:
            RAGOperationError: vector store 取得失敗
            DomainException: folder 不存在或 token 沒權限
        """
        folder = folder or self.indexing_service.get_folder(folder_id, token)
        vector_table_uuid = str(folder.vector_table_uuid)

        try:
            vector_store = self.vector_store_manager.get_or_create(
                folder_id=folder_id,
                vector_table_uuid=vector_table_uuid,
            )
            logger.debug(
                f"[VECTOR_STORE] fid={folder_id} tok={mask_token(token)} | "
                f"obtained table=data_{folder_id}_{vector_table_uuid}"
            )
            return vector_store
        except Exception as e:
            log_err(logger, "VECTOR_STORE_FAIL", e, folder_id=folder_id, token=token)
            raise RAGOperationError(
                operation="vector_store_access",
                reason=str(e),
                details={"folder_id": folder_id, "vector_table_uuid": vector_table_uuid},
            )

    def invalidate_query_engine_cache(self, folder_id: int) -> None:
        """從 cache 移除指定 folder 的 QueryEngine(index 變更後呼叫)。"""
        key = f"{folder_id}"
        if key in self.query_engines:
            del self.query_engines[key]
            logger.debug(f"Invalidated QueryEngine cache for folder {folder_id}")

    def invalidate_all_query_engines(self) -> None:
        """清空全部 QueryEngine cache(embedding / reranker 熱改後必叫 —
        cache 內凍著舊 reranker 參照與舊 embed_model 建的 index)。"""
        n = len(self.query_engines)
        self.query_engines.clear()
        logger.info(f"[RUNTIME] cleared {n} cached QueryEngine(s)")

    # ------------------------------------------------------------------
    # 執行期熱改 rebind(admin 設定面板;src/config/runtime_overrides 寫完
    # ConfigModel 後呼叫)。全部**就地變更** — sub-service 持 ctx 參照,
    # 換整顆 ctx 舊參照會失聯。
    # ------------------------------------------------------------------

    def apply_runtime_changes(self, groups: list[str]) -> None:
        """依 rebind 群組把「已就地改好的 ConfigModel」接到活著的物件上。

        groups 來自 runtime_overrides.rebind_groups_for(applied paths)。
        """
        rag_config = Config.get_config_model().rag
        if "rag.retrieval" in groups:
            self._rebind_retrieval(rag_config)
        if "rag.rerank" in groups:
            self._rebind_reranker(rag_config)
        # llm / contextual / asr 都凍在 indexer 建構鏈 → 重建 indexer(便宜:
        # embed_model 是注入參照,不重載模型)
        if any(g in groups for g in ("rag.llm", "rag.contextual_retrieval", "rag.asr")) \
                and "rag.embedding" not in groups:
            # 沿用現任 indexer 注入的 embed_model(不讀 Settings — 其 getter
            # 在未設時會嘗試建 OpenAI 預設)
            self._rebuild_indexer(rag_config, embed_model=getattr(self.indexer, "_embed_model", None))
        if "rag.embedding" in groups:
            self._rebind_embedding(rag_config)

    def _rebind_retrieval(self, rag_config) -> None:
        """ctx 上凍著的檢索標量(其餘檢索參數本就 request-time 讀 config)。"""
        r = rag_config.retrieval
        am = getattr(r, "auto_merging", None)
        if am is not None:
            self.auto_merging_enabled = bool(am.enabled)
            self.merge_threshold = float(am.merge_threshold)
        self.expand_neighbors = int(getattr(r, "expand_context_neighbors", self.expand_neighbors))
        logger.info(
            f"[RUNTIME] retrieval rebound: auto_merging={self.auto_merging_enabled} "
            f"threshold={self.merge_threshold} expand={self.expand_neighbors}")

    def _rebind_reranker(self, rag_config) -> None:
        """重建 Reranker(關掉 → None;開了 → 新 instance)+ 清 QE cache
        (cache 凍著舊 reranker 參照)。修掉「boot 時 disabled 就永遠 None」。"""
        rerank_config = getattr(rag_config, "rerank", None)
        new_reranker = None
        if rerank_config and rerank_config.enabled:
            from src.domain.rag.reranker import Reranker
            new_reranker = Reranker.from_config(rerank_config)
        self.reranker = new_reranker
        self.invalidate_all_query_engines()
        logger.info(f"[RUNTIME] reranker rebound: {'on' if new_reranker else 'off'}")

    def _rebuild_indexer(self, rag_config, embed_model=None) -> None:
        """重建 HierarchicalIndexer(context generator / asr provider 凍在其
        建構鏈)。呼叫端經 ctx.indexer 逐次取用 → 換欄位即全體生效;
        進行中的索引 job 用舊 indexer 跑完(參照還在),下一個 job 用新的。"""
        from src.domain.rag.asr_provider import create_asr_provider
        from src.domain.rag.context_generator import ContextGenerator

        context_generator = None
        try:
            context_generator = ContextGenerator.from_config(rag_config)
        except Exception as e:
            logger.warning(f"[RUNTIME] ContextGenerator rebuild failed (disabled): {e}")
        asr_cfg = getattr(rag_config, "asr", None)
        self.indexer = HierarchicalIndexer(
            leaf_chunk_size=self.leaf_chunk_size,
            parent_target_tokens=self.parent_target_tokens,
            chunk_overlap=self.chunk_overlap,
            context_generator=context_generator,
            embedding_model_name=self.chunker_tokenizer_name,
            embed_model=embed_model,
            asr_provider=create_asr_provider(asr_cfg),
            asr_enabled=(asr_cfg.enabled if asr_cfg else True),
        )
        logger.info("[RUNTIME] indexer rebuilt (llm/contextual/asr rebound)")

    def _rebind_embedding(self, rag_config) -> None:
        """embedding 熱改(warn 級):重建 provider 鏈 → 換 Settings.embed_model
        → 更新 ctx 欄位 → VSM 換維度並清 store cache → 重建 indexer →
        清 QE cache。舊 folder 的向量與新模型不相容 — 警告由 API 層帶給前端。
        """
        provider_info = self._load_embedding_provider(rag_config)
        self.embedding_provider = provider_info["provider"]
        self.embed_dim = provider_info["embed_dim"]
        self.model_name = provider_info["model_name"]
        self.chunker_tokenizer_name = provider_info["chunker_tokenizer_name"]
        self.vector_store_manager.update_embed_dim(provider_info["embed_dim"])
        self._rebuild_indexer(rag_config, embed_model=provider_info.get("embed_model"))
        self.invalidate_all_query_engines()
        logger.info(
            f"[RUNTIME] embedding rebound: {self.model_name} (dim={self.embed_dim}) — "
            "既有 folder 需重建索引")
