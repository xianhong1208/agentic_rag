
"""Hierarchical chunking — 把 leaf chunks 聚合成 parent

設計取捨:
- LlamaIndex 內建的 HierarchicalNodeParser 對純文字效果好,但會繞過你的 Docling 結構化 chunk。
  Docling 已經產出「表格保留 / 標題對齊」的好 chunk,丟掉太可惜。
- 因此這裡採用後合成策略:Docling 先做 leaf,再用 token 預算把 leaf 聚合成 parent。
  Parent 不重新切,只是 leaf 的有序 join + metadata 連結。

Metadata schema (寫入 LlamaIndex Node.metadata,不動 PGVector schema):
    leaf:
        node_role:        "leaf"
        chunk_index:      順序索引(同 file 內 0-based)
        parent_node_id:   所屬 parent 的 node_id
        total_chunks:     此 file 的 leaf 總數

    parent:
        node_role:        "parent"
        children_node_ids: list[str]
        children_index_range: [start, end]   # inclusive
        chunk_count:      len(children_node_ids)
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from uuid import uuid4

from llama_index.core import Document
from llama_index.core.schema import TextNode

from src.log import get_api_logger

logger = get_api_logger()


def estimate_tokens(text: str) -> int:
    """粗估文字 token 數(中文 1 char ≈ 1.5 token,英文 1 word ≈ 1.3 token)。

    用在 hierarchy 預算決策;要精確請改用 tiktoken。

    Args:
        text: 要估的文字。

    Returns:
        粗估 token 數(int)。
    """
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.3)


def build_hierarchy(
    leaf_documents: List[Document],
    parent_target_tokens: int = 1024,
    base_metadata: Optional[dict] = None,
) -> Tuple[List[TextNode], List[TextNode]]:
    """把 leaf documents 聚合成 (leaf_nodes, parent_nodes) 兩階層

    Args:
        leaf_documents: Docling/SentenceSplitter 切好的 leaf chunks(已含結構化內容)
        parent_target_tokens: 每個 parent 累積到此 token 量就封頂(預設對齊 config.hierarchy_sizes[0])
        base_metadata: 共用 metadata(file_id, file_name 等),會合併進每個 node

    Returns:
        (leaf_nodes, parent_nodes) — 兩個 list
        - leaf_nodes 才會被 embed + 存進 vector store
        - parent_nodes 也會被存(無 embedding,純文本快取),供 auto-merge 時 lookup

    為什麼 parent 也存:當 auto-merge 觸發時,需要快速取得 parent 的完整文字。
    存在 PGVector 同一表(用 metadata.node_role 區分)比另開表簡單,且查詢更快。
    """
    if not leaf_documents:
        return [], []

    base_metadata = base_metadata or {}
    leaf_nodes: List[TextNode] = []
    parent_nodes: List[TextNode] = []

    # Group leaves into parents by token budget
    current_group: List[Tuple[int, Document]] = []  # [(leaf_index, doc), ...]
    current_tokens = 0

    def flush_group():
        """把累積的 leaf group 變成一個 parent + 對應的 leaf nodes"""
        if not current_group:
            return

        parent_id = str(uuid4())
        leaf_ids = []
        leaf_texts = []
        index_start = current_group[0][0]
        index_end = current_group[-1][0]

        # Create leaf nodes with parent linkage
        for leaf_idx, leaf_doc in current_group:
            leaf_id = str(uuid4())
            leaf_meta = {
                **base_metadata,
                **{k: v for k, v in leaf_doc.metadata.items() if v is not None},
                "node_role": "leaf",
                "chunk_index": leaf_idx,
                "parent_node_id": parent_id,
                "total_chunks": len(leaf_documents),
            }
            leaf_node = TextNode(
                id_=leaf_id,
                text=leaf_doc.text,
                metadata=leaf_meta,
            )
            leaf_nodes.append(leaf_node)
            leaf_ids.append(leaf_id)
            leaf_texts.append(leaf_doc.text)

        # Create parent node — text 是 children 順序拼接
        # 用「\n\n」分隔,保留結構可讀性
        parent_text = "\n\n".join(leaf_texts)
        parent_meta = {
            **base_metadata,
            "node_role": "parent",
            "children_node_ids": leaf_ids,
            "children_index_range": [index_start, index_end],
            "chunk_count": len(leaf_ids),
        }
        parent_node = TextNode(
            id_=parent_id,
            text=parent_text,
            metadata=parent_meta,
        )
        parent_nodes.append(parent_node)

    # Walk leaves, accumulate until budget hit
    for i, leaf_doc in enumerate(leaf_documents):
        tokens = estimate_tokens(leaf_doc.text)

        # If adding this leaf would exceed budget AND we have at least 1 already → flush
        if current_tokens + tokens > parent_target_tokens and current_group:
            flush_group()
            current_group = []
            current_tokens = 0

        current_group.append((i, leaf_doc))
        current_tokens += tokens

    # Final flush
    flush_group()

    logger.info(
        f"Hierarchy built: {len(leaf_documents)} leaves → "
        f"{len(parent_nodes)} parents (avg {len(leaf_documents)/max(len(parent_nodes),1):.1f} leaves/parent)"
    )

    return leaf_nodes, parent_nodes
