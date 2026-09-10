
"""Embedding 批次執行 — retry/backoff(M14 自 hierarchical_indexer 拆出,逐字搬移)。

短暫錯誤(連線/5xx/rate-limit/timeout)用 1→2→4s backoff 重試;永久錯誤直接 raise。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.log import get_api_logger

logger = get_api_logger()

_EMBEDDING_BATCH_SIZE = 50

_EMBED_RETRY_ATTEMPTS = 3
_EMBED_RETRY_BASE_DELAY = 1.0  # seconds; doubles per attempt
_EMBED_RETRYABLE_PATTERNS = (
    "timeout", "timed out",
    "connection", "connectionerror", "remotedisconnected",
    "503", "502", "504", "429", "service unavailable", "bad gateway",
    "rate limit", "too many requests", "server error",
    "network", "broken pipe", "reset by peer",
)


def _is_retryable_embedding_error(exc: BaseException) -> bool:
    """判斷 exception 是否值得 retry(用 class name + message pattern match)。

    embedding client 可能是 httpx / requests / urllib3 / llama_index wrapper,
    isinstance() 抓不準;改用字串 pattern 涵蓋常見 transient 錯誤,免硬綁特定 HTTP 函式庫。

    Args:
        exc: 從 embed 呼叫拋出來的 exception。

    Returns:
        True = transient(可 retry);False = 永久錯(立刻 propagate)。
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return any(p in name or p in msg for p in _EMBED_RETRYABLE_PATTERNS)


async def _embed_batch_with_retry(
    embed_model, batch_texts, file_name: str,
    batch_start: int, batch_end: int, n_leaves: int,
):
    """跑 get_text_embedding_batch,transient 錯誤自動 exponential backoff retry。

    永久錯誤(_is_retryable_embedding_error 不接受的)立刻 re-raise。
    重試之間用 async sleep,不阻塞 event loop。

    Args:
        embed_model: 已配置好的 LlamaIndex 的 embed model。
        batch_texts: 此批要 embed 的文字 list。
        file_name: log 用的檔名 tag。
        batch_start: 此批在所有 leaves 中的起始 index。
        batch_end: 結束 index(exclusive)。
        n_leaves: 整檔總 leaf 數,log 用。

    Returns:
        每筆 text 對應的 embedding vector list。

    Raises:
        最後一次嘗試的 exception(retry 次數用完或不可重試)。
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(_EMBED_RETRY_ATTEMPTS + 1):
        try:
            # sync HTTP call — 丟 thread pool,別卡 event loop(一批 50 chunks
            # 對 vLLM 可到數秒,卡住的話 API/SSE/cancel 全部凍結,heartbeat
            # 斷更會讓 watchdog 誤判 job 死亡)
            result = await asyncio.to_thread(
                embed_model.get_text_embedding_batch, batch_texts
            )
            # M3 修:provider 少回(部分失敗但 HTTP 200 / 回應截斷)時,呼叫端
            # zip 會靜默丟尾端 → NULL embedding 入庫、那些 chunk 永遠檢索不到。
            # 長度必須嚴格相等,不符立即報錯(可重試類)。
            if len(result) != len(batch_texts):
                raise ValueError(
                    f"Embedding batch size mismatch for {file_name}: sent "
                    f"{len(batch_texts)} texts, got {len(result)} embeddings "
                    f"(batch [{batch_start}-{batch_end}))"
                )
            return result
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_embedding_error(exc):
                # Permanent error — no point retrying. Surface immediately.
                raise
            if attempt >= _EMBED_RETRY_ATTEMPTS:
                # Exhausted retry budget — surface the last error.
                raise
            delay = _EMBED_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Embedding batch [{batch_start}-{batch_end}) of {n_leaves} "
                f"({file_name}) transient failure ({type(exc).__name__}: {exc}); "
                f"retry {attempt + 1}/{_EMBED_RETRY_ATTEMPTS} after {delay:.1f}s"
            )
            await asyncio.sleep(delay)
    # Defensive — should be unreachable because the loop above re-raises.
    if last_exc:
        raise last_exc
    raise RuntimeError("embedding retry loop exited without result")
