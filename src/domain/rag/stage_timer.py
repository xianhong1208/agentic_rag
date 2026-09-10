
"""StageTimer — 單檔索引的階段耗時計(loading / contextualizing / embedding / writing)

回答「每個階段花了多久」:掛在 progress_cb 鏈上當觀察者 — 進度回報本來就
會在每次 stage 切換時流過這裡,第一次看到新 stage 就把上一個 stage 的碼表
關掉。不開 thread、不改變轉發語意(原樣 pass-through 給 inner cb)。

產出去向:adapter 在單檔結束時呼叫 finish(),結果併入該檔的 file_timings
entry(stage_ms 欄位)→ 隨 IndexJobs 持久化,GET /index/jobs 直接可查:

    "file_timings": [{
        "file_name": "大文件.pdf", "total_ms": 183200.5,
        "stage_ms": {"loading": 92100.3, "contextualizing": 61400.8,
                     "embedding": 22300.1, "writing": 7400.2}, ...
    }]

同一 stage 斷續出現(理論上不會,防禦性)時間會累加;keepalive 補發的
心跳是「同 stage 重複回報」,不觸發切換,不影響計時。
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional


class StageTimer:
    """progress_cb 觀察者:量測每個 stage 的 wall-clock 耗時。

    Usage:
        timer = StageTimer(inner=existing_cb)
        ...把 timer 當 progress_cb 傳進 indexer...
        stage_ms = timer.finish()   # {"loading": 92100.3, ...}
    """

    def __init__(self, inner: Optional[Callable] = None):
        self._inner = inner
        self._current: Optional[str] = None
        self._started_at: Optional[float] = None
        self._elapsed: Dict[str, float] = {}

    def __call__(self, stage: str, done, total) -> None:
        now = time.perf_counter()
        if stage != self._current:
            self._close(now)
            self._current = stage
            self._started_at = now
        if self._inner is not None:
            # 轉發失敗不影響計時,也不往上炸(與 _report_chunk_progress 同紀律)
            try:
                self._inner(stage, done, total)
            except Exception:
                pass

    def _close(self, now: float) -> None:
        if self._current is not None and self._started_at is not None:
            self._elapsed[self._current] = (
                self._elapsed.get(self._current, 0.0) + (now - self._started_at)
            )

    def finish(self) -> Dict[str, float]:
        """關掉進行中的碼表,回傳 {stage: 毫秒}。可重複呼叫(冪等)。"""
        self._close(time.perf_counter())
        self._current = None
        self._started_at = None
        return {k: round(v * 1000, 1) for k, v in self._elapsed.items()}
