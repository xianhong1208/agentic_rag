
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from uuid import UUID


class FileConfigData(BaseModel):
    """文件配置信息模型"""
    id: UUID
    folder_id: int
    file_name: str
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    upload_time: datetime
    updated_time: datetime

class FileDownloadData(BaseModel):
    """文件下載專用模型，包含文件內容"""
    id: UUID
    folder_id: int
    file_name: str
    file_content: bytes
    file_size: int
    mime_type: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    upload_time: datetime
    updated_time: datetime



class FolderConfigData(BaseModel):
    """資料夾信息模型"""
    id: int
    name: str
    description: Optional[str] = None
    file_count: int = 0
    total_size: int = 0
    user_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# H5: 定義下沉到 domain(src/domain/rag/dto.py);此處 re-export 維持既有 import 路徑。
from src.domain.rag.dto import RAGChunkMetadata, RAGSearchResult  # noqa: E402,F401


class RAGQueryResult(BaseModel):
    """RAG 查詢響應模型"""
    query: str
    results: List[RAGSearchResult]
    total_results: int
    retrieval_time_ms: Optional[float] = None


class FileIndexData(BaseModel):
    """文件索引信息模型"""
    file_id: UUID
    file_name: str
    folder_id: int
    num_chunks: int
    indexed_at: datetime
    status: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int


