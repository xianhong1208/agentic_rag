
"""StageTimer 單元測試 — 每個索引階段的耗時量測

契約:掛在 progress_cb 鏈上觀察 stage 切換;同 stage 重複回報(keepalive
心跳)不影響計時;finish() 收斂進行中的碼表並回傳 {stage: 毫秒}。
"""

import time

from src.domain.rag.stage_timer import StageTimer


def test_measures_each_stage_duration():
    """各 stage 依切換點分段計時(TC-stage-timer-01)"""
    t = StageTimer()
    t("loading", None, None)
    time.sleep(0.10)
    t("contextualizing", 0, 50)
    time.sleep(0.05)
    t("embedding", 0, 50)
    time.sleep(0.02)
    out = t.finish()

    assert set(out) == {"loading", "contextualizing", "embedding"}
    assert out["loading"] >= 90, out          # ~100ms
    assert out["contextualizing"] >= 40, out  # ~50ms
    assert out["embedding"] >= 15, out        # ~20ms
    # 各段不應吃到別段的時間(上限抓寬鬆防 CI 抖動)
    assert out["embedding"] < 100, out


def test_same_stage_repeats_do_not_reset_clock():
    """同 stage 重複回報(進度 tick / keepalive 心跳)不重置碼表(TC-stage-timer-02)"""
    t = StageTimer()
    t("embedding", 0, 100)
    time.sleep(0.03)
    t("embedding", 50, 100)   # 進度 tick
    t("embedding", 50, 100)   # keepalive 重發
    time.sleep(0.03)
    out = t.finish()
    assert out["embedding"] >= 50, out  # 兩段合計 ~60ms,沒被 tick 重置


def test_forwards_to_inner_cb_and_swallows_inner_errors():
    """原樣轉發給 inner cb;inner 炸掉不影響計時(TC-stage-timer-03)"""
    seen = []

    def inner(stage, done, total):
        seen.append((stage, done, total))
        raise RuntimeError("inner 故意炸")

    t = StageTimer(inner=inner)
    t("loading", 1, 3)
    t("loading", 2, 3)
    out = t.finish()
    assert seen == [("loading", 1, 3), ("loading", 2, 3)]
    assert "loading" in out


def test_finish_is_idempotent():
    """finish() 可重複呼叫,結果一致(TC-stage-timer-04)"""
    t = StageTimer()
    t("writing", 10, 10)
    time.sleep(0.02)
    first = t.finish()
    second = t.finish()
    assert first == second


def test_interleaved_stage_accumulates():
    """stage 斷續出現時時間累加(防禦性)(TC-stage-timer-05)"""
    t = StageTimer()
    t("loading", None, None)
    time.sleep(0.02)
    t("contextualizing", 0, 10)
    time.sleep(0.02)
    t("loading", None, None)   # 理論上不會,防禦性
    time.sleep(0.02)
    out = t.finish()
    assert out["loading"] >= 35, out  # 兩段 loading 累加 ~40ms
