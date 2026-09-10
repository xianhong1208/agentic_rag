
"""Context 生成中途 abort 的 LLM 斷線回歸測試

契約:檔案在 contextualizing 階段被刪除時,除了「後續 chunk 不再呼叫
LLM」(既有檢查點),abort watcher 還要**立刻 close client** 把飛行中的
請求連線切斷 — vLLM 偵測 disconnect 即中止生成,GPU 不為註定被丟棄的
結果繼續燒。
"""

import threading
import time

from src.domain.rag.context_generator import ContextGenerator


class _FakeLLMClient:
    """chat.completions.create 會阻塞到 close() 為止的假 client。

    模擬「飛行中的 LLM 請求」:沒有 abort 斷線的話,每個請求都要等
    _HANG_SECONDS 才回來;close() 一呼叫立刻拋錯(連線被切)。
    """

    _HANG_SECONDS = 30.0

    def __init__(self):
        self.closed = threading.Event()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        if self.closed.wait(timeout=self._HANG_SECONDS):
            raise RuntimeError("connection closed by abort watcher")
        raise AssertionError("fake LLM 請求跑滿 30s — abort 沒有斷線")

    def close(self):
        self.closed.set()


async def test_abort_closes_client_and_cuts_inflight_calls(mocker):
    """abort flag 立起後,飛行中的 LLM 呼叫必須被斷線快速收場(TC-ctx-abort-01)"""
    fake = _FakeLLMClient()
    gen = ContextGenerator.__new__(ContextGenerator)  # 不走 __init__(免 config)
    gen._llm_config = None
    gen._model = "fake"
    gen._max_context_length = 150
    gen._max_concurrent = 4
    gen._max_doc_chars = 1000
    gen._max_tokens = 64
    gen._reasoning_effort = None
    mocker.patch.object(ContextGenerator, "_create_sync_client", return_value=fake)

    aborted = threading.Event()

    def should_abort():
        return aborted.is_set()

    import asyncio

    async def flip_abort_soon():
        await asyncio.sleep(0.3)   # 讓幾個請求先起飛
        aborted.set()

    t0 = time.monotonic()
    results, _ = await asyncio.gather(
        gen.generate_batch(
            chunks=["段落一", "段落二", "段落三", "段落四"],
            full_document="測試文件全文",
            file_name="deleted.docx",
            should_abort=should_abort,
        ),
        flip_abort_soon(),
    )
    elapsed = time.monotonic() - t0

    assert fake.closed.is_set(), "abort 後 client 必須被 close"
    # 沒斷線的話至少卡 30s;斷線後全部快速收場(fallback prefix)
    assert elapsed < 5.0, f"abort 斷線失效,耗時 {elapsed:.1f}s"
    assert len(results) == 4, "每個 chunk 都要有結果(fallback),不能缺"
