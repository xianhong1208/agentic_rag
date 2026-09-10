
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

class UpdateFileRequest(BaseModel):
    """更新文件請求模型"""
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class BatchDeleteRequest(BaseModel):
    """批次刪除請求模型"""
    file_ids: Optional[List[UUID]] = None
    delete_all: bool = False


class CreateFolderRequest(BaseModel):
    """在指定空間創建資料夾請求模型"""
    name: str
    description: Optional[str] = None

class UpdateFolderRequest(BaseModel):
    """更新資料夾請求模型"""
    name: Optional[str] = None
    description: Optional[str] = None

# RAG Response Models


class IndexRequest(BaseModel):
    """索引文件請求模型。

    兩個欄位都允許 ``None`` — 為 None 時 indexing 流程會從
    ``config.rag.chunking`` 讀預設(leaf_chunk_size / chunk_overlap)。
    """
    chunk_size: Optional[int] = Field(
        default=None,
        ge=100,
        le=2000,
        # examples 影響 Swagger "Example Value";不傳此欄時 indexing 用 config 預設,
        # 所以 example 對齊 config 當前 hierarchy_sizes[1] (leaf_chunk_size=256)。
        examples=[256],
        description=(
            "分塊大小(字元數)。未提供時使用 `config.rag.chunking.hierarchy_sizes[1]`"
            "(當前預設 = 256)。"
        ),
    )
    chunk_overlap: Optional[int] = Field(
        default=None,
        ge=0,
        le=500,
        examples=[50],
        description=(
            "分塊重疊大小。未提供時使用 `config.rag.chunking.chunk_overlap`"
            "(當前預設 = 50)。注意:應 < chunk_size。"
        ),
    )

    model_config = {
        # 提供兩個範例:空 body (用 config 預設,最常見) + 顯式覆寫
        "json_schema_extra": {
            "examples": [
                {},
                {"chunk_size": 256, "chunk_overlap": 50},
            ]
        }
    }


class QueryRequest(BaseModel):
    """查詢請求模型

    所有 retrieval-tuning 欄位都允許 ``None``;為 None 時 API 端會從
    `config.yaml` 的 `rag.retrieval.*` 預設值讀取,確保 API 行為跟 server
    配置保持一致。如此 ops 改了 config 就會立刻影響 API 預設行為,
    不會再有「Pydantic 寫死的值跟 config 不同步」的問題。
    """
    query: str = Field(..., examples=["這份文件的核心結論是什麼?"], description="查詢字符串")
    folder_name: str = Field(..., examples=["my-folder"], description="資料夾名稱")
    # 以下 4 個調參欄位 — example 數值對齊 config.rag.retrieval.default_*。
    # 不傳就拿 config 值,所以 example 就用 config 當前值是最直觀的。
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        examples=[10],
        description="返回前 K 個結果。None = 用 `config.rag.retrieval.default_top_k`(當前 = 10)。",
    )
    similarity_cutoff: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        examples=[0.25],
        description=(
            "相似度閾值。None = 用 `config.rag.retrieval.default_similarity_cutoff`(當前 = 0.25)。"
            "Reranker enabled 時此值會被忽略,改由 `rerank.score_threshold` 過濾。"
        ),
    )
    sparse_top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        examples=[12],
        description="稀疏(關鍵字)檢索候選數量。None = 用 `config.rag.retrieval.default_sparse_top_k`(當前 = 12)。",
    )
    hybrid_alpha: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        examples=[0.75],
        description="混合檢索中向量與關鍵字分數的權重 (0=純 BM25, 1=純向量)。None = 用 `config.rag.retrieval.default_hybrid_alpha`(當前 = 0.75)。",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                # 最常見用法 — 只傳必填,4 個 retrieval 參數全用 config 預設
                {"query": "這份文件的核心結論是什麼?", "folder_name": "my-folder"},
                # 顯式覆寫(對齊 config 預設值,方便 copy-edit)
                {
                    "query": "這份文件的核心結論是什麼?",
                    "folder_name": "my-folder",
                    "top_k": 10,
                    "similarity_cutoff": 0.25,
                    "sparse_top_k": 12,
                    "hybrid_alpha": 0.75,
                },
            ]
        }
    }

# H5: 定義下沉到 domain(src/domain/rag/dto.py);此處 re-export 維持既有 import 路徑。
from src.domain.rag.dto import FileRequest  # noqa: E402,F401

