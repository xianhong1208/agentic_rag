# SPEC-hierarchy: Hierarchical Chunking (leaf → parent aggregation)


| Item | Content |
|------|------|
| Module | `src/domain/rag/hierarchy.py` |
| Test | `tests/test_hierarchy.py` |
| Version | v1.0 (feat/rag-robustness; registers the 9 existing tests + fills coverage gaps) |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Aggregates the leaf chunks produced by Docling / SentenceSplitter into parent nodes under a token budget
(`build_hierarchy`), and provides `estimate_tokens` for a rough token estimate. A parent does not re-split; it is simply an
ordered join of its leaves plus metadata links, for lookup during auto-merge retrieval. This spec covers only the pure logic;
PGVector access and auto-merge retrieval belong to integration testing.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-hierarchy-01 | `estimate_tokens` estimates characters in the Chinese range ('一' U+4E00 ~ '鿿' U+9FFF) at 1.5 token/char | `estimate_tokens("公司財報") == int(4 * 1.5)` |
| REQ-hierarchy-02 | Non-Chinese-range characters (English, digits, kana, etc.) are estimated at 0.3 token/char | `"hello"` → `int(5*0.3)`; `"12345"` → `int(5*0.3)`; hiragana is not counted as Chinese |
| REQ-hierarchy-03 | An empty string returns 0 | `estimate_tokens("") == 0` |
| REQ-hierarchy-04 | Mixed Chinese/English sums per-character by each coefficient, then takes int | `"公司ABC"` → `int(2*1.5 + 3*0.3)` |
| REQ-hierarchy-05 | `build_hierarchy` on empty input returns `([], [])` | empty list → two empty lists |
| REQ-hierarchy-06 | leaf / parent metadata schema: a leaf has node_role="leaf", chunk_index, parent_node_id, total_chunks; a parent has node_role="parent", children_node_ids, children_index_range (inclusive), chunk_count | In the single-leaf case every field value is precisely assertable, and leaf.parent_node_id == parent.id_, parent.children_node_ids == [leaf.id_] |
| REQ-hierarchy-07 | Token-budget grouping: a group is sealed once the running total exceeds parent_target_tokens; a total within budget all maps to one parent; a single leaf exceeding the budget forms its own group (not discarded) | small input → 1 parent; over-budget input → ≥2 parents with non-overlapping ranges; every leaf over budget → one leaf per parent |
| REQ-hierarchy-08 | parent.text is its children leaves joined in order with `"\n\n"` | three text segments appear in parent.text in their original order |
| REQ-hierarchy-09 | Metadata merge rules: base_metadata is copied to every leaf and parent; a leaf's own metadata is retained, with keys whose value is None filtered out; on a key collision, leaf metadata overrides base; base_metadata is optional (None → {}) | In each case the leaf / parent metadata content is precisely assertable |
| REQ-hierarchy-10 | Cross-parent consistency: chunk_index is globally contiguous (0-based), total_chunks is the total leaf count, and each parent's children_index_range is contiguous and mutually non-overlapping | when split across multiple parents, chunk_index == [0..n-1], total_chunks is consistent, and once ranges are sorted the tail of the earlier < the head of the later |

## 3. Non-Functional Requirements

- Pure functions, with no DB / network / GPU dependency; node ids use uuid4, and tests assert relationships (ids pointing at each other) rather than fixed values.

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| `leaf_documents=[]` | returns `([], [])`, no exception |
| `base_metadata=None` (omitted) | treated as `{}`, builds normally |
| a single leaf already exceeds the token budget | still forms its own parent, not discarded, not re-split |
| a leaf metadata value is None | that key is not copied into the leaf node |
| a leaf metadata key collides with base_metadata | the leaf value wins (the parent still uses the base value) |

## 5. Dependencies & Assumptions

- `llama_index.core.Document` / `TextNode` — used only as data containers, no mock needed.
- `src.log.get_api_logger` — logging only.
- Note (recorded on file): the `estimate_tokens` docstring says "1 English word ≈ 1.3 token", while the implementation uses 0.3 token/char (per-character); the two descriptions are inconsistent, and the tests follow the implementation's behavior.

## 6. Traceability

> TC-hierarchy-01 ~ 09 register existing tests; TC-hierarchy-10 ~ 16 are this round's gap-filling tests.

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-hierarchy-01 | TC-hierarchy-01 | `tests/test_hierarchy.py::test_estimate_tokens_chinese` |
| REQ-hierarchy-02 | TC-hierarchy-02, TC-hierarchy-11 | `tests/test_hierarchy.py::test_estimate_tokens_english`, `::test_estimate_tokens_non_cjk_range_counts_as_other` |
| REQ-hierarchy-03 | TC-hierarchy-03 | `tests/test_hierarchy.py::test_estimate_tokens_empty` |
| REQ-hierarchy-04 | TC-hierarchy-10 | `tests/test_hierarchy.py::test_estimate_tokens_mixed_chinese_english` |
| REQ-hierarchy-05 | TC-hierarchy-09 | `tests/test_hierarchy.py::test_build_hierarchy_empty_input` |
| REQ-hierarchy-06 | TC-hierarchy-04 | `tests/test_hierarchy.py::test_build_hierarchy_single_small_doc` |
| REQ-hierarchy-07 | TC-hierarchy-05, TC-hierarchy-06, TC-hierarchy-12 | `tests/test_hierarchy.py::test_build_hierarchy_multiple_leaves_in_one_parent`, `::test_build_hierarchy_splits_when_token_budget_exceeded`, `::test_build_hierarchy_oversized_leaf_gets_own_parent` |
| REQ-hierarchy-08 | TC-hierarchy-07 | `tests/test_hierarchy.py::test_build_hierarchy_parent_text_concatenation` |
| REQ-hierarchy-09 | TC-hierarchy-08, TC-hierarchy-13, TC-hierarchy-15, TC-hierarchy-16 | `tests/test_hierarchy.py::test_build_hierarchy_metadata_propagation`, `::test_build_hierarchy_filters_none_metadata_values`, `::test_build_hierarchy_default_base_metadata`, `::test_build_hierarchy_leaf_metadata_overrides_base` |
| REQ-hierarchy-10 | TC-hierarchy-06, TC-hierarchy-14 | `tests/test_hierarchy.py::test_build_hierarchy_splits_when_token_budget_exceeded`, `::test_build_hierarchy_chunk_index_and_total_chunks_across_parents` |
