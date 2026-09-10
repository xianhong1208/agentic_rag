
"""Hierarchical Indexer — Docling + leaf/parent hierarchy + Contextual Retrieval

跟前一版 flat RAG 的 DocumentIndexer 差別:
  flat RAG: Docling chunks -> SentenceSplitter -> Contextual Retrieval -> embed -> PGVector
  此模組  : Docling chunks -> build_hierarchy(leaves + parents)
                          -> Contextual Retrieval (only on leaves)
                          -> embed (only leaves)
                          -> store BOTH leaves and parents (parents have null embedding)

Parent 為什麼存進 vector_store 但不 embed?
  - Parent 內容 = 多 leaf 順序拼接,本身就是 leaves 的 superset
  - 對 parent 做 vector retrieval 會跟 leaves 重複命中
  - BM25 也類似(parent 文字含所有 leaf 文字)
  - 所以 parent 不參與 ranking,只在 auto-merge 時被 fetch_node 撈出來
  - 存在同一張表是為了利用 PGVector 的 transactional 寫入(原子性)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from llama_index.core import Document, Settings
from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore

from src.log import get_api_logger
from src.domain.rag.docling_loader import resolve_assets_dir
# M14: 檔案載入與切分已拆出(逐字搬移);indexer 組合使用,公開 API 以委派保留
from src.domain.rag.document_loader import DocumentLoader, clean_text
from src.domain.rag.leaf_splitter import LeafSplitter
from src.domain.rag.embedding.batch_exec import (
    _EMBEDDING_BATCH_SIZE,
    _embed_batch_with_retry,
)
from src.domain.rag.hierarchy import build_hierarchy

if TYPE_CHECKING:
    from src.domain.rag.context_generator import ContextGenerator

logger = get_api_logger()


# chunk 級進度回報 signature: (stage, done, total)
# stage ∈ {"contextualizing", "embedding", "writing"}
ChunkProgressCallback = Callable[[str, Optional[int], Optional[int]], None]


class IndexingAbortedError(RuntimeError):
    """should_abort 觸發 — 檔案在索引途中被刪除等原因,中止本檔索引。

    存在性 gate 只能在階段邊界擋(見 adapter/rag_indexing.py 的 gate 1-3);
    contextualizing / embedding 是長階段,靠這個例外做 stage 內的 cooperative
    cancellation。caller(adapter)捕捉後轉成 FileNotFoundError 走既有 abort 路徑。
    """


async def _to_thread_protected(fn, *args):
    """to_thread + 取消保護:cancel 到達時等 thread 跑完才讓取消往上傳。

    task.cancel() 會立刻中斷 ``await to_thread(...)``,但底層 thread 無法中斷、
    會變孤兒繼續跑。對純讀呼叫(embedding)無所謂;對 DB 寫入(pgvector bulk
    insert)不行 — 孤兒寫入會跟 DROP TABLE / 新 job 競速,PGVectorStore.add
    甚至會把剛被 DROP 的表自動建回來。此 helper 保證:取消生效前,寫入
    thread 一定已經結束。

    Args:
        fn: 要在 thread 跑的 sync callable。
        *args: 傳給 fn 的位置參數。

    Returns:
        fn 的回傳值(未被取消時)。

    Raises:
        asyncio.CancelledError: 取消訊號到達 — 但保證 thread 已跑完才 raise。
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, lambda: fn(*args))
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        try:
            await fut  # 等孤兒 thread 收尾;結果丟棄
        except Exception:
            pass  # thread 自己的錯誤此時已無關緊要 — 我們正在被取消
        raise


def _raise_if_aborted(
    should_abort: Optional[Callable[[], bool]],
    file_name: str,
    stage: str,
) -> None:
    """stage 內檢查點:abort 條件成立即中止本檔索引。

    should_abort 由 caller 保證不 raise(adapter 端 probe 自帶 fail-open),
    這裡不再包 try — 真的炸了寧可讓 indexing 失敗浮上來,也不要靜默略過 abort。
    """
    if should_abort and should_abort():
        raise IndexingAbortedError(f"{file_name}: indexing aborted during {stage}")


