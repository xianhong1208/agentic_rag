
"""配置模型

將所有 Pydantic 配置模型集中在此處，以便在項目中重用。
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class ServerConfig(BaseModel):
    """服務器配置"""
    host: str
    port: int
    transport: str


class DatabaseConfig(BaseModel):
    """資料庫配置"""
    url: str
    echo: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None


class DynamicToolsConfig(BaseModel):
    """動態工具過濾配置

    enabled: false → 所有認證 token 看到全部工具
    enabled: true  → token 只看到為它建立的動態工具（靜態工具所有人都看得到）
    """
    enabled: bool = False


class AuthConfig(BaseModel):
    """認證配置 - 使用遠端 Token Server 驗證"""
    enabled: bool
    token_server_url: Optional[str] = None  # Token Server URL（啟用認證時必須提供）

    # 連線設定
    cache_ttl: int = 60  # 驗證結果快取時間（秒）
    request_timeout: float = 5.0  # HTTP 請求超時（秒）
    retry_count: int = 2  # 失敗重試次數
    dynamic_tools: Optional[DynamicToolsConfig] = None


class LoggingConfig(BaseModel):
    """日誌配置"""
    level: str
    format: str
    file: Optional[str]
    max_size: str
    backup_count: int


class AppConfig(BaseModel):
    """應用程序配置

    版本欄位不存在:唯一來源是 pyproject.toml 的 [project].version,
    由 src/version.py 的 get_version() 解析。
    """
    name: str = "Agentic RAG"
    title: str = "Agentic RAG MCP Server"
    description: str = "Agentic RAG — Hierarchical RAG with auto-merging retrieval"
    lifespan: Optional[str] = None
    # Per-folder MCP tool 名稱前綴(預設 Agentic_)
    tool_prefix: str = "Agentic"


class RouterConfig(BaseModel):
    """API 路由配置"""
    module: str
    router_name: str
    prefix: str


class McpToolsConfig(BaseModel):
    """MCP 工具配置"""
    module: str
    function_name: str


class ModuleConfig(BaseModel):
    """模組配置"""
    api_router: Optional[RouterConfig]
    mcp_tools: Optional[McpToolsConfig]
    description: str


class ModulesConfig(BaseModel):
    """模組總配置"""
    model_config = ConfigDict(extra="allow")

    enabled: List[str]


class RAGEmbeddingConfig(BaseModel):
    """RAG 嵌入配置"""
    provider: str  # "openai", "azure", "vllm", "ollama"
    model: str
    dimension: int
    api_key: Optional[str] = None  # Direct API key
    api_key_env: Optional[str] = None  # Environment variable name for API key
    base_url: Optional[str] = None  # Also used as azure_endpoint for Azure provider
    api_version: Optional[str] = None  # Azure API version (e.g., "2024-02-01")
    azure_deployment: Optional[str] = None  # Azure deployment name
    # e5 系模型的訓練契約:查詢加 "query: "、文件加 "passage: " 前綴,
    # 不加會顯著劣化檢索。bge 系留空(預設)= 行為完全不變。
    # ⚠️ 改前綴 = 改向量空間,既有索引需全量 reindex 才一致
    query_prefix: str = ""
    passage_prefix: str = ""


class RAGChunkingConfig(BaseModel):
    """RAG 分塊配置 — 支援平面分塊(flat) 與階層分塊(hierarchical / auto-merging)"""
    # 平面分塊欄位(flat 模式用,本專案不需要可不填)
    default_chunk_size: Optional[int] = None
    default_overlap: Optional[int] = None
    max_chunk_size: int = 2000
    # 階層分塊欄位(Agentic 新增)
    hierarchy_sizes: Optional[List[int]] = None  # [parent_target_tokens, leaf_chunk_size]
    chunk_overlap: int = 50


class AutoMergingConfig(BaseModel):
    """Auto-Merging Retriever 配置"""
    enabled: bool = True
    merge_threshold: float = 0.5  # 命中比例 ≥ 此值即升級到 parent


class RAGRetrievalConfig(BaseModel):
    """RAG 檢索配置"""
    default_top_k: int
    default_similarity_cutoff: float
    default_sparse_top_k: int = 12
    default_hybrid_alpha: float = 0.75
    hybrid_search: bool
    text_search_config: str = "jiebacfg"
    # 混合檢索融合法:
    #   "rrf"    = 我們自己的 Reciprocal Rank Fusion(dense + sparse 各自名次
    #              1/(k+rank) 相加重排;BM25 真正影響排序,業界標準)
    #   "concat" = llama_index 原生(dense+sparse 串接去重;dense 主導,BM25
    #              只補尾巴 → hybrid 實質等於 vector,舊行為)
    hybrid_fusion: str = "rrf"
    rrf_k: int = 60  # RRF 常數(越大越平滑;業界慣用 60)
    return_resource_files: bool = False
    # Agentic 新增
    auto_merging: Optional[AutoMergingConfig] = None
    expand_context_default: bool = True
    expand_context_neighbors: int = 2
    # 同時執行的查詢上限(REST + MCP 共用一個 semaphore;超過的排隊不丟棄)。
    # 上限依據:sync 主 engine pool 5+10、共用 async engine pool 5+10、
    # 每 folder 的 PGVector async pool 5+10 — 8 條並發查詢時各池都有餘裕。
    max_concurrent_queries: int = 8


class RAGVectorStoreConfig(BaseModel):
    """RAG 向量存儲配置"""
    type: str
    table_prefix: str


class RAGLLMConfig(BaseModel):
    """RAG LLM 配置（用於 Contextual Retrieval 等需要 LLM 的功能）"""
    provider: str = "azure"  # "azure", "openai", "vllm", "ollama"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # Azure endpoint
    api_version: Optional[str] = "2024-12-01-preview"
    azure_deployment: Optional[str] = None


class ContextualRetrievalConfig(BaseModel):
    """Contextual Retrieval 配置"""
    enabled: bool = False
    max_context_length: int = 150
    max_concurrent: int = 5
    max_doc_chars: int = 60000
    max_tokens: int = 1024
    reasoning_effort: Optional[str] = None
    # Agentic 新增:可指定僅對 leaf / parent / 全部 chunks 加 context prefix
    apply_to: str = "all"  # "leaf" / "parent" / "all"


class RerankConfig(BaseModel):
    """Reranker 配置"""
    enabled: bool = False
    model: str = "BAAI/bge-reranker-v2-m3"
    base_url: str = "http://localhost:8787"
    api_key: Optional[str] = None
    top_n: Optional[int] = None  # 重排後保留前 N 個結果（None = 保留全部）
    score_threshold: float = 0.0  # 重排分數門檻
    # 送 /v1/score 前的輸入模板,{text} 為佔位符。指令微調型 reranker(如 mxbai)
    # 必須套官方模板分數分佈才正常;傳統 cross-encoder(bge 系)保持預設 = 原文直送。
    query_template: str = "{text}"
    document_template: str = "{text}"


class DoclingConfig(BaseModel):
    """Docling 文件解析配置"""
    device: str = "cpu"  # "cpu", "cuda", "cuda:0", "cuda:4" 等
    ocr_enabled: bool = True  # 是否啟用 OCR（掃描版 PDF 需要）
    # OCR 模型等級(PP-OCRv6 系列,多語系統一模型):tiny / small / medium。
    # medium 準確率最高、單頁推理較慢;torch 權重需在
    # assets/docling_models/RapidOcr/torch/PP-OCRv6/{det,rec}/PP-OCRv6_{det,rec}_<scale>.pth,
    # 缺檔會 log error 並在模型載入時失敗(推論引擎 = rapidocr torch backend,
    # 跟 docling 其他模型共用 torch,CUDA/ROCm 通吃,不再依賴 onnxruntime)
    ocr_model_scale: str = "small"
    hf_offline: bool = False  # 離線部署開關：True → 設 HF_HUB_OFFLINE=1，且 assets/ 找不到本地模型/tokenizer 時啟動失敗
    compile_models: bool = False  # torch.compile 模型優化（推理快但啟動慢 ~120s，適合不常重啟的環境）


class AsrConfig(BaseModel):
    """音檔轉錄(ASR)來源選擇 — BL-06。

    舊行為是純 auto-discover(assets/whisper_models/*.pt 在就掛 audio pipeline,
    無任何開關)。刻意只留最小欄位集(每個 config 欄位都是永久維護面):
    裁切/幻覺過濾維持程式內恆開(audio_defense)。provider 對應
    src/domain/rag/asr_provider.py 的工廠。
    """
    enabled: bool = True                    # False = 不轉錄音檔(即使模型在)
    # docling-whisper(本地)| openai-compatible(雲端/自架 HTTP;
    # OpenAI / Groq / vLLM whisper / faster-whisper-server 皆相容)|
    # fireredasr(本地 FireRedASR-AED-L,繁中輸出;權重見 fireredasr_provider.py)
    provider: str = "docling-whisper"
    # ---- 雲端(openai-compatible)專用:POST {base_url}/audio/transcriptions ----
    base_url: Optional[str] = None          # 如 http://host:8000/v1
    api_key: Optional[str] = None
    model: Optional[str] = None             # 雲端模型名,如 whisper-1


class IndexingConfig(BaseModel):
    """背景 indexing job 行為控制"""
    # 同時處理的檔案上限(per-job semaphore)。預設 4:docling convert 已由
    # DOCLING_INFER_LOCK 序列化(單 GPU 本來也做不了多路 forward),再開到 100
    # 只會讓 100 個 to_thread 堆在鎖上、各佔一條 worker thread,餓死 context-gen /
    # embedding / media 共用的 default executor(~32 threads)。留 4 讓「A 檔 embed
    # 時 B 檔 convert」有流水線重疊。吞吐不夠或機台夠力可調高;env var
    # RAG_INDEXING_CONCURRENCY / config 均可 override。
    max_concurrent_jobs: int = 4

    # 單檔 indexing 上限(秒);env RAG_PER_FILE_TIMEOUT_SECONDS override。
    # 預設 10 天:慢機台 + 200 頁掃描 PDF 走 OCR 會超過舊預設 30min → timeout 失敗。
    # 幾乎等同不設限,靠 keepalive(60s 心跳)避免 watchdog 誤判。
    per_file_timeout_seconds: int = 864000  # 10 days

    # 整個 job 上限(秒);env RAG_JOB_TIMEOUT_SECONDS override。0/負值 = disable。
    # ⚠️ 必須 >= per_file_timeout_seconds,否則 job 會先掛、檔案還沒跑完 → 同設 10 天。
    job_timeout_seconds: int = 864000  # 10 days


class RAGConfig(BaseModel):
    """RAG 系統配置"""
    enabled: bool = True
    embedding: RAGEmbeddingConfig
    chunking: RAGChunkingConfig
    retrieval: RAGRetrievalConfig
    vector_store: RAGVectorStoreConfig
    llm: Optional[RAGLLMConfig] = None
    contextual_retrieval: Optional[ContextualRetrievalConfig] = None
    rerank: Optional[RerankConfig] = None
    docling: Optional[DoclingConfig] = None
    asr: Optional[AsrConfig] = None
    indexing: Optional[IndexingConfig] = None


class ConfigModel(BaseModel):
    """完整配置模型"""
    server: ServerConfig
    database: DatabaseConfig
    auth: AuthConfig
    logging: LoggingConfig
    app: AppConfig
    modules: ModulesConfig
    rag: Optional[RAGConfig] = None


__all__ = [
    "ServerConfig",
    "DatabaseConfig",
    "DynamicToolsConfig",
    "AuthConfig",
    "LoggingConfig",
    "AppConfig",
    "RouterConfig",
    "McpToolsConfig",
    "ModuleConfig",
    "ModulesConfig",
    "RAGEmbeddingConfig",
    "RAGChunkingConfig",
    "AutoMergingConfig",
    "RAGRetrievalConfig",
    "RAGVectorStoreConfig",
    "RAGLLMConfig",
    "ContextualRetrievalConfig",
    "RerankConfig",
    "DoclingConfig",
    "RAGConfig",
    "ConfigModel",
]
