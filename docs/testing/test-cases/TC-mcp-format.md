# TC-mcp-format:MCP 工具 log 摘要格式化 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-mcp-format](../specs/SPEC-mcp-format.md) |
| 測試層級 | 單元(僅格式化純函式) |
| 測試腳本 | `tests/test_mcp_format_helpers.py` |

---

## TC-mcp-format-01:_truncate 輸入 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `_truncate(None, 10)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 回 `""` |
| **實作** | `tests/test_mcp_format_helpers.py::test_truncate_none_returns_empty_string` |

## TC-mcp-format-02:_truncate 未超長原樣回傳

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `("abc", 10)`、`("abcdefghij", 10)`(剛好等長) |
| **測試步驟** | 1. 各呼叫一次 |
| **預期結果** | 皆原樣回傳 |
| **實作** | `tests/test_mcp_format_helpers.py::test_truncate_short_and_exact_length_unchanged` |

## TC-mcp-format-03:_truncate 超長截斷加省略號

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `("abcdefghijk", 10)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 回 `"abcdefghi…"`,總長 == 10 |
| **實作** | `tests/test_mcp_format_helpers.py::test_truncate_long_string_appends_ellipsis` |

## TC-mcp-format-04:_truncate 非字串輸入

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `(12345, 10)`、`(12345678901, 10)` |
| **測試步驟** | 1. 各呼叫一次 |
| **預期結果** | `"12345"`;`"123456789…"`(先 `str()` 再截斷) |
| **實作** | `tests/test_mcp_format_helpers.py::test_truncate_coerces_non_string_input` |

## TC-mcp-format-05:_visual_width ASCII

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"abc 123"` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 7 |
| **實作** | `tests/test_mcp_format_helpers.py::test_visual_width_ascii_one_column_each` |

## TC-mcp-format-06:_visual_width CJK / 全形

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-06 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"中文"`、`"Ａ"`(fullwidth A) |
| **測試步驟** | 1. 各呼叫一次 |
| **預期結果** | 4;2 |
| **實作** | `tests/test_mcp_format_helpers.py::test_visual_width_cjk_and_fullwidth_two_columns` |

## TC-mcp-format-07:_visual_width emoji

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"😀"`(0x1F600)、`"☀"`(0x2600) |
| **測試步驟** | 1. 各呼叫一次 |
| **預期結果** | 皆為 2 |
| **實作** | `tests/test_mcp_format_helpers.py::test_visual_width_emoji_two_columns` |

## TC-mcp-format-08:_visual_width 混合與空字串

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `""`、`"a中b"` |
| **測試步驟** | 1. 各呼叫一次 |
| **預期結果** | 0;4(1+2+1) |
| **實作** | `tests/test_mcp_format_helpers.py::test_visual_width_mixed_and_empty` |

## TC-mcp-format-09:_center_line ASCII 置中

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `("ab", width=10)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | `"    ab"`(左補 4 空格,不補右側) |
| **實作** | `tests/test_mcp_format_helpers.py::test_center_line_pads_ascii` |

## TC-mcp-format-10:_center_line 中文寬度納入

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-10 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `("中文", width=10)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | `"   中文"`(視覺寬 4 → 左補 3 空格) |
| **實作** | `tests/test_mcp_format_helpers.py::test_center_line_accounts_for_cjk_width` |

## TC-mcp-format-11:_center_line 過寬原樣回傳

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-11 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `("x"*12, width=10)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 原樣回傳(無 padding) |
| **實作** | `tests/test_mcp_format_helpers.py::test_center_line_wide_text_returned_as_is` |

## TC-mcp-format-12:_center_line 預設寬度 _BOX_WIDTH

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-12 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `_center_line("hi")` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | `" " * ((_BOX_WIDTH - 2) // 2) + "hi"` |
| **實作** | `tests/test_mcp_format_helpers.py::test_center_line_default_width_is_box_width` |

## TC-mcp-format-13:_format_search_body 空 response

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-13 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `{}` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 恰為兩行:`  Query     : ""` 與 `  Results   : 0`;無 Roles / Files / Scores / Hint |
| **實作** | `tests/test_mcp_format_helpers.py::test_format_search_body_empty_response` |

## TC-mcp-format-14:_format_search_body 完整 response

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-14 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 3 筆 results(leaf / parent(merged 2) / expanded,兩個檔名,scores 0.9/0.8/0.7)+ `_hint` |
| **測試步驟** | 1. 呼叫<br>2. 檢查各區塊 |
| **預期結果** | Query 原文;Results 3;`leaf:1`、`parent:1(+2 merged)`、`expanded:1`;`a.pdf:2`、`b.txt:1`;`min=0.700  max=0.900  avg=0.800`;Hint 行存在 |
| **實作** | `tests/test_mcp_format_helpers.py::test_format_search_body_full_response` |

## TC-mcp-format-15:檔案超過 3 個顯示 +N more

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-15 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 4 筆 results,檔名各不相同 |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | Files 行含 `+1 more` |
| **實作** | `tests/test_mcp_format_helpers.py::test_format_search_body_more_than_three_files_summarized` |

## TC-mcp-format-16:長 query 截斷

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-mcp-format-16 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | query 為 100 個 `q` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | Query 行為 69 個 `q` + `…`(70 字元截斷) |
| **實作** | `tests/test_mcp_format_helpers.py::test_format_search_body_long_query_truncated` |
