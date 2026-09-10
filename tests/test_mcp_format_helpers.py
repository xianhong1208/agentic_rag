
"""Unit tests for src/fastmcp_tools/agentic_tools.py 的格式化純函式

不依賴 DB / vLLM / 任何外部服務 — 只測 _truncate / _visual_width /
_center_line / _format_search_body 四個純函式。
(agentic_tools 頂層 import 較重(llama_index 系),但不連 DB / 網路,可安全 import。)
跑法:cd agentic_rag && uv run pytest tests/test_mcp_format_helpers.py -v
"""

import pytest

from src.fastmcp_tools.agentic_tools import (
    _BOX_WIDTH,
    _center_line,
    _format_search_body,
    _truncate,
    _visual_width,
)


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

def test_truncate_none_returns_empty_string():
    """輸入 None 應回空字串(TC-mcp-format-01)"""
    assert _truncate(None, 10) == ""


def test_truncate_short_and_exact_length_unchanged():
    """長度 <= max_len 的字串原樣回傳(含剛好等長)(TC-mcp-format-02)"""
    assert _truncate("abc", 10) == "abc"
    assert _truncate("abcdefghij", 10) == "abcdefghij"


def test_truncate_long_string_appends_ellipsis():
    """超長字串截為 max_len-1 字元 + 省略號,總長 == max_len(TC-mcp-format-03)"""
    out = _truncate("abcdefghijk", 10)
    assert out == "abcdefghi…"
    assert len(out) == 10


def test_truncate_coerces_non_string_input():
    """非字串輸入應先 str() 轉換再處理(TC-mcp-format-04)"""
    assert _truncate(12345, 10) == "12345"
    assert _truncate(12345678901, 10) == "123456789…"


# ---------------------------------------------------------------------------
# _visual_width
# ---------------------------------------------------------------------------

def test_visual_width_ascii_one_column_each():
    """ASCII 字元每個算 1 column(TC-mcp-format-05)"""
    assert _visual_width("abc 123") == 7


def test_visual_width_cjk_and_fullwidth_two_columns():
    """CJK 與全形字元每個算 2 columns(TC-mcp-format-06)"""
    assert _visual_width("中文") == 4
    assert _visual_width("Ａ") == 2  # fullwidth A


def test_visual_width_emoji_two_columns():
    """emoji(0x1F000-0x1FFFF / 0x2600-0x27FF)每個算 2 columns(TC-mcp-format-07)"""
    assert _visual_width("😀") == 2
    assert _visual_width("☀") == 2


def test_visual_width_mixed_and_empty():
    """混合字串寬度為逐字元加總,空字串為 0(TC-mcp-format-08)"""
    assert _visual_width("") == 0
    assert _visual_width("a中b") == 4  # 1 + 2 + 1


# ---------------------------------------------------------------------------
# _center_line
# ---------------------------------------------------------------------------

def test_center_line_pads_ascii():
    """ASCII 文字置中:左側補 (width - vw) // 2 個空格,不補右側(TC-mcp-format-09)"""
    assert _center_line("ab", width=10) == "    ab"


def test_center_line_accounts_for_cjk_width():
    """中文寬度以 2 columns 計算後再置中(TC-mcp-format-10)"""
    # "中文" 視覺寬 4,(10-4)//2 = 3 個前導空格
    assert _center_line("中文", width=10) == "   中文"


def test_center_line_wide_text_returned_as_is():
    """視覺寬度 >= width 時原樣回傳不加 padding(TC-mcp-format-11)"""
    text = "x" * 12
    assert _center_line(text, width=10) == text


def test_center_line_default_width_is_box_width():
    """未指定 width 時使用 _BOX_WIDTH 常數置中(TC-mcp-format-12)"""
    out = _center_line("hi")
    assert out == " " * ((_BOX_WIDTH - 2) // 2) + "hi"


# ---------------------------------------------------------------------------
# _format_search_body
# ---------------------------------------------------------------------------

def test_format_search_body_empty_response():
    """空 response 只輸出 Query 與 Results 兩行,無 Roles/Files/Scores/Hint(TC-mcp-format-13)"""
    lines = _format_search_body({})
    assert lines == ['  Query     : ""', "  Results   : 0"]


def test_format_search_body_full_response():
    """完整 response 應輸出 roles 分佈(含 merged)、files 分佈、scores 統計與 hint(TC-mcp-format-14)"""
    response = {
        "query": "營收表現",
        "total_results": 3,
        "results": [
            {"node_role": "leaf", "file_name": "a.pdf", "score": 0.9},
            {"node_role": "parent", "file_name": "a.pdf", "score": 0.8, "merged_from_leaves": 2},
            {"node_role": "expanded", "file_name": "b.txt", "score": 0.7},
        ],
        "_hint": "try a narrower query",
    }
    lines = _format_search_body(response)
    joined = "\n".join(lines)

    assert '  Query     : "營收表現"' in lines
    assert "  Results   : 3" in lines
    assert "leaf:1" in joined
    assert "parent:1(+2 merged)" in joined
    assert "expanded:1" in joined
    assert "a.pdf:2" in joined
    assert "b.txt:1" in joined
    assert "min=0.700  max=0.900  avg=0.800" in joined
    assert "  Hint      : try a narrower query" in lines


def test_format_search_body_more_than_three_files_summarized():
    """超過 3 個檔案時只列 top 3,其餘以 +N more 摘要(TC-mcp-format-15)"""
    response = {
        "query": "q",
        "total_results": 4,
        "results": [
            {"node_role": "leaf", "file_name": f"f{i}.txt", "score": 0.5} for i in range(4)
        ],
    }
    joined = "\n".join(_format_search_body(response))
    assert "+1 more" in joined


def test_format_search_body_long_query_truncated():
    """超長 query 應截斷為 70 字元內加省略號(TC-mcp-format-16)"""
    response = {"query": "q" * 100, "total_results": 0, "results": []}
    lines = _format_search_body(response)
    assert lines[0] == '  Query     : "' + "q" * 69 + '…"'