def _report_chunk_progress(
    cb: Optional[ChunkProgressCallback],
    stage: str,
    done: Optional[int],
    total: Optional[int],
) -> None:
    """進度回報失敗絕不能弄死 indexing——吞掉並 debug log。"""
    if cb is None:
        return
    try:
        cb(stage, done, total)
    except Exception as e:  # pragma: no cover - 防禦性
        logger.debug(f"chunk progress callback failed (ignored): {e}")


# Pre-load NLTK punkt tokenizer (沿用前一版 flat RAG 的做法,multi-thread 安全)
try:
    import nltk
    _assets = resolve_assets_dir()
    if _assets:
        _nltk_data = _assets / "nltk_data"
        if _nltk_data.is_dir() and str(_nltk_data) not in nltk.data.path:
            nltk.data.path.insert(0, str(_nltk_data))
    try:
        import llama_index.core._static as _llama_static
        _static_root = next(iter(_llama_static.__path__), None)
        if _static_root:
            _llama_cache = Path(_static_root) / "nltk_cache"
            if _llama_cache.is_dir() and str(_llama_cache) not in nltk.data.path:
                nltk.data.path.insert(0, str(_llama_cache))
    except Exception:
        pass
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    logger.warning("NLTK punkt_tab not found")
except Exception:
    pass


# Whisper 音檔防禦(anti-hallucination patch / 幻覺過濾 / 靜音裁切)
# 已搬到 audio_defense.py;import 即套用 whisper patch(時序不變 — 本模組
# 一定先於 get_converter() 被 import)。media router 也從那裡 import。
from src.domain.rag.audio_defense import (  # noqa: F401
    _AUDIO_TRIM_EXTENSIONS,
    _filter_whisper_hallucinations,
    _trim_audio_leading_silence,
)