class IndexDocumentResponse(BaseModel):
    """Single file indexing response model"""
    file_id: str = Field(..., description="File ID")
    index_id: str = Field(..., description="Index ID")
    num_chunks: int = Field(..., description="Number of chunks created")
    status: str = Field(..., description="Index status (indexed, already_indexed, failed)")
    indexed_at: str = Field(..., description="Index timestamp in ISO format")
    message: str = Field(..., description="Response message")


class FileIndexResult(BaseModel):
    """File index result model (for batch operations)"""
    file_id: str = Field(..., description="File ID")
    filename: str = Field(..., description="Filename")
    status: str = Field(..., description="Processing status (success, failed, skipped)")
    message: str = Field(..., description="Processing message")
    num_chunks: Optional[int] = Field(None, description="Number of chunks (on success)")


class IndexFolderResponse(BaseModel):
    """Folder batch indexing response model"""
    folder_id: int = Field(..., description="Folder ID")
    total_files: int = Field(..., description="Total number of files")
    successful: int = Field(..., description="Number of successfully indexed files")
    failed: int = Field(..., description="Number of failed indexing operations")
    skipped: int = Field(..., description="Number of skipped files")
    results: List[FileIndexResult] = Field(default_factory=list, description="Detailed results list")
    message: str = Field(..., description="Batch processing summary message")


class DeleteFolderIndexResponse(BaseModel):
    """Folder batch delete index response model"""
    folder_id: int = Field(..., description="Folder ID")
    total_files: int = Field(..., description="Total number of files")
    successful: int = Field(..., description="Number of successfully deleted indexes")
    failed: int = Field(..., description="Number of failed delete operations")
    results: List[FileIndexResult] = Field(default_factory=list, description="Detailed results list")
    message: str = Field(..., description="Batch processing summary message")


class IndexJobStatusResponse(BaseModel):
    """Background indexing job status response"""

    job_id: str = Field(..., description="Job identifier")
    folder_id: int = Field(..., description="Target folder ID")
    status: str = Field(
        ...,
        description="Job status (pending, running, succeeded, partial_success, failed, cancelled)",
    )
    total_files: int = Field(..., description="Total number of files scheduled")
    processed_files: int = Field(..., description="Number of files processed so far")
    current_index: int = Field(..., description="Current file position (1-based)")
    current_file_id: Optional[str] = Field(None, description="Current file ID being processed")
    current_file_name: Optional[str] = Field(None, description="Current file name being processed")
    current_file_stage: Optional[str] = Field(
        None,
        description="Current file chunk-level stage: loading / contextualizing / embedding / writing "
                    "(None between files or after the file completes)",
    )
    current_file_chunks_done: Optional[int] = Field(
        None, description="Chunks completed in the current stage of the current file"
    )
    current_file_chunks_total: Optional[int] = Field(
        None, description="Total leaf chunks of the current file (chunk progress done/total)"
    )
    current_file_eta_seconds: Optional[int] = Field(
        None,
        description="Estimated seconds until the current stage finishes, extrapolated from "
                    "the observed chunk rate (None while calibrating or between stages)",
    )
    eta_seconds: Optional[int] = Field(
        None,
        description="Rough estimated seconds until the whole job finishes "
                    "(avg completed-file duration × remaining files; None until the first file completes)",
    )
    last_file_status: Optional[str] = Field(None, description="Status of the last processed file")
    last_message: Optional[str] = Field(None, description="Message from the last processed file")
    message: Optional[str] = Field(None, description="Job level message")
    error: Optional[str] = Field(None, description="Error details when the job fails")
    skip_existing: bool = Field(default=True, description="Whether existing indexes were skipped")
    started_at: str = Field(..., description="Job start timestamp (ISO 8601 format)")
    completed_at: Optional[str] = Field(None, description="Job completion timestamp (ISO 8601 format)")
    last_updated_at: Optional[str] = Field(
        None,
        description="Last heartbeat timestamp (A3 watchdog uses this to detect staleness)",
    )
    result_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Final indexing summary when job succeeds"
    )
    # per-file timings; empty until at least one file has been processed
    file_timings: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-file timing audit: [{file_id, file_name, status, total_ms, load_ms, index_ms, chunks}, ...]"
                    " — chunks = 該檔切出的 leaf chunk 數(持久紀錄)",
    )
    # Part 3 — file_ids this job will/did process (populated for file-scoped jobs only)
    scope_file_ids: List[str] = Field(
        default_factory=list,
        description="Files this job will process (only populated for start_indexing_files calls)",
    )


