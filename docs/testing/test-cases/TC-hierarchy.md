# TC-hierarchy:Hierarchical Chunking 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-hierarchy](../specs/SPEC-hierarchy.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_hierarchy.py` |

> TC-hierarchy-01 ~ 09 為既有測試補登記;TC-hierarchy-10 ~ 16 為本次缺口補測。
> 全部案例純邏輯、無 mock。跑法:`cd agentic_rag && uv run pytest tests/test_hierarchy.py -v`

---

## TC-hierarchy-01:estimate_tokens — 中文 1.5 token/char

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"公司財報"`(4 個中文字) |
| **測試步驟** | 1. 呼叫 `estimate_tokens()` |
| **預期結果** | 回 `int(4 * 1.5)` |
| **實作** | `tests/test_hierarchy.py::test_estimate_tokens_chinese` |

## TC-hierarchy-02:estimate_tokens — 英文 0.3 token/char

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"hello"` |
| **測試步驟** | 1. 呼叫 `estimate_tokens()` |
| **預期結果** | 回 `int(5 * 0.3)` |
| **實作** | `tests/test_hierarchy.py::test_estimate_tokens_english` |

## TC-hierarchy-03:estimate_tokens — 空字串

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `""` |
| **測試步驟** | 1. 呼叫 `estimate_tokens()` |
| **預期結果** | 回 `0` |
| **實作** | `tests/test_hierarchy.py::test_estimate_tokens_empty` |

## TC-hierarchy-04:build_hierarchy — 單一小 leaf 的完整 metadata schema

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-06 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 1 個小 Document,`parent_target_tokens=1024`,base_metadata 含 file_id / file_name |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 檢查 leaf 與 parent 的 metadata |
| **預期結果** | 1 leaf + 1 parent;leaf:node_role="leaf"、parent_node_id==parent.id_、chunk_index==0、total_chunks==1;parent:node_role="parent"、children_node_ids==[leaf.id_]、chunk_count==1、children_index_range==[0,0] |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_single_small_doc` |

## TC-hierarchy-05:build_hierarchy — 多 leaf 在預算內歸一 parent

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 3 個短 Document,`parent_target_tokens=1024` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 檢查 parent 數與 leaf 指向 |
| **預期結果** | 3 leaves、1 parent;chunk_count==3、children_index_range==[0,2];所有 leaf 的 parent_node_id 相同 |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_multiple_leaves_in_one_parent` |

## TC-hierarchy-06:build_hierarchy — 超過 token 預算拆多 parent

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-07、REQ-hierarchy-10 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 4 個約 67 token 的中文 Document,`parent_target_tokens=100` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 排序各 parent 的 children_index_range 檢查重疊 |
| **預期結果** | 4 leaves、≥2 parents;ranges 排序後互不重疊(前段尾 < 後段頭) |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_splits_when_token_budget_exceeded` |

## TC-hierarchy-07:build_hierarchy — parent.text 順序拼接

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 3 個 Document(第一段 / 第二段 / 第三段) |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 檢查 parent.text 內容與出現順序 |
| **預期結果** | 三段皆在 parent.text 且 index 依原順序遞增 |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_parent_text_concatenation` |

## TC-hierarchy-08:build_hierarchy — base_metadata 傳播與 leaf 自身 metadata 保留

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | leaf 帶 `{"existing_key": "preserve_me"}`;base 含 file_id / file_name / folder_name |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 逐鍵比對 leaf 與 parent metadata |
| **預期結果** | base 三鍵同時出現在 leaf 與 parent;leaf 的 existing_key 保留 |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_metadata_propagation` |

## TC-hierarchy-09:build_hierarchy — 空輸入

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `leaf_documents=[]` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()` |
| **預期結果** | 回 `([], [])` |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_empty_input` |

## TC-hierarchy-10:estimate_tokens — 中英混合加總

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"公司ABC"`(2 中文 + 3 英文) |
| **測試步驟** | 1. 呼叫 `estimate_tokens()` |
| **預期結果** | 回 `int(2*1.5 + 3*0.3)` |
| **實作** | `tests/test_hierarchy.py::test_estimate_tokens_mixed_chinese_english` |

## TC-hierarchy-11:estimate_tokens — 數字與假名不算中文區段

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"12345"` 與平假名 `"あいう"` |
| **測試步驟** | 1. 分別呼叫 `estimate_tokens()` |
| **預期結果** | `"12345"` → `int(5*0.3)`;`"あいう"` → `0`(假名 < U+4E00,按 0.3/char 計) |
| **實作** | `tests/test_hierarchy.py::test_estimate_tokens_non_cjk_range_counts_as_other` |

## TC-hierarchy-12:build_hierarchy — 單 leaf 超預算自成一 parent

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 3 個各自遠超預算的 Document,`parent_target_tokens=10` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 檢查 parent 數與各自 chunk_count |
| **預期結果** | 3 leaves、3 parents,每個 parent 的 chunk_count==1(不丟棄) |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_oversized_leaf_gets_own_parent` |

## TC-hierarchy-13:build_hierarchy — leaf metadata 中 None 值濾除

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | leaf metadata=`{"keep_me": "v", "drop_me": None}` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 檢查 leaf node metadata |
| **預期結果** | `keep_me == "v"` 保留;`drop_me` 不存在於 leaf metadata |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_filters_none_metadata_values` |

## TC-hierarchy-14:build_hierarchy — 跨 parent 的 chunk_index 連續與 total_chunks

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-10 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 4 個中文 Document(拆組情境),`parent_target_tokens=100` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 確認確實拆為 ≥2 parents<br>3. 收集所有 leaf 的 chunk_index / total_chunks |
| **預期結果** | chunk_index 序列 == `[0, 1, 2, 3]`(全域連續);所有 leaf 的 total_chunks == 4 |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_chunk_index_and_total_chunks_across_parents` |

## TC-hierarchy-15:build_hierarchy — 不傳 base_metadata

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 1 個 Document,省略 base_metadata 參數 |
| **測試步驟** | 1. 呼叫 `build_hierarchy(leaf_documents=[...], parent_target_tokens=1024)` |
| **預期結果** | 正常建出 1 leaf + 1 parent,leaf node_role=="leaf",不拋例外 |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_default_base_metadata` |

## TC-hierarchy-16:build_hierarchy — leaf metadata 覆蓋 base_metadata

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-hierarchy-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | base=`{"file_name": "base-level.txt"}`;leaf metadata=`{"file_name": "leaf-level.txt"}` |
| **測試步驟** | 1. 呼叫 `build_hierarchy()`<br>2. 分別檢查 leaf 與 parent 的 file_name |
| **預期結果** | leaf 的 file_name == `"leaf-level.txt"`(leaf 優先);parent 的 file_name == `"base-level.txt"`(用 base) |
| **實作** | `tests/test_hierarchy.py::test_build_hierarchy_leaf_metadata_overrides_base` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