class HierarchicalIndexer:
    """Docling + hierarchy + contextual retrieval 整合索引器"""

    def __init__(
        self,
        leaf_chunk_size: int = 256,
        parent_target_tokens: int = 1024,
        chunk_overlap: int = 50,
        context_generator: Optional["ContextGenerator"] = None,
        embedding_model_name: Optional[str] = None,
        embed_model=None,
        asr_provider=None,
        asr_enabled: bool = True,
    ):
        self._leaf_chunk_size = leaf_chunk_size
        self._parent_target_tokens = parent_target_tokens
        self._chunk_overlap = chunk_overlap
        self._context_generator = context_generator
        self._embedding_model_name = embedding_model_name
        # H6: 注入 embed_model,取代對全域 Settings.embed_model 的讀取。
        # 全域共享 → 同 process 無法多租戶/多設定 embedding、A/B reindex 不可能。
        self._embed_model = embed_model

        # M14: 載入與切分拆為獨立協作者(邏輯逐字搬出,參數一對一傳遞)
        self._document_loader = DocumentLoader(
            leaf_chunk_size=leaf_chunk_size,
            embedding_model_name=embedding_model_name,
            has_context_generator=context_generator is not None,
            asr_provider=asr_provider,   # BL-07: None → default docling-whisper
            asr_enabled=asr_enabled,
        )
        self._leaf_splitter = LeafSplitter(
            leaf_chunk_size=leaf_chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model_name=embedding_model_name,
            has_context_generator=context_generator is not None,
        )

        cr_status = "enabled" if context_generator else "disabled"
        logger.info(
            f"HierarchicalIndexer initialized "
            f"(leaf_size={leaf_chunk_size}, parent_target={parent_target_tokens}, "
            f"contextual_retrieval={cr_status})"
        )

    @staticmethod
    def _clean_text(text: str) -> str:
        # M14: 本體搬至 document_loader.clean_text;保留委派維持既有呼叫點
        return clean_text(text)

    def load_document_from_file(
        self,
        file_path: str,
        file_id: str,
        file_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[ChunkProgressCallback] = None,
    ) -> Document:
        """檔案 → Document(公開 API;adapter 經 ctx.indexer 呼叫)。

        M14: 三路載入邏輯逐字搬至 DocumentLoader.load,此處委派 — 簽名與行為不變。
        """
        return self._document_loader.load(
            file_path=file_path,
            file_id=file_id,
            file_name=file_name,
            metadata=metadata,
            progress_cb=progress_cb,
        )

    def _split_into_leaf_documents(self, document: Document) -> List[Document]:
        # M14: 本體搬至 LeafSplitter.split_into_leaf_documents;委派保留內部呼叫點
        return self._leaf_splitter.split_into_leaf_documents(document)

    async def index_document(
        self,
        document: Document,
        vector_store: PGVectorStore,
        progress_cb: Optional[ChunkProgressCallback] = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, int]:
        """索引一份文件:leaf chunks → contextual prefix → embed → 與 parent 一起存入 PGVector

        Args:
            document: 已 load 的完整 Document。
            vector_store: 目標 PGVector store。
            progress_cb: chunk 級進度回報 ``(stage, done, total)``;None 靜默。
                stage 依序 contextualizing → embedding → writing,done/total 為
                該 stage 已完成 / 全部 chunk 數(讓 job 狀態能顯示「切到多少 ?/?」)。
            should_abort: 回傳 True 即中止本檔(檔案途中被刪)。在
                contextualizing 每 chunk、embedding 每批、writing 前檢查;
                None 不檢查。觸發時 raise IndexingAbortedError。

        Returns:
            {"leaves": N, "parents": M}

        Raises:
            IndexingAbortedError: should_abort 在任一檢查點回傳 True。
        """
        file_name = document.metadata.get("file_name", "unknown")

        # 1. Split to leaf documents
        leaf_docs = self._split_into_leaf_documents(document)
        if not leaf_docs:
            # M4 修:切不出 chunk 不能靜默回 0 — 上層會記成「indexed / 0 chunks」
            # 並寫入 content_hash,之後同檔重索引全被短路,永遠救不回。
            # raise → 上層標 failed(帶原因),使用者看得見、可修檔重試。
            raise ValueError(
                f"No indexable content: {file_name} produced 0 chunks "
                "(empty or whitespace-only document)"
            )
        n_chunks = len(leaf_docs)
        logger.info(f"Chunked {file_name}: {n_chunks} leaf chunks")

        # 2. Apply Contextual Retrieval to leaves (the value-add of the flat-RAG baseline kept)
        if self._context_generator and document.text:
            _raise_if_aborted(should_abort, file_name, "contextualizing")
            _report_chunk_progress(progress_cb, "contextualizing", 0, n_chunks)
            chunk_texts = [d.text for d in leaf_docs]
            contextualized = await self._context_generator.generate_batch(
                chunks=chunk_texts,
                full_document=document.text,
                file_name=file_name,
                on_progress=lambda done, total: _report_chunk_progress(
                    progress_cb, "contextualizing", done, total
                ),
                should_abort=should_abort,
            )
            # generate_batch 遇 abort 只是讓剩餘 chunk 快速 no-op 收尾,
            # 這裡才是真正的中止點——結果直接丟棄,不進 embedding
            _raise_if_aborted(should_abort, file_name, "contextualizing")
            # LLM 回傳的 contextual prefix 也要再過 _clean_text — reasoning model 偶爾會
            # 在輸出中夾控制字元(尤其 reasoning_content fallback 路徑),確保進 PGVector 前安全
            leaf_docs = [
                Document(text=self._clean_text(ct), metadata=ld.metadata.copy())
                for ld, ct in zip(leaf_docs, contextualized)
            ]
            logger.info(f"Contextual prefixes applied to {len(leaf_docs)} leaves ({file_name})")

        # 3. Build hierarchy (leaves + parents)
        base_metadata = {
            k: v for k, v in document.metadata.items()
            if v is not None and not k.startswith("_")
        }
        leaf_nodes, parent_nodes = build_hierarchy(
            leaf_documents=leaf_docs,
            parent_target_tokens=self._parent_target_tokens,
            base_metadata=base_metadata,
        )

        # 4. Embed leaves only (parents stay un-embedded)
        # H6: 優先用注入的 embed_model;未注入才 fallback 全域(向下相容)
        embed_model = self._embed_model if self._embed_model is not None else Settings.embed_model
        if embed_model is None:
            raise RuntimeError("Embedding model not configured (neither injected nor global)")

        leaf_texts = [n.text for n in leaf_nodes]
        n_leaves = len(leaf_texts)
        n_batches = (n_leaves + _EMBEDDING_BATCH_SIZE - 1) // _EMBEDDING_BATCH_SIZE
        _report_chunk_progress(progress_cb, "embedding", 0, n_leaves)
        leaf_embeddings: list = []
        for i in range(n_batches):
            _raise_if_aborted(should_abort, file_name, "embedding")
            batch_start = i * _EMBEDDING_BATCH_SIZE
            batch_end = min(batch_start + _EMBEDDING_BATCH_SIZE, n_leaves)
            batch_texts = leaf_texts[batch_start:batch_end]
            try:
                batch_embeddings = await _embed_batch_with_retry(
                    embed_model, batch_texts, file_name, batch_start, batch_end, n_leaves
                )
            except Exception as exc:
                logger.error(
                    f"Embedding batch failed at leaves [{batch_start}-{batch_end}) "
                    f"of {n_leaves} ({file_name}) after retries: {exc}"
                )
                raise
            leaf_embeddings.extend(batch_embeddings)
            _report_chunk_progress(progress_cb, "embedding", batch_end, n_leaves)
            logger.info(
                f"Embedded batch {i + 1}/{n_batches} "
                f"({batch_start}-{batch_end} of {n_leaves})"
            )
        for n, emb in zip(leaf_nodes, leaf_embeddings):
            n.embedding = emb

        # Parent nodes: 給一個 zero vector(PGVector 不允許 NULL embedding)
        # 配合 query 階段過濾 node_role=leaf,parent 不會干擾 ranking
        embed_dim = len(leaf_embeddings[0]) if leaf_embeddings else 1024
        zero_vec = [0.0] * embed_dim
        for p in parent_nodes:
            p.embedding = zero_vec

        # 5. Bulk insert (leaves + parents in single transaction)
        _raise_if_aborted(should_abort, file_name, "writing")
        _report_chunk_progress(progress_cb, "writing", n_leaves, n_leaves)
        all_nodes: List[TextNode] = list(leaf_nodes) + list(parent_nodes)

        # C2 修:寫入前冪等清掉此 file 的舊 chunks。node id 每次 uuid4 重生、
        # PGVector 不去重 — 任何「上次寫入成功但收尾失敗(timeout cancel /
        # record_index_success 炸 / gate 3)」的重跑,都會把第二份完整向量
        # 疊進同一張表。表不存在(首次索引)時靜默略過。
        file_id_meta = document.metadata.get("file_id")
        if file_id_meta:
            def _purge_stale():
                from src.domain.rag.chunk_lookup import ChunkLookup
                from src.domain.rag.vector_store_manager import VectorStoreManager
                try:
                    table = ChunkLookup._get_table_name(vector_store)
                    removed = VectorStoreManager.delete_chunks_by_file(table, str(file_id_meta))
                    if removed:
                        logger.info(
                            f"[REINDEX_PURGE] removed {removed} stale chunk(s) of "
                            f"file {file_id_meta} before write")
                except Exception as purge_err:  # 表不存在等 — 首次索引屬正常
                    logger.debug(f"stale-chunk purge skipped: {purge_err}")
            await _to_thread_protected(_purge_stale)
        # bulk insert 是 sync SQLAlchemy,大檔數百 nodes 可到數秒 — 下放 thread
        # pool 免卡 loop;用 _to_thread_protected 而非裸 to_thread:這是 DB 寫入,
        # 取消時必須等它寫完,不能留孤兒 insert 跟 DROP TABLE 競速
        await _to_thread_protected(vector_store.add, all_nodes)

        # 6. 確保此 table 有 HNSW vector index
        # vector_store.add() 觸發 PGVectorStore 建 table(若不存在)。
        # 加完馬上補 HNSW,避免要等下次 server 重啟才有 index → 新 folder 立即享有快速 search。
        # 冪等,table 已有 HNSW 時微秒級跳過。
        try:
            from src.domain.rag.chunk_lookup import ChunkLookup
            from src.utils.db_bootstrap import ensure_hnsw_for_table

            table_name = ChunkLookup._get_table_name(vector_store)
            engine = ChunkLookup._get_engine(vector_store)
            created = await asyncio.to_thread(
                ensure_hnsw_for_table, engine, table_name, logger
            )
            if created:
                logger.info(f"✅ HNSW index auto-created for new table: {table_name}")
        except Exception as e:
            # 不致命,沒 HNSW 也能跑(seq scan 慢點而已)
            logger.warning(f"⚠️ HNSW post-index hook failed (not fatal): {e}")

        logger.info(
            f"Indexed {file_name}: {len(leaf_nodes)} leaves + {len(parent_nodes)} parents"
        )
        return {"leaves": len(leaf_nodes), "parents": len(parent_nodes)}