class FileIndexStatusResponse(BaseModel):
    """Per-file index status response (Part 3).

    Returned by GET /api/rag/file/{file_id}/index/status. The ``status`` field
    is one of: indexed, indexing, queued, failed, not_indexed.
    """

    file_id: str = Field(..., description="File ID")
    file_name: str = Field(..., description="File name")
    status: str = Field(..., description="indexed / indexing / queued / failed / not_indexed")
    num_chunks: Optional[int] = Field(None, description="Chunk count (when indexed)")
    indexed_at: Optional[str] = Field(None, description="ISO timestamp when last indexed")
    job_id: Optional[str] = Field(None, description="Active job id (when indexing/queued)")
    progress: Optional[Dict[str, int]] = Field(
        None, description="Progress snapshot {current_index, total_files}"
    )
    error: Optional[str] = Field(None, description="Last error message (when failed)")


class IndexingMetadata(BaseModel):
    """Auto-indexing metadata response (for file upload endpoints)"""
    auto_index_enabled: bool = Field(..., description="Whether auto-indexing was triggered")
    job_id: Optional[str] = Field(None, description="Background indexing job ID (if auto_index_enabled)")
    status: Optional[str] = Field(None, description="Job status (pending, running, succeeded, failed)")
    total_files: Optional[int] = Field(None, description="Total files scheduled for indexing")
    message: str = Field(..., description="Indexing status message")


# =============================================================================
# 共用 envelope + error 模型 — 給 endpoint 用 response_model= / responses= 標註
# 規則:任何成功回應一律走 {"data": ..., "message": ...},錯誤走 {"detail": ...}
# =============================================================================


class ErrorDetailResponse(BaseModel):
    """錯誤 envelope ─ FastAPI HTTPException 的標準格式。

    middleware 對 DomainException 也會輸出此形狀。
    用於 endpoint 的 responses={404: {"model": ErrorDetailResponse}} 標註。
    """
    detail: str = Field(..., examples=["folder 99999 not found"], description="人類可讀的錯誤訊息")


# ---- Folder resource ----


class FolderResource(BaseModel):
    """資料夾資源 (對應 db.db.Folder ORM row)。

    `model_config.from_attributes=True` 讓 FastAPI 能直接接受 adapter 回的
    ``FolderConfigData`` 或 SQLAlchemy ORM Folder(不必先 dict 化)。
    ``created_at``/``updated_at`` 收 ``datetime`` ─ Pydantic v2 序列化時自動
    產生 ISO 字串給 client(client 端體感不變)。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["my-folder"])
    description: Optional[str] = Field(None)
    file_count: Optional[int] = Field(None, description="此 folder 內檔案數")
    total_size: Optional[int] = Field(None, description="bytes,所有檔總和")
    user_token: Optional[str] = Field(None, description="擁有者 token(只回給擁有者自己)")
    vector_table_uuid: Optional[str] = Field(None, description="vector store table 對應的 UUID")
    created_at: Optional[datetime] = Field(None, description="序列化為 ISO 字串")
    updated_at: Optional[datetime] = Field(None, description="序列化為 ISO 字串")


class FolderDeletedResponse(BaseModel):
    """DELETE /api/folders/{id} 成功回應。"""
    detail: str = Field(..., examples=["Folder 1 deleted successfully"])


# ---- File resource ----


class FileResource(BaseModel):
    """檔案資源 (對應 db.db.File ORM row)。

    跟 FolderResource 同樣的處理:`from_attributes=True` 才能直接接收 ORM /
    BaseModel 物件;``id`` 收 ``UUID`` 然後序列化為字串;``upload_time`` /
    ``updated_time`` 收 ``datetime``,Pydantic v2 序列化時自動轉 ISO 字串。
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., examples=["bdb19c41-0012-4400-9172-67c8dbd08d56"])
    folder_id: int = Field(...)
    file_name: str = Field(..., examples=["report.pdf"])
    file_path: str = Field(..., description="storage/{token}/{folder}/{uuid} 內部路徑,download endpoint 才會解析成實體檔")
    file_size: int = Field(..., description="bytes")
    mime_type: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    tags: Optional[List[str]] = Field(None)
    content_hash: Optional[str] = Field(None, description="sha256 hex(D3 idempotency 用)")
    upload_time: Optional[datetime] = Field(None, description="序列化為 ISO 字串")
    updated_time: Optional[datetime] = Field(None, description="序列化為 ISO 字串")


