
"""Reranker — Cross-encoder based result reranking

Uses a vLLM/OpenAI-compatible score API (e.g., BAAI/bge-reranker-v2-m3)
to rerank retrieval results for better precision.

The reranker takes query-chunk pairs and produces relevance scores,
which are more accurate than bi-encoder cosine similarity.
"""

from __future__ import annotations

import os
from typing import List, Optional, TYPE_CHECKING

import httpx
import requests as http_requests
from src.log import get_api_logger

if TYPE_CHECKING:
    from llama_index.core.schema import NodeWithScore

logger = get_api_logger()


class Reranker:
    """Cross-encoder reranker using vLLM score API"""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        top_n: Optional[int] = None,
        score_threshold: float = 0.0,
        timeout: float = 10.0,
        query_template: str = "{text}",
        document_template: str = "{text}",
    ):
        """Initialize reranker

        Args:
            base_url: vLLM/OpenAI-compatible API base URL (e.g., http://localhost:8787)
            model: Model name (e.g., BAAI/bge-reranker-v2-m3)
            api_key: API key (default: not-needed for local vLLM)
            top_n: Keep top N results after reranking (None = keep all)
            score_threshold: Minimum rerank score to keep (default 0.0)
            timeout: HTTP request timeout in seconds
            query_template: 查詢包裝模板,{text} 為佔位符(指令微調型 reranker 用)
            document_template: 文件包裝模板,{text} 為佔位符
        """
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._top_n = top_n
        self._score_threshold = score_threshold
        self._timeout = timeout
        # 用 str.replace 而非 str.format:chunk 內文可能含 {} 大括號,format 會炸
        self._query_template = query_template or "{text}"
        self._document_template = document_template or "{text}"
        # async client lazy 建立(必須在 event loop 內建);連線池跨查詢重用
        self._async_client: Optional[httpx.AsyncClient] = None

        logger.info(
            f"Reranker initialized (model={model}, base_url={base_url}, "
            f"top_n={top_n}, score_threshold={score_threshold})"
        )

    @classmethod
    def from_config(cls, rerank_config) -> Optional["Reranker"]:
        """Create Reranker from config

        Returns:
            Reranker instance, or None if not configured/enabled
        """
        if not rerank_config or not rerank_config.enabled:
            logger.info("Reranker is disabled")
            return None

        try:
            instance = cls(
                base_url=rerank_config.base_url,
                model=rerank_config.model,
                api_key=getattr(rerank_config, 'api_key', 'not-needed') or 'not-needed',
                top_n=getattr(rerank_config, 'top_n', None),
                score_threshold=getattr(rerank_config, 'score_threshold', 0.0),
                query_template=getattr(rerank_config, 'query_template', '{text}'),
                document_template=getattr(rerank_config, 'document_template', '{text}'),
            )
            # 背景 thread 跑連線驗證 — from_config 由 lazy RAGAdapter 在第一個
            # request 的 event loop 上呼叫,sync HTTP(3s timeout)直接跑會把
            # 整個 loop 卡住。驗證只是 log 警告,fire-and-forget 即可。
            import threading
            threading.Thread(
                target=instance.verify_connection,
                daemon=True,
                name="rerank-verify",
            ).start()
            return instance
        except Exception as e:
            logger.error(f"Failed to create Reranker: {e}")
            return None

    def verify_connection(self) -> None:
        """啟動時 best-effort 驗證 rerank 服務有 serve 這個 model 名。

        model 名跟 vllm serve 不一致時 /v1/score 回 404,而 rerank() 對所有
        錯誤都 fallback 原始排序(只有 warning log)— rerank 形同靜默關閉。
        這裡在啟動就大聲報 error,不擋啟動(服務可能晚點才起來)。
        """
        try:
            resp = http_requests.get(
                f"{self._base_url}/v1/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=3.0,
            )
            resp.raise_for_status()
            served = [m.get("id") for m in resp.json().get("data", [])]
            if self._model not in served:
                logger.error(
                    f"Reranker model '{self._model}' is NOT served at "
                    f"{self._base_url} (served: {served}). /v1/score will 404 and "
                    f"rerank will silently fall back to raw retrieval order — "
                    f"fix config rag.rerank.model or the vLLM service."
                )
        except Exception as e:
            logger.warning(
                f"Reranker connectivity check failed ({self._base_url}): {e}. "
                f"If the service stays unreachable, rerank silently falls back "
                f"to raw retrieval order."
            )

    def rerank(
        self,
        query: str,
        nodes: List["NodeWithScore"],
        top_n: Optional[int] = None,
    ) -> List["NodeWithScore"]:
        """Rerank nodes using cross-encoder scores

        Args:
            query: Original query text
            nodes: Retrieved nodes to rerank
            top_n: Override default top_n (optional)

        Returns:
            Reranked list of NodeWithScore (sorted by rerank score, descending)
        """
        if not nodes:
            return nodes

        effective_top_n = top_n or self._top_n

        try:
            # Call score API for each query-chunk pair
            scores = self._get_scores(query, [node.text for node in nodes])

            # Attach rerank scores and sort
            scored_nodes = list(zip(nodes, scores))
            scored_nodes.sort(key=lambda x: x[1], reverse=True)

            # Filter by threshold and top_n
            result = []
            for node, score in scored_nodes:
                if score < self._score_threshold:
                    continue
                # Replace node score with rerank score
                node.score = score
                result.append(node)
                if effective_top_n and len(result) >= effective_top_n:
                    break

            logger.info(
                f"Reranked {len(nodes)} → {len(result)} results "
                f"(top_n={effective_top_n}, threshold={self._score_threshold})"
            )
            return result

        except Exception as e:
            logger.warning(f"Reranking failed, returning original results: {e}")
            return nodes

    async def arerank(
        self,
        query: str,
        nodes: List["NodeWithScore"],
        top_n: Optional[int] = None,
    ) -> List["NodeWithScore"]:
        """rerank() 的 async 版 — 查詢路徑用,scoring HTTP 不佔 event loop。

        降級行為與 sync 版完全一致:任何失敗回原始排序(分數保留)。

        Args:
            query: 原始查詢字串。
            nodes: 待重排的檢索結果。
            top_n: 覆寫預設 top_n(可選)。

        Returns:
            重排後的 NodeWithScore list(分數降冪)。
        """
        if not nodes:
            return nodes

        effective_top_n = top_n or self._top_n

        try:
            scores = await self._aget_scores(query, [node.text for node in nodes])

            scored_nodes = list(zip(nodes, scores))
            scored_nodes.sort(key=lambda x: x[1], reverse=True)

            result = []
            for node, score in scored_nodes:
                if score < self._score_threshold:
                    continue
                node.score = score
                result.append(node)
                if effective_top_n and len(result) >= effective_top_n:
                    break

            logger.info(
                f"Reranked {len(nodes)} → {len(result)} results "
                f"(top_n={effective_top_n}, threshold={self._score_threshold})"
            )
            return result

        except Exception as e:
            logger.warning(f"Reranking failed, returning original results: {e}")
            return nodes

    async def _aget_scores(self, query: str, texts: List[str]) -> List[float]:
        """_get_scores 的 async 版(httpx.AsyncClient,連線池重用)。

        同 sync 版:timeout / 連線錯誤一律讓例外傳播,由 arerank() 統一
        fallback 原始排序 — 絕不回全零分數(會被 threshold 濾成空結果)。
        """
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout)

        response = await self._async_client.post(
            f"{self._base_url}/v1/score",
            json={
                "model": self._model,
                "text_1": self._query_template.replace("{text}", query),
                "text_2": [self._document_template.replace("{text}", t) for t in texts],
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        response.raise_for_status()

        data = response.json()
        score_items = data.get("data", [])
        score_items.sort(key=lambda x: x.get("index", 0))
        return [item.get("score", 0.0) for item in score_items]

    def _get_scores(self, query: str, texts: List[str]) -> List[float]:
        """Call vLLM score API for query-text pairs

        vLLM score API format:
        POST /v1/score
        {"model": "...", "text_1": "query", "text_2": ["doc1", "doc2", ...]}

        Returns:
            List of relevance scores (one per text)
        """
        url = f"{self._base_url}/v1/score"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "model": self._model,
            "text_1": self._query_template.replace("{text}", query),
            "text_2": [self._document_template.replace("{text}", t) for t in texts],
        }

        # ⚠️ timeout / 連線錯誤絕不能在這裡吞掉回全零分數:全零會被上層的
        # score_threshold 全數濾掉 → 查詢回「空結果」,對呼叫端等於「查無資料」
        # 的錯誤答案。讓例外往上傳,rerank() 的 except Exception 統一 fallback
        # 原始檢索排序(分數保留),那才是正確的降級。
        response = http_requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        # vLLM returns: {"data": [{"index": 0, "score": 0.42}, ...]}
        score_items = data.get("data", [])
        # Sort by index to ensure correct ordering
        score_items.sort(key=lambda x: x.get("index", 0))
        scores = [item.get("score", 0.0) for item in score_items]

        return scores
