
"""Domain 層共享 DTO — 修 H5(層次反向依賴)。

這些是純資料型別(pydantic),被 domain / adapter / api 三層共用。原本
散在 adapter.model 與 api.router.response,導致 domain(query_engine /
index_service)反過來 import 外層 → 層次倒置、潛在 import 循環。

改由最內層 domain 定義,外層(adapter.model / api.router.response)re-export
以維持既有 import 路徑不變(向下相容)。方向從此一律向內。
"""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class FileRequest(BaseModel):
    """待索引檔案的 DTO(由 IndexingService 從 File ORM 轉出,供索引流程消費)。"""
    id: UUID
    folder_id: int
    file_name: str
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    # sha256(content). Populated by IndexingService._to_file_request from the
    # File ORM row; consumed by RAGIndexingService for idempotent re-index check.
    content_hash: Optional[str] = None


class RAGChunkMetadata(BaseModel):
    """RAG 檢索結果中單個塊的元數據。"""
    node_id: UUID
    mcp_file_id: str
    file_name: str
    folder_name: Optional[str] = None
    # BL-05 引用溯源(docling 路徑索引的資料才有;舊索引/純文字為 None)
    page: Optional[int] = None
    headings: Optional[List[str]] = None


class RAGSearchResult(BaseModel):
    """RAG 檢索單個結果。"""
    text: str
    score: float
    metadata: RAGChunkMetadata
