# SPEC-mcp-format: MCP Tool Log Summary Formatting


| Item | Content |
|------|---------|
| Module | `src/fastmcp_tools/agentic_tools.py` (formatting pure functions only) |
| Test | `tests/test_mcp_format_helpers.py` |
| Version | feat/rag-robustness |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

At the end of every MCP tool call, `agentic_tools.py` emits a multi-line "summary box" log.
This spec covers only the **formatting pure functions that are independent of the DB and FastMCP**:

- `_truncate(s, max_len)`: truncates an overlong string and appends an ellipsis.
- `_visual_width(s)`: estimates terminal visual width (CJK / full-width / emoji = 2 columns).
- `_center_line(text, width=_BOX_WIDTH)`: centers by visual width (left-padding only).
- `_format_search_body(response)`: box content for search mode
  (Query / Results / Roles distribution / Files distribution / Scores statistics / Hint).

Out of scope: MCP tool registration and business functions such as `handle_search` (which depend on FastMCP + DB and belong to integration testing).
`_format_summary_box` / `_format_list_body` / `_format_read_body` depend on the log-wiring composition layer and are not included in this round (a possible future extension).

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|-------------|-------------|-------------------------------------------|
| REQ-mcp-format-01 | `_truncate(None)` is safe | `None` input returns an empty string |
| REQ-mcp-format-02 | No change when within length | Returned as-is when `len(s) <= max_len` (including exact length) |
| REQ-mcp-format-03 | Overlong truncation | Returns `s[:max_len-1] + "…"`, total length exactly `max_len` |
| REQ-mcp-format-04 | Tolerates non-string input | Applies truncation rules after coercing with `str()` |
| REQ-mcp-format-05 | ASCII width = 1 | Each ASCII character counts as 1 column |
| REQ-mcp-format-06 | CJK / full-width width = 2 | Characters whose East Asian Width is W / F count as 2 columns |
| REQ-mcp-format-07 | Emoji width = 2 | Characters in ranges `0x1F000-0x1FFFF` and `0x2600-0x27FF` count as 2 columns |
| REQ-mcp-format-08 | Per-character sum | A mixed string is the sum of each character's width; an empty string is 0 |
| REQ-mcp-format-09 | Center with left padding | Leading spaces = `(width - visual_width) // 2`; no right padding |
| REQ-mcp-format-10 | Centering accounts for CJK width | Chinese padding is computed as 2 columns per character |
| REQ-mcp-format-11 | Overwide returned as-is | No padding added when visual width >= width |
| REQ-mcp-format-12 | Default width | Uses `_BOX_WIDTH` (90) when width is not specified |
| REQ-mcp-format-13 | Minimal output for empty response | Only two lines, Query (empty string) and Results (0); no Roles / Files / Scores / Hint |
| REQ-mcp-format-14 | Full search body | Outputs roles distribution (parent includes `+N merged`), files distribution, scores min/max/avg (three decimal places), and hint |
| REQ-mcp-format-15 | File distribution summary | Lists only the top 3 files when there are more than 3; the rest shown as `+N more` |
| REQ-mcp-format-16 | Long field truncation | Truncates query / hint at 70 characters with an ellipsis |

## 3. Non-Functional Requirements

- Pure functions; must not trigger DB / network / FastMCP.
- Module-level imports are heavy (llama_index family), but **no connections are established**, so unit tests can import directly (import safety confirmed by test on 2026-07-09).

## 4. Edge Cases and Errors

| Scenario | Expected behavior |
|----------|-------------------|
| `_truncate(None, n)` | Returns `""` |
| `_truncate(12345, n)` | Processed as `str(12345)` |
| `_visual_width("")` | 0 |
| `_center_line` text wider than width | Returned as-is |
| `_format_search_body({})` | Two-line basic output, no exception |
| response["results"] is `None` | Treated as an empty list (`or []`) |

## 5. Dependencies and Assumptions

- `_visual_width` depends on the standard-library `unicodedata`.
- Importing `src.fastmcp_tools.agentic_tools` transitively imports modules such as FileDB and the RAG adapter (definitions only, no connections). If module-level imports ever add connection behavior, this test file must switch to lazy imports or be skipped.

## 6. Traceability

| Requirement | Test Case | Test Script |
|-------------|-----------|-------------|
| REQ-mcp-format-01 | TC-mcp-format-01 | `tests/test_mcp_format_helpers.py::test_truncate_none_returns_empty_string` |
| REQ-mcp-format-02 | TC-mcp-format-02 | `::test_truncate_short_and_exact_length_unchanged` |
| REQ-mcp-format-03 | TC-mcp-format-03 | `::test_truncate_long_string_appends_ellipsis` |
| REQ-mcp-format-04 | TC-mcp-format-04 | `::test_truncate_coerces_non_string_input` |
| REQ-mcp-format-05 | TC-mcp-format-05 | `::test_visual_width_ascii_one_column_each` |
| REQ-mcp-format-06 | TC-mcp-format-06 | `::test_visual_width_cjk_and_fullwidth_two_columns` |
| REQ-mcp-format-07 | TC-mcp-format-07 | `::test_visual_width_emoji_two_columns` |
| REQ-mcp-format-08 | TC-mcp-format-08 | `::test_visual_width_mixed_and_empty` |
| REQ-mcp-format-09 | TC-mcp-format-09 | `::test_center_line_pads_ascii` |
| REQ-mcp-format-10 | TC-mcp-format-10 | `::test_center_line_accounts_for_cjk_width` |
| REQ-mcp-format-11 | TC-mcp-format-11 | `::test_center_line_wide_text_returned_as_is` |
| REQ-mcp-format-12 | TC-mcp-format-12 | `::test_center_line_default_width_is_box_width` |
| REQ-mcp-format-13 | TC-mcp-format-13 | `::test_format_search_body_empty_response` |
| REQ-mcp-format-14 | TC-mcp-format-14 | `::test_format_search_body_full_response` |
| REQ-mcp-format-15 | TC-mcp-format-15 | `::test_format_search_body_more_than_three_files_summarized` |
| REQ-mcp-format-16 | TC-mcp-format-16 | `::test_format_search_body_long_query_truncated` |

(The test-script column omits the common prefix `tests/test_mcp_format_helpers.py`.)
