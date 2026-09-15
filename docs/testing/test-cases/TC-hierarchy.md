# TC-hierarchy: Hierarchical Chunking Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-hierarchy](../specs/SPEC-hierarchy.md) |
| Test level | Unit |
| Test script | `tests/test_hierarchy.py` |

> TC-hierarchy-01 to 09 register existing tests; TC-hierarchy-10 to 16 fill remaining coverage gaps.
> All cases are pure logic with no mocks. Run with: `cd agentic_rag && uv run pytest tests/test_hierarchy.py -v`

---

## TC-hierarchy-01: estimate_tokens — Chinese at 1.5 token/char

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"公司財報"` (4 Chinese characters) |
| **Test steps** | 1. Call `estimate_tokens()` |
| **Expected result** | Returns `int(4 * 1.5)` |
| **Implementation** | `tests/test_hierarchy.py::test_estimate_tokens_chinese` |

## TC-hierarchy-02: estimate_tokens — English at 0.3 token/char

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"hello"` |
| **Test steps** | 1. Call `estimate_tokens()` |
| **Expected result** | Returns `int(5 * 0.3)` |
| **Implementation** | `tests/test_hierarchy.py::test_estimate_tokens_english` |

## TC-hierarchy-03: estimate_tokens — empty string

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `""` |
| **Test steps** | 1. Call `estimate_tokens()` |
| **Expected result** | Returns `0` |
| **Implementation** | `tests/test_hierarchy.py::test_estimate_tokens_empty` |

## TC-hierarchy-04: build_hierarchy — full metadata schema for a single small leaf

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-06 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 1 small Document, `parent_target_tokens=1024`, base_metadata with file_id / file_name |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the leaf and parent metadata |
| **Expected result** | 1 leaf + 1 parent; leaf: node_role="leaf", parent_node_id==parent.id_, chunk_index==0, total_chunks==1; parent: node_role="parent", children_node_ids==[leaf.id_], chunk_count==1, children_index_range==[0,0] |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_single_small_doc` |

## TC-hierarchy-05: build_hierarchy — multiple leaves grouped into one parent within budget

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 3 short Documents, `parent_target_tokens=1024` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the parent count and the leaves' pointers |
| **Expected result** | 3 leaves, 1 parent; chunk_count==3, children_index_range==[0,2]; all leaves have the same parent_node_id |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_multiple_leaves_in_one_parent` |

## TC-hierarchy-06: build_hierarchy — split into multiple parents when the token budget is exceeded

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-07, REQ-hierarchy-10 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 4 Chinese Documents of about 67 tokens each, `parent_target_tokens=100` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Sort each parent's children_index_range and check for overlap |
| **Expected result** | 4 leaves, >=2 parents; sorted ranges do not overlap (the end of an earlier range < the start of the next) |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_splits_when_token_budget_exceeded` |

## TC-hierarchy-07: build_hierarchy — parent.text concatenated in order

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 3 Documents (第一段 / 第二段 / 第三段) |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the content and order of parent.text |
| **Expected result** | All three segments are in parent.text, with index increasing in the original order |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_parent_text_concatenation` |

## TC-hierarchy-08: build_hierarchy — base_metadata propagation and leaf's own metadata preserved

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | leaf carries `{"existing_key": "preserve_me"}`; base has file_id / file_name / folder_name |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Compare leaf and parent metadata key by key |
| **Expected result** | All three base keys appear in both leaf and parent; the leaf's existing_key is preserved |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_metadata_propagation` |

## TC-hierarchy-09: build_hierarchy — empty input

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `leaf_documents=[]` |
| **Test steps** | 1. Call `build_hierarchy()` |
| **Expected result** | Returns `([], [])` |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_empty_input` |

## TC-hierarchy-10: estimate_tokens — mixed Chinese-English sum

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"公司ABC"` (2 Chinese + 3 English) |
| **Test steps** | 1. Call `estimate_tokens()` |
| **Expected result** | Returns `int(2*1.5 + 3*0.3)` |
| **Implementation** | `tests/test_hierarchy.py::test_estimate_tokens_mixed_chinese_english` |

## TC-hierarchy-11: estimate_tokens — digits and kana do not count as Chinese ranges

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"12345"` and hiragana `"あいう"` |
| **Test steps** | 1. Call `estimate_tokens()` on each |
| **Expected result** | `"12345"` -> `int(5*0.3)`; `"あいう"` -> `0` (kana < U+4E00, counted at 0.3/char) |
| **Implementation** | `tests/test_hierarchy.py::test_estimate_tokens_non_cjk_range_counts_as_other` |

## TC-hierarchy-12: build_hierarchy — an oversized single leaf becomes its own parent

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 3 Documents each far exceeding the budget, `parent_target_tokens=10` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the parent count and each chunk_count |
| **Expected result** | 3 leaves, 3 parents, each parent's chunk_count==1 (nothing dropped) |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_oversized_leaf_gets_own_parent` |

## TC-hierarchy-13: build_hierarchy — None values in leaf metadata are filtered out

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | leaf metadata=`{"keep_me": "v", "drop_me": None}` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the leaf node metadata |
| **Expected result** | `keep_me == "v"` is preserved; `drop_me` is absent from the leaf metadata |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_filters_none_metadata_values` |

## TC-hierarchy-14: build_hierarchy — contiguous chunk_index across parents and total_chunks

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-10 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 4 Chinese Documents (split scenario), `parent_target_tokens=100` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Confirm it actually splits into >=2 parents<br>3. Collect chunk_index / total_chunks of all leaves |
| **Expected result** | The chunk_index sequence == `[0, 1, 2, 3]` (globally contiguous); total_chunks == 4 for all leaves |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_chunk_index_and_total_chunks_across_parents` |

## TC-hierarchy-15: build_hierarchy — without passing base_metadata

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | 1 Document, omitting the base_metadata parameter |
| **Test steps** | 1. Call `build_hierarchy(leaf_documents=[...], parent_target_tokens=1024)` |
| **Expected result** | Builds 1 leaf + 1 parent normally, leaf node_role=="leaf", no exception raised |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_default_base_metadata` |

## TC-hierarchy-16: build_hierarchy — leaf metadata overrides base_metadata

| Field | Content |
|-------|---------|
| **Requirement** | REQ-hierarchy-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | base=`{"file_name": "base-level.txt"}`; leaf metadata=`{"file_name": "leaf-level.txt"}` |
| **Test steps** | 1. Call `build_hierarchy()`<br>2. Check the file_name of the leaf and the parent separately |
| **Expected result** | The leaf's file_name == `"leaf-level.txt"` (leaf takes precedence); the parent's file_name == `"base-level.txt"` (uses base) |
| **Implementation** | `tests/test_hierarchy.py::test_build_hierarchy_leaf_metadata_overrides_base` |

> Authoring principles: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
