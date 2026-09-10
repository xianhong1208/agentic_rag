"""Unit tests for hierarchy.build_hierarchy

不依賴 DB / vLLM / 任何外部服務 — 純邏輯測試。
跑法:cd agentic_rag && uv run pytest tests/test_hierarchy.py -v
對應文件:docs/testing/specs/SPEC-hierarchy.md、docs/testing/test-cases/TC-hierarchy.md
"""

from llama_index.core import Document

from src.domain.rag.hierarchy import build_hierarchy, estimate_tokens


def test_estimate_tokens_chinese():
    """中文字元用 1.5 token/char 估算 (TC-hierarchy-01)"""
    assert estimate_tokens("公司財報") == int(4 * 1.5)


def test_estimate_tokens_english():
    """英文用 0.3 token/char(粗估)(TC-hierarchy-02)"""
    assert estimate_tokens("hello") == int(5 * 0.3)


def test_estimate_tokens_empty():
    """空字串回 0 (TC-hierarchy-03)"""
    assert estimate_tokens("") == 0


def test_build_hierarchy_single_small_doc():
    """1 個小 leaf → 1 個 parent 包 1 個 leaf (TC-hierarchy-04)"""
    leaves = [Document(text="短短的內容", metadata={"file_id": "f1", "file_name": "a.txt"})]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata={"file_id": "f1", "file_name": "a.txt"},
    )

    assert len(leaf_nodes) == 1
    assert len(parent_nodes) == 1

    leaf = leaf_nodes[0]
    parent = parent_nodes[0]

    assert leaf.metadata["node_role"] == "leaf"
    assert leaf.metadata["parent_node_id"] == parent.id_
    assert leaf.metadata["chunk_index"] == 0
    assert leaf.metadata["total_chunks"] == 1

    assert parent.metadata["node_role"] == "parent"
    assert parent.metadata["children_node_ids"] == [leaf.id_]
    assert parent.metadata["chunk_count"] == 1
    assert parent.metadata["children_index_range"] == [0, 0]


def test_build_hierarchy_multiple_leaves_in_one_parent():
    """3 個 leaf,token 總和 < parent_target_tokens → 全部歸一個 parent (TC-hierarchy-05)"""
    leaves = [
        Document(text="leaf one short text"),
        Document(text="leaf two short text"),
        Document(text="leaf three short text"),
    ]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata={"file_id": "f1"},
    )

    assert len(leaf_nodes) == 3
    assert len(parent_nodes) == 1

    parent = parent_nodes[0]
    assert parent.metadata["chunk_count"] == 3
    assert parent.metadata["children_index_range"] == [0, 2]

    # 所有 leaves 指向同一個 parent
    parent_ids = {ln.metadata["parent_node_id"] for ln in leaf_nodes}
    assert parent_ids == {parent.id_}


def test_build_hierarchy_splits_when_token_budget_exceeded():
    """leaves token 總和超過 parent_target → 拆成多 parent (TC-hierarchy-06)"""
    # 每段中文約 30 字 → ~45 token,設 budget=100 → 應該 2 leaves 一組
    leaves = [
        Document(text="這是測試段落數字一" * 5),  # ~45 chars * 1.5 = ~67 tokens
        Document(text="這是測試段落數字二" * 5),
        Document(text="這是測試段落數字三" * 5),
        Document(text="這是測試段落數字四" * 5),
    ]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=100,
        base_metadata={},
    )

    assert len(leaf_nodes) == 4
    assert len(parent_nodes) >= 2  # 至少分 2 組

    # 每個 parent 的 children_index_range 應連續且不重疊
    ranges = [p.metadata["children_index_range"] for p in parent_nodes]
    ranges.sort()
    for i in range(len(ranges) - 1):
        assert ranges[i][1] < ranges[i + 1][0], "Parent ranges should not overlap"


def test_build_hierarchy_parent_text_concatenation():
    """parent.text 應為其 children leaves 的順序 join (TC-hierarchy-07)"""
    leaves = [
        Document(text="第一段"),
        Document(text="第二段"),
        Document(text="第三段"),
    ]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata={},
    )

    parent = parent_nodes[0]
    # parent text = "第一段\n\n第二段\n\n第三段"
    assert "第一段" in parent.text
    assert "第二段" in parent.text
    assert "第三段" in parent.text
    assert parent.text.index("第一段") < parent.text.index("第二段") < parent.text.index("第三段")


