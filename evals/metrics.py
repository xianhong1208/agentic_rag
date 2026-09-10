
"""評測指標純函式(BL-01 檢索 / BL-02 ASR 共用)。

零外部依賴、零 I/O — 由 tests/test_eval_metrics.py 鎖行為,
跑分腳本(scripts/run_rag_eval.py / run_asr_eval.py)呼叫。
"""

from __future__ import annotations

import re
from typing import List, Sequence

# ---------------------------------------------------------------------------
# CER — 字元錯誤率(ASR)
# ---------------------------------------------------------------------------

_NORMALIZE_STRIP = re.compile(r"[\s,,。.、;;::!!??\"'「」『』()()\-—·…]+")


def _normalize(text: str) -> str:
    """去空白與常見標點 — ASR 輸出常無標點,不因標點差異罰分。"""
    return _NORMALIZE_STRIP.sub("", text)


def cer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """字元錯誤率 = levenshtein(ref, hyp) / len(ref)。

    Args:
        reference: 人工校對的 golden transcript。
        hypothesis: ASR 輸出。
        normalize: 去空白/標點後再比(預設開)。

    Returns:
        0.0(完全一致)~ 上不封頂(插入過多時可 >1);ref 空而 hyp 非空回 1.0。
    """
    if normalize:
        reference, hypothesis = _normalize(reference), _normalize(hypothesis)
    if not reference:
        return 0.0 if not hypothesis else 1.0

    # 標準 DP levenshtein(字元級,兩列滾動)
    prev = list(range(len(hypothesis) + 1))
    for i, rc in enumerate(reference, 1):
        curr = [i]
        for j, hc in enumerate(hypothesis, 1):
            curr.append(min(
                prev[j] + 1,          # deletion
                curr[j - 1] + 1,      # insertion
                prev[j - 1] + (rc != hc),  # substitution
            ))
        prev = curr
    return prev[-1] / len(reference)


# ---------------------------------------------------------------------------
# 簡體字比率(啟發式)— 驗「輸出是否繁中」(FireRedASR 輸出簡體的驗收指標)
# ---------------------------------------------------------------------------

# 「簡繁不同形」的高頻簡體字樣本(啟發式;非窮舉 — 夠判斷輸出語系傾向。
# ⚠️ 只放簡體獨有字形 — 簡繁同形字(系/中/近/余 等)絕不能進來,否則繁中誤判)
_SIMPLIFIED_CHARS = set(
    "会议记录检统计设进军对开关买卖东车书长门问间闻风飞马鸟龙点级红绿"
    "语说读写听讲话让认识谁请谢边这远运动过还货质银钱铁钟错难题华万"
    "与专业丛严个临为丽举义乐习乡产亲亿仅从仓仪们价众优传伤体办务"
)


def simplified_char_ratio(text: str) -> float:
    """CJK 字元中屬於「簡體獨有形」樣本集的比率。

    啟發式:>0 即混入簡體;繁中輸出驗收要求 ≈0。無 CJK 字元回 0.0。
    """
    cjk = [c for c in text if "一" <= c <= "鿿"]
    if not cjk:
        return 0.0
    return sum(1 for c in cjk if c in _SIMPLIFIED_CHARS) / len(cjk)


# ---------------------------------------------------------------------------
# 檢索指標(RAG)
# ---------------------------------------------------------------------------

def recall_at_k(retrieved: Sequence[str], expected: List[str], k: int) -> float:
    """top-k 內命中的期望項比例(期望多項時為部分分)。"""
    if not expected:
        return 1.0
    top = set(retrieved[:k])
    return sum(1 for e in expected if e in top) / len(expected)


def mrr(retrieved: Sequence[str], expected: List[str]) -> float:
    """Mean Reciprocal Rank(單查詢版):第一個命中位置的倒數;無命中 0。"""
    exp = set(expected)
    for i, r in enumerate(retrieved, 1):
        if r in exp:
            return 1.0 / i
    return 0.0
