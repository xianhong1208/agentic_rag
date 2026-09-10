
"""PrefixedEmbedding — 為 e5 系模型自動加 query/passage 前綴的包裝層。

e5(multilingual-e5-*)的訓練契約:查詢文字前綴 ``query: ``、文件文字前綴
``passage: ``,不加前綴檢索品質顯著劣化。bge 系不需要前綴。

llama_index 的 BaseEmbedding 本來就把「查詢」與「文件」分成不同方法
(_get_query_embedding vs _get_text_embedding),所以這裡各自攔截加前綴即可,
上游(indexer / query engine)完全不用改。前綴皆空字串時 rag_context 不會套用
本包裝,bge 路徑零額外開銷。
"""

from typing import Any, List

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr


class PrefixedEmbedding(BaseEmbedding):
    """包住任意 BaseEmbedding,查詢/文件各加固定前綴。"""

    _inner: Any = PrivateAttr()
    _query_prefix: str = PrivateAttr()
    _passage_prefix: str = PrivateAttr()

    def __init__(self, inner: BaseEmbedding, query_prefix: str = "", passage_prefix: str = "", **kwargs):
        super().__init__(
            model_name=inner.model_name,
            embed_batch_size=inner.embed_batch_size,
            **kwargs,
        )
        self._inner = inner
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix

    # ── 查詢側 ──────────────────────────────────────────────
    def _get_query_embedding(self, query: str) -> List[float]:
        return self._inner._get_query_embedding(self._query_prefix + query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await self._inner._aget_query_embedding(self._query_prefix + query)

    # ── 文件側 ──────────────────────────────────────────────
    def _get_text_embedding(self, text: str) -> List[float]:
        return self._inner._get_text_embedding(self._passage_prefix + text)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._inner._get_text_embeddings([self._passage_prefix + t for t in texts])

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return await self._inner._aget_text_embedding(self._passage_prefix + text)

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await self._inner._aget_text_embeddings([self._passage_prefix + t for t in texts])