def test_build_hierarchy_metadata_propagation():
    """base_metadata 應該複製到每個 leaf 與 parent (TC-hierarchy-08)"""
    leaves = [Document(text="x", metadata={"existing_key": "preserve_me"})]

    base = {"file_id": "f1", "file_name": "report.pdf", "folder_name": "公司"}

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata=base,
    )

    for k, v in base.items():
        assert leaf_nodes[0].metadata[k] == v
        assert parent_nodes[0].metadata[k] == v

    # leaf 自己的 metadata 也保留
    assert leaf_nodes[0].metadata["existing_key"] == "preserve_me"


def test_build_hierarchy_empty_input():
    """空輸入回 ([], []) (TC-hierarchy-09)"""
    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=[],
        parent_target_tokens=1024,
        base_metadata={},
    )
    assert leaf_nodes == []
    assert parent_nodes == []


# ============================================================================
# 缺口補測(metadata 邊界、混合中英文估算等)
# ============================================================================

def test_estimate_tokens_mixed_chinese_english():
    """中英混合各按自己的係數加總後取 int (TC-hierarchy-10)"""
    # "公司ABC" = 2 中文 * 1.5 + 3 英文 * 0.3
    assert estimate_tokens("公司ABC") == int(2 * 1.5 + 3 * 0.3)


def test_estimate_tokens_non_cjk_range_counts_as_other():
    """數字與日文假名不在中文區段('一'~'鿿'),皆以 0.3/char 計 (TC-hierarchy-11)"""
    assert estimate_tokens("12345") == int(5 * 0.3)
    # 平假名 (U+3042 起) < U+4E00,不算中文 → 3 * 0.3 = 0.9 → 0
    assert estimate_tokens("あいう") == 0


def test_build_hierarchy_oversized_leaf_gets_own_parent():
    """每個 leaf 都超過 token 預算 → 一 leaf 一 parent,不會丟棄 (TC-hierarchy-12)"""
    leaves = [
        Document(text="這是超過預算的長段落之一" * 3),
        Document(text="這是超過預算的長段落之二" * 3),
        Document(text="這是超過預算的長段落之三" * 3),
    ]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=10,  # 遠小於任一 leaf
        base_metadata={},
    )

    assert len(leaf_nodes) == 3
    assert len(parent_nodes) == 3
    for parent in parent_nodes:
        assert parent.metadata["chunk_count"] == 1


def test_build_hierarchy_filters_none_metadata_values():
    """leaf 原有 metadata 中值為 None 的 key 不複製進 leaf node (TC-hierarchy-13)"""
    leaves = [Document(text="內容", metadata={"keep_me": "v", "drop_me": None})]

    leaf_nodes, _ = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata={},
    )

    assert leaf_nodes[0].metadata["keep_me"] == "v"
    assert "drop_me" not in leaf_nodes[0].metadata


def test_build_hierarchy_chunk_index_and_total_chunks_across_parents():
    """拆成多 parent 時 chunk_index 仍全域連續,total_chunks 為 leaf 總數 (TC-hierarchy-14)"""
    leaves = [Document(text="這是測試段落內容編號" * 5) for _ in range(4)]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=100,
        base_metadata={},
    )

    assert len(parent_nodes) >= 2  # 確認確實有拆組
    assert [ln.metadata["chunk_index"] for ln in leaf_nodes] == [0, 1, 2, 3]
    assert all(ln.metadata["total_chunks"] == 4 for ln in leaf_nodes)


def test_build_hierarchy_default_base_metadata():
    """不傳 base_metadata(None)也能正常建立 (TC-hierarchy-15)"""
    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=[Document(text="內容")],
        parent_target_tokens=1024,
    )

    assert len(leaf_nodes) == 1
    assert len(parent_nodes) == 1
    assert leaf_nodes[0].metadata["node_role"] == "leaf"


def test_build_hierarchy_leaf_metadata_overrides_base():
    """leaf 自身 metadata 與 base_metadata 同 key 時以 leaf 為準;parent 用 base (TC-hierarchy-16)"""
    leaves = [Document(text="內容", metadata={"file_name": "leaf-level.txt"})]

    leaf_nodes, parent_nodes = build_hierarchy(
        leaf_documents=leaves,
        parent_target_tokens=1024,
        base_metadata={"file_name": "base-level.txt"},
    )

    assert leaf_nodes[0].metadata["file_name"] == "leaf-level.txt"
    assert parent_nodes[0].metadata["file_name"] == "base-level.txt"


def test_build_hierarchy_empty_input():
    """空 leaf 清單:回空 leaves/parents,不炸(flush_group 空群 early-return)。"""
    from src.domain.rag.hierarchy import build_hierarchy
    leaves, parents = build_hierarchy(
        leaf_documents=[], parent_target_tokens=512, base_metadata={})
    assert leaves == [] and parents == []
