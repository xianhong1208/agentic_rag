# SPEC-mcp-format:MCP 工具 log 摘要格式化


| 項目 | 內容 |
|------|------|
| 模組 | `src/fastmcp_tools/agentic_tools.py`(僅格式化純函式) |
| 對應測試 | `tests/test_mcp_format_helpers.py` |
| 版本 | feat/rag-robustness |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

`agentic_tools.py` 在每次 MCP tool 呼叫結束時輸出一個多行「摘要方框」log。
本規格只涵蓋其中**與 DB / FastMCP 無關的格式化純函式**:

- `_truncate(s, max_len)`:超長字串截斷加省略號。
- `_visual_width(s)`:估算終端機視覺寬度(CJK / 全形 / emoji = 2 columns)。
- `_center_line(text, width=_BOX_WIDTH)`:依視覺寬度置中(僅補左側)。
- `_format_search_body(response)`:search mode 的方框內容
  (Query / Results / Roles 分佈 / Files 分佈 / Scores 統計 / Hint)。

不在範圍:MCP tool 註冊、`handle_search` 等業務函式(依賴 FastMCP + DB,屬整合測試)。
`_format_summary_box` / `_format_list_body` / `_format_read_body` 依賴 log wiring 的組合層,
本輪未納入(可後續擴充)。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-mcp-format-01 | `_truncate(None)` 安全 | 輸入 `None` 回空字串 |
| REQ-mcp-format-02 | 未超長不動 | `len(s) <= max_len` 時原樣回傳(含剛好等長) |
| REQ-mcp-format-03 | 超長截斷 | 回傳 `s[:max_len-1] + "…"`,總長恰為 `max_len` |
| REQ-mcp-format-04 | 非字串輸入容忍 | 先 `str()` 轉換再套用截斷規則 |
| REQ-mcp-format-05 | ASCII 寬度 = 1 | 每個 ASCII 字元計 1 column |
| REQ-mcp-format-06 | CJK / 全形寬度 = 2 | East Asian Width 為 W / F 的字元計 2 columns |
| REQ-mcp-format-07 | emoji 寬度 = 2 | `0x1F000-0x1FFFF`、`0x2600-0x27FF` 範圍計 2 columns |
| REQ-mcp-format-08 | 逐字元加總 | 混合字串為各字元寬度總和;空字串為 0 |
| REQ-mcp-format-09 | 置中補左側 | 前導空格數 = `(width - 視覺寬) // 2`,不補右側 |
| REQ-mcp-format-10 | 置中考慮 CJK 寬度 | 中文以視覺寬 2/字計算 padding |
| REQ-mcp-format-11 | 過寬原樣回傳 | 視覺寬 >= width 時不加 padding |
| REQ-mcp-format-12 | 預設寬度 | 未指定 width 時用 `_BOX_WIDTH`(90) |
| REQ-mcp-format-13 | 空 response 最小輸出 | 只有 Query(空字串)與 Results(0)兩行,無 Roles / Files / Scores / Hint |
| REQ-mcp-format-14 | 完整 search body | 輸出 roles 分佈(parent 含 `+N merged`)、files 分佈、scores min/max/avg(三位小數)、hint |
| REQ-mcp-format-15 | 檔案分佈摘要 | 超過 3 個檔案只列 top 3,其餘以 `+N more` 表示 |
| REQ-mcp-format-16 | 長欄位截斷 | query / hint 以 70 字元截斷加省略號 |

## 3. 非功能需求

- 純函式,不得觸發 DB / 網路 / FastMCP。
- 模組頂層 import 較重(llama_index 系),但**不建立任何連線**,單元測試可直接 import
  (已於 2026-07-09 實測確認 import 安全)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| `_truncate(None, n)` | 回 `""` |
| `_truncate(12345, n)` | 依 `str(12345)` 處理 |
| `_visual_width("")` | 0 |
| `_center_line` 文字比 width 寬 | 原樣回傳 |
| `_format_search_body({})` | 兩行基本輸出,不拋錯 |
| response["results"] 為 `None` | 視為空 list(`or []`) |

## 5. 相依與假設 (Dependencies & Assumptions)

- `_visual_width` 依賴標準庫 `unicodedata`。
- import `src.fastmcp_tools.agentic_tools` 會連帶 import FileDB / rag adapter 等模組
  (僅定義,不連線);若未來頂層 import 加入連線行為,本測試檔須改為延遲 import 或跳過。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
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

(測試腳本欄位省略共同前綴 `tests/test_mcp_format_helpers.py`。)
