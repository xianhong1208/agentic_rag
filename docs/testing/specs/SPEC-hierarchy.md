# SPEC-hierarchy:Hierarchical Chunking(leaf → parent 聚合)


| 項目 | 內容 |
|------|------|
| 模組 | `src/domain/rag/hierarchy.py` |
| 對應測試 | `tests/test_hierarchy.py` |
| 版本 | v1.0(feat/rag-robustness;補登記既有 9 個測試 + 缺口補測) |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

把 Docling / SentenceSplitter 產出的 leaf chunks 依 token 預算後合成 parent 節點
(`build_hierarchy`),並提供粗估 token 的 `estimate_tokens`。parent 不重切,只是 leaf 的
有序 join + metadata 連結,供 auto-merge 檢索時 lookup。本 spec 只涵蓋純邏輯;
PGVector 存取與 auto-merge 檢索屬整合測試範疇。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-hierarchy-01 | `estimate_tokens` 對中文區段('一' U+4E00 ~ '鿿' U+9FFF)字元以 1.5 token/char 估算 | `estimate_tokens("公司財報") == int(4 * 1.5)` |
| REQ-hierarchy-02 | 非中文區段字元(英文、數字、假名等)以 0.3 token/char 估算 | `"hello"` → `int(5*0.3)`;`"12345"` → `int(5*0.3)`;平假名不算中文 |
| REQ-hierarchy-03 | 空字串回 0 | `estimate_tokens("") == 0` |
| REQ-hierarchy-04 | 中英混合逐字元按各自係數加總後取 int | `"公司ABC"` → `int(2*1.5 + 3*0.3)` |
| REQ-hierarchy-05 | `build_hierarchy` 空輸入回 `([], [])` | 空 list → 兩個空 list |
| REQ-hierarchy-06 | leaf / parent metadata schema:leaf 含 node_role="leaf"、chunk_index、parent_node_id、total_chunks;parent 含 node_role="parent"、children_node_ids、children_index_range(inclusive)、chunk_count | 單一 leaf 案例中所有欄位值可精確斷言,且 leaf.parent_node_id == parent.id_、parent.children_node_ids == [leaf.id_] |
| REQ-hierarchy-07 | token 預算分組:累計超過 parent_target_tokens 即封組;總和在預算內全歸一 parent;單一 leaf 超過預算時自成一組(不丟棄) | 小輸入 → 1 parent;超預算輸入 → ≥2 parent 且 range 不重疊;每 leaf 皆超預算 → 一 leaf 一 parent |
| REQ-hierarchy-08 | parent.text 為其 children leaves 依序以 `"\n\n"` join | 三段文字在 parent.text 中依原順序出現 |
| REQ-hierarchy-09 | metadata 合併規則:base_metadata 複製到每個 leaf 與 parent;leaf 自身 metadata 保留且值為 None 的 key 濾除;同 key 時 leaf metadata 覆蓋 base;base_metadata 可不傳(None → {}) | 各案例中 leaf / parent metadata 內容可精確斷言 |
| REQ-hierarchy-10 | 跨 parent 一致性:chunk_index 全域連續(0-based)、total_chunks 為 leaf 總數、各 parent 的 children_index_range 連續且互不重疊 | 拆成多 parent 時 chunk_index == [0..n-1]、total_chunks 一致、ranges 排序後前段尾 < 後段頭 |

## 3. 非功能需求 (Non-Functional)

- 純函式,無 DB / 網路 / GPU 相依;node id 用 uuid4,測試以關聯性(id 互指)斷言而非固定值。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| `leaf_documents=[]` | 回 `([], [])`,不拋例外 |
| `base_metadata=None`(未傳) | 視為 `{}`,正常建立 |
| 單一 leaf 即超過 token 預算 | 仍自成一 parent,不丟棄、不再切 |
| leaf metadata 值為 None | 該 key 不複製進 leaf node |
| leaf metadata 與 base_metadata 同 key | leaf 值優先(parent 仍用 base 值) |

## 5. 相依與假設 (Dependencies & Assumptions)

- `llama_index.core.Document` / `TextNode` — 僅作資料容器,無需 mock。
- `src.log.get_api_logger` — 僅寫 log。
- 備註(記錄於案):`estimate_tokens` docstring 寫「英文 1 word ≈ 1.3 token」,
  實作為 0.3 token/char(逐字元),兩者敘述不一致;測試以實作行為為準。

## 6. 可追溯性矩陣 (Traceability)

> TC-hierarchy-01 ~ 09 為既有測試補登記;TC-hierarchy-10 ~ 16 為本次缺口補測。

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-hierarchy-01 | TC-hierarchy-01 | `tests/test_hierarchy.py::test_estimate_tokens_chinese` |
| REQ-hierarchy-02 | TC-hierarchy-02、TC-hierarchy-11 | `tests/test_hierarchy.py::test_estimate_tokens_english`、`::test_estimate_tokens_non_cjk_range_counts_as_other` |
| REQ-hierarchy-03 | TC-hierarchy-03 | `tests/test_hierarchy.py::test_estimate_tokens_empty` |
| REQ-hierarchy-04 | TC-hierarchy-10 | `tests/test_hierarchy.py::test_estimate_tokens_mixed_chinese_english` |
| REQ-hierarchy-05 | TC-hierarchy-09 | `tests/test_hierarchy.py::test_build_hierarchy_empty_input` |
| REQ-hierarchy-06 | TC-hierarchy-04 | `tests/test_hierarchy.py::test_build_hierarchy_single_small_doc` |
| REQ-hierarchy-07 | TC-hierarchy-05、TC-hierarchy-06、TC-hierarchy-12 | `tests/test_hierarchy.py::test_build_hierarchy_multiple_leaves_in_one_parent`、`::test_build_hierarchy_splits_when_token_budget_exceeded`、`::test_build_hierarchy_oversized_leaf_gets_own_parent` |
| REQ-hierarchy-08 | TC-hierarchy-07 | `tests/test_hierarchy.py::test_build_hierarchy_parent_text_concatenation` |
| REQ-hierarchy-09 | TC-hierarchy-08、TC-hierarchy-13、TC-hierarchy-15、TC-hierarchy-16 | `tests/test_hierarchy.py::test_build_hierarchy_metadata_propagation`、`::test_build_hierarchy_filters_none_metadata_values`、`::test_build_hierarchy_default_base_metadata`、`::test_build_hierarchy_leaf_metadata_overrides_base` |
| REQ-hierarchy-10 | TC-hierarchy-06、TC-hierarchy-14 | `tests/test_hierarchy.py::test_build_hierarchy_splits_when_token_budget_exceeded`、`::test_build_hierarchy_chunk_index_and_total_chunks_across_parents` |