class FileUploadResponse(BaseModel):
    """POST /api/folders/{folder_id}/file 回應 ─ 含 file_info + auto-index 觸發狀態。"""
    file_info: FileResource
    indexing: IndexingMetadata
    message: str = Field(..., examples=["File uploaded successfully"])


class FileDeletedResponse(BaseModel):
    """DELETE /api/folders/{folder_id}/files/{file_id} 成功回應。"""
    success: bool = Field(..., examples=[True])
    message: str = Field(..., examples=["File deleted successfully"])


# ---- Cache / health ----


class HealthStatusResponse(BaseModel):
    """GET /health 基本回應。"""
    status: str = Field(..., examples=["healthy"])
    timestamp: str = Field(..., description="ISO timestamp")


class CacheClearResponse(BaseModel):
    """POST /health/cache/clear 回應。"""
    status: str = Field(..., examples=["success"])
    message: str = Field(...)
    items_removed: int = Field(...)
    timestamp: str = Field(...)


# ---- Index lifecycle envelopes ----


class IndexJobEnvelope(BaseModel):
    """指 indexing-job-related endpoints 的 envelope: {data: IndexJobStatusResponse, message}。"""
    data: IndexJobStatusResponse
    message: str


class FileIndexStatusEnvelope(BaseModel):
    """GET /file/{id}/index/status envelope: {data: FileIndexStatusResponse, message}。"""
    data: FileIndexStatusResponse
    message: str


class IndexJobCancelResponse(BaseModel):
    """DELETE /index/jobs/{job_id} 回應。"""
    data: Dict[str, Any] = Field(
        ...,
        examples=[{"cancelled": True, "job_id": "uuid-..."}],
        description="{cancelled: bool, job_id: str}",
    )
    message: str = Field(..., examples=["Job cancelled"])


class IndexJobListResponse(BaseModel):
    """GET /index/jobs 回應 ─ counts + jobs list。"""
    counts: Dict[str, int] = Field(
        ...,
        examples=[{"pending": 0, "running": 1, "succeeded": 5, "partial_success": 0, "failed": 0, "cancelled": 0, "total": 6}],
        description="每個狀態的 job 數量 + total",
    )
    jobs: List[IndexJobStatusResponse] = Field(default_factory=list)


class IndexedFileEntry(BaseModel):
    """GET /indexed-files 內單一條目。"""
    file_id: str
    file_name: str
    num_chunks: int
    indexed_at: str
    status: str = Field(..., description="indexed / failed / deleted")
    embedding_model: Optional[str]
    chunk_size: Optional[int]
    chunk_overlap: Optional[int]


class IndexedFilesResponse(BaseModel):
    """GET /indexed-files envelope。"""
    data: List[IndexedFileEntry]
    message: str = Field(..., examples=["Found 3 indexed files"])


class IndexDocumentEnvelope(BaseModel):
    """POST /file/{id}/index (sync) 回應 envelope。"""
    data: IndexDocumentResponse
    message: str = Field(..., examples=["File indexed successfully with 5 chunks"])


# ---- Query ----


class RAGChunkMetadataDoc(BaseModel):
    """檢索命中片段的 metadata 形狀。"""
    node_id: str = Field(..., description="vector store node id")
    mcp_file_id: Optional[str] = Field(None, description="檔案 UUID")
    file_name: Optional[str]
    folder_name: Optional[str]
    page: Optional[int] = Field(None, description="來源頁碼(docling 解析的分頁文件才有)")
    headings: Optional[List[str]] = Field(None, description="所屬標題鏈(引用溯源)")


class RAGSearchResultDoc(BaseModel):
    """單一命中結果。"""
    text: str = Field(..., description="命中片段內容")
    score: float = Field(..., description="排序分數(reranker 啟用時為 rerank score)")
    metadata: RAGChunkMetadataDoc


class QueryResponseData(BaseModel):
    """POST /api/rag/query 的 data 區塊。"""
    query: str
    results: List[RAGSearchResultDoc] = Field(default_factory=list)
    total_results: int
    retrieval_time_ms: Optional[float] = Field(None)


class QueryResponse(BaseModel):
    """POST /api/rag/query envelope。"""
    data: QueryResponseData
    message: str = Field(..., examples=["Query returned 5 results"])
