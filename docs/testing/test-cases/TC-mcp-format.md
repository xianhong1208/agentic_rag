# TC-mcp-format: MCP Tool Log Summary Formatting Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-mcp-format](../specs/SPEC-mcp-format.md) |
| Test level | Unit (formatting pure functions only) |
| Test script | `tests/test_mcp_format_helpers.py` |

---

## TC-mcp-format-01: _truncate with None input

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `_truncate(None, 10)` |
| **Test steps** | 1. Call |
| **Expected result** | Returns `""` |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_truncate_none_returns_empty_string` |

## TC-mcp-format-02: _truncate returns string unchanged when within length

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `("abc", 10)`, `("abcdefghij", 10)` (exact length) |
| **Test steps** | 1. Call each once |
| **Expected result** | Both returned as-is |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_truncate_short_and_exact_length_unchanged` |

## TC-mcp-format-03: _truncate appends ellipsis when overlong

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `("abcdefghijk", 10)` |
| **Test steps** | 1. Call |
| **Expected result** | Returns `"abcdefghi…"`, total length == 10 |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_truncate_long_string_appends_ellipsis` |

## TC-mcp-format-04: _truncate with non-string input

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `(12345, 10)`, `(12345678901, 10)` |
| **Test steps** | 1. Call each once |
| **Expected result** | `"12345"`; `"123456789…"` (coerce with `str()`, then truncate) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_truncate_coerces_non_string_input` |

## TC-mcp-format-05: _visual_width with ASCII

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"abc 123"` |
| **Test steps** | 1. Call |
| **Expected result** | 7 |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_visual_width_ascii_one_column_each` |

## TC-mcp-format-06: _visual_width with CJK / full-width

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-06 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"中文"`, `"Ａ"` (fullwidth A) |
| **Test steps** | 1. Call each once |
| **Expected result** | 4; 2 |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_visual_width_cjk_and_fullwidth_two_columns` |

## TC-mcp-format-07: _visual_width with emoji

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"😀"` (0x1F600), `"☀"` (0x2600) |
| **Test steps** | 1. Call each once |
| **Expected result** | Both 2 |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_visual_width_emoji_two_columns` |

## TC-mcp-format-08: _visual_width with mixed and empty strings

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `""`, `"a中b"` |
| **Test steps** | 1. Call each once |
| **Expected result** | 0; 4 (1+2+1) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_visual_width_mixed_and_empty` |

## TC-mcp-format-09: _center_line centers ASCII

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `("ab", width=10)` |
| **Test steps** | 1. Call |
| **Expected result** | `"    ab"` (4 spaces of left padding, none on the right) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_center_line_pads_ascii` |

## TC-mcp-format-10: _center_line accounts for CJK width

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-10 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `("中文", width=10)` |
| **Test steps** | 1. Call |
| **Expected result** | `"   中文"` (visual width 4 -> 3 spaces of left padding) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_center_line_accounts_for_cjk_width` |

## TC-mcp-format-11: _center_line returns overwide text as-is

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-11 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `("x"*12, width=10)` |
| **Test steps** | 1. Call |
| **Expected result** | Returned as-is (no padding) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_center_line_wide_text_returned_as_is` |

## TC-mcp-format-12: _center_line default width _BOX_WIDTH

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-12 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `_center_line("hi")` |
| **Test steps** | 1. Call |
| **Expected result** | `" " * ((_BOX_WIDTH - 2) // 2) + "hi"` |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_center_line_default_width_is_box_width` |

## TC-mcp-format-13: _format_search_body with empty response

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-13 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `{}` |
| **Test steps** | 1. Call |
| **Expected result** | Exactly two lines: `  Query     : ""` and `  Results   : 0`; no Roles / Files / Scores / Hint |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_format_search_body_empty_response` |

## TC-mcp-format-14: _format_search_body with a full response

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-14 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 3 results (leaf / parent (2 merged) / expanded, two file names, scores 0.9/0.8/0.7) plus `_hint` |
| **Test steps** | 1. Call<br>2. Check each section |
| **Expected result** | Query verbatim; Results 3; `leaf:1`, `parent:1(+2 merged)`, `expanded:1`; `a.pdf:2`, `b.txt:1`; `min=0.700  max=0.900  avg=0.800`; Hint line present |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_format_search_body_full_response` |

## TC-mcp-format-15: more than 3 files shown as +N more

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-15 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 4 results, each with a distinct file name |
| **Test steps** | 1. Call |
| **Expected result** | Files line includes `+1 more` |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_format_search_body_more_than_three_files_summarized` |

## TC-mcp-format-16: long query truncation

| Field | Content |
|-------|---------|
| **Requirement** | REQ-mcp-format-16 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | query of 100 `q` characters |
| **Test steps** | 1. Call |
| **Expected result** | Query line is 69 `q` characters + `…` (truncated at 70 characters) |
| **Implementation** | `tests/test_mcp_format_helpers.py::test_format_search_body_long_query_truncated` |
