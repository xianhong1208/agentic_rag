"""Unit tests for src/config (model.py + config_manager.py)

不依賴 DB / vLLM / 任何外部服務 — 純邏輯測試。
YAML 一律寫進 pytest tmp_path;路徑驗證靠 monkeypatch.chdir 控制基準目錄。
跑法:cd agentic_rag && uv run pytest tests/test_config.py -v
"""

import pytest
from pydantic import ValidationError

from src.config.model import (
    ServerConfig,
    DatabaseConfig,
    DynamicToolsConfig,
    AuthConfig,
    AppConfig,
    ModulesConfig,
    RAGChunkingConfig,
    AutoMergingConfig,
    RAGRetrievalConfig,
    ContextualRetrievalConfig,
    RerankConfig,
    IndexingConfig,
    RAGConfig,
    ConfigModel,
)
from src.config.config_manager import Config, get_config


# ---------------------------------------------------------------------------
# 共用 fixture / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_config_state():
    """每個 test 前後重置 Config 類別層級狀態,避免測試間互相污染"""
    Config._config = {}
    Config._config_model = None
    Config._module_configs = {}
    yield
    Config._config = {}
    Config._config_model = None
    Config._module_configs = {}


VALID_YAML = """\
server:
  host: 127.0.0.1
  port: 8080
  transport: sse
database:
  url: "postgresql://u:p@localhost:5432/db"
  echo: false
  pool_size: 5
  max_overflow: 10
  pool_timeout: 30
  pool_recycle: 3600
auth:
  enabled: false
logging:
  level: INFO
  format: "{time} {message}"
  file: null
  max_size: 10MB
  backup_count: 3
app:
  name: TestApp
modules:
  enabled: []
"""


def _write_config(tmp_path, monkeypatch, text, name="config.yaml"):
    """把 YAML 寫進 tmp_path 並 chdir 過去(讓路徑白名單以 tmp_path 為基準)"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / name).write_text(text, encoding="utf-8")
    return name


# ---------------------------------------------------------------------------
# config/model.py — 代表性 Pydantic models
# ---------------------------------------------------------------------------

def test_server_config_required_and_coercion():
    """ServerConfig 必填齊全可建立,port 字串自動轉 int (TC-config-01)"""
    cfg = ServerConfig(host="0.0.0.0", port="8080", transport="sse")
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8080
    assert cfg.transport == "sse"


def test_server_config_missing_required():
    """ServerConfig 缺 host/port/transport 任一必填 → ValidationError (TC-config-02)"""
    with pytest.raises(ValidationError) as exc_info:
        ServerConfig(host="0.0.0.0")
    missing = {e["loc"][0] for e in exc_info.value.errors()}
    assert missing == {"port", "transport"}


def test_database_config_optional_defaults():
    """DatabaseConfig 的 host/port/database/user/password 預設 None (TC-config-03)"""
    cfg = DatabaseConfig(
        url="sqlite://", echo=False, pool_size=5,
        max_overflow=10, pool_timeout=30, pool_recycle=3600,
    )
    assert cfg.host is None
    assert cfg.port is None
    assert cfg.database is None
    assert cfg.user is None
    assert cfg.password is None


def test_auth_config_defaults():
    """AuthConfig 只給 enabled,其餘連線設定用預設值 (TC-config-04)"""
    cfg = AuthConfig(enabled=True)
    assert cfg.token_server_url is None
    assert cfg.cache_ttl == 60
    assert cfg.request_timeout == 5.0
    assert cfg.retry_count == 2
    assert cfg.dynamic_tools is None


def test_auth_config_missing_enabled():
    """AuthConfig 缺必填 enabled → ValidationError (TC-config-05)"""
    with pytest.raises(ValidationError):
        AuthConfig()


def test_dynamic_tools_config_default_disabled():
    """DynamicToolsConfig.enabled 預設 False (TC-config-06)"""
    assert DynamicToolsConfig().enabled is False


def test_app_config_all_defaults():
    """AppConfig 無參數建立時使用全部預設值 (TC-config-07)"""
    cfg = AppConfig()
    assert cfg.name == "Agentic RAG"
    # version 欄位已自 AppConfig 移除 — 版本唯一來源是 pyproject.toml
    # (src/version.py get_version()),config 不再攜帶版本避免雙源漂移
    assert not hasattr(cfg, "version")
    assert cfg.title == "Agentic RAG MCP Server"
    assert cfg.lifespan is None
    assert cfg.tool_prefix == "Agentic"


def test_rag_chunking_config_defaults():
    """RAGChunkingConfig 平面欄位預設 None,max_chunk_size=2000、chunk_overlap=50 (TC-config-08)"""
    cfg = RAGChunkingConfig()
    assert cfg.default_chunk_size is None
    assert cfg.default_overlap is None
    assert cfg.max_chunk_size == 2000
    assert cfg.hierarchy_sizes is None
    assert cfg.chunk_overlap == 50


def test_auto_merging_config_defaults():
    """AutoMergingConfig 預設 enabled=True、merge_threshold=0.5 (TC-config-09)"""
    cfg = AutoMergingConfig()
    assert cfg.enabled is True
    assert cfg.merge_threshold == 0.5


def test_rag_retrieval_config_required_and_defaults():
    """RAGRetrievalConfig 必填三欄 + 其餘預設(sparse 12 / alpha 0.75 / jiebacfg 等) (TC-config-10)"""
    cfg = RAGRetrievalConfig(
        default_top_k=10, default_similarity_cutoff=0.25, hybrid_search=True,
    )
    assert cfg.default_sparse_top_k == 12
    assert cfg.default_hybrid_alpha == 0.75
    assert cfg.text_search_config == "jiebacfg"
    assert cfg.return_resource_files is False
    assert cfg.auto_merging is None
    assert cfg.expand_context_default is True
    assert cfg.expand_context_neighbors == 2


def test_contextual_retrieval_config_defaults():
    """ContextualRetrievalConfig 預設 enabled=False、apply_to='all' (TC-config-11)"""
    cfg = ContextualRetrievalConfig()
    assert cfg.enabled is False
    assert cfg.max_context_length == 150
    assert cfg.max_concurrent == 5
    assert cfg.apply_to == "all"


def test_rerank_config_defaults():
    """RerankConfig 預設 disabled、bge-reranker 模型、threshold 0.0 (TC-config-12)"""
    cfg = RerankConfig()
    assert cfg.enabled is False
    assert cfg.model == "BAAI/bge-reranker-v2-m3"
    assert cfg.base_url == "http://localhost:8787"
    assert cfg.top_n is None
    assert cfg.score_threshold == 0.0


def test_indexing_config_defaults():
    """IndexingConfig 預設 100 併發 / 10 天單檔 / 10 天 job 上限 (TC-config-13)

    timeout 預設 2026-08 從 1800s/21600s 放寬到 10 天(慢機台大檔 OCR;
    watchdog 誤判由 keepalive 60s 心跳兜底)。
    """
    cfg = IndexingConfig()
    assert cfg.max_concurrent_jobs == 4
    assert cfg.per_file_timeout_seconds == 864000
    assert cfg.job_timeout_seconds == 864000


def test_rag_config_nested_assembly():
    """RAGConfig 用巢狀 dict 組裝子 models,optional 子項預設 None (TC-config-14)"""
    cfg = RAGConfig(
        embedding={"provider": "vllm", "model": "bge-m3", "dimension": 1024},
        chunking={"hierarchy_sizes": [1024, 256]},
        retrieval={
            "default_top_k": 10,
            "default_similarity_cutoff": 0.25,
            "hybrid_search": True,
            "auto_merging": {"enabled": True, "merge_threshold": 0.6},
        },
        vector_store={"type": "pgvector", "table_prefix": "rag_"},
    )
    assert cfg.enabled is True
    assert cfg.embedding.provider == "vllm"
    assert cfg.chunking.hierarchy_sizes == [1024, 256]
    assert isinstance(cfg.retrieval.auto_merging, AutoMergingConfig)
    assert cfg.retrieval.auto_merging.merge_threshold == 0.6
    assert cfg.llm is None
    assert cfg.rerank is None
    assert cfg.docling is None
    assert cfg.indexing is None


def test_config_model_full_tree():
    """ConfigModel 主樹從巢狀 dict 組裝成功,rag 預設 None (TC-config-15)"""
    cfg = ConfigModel(
        server={"host": "h", "port": 1, "transport": "sse"},
        database={
            "url": "sqlite://", "echo": False, "pool_size": 1,
            "max_overflow": 1, "pool_timeout": 1, "pool_recycle": 1,
        },
        auth={"enabled": False},
        logging={
            "level": "INFO", "format": "f", "file": None,
            "max_size": "10MB", "backup_count": 1,
        },
        app={},
        modules={"enabled": ["a", "b"]},
    )
    assert isinstance(cfg.server, ServerConfig)
    assert cfg.modules.enabled == ["a", "b"]
    assert cfg.rag is None


def test_config_model_missing_section():
    """ConfigModel 缺 server 區塊 → ValidationError (TC-config-16)"""
    with pytest.raises(ValidationError) as exc_info:
        ConfigModel(
            database={
                "url": "sqlite://", "echo": False, "pool_size": 1,
                "max_overflow": 1, "pool_timeout": 1, "pool_recycle": 1,
            },
            auth={"enabled": False},
            logging={
                "level": "INFO", "format": "f", "file": None,
                "max_size": "10MB", "backup_count": 1,
            },
            app={},
            modules={"enabled": []},
        )
    assert any(e["loc"][0] == "server" for e in exc_info.value.errors())


def test_modules_config_extra_allowed():
    """ModulesConfig extra='allow':額外模組區塊被保留不報錯 (TC-config-17)"""
    cfg = ModulesConfig(enabled=["demo"], demo={"description": "x"})
    assert cfg.enabled == ["demo"]
    assert cfg.model_dump()["demo"] == {"description": "x"}


# ---------------------------------------------------------------------------
# config/config_manager.py — _validate_config_path
# ---------------------------------------------------------------------------

def test_validate_config_path_allows_relative_paths(tmp_path, monkeypatch):
    """cwd 下的相對路徑(根層 / config/ / 子目錄)都通過驗證 (TC-config-18)"""
    monkeypatch.chdir(tmp_path)
    assert Config._validate_config_path("config.yaml").name == "config.yaml"
    assert Config._validate_config_path("config/app.yaml").name == "app.yaml"
    # ALLOWED_CONFIG_DIRS 含 "." → cwd 下任意子路徑都允許
    assert Config._validate_config_path("sub/dir/x.yml").suffix == ".yml"


def test_validate_config_path_rejects_traversal(tmp_path, monkeypatch):
    """../ 路徑穿越到 cwd 之外 → ValueError (TC-config-19)"""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="outside the allowed base directory"):
        Config._validate_config_path("../evil.yaml")


def test_validate_config_path_rejects_absolute_outside(tmp_path, monkeypatch):
    """cwd 之外的絕對路徑 → ValueError (TC-config-20)"""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="outside the allowed base directory"):
        Config._validate_config_path("/etc/passwd.yaml")


def test_validate_config_path_rejects_bad_extension(tmp_path, monkeypatch):
    """非 .yaml/.yml 副檔名 → ValueError (TC-config-21)"""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="extension"):
        Config._validate_config_path("config.txt")


# ---------------------------------------------------------------------------
# config/config_manager.py — get_config / set_config 生命週期
# ---------------------------------------------------------------------------

def test_get_config_valid_yaml(tmp_path, monkeypatch):
    """合法 YAML → 回傳 ConfigModel,getters 可取得各區塊 (TC-config-22)"""
    name = _write_config(tmp_path, monkeypatch, VALID_YAML)
    model = get_config(name)
    assert isinstance(model, ConfigModel)
    assert model.server.port == 8080
    assert model.app.name == "TestApp"
    # class-level getters 與便利函數一致
    assert Config.get_server_config().host == "127.0.0.1"
    assert Config.get_auth_config().enabled is False
    assert Config.get_auth_config().cache_ttl == 60  # AuthConfig 預設值補齊
    assert Config.get_logging_config().level == "INFO"
    assert Config.get_modules_config().enabled == []
    assert Config.get_config()["server"]["port"] == 8080


def test_get_config_env_var_placeholder_not_expanded(tmp_path, monkeypatch):
    """`${VAR:-default}` 佔位符不做環境變數展開,保留字面值 (TC-config-23)

    原始碼只用 yaml.safe_load,沒有任何 expandvars/envsubst 邏輯;
    即使環境變數有設定,載入結果仍是原字串。此測試固定住現行行為。
    """
    monkeypatch.setenv("TEST_DB_URL", "postgresql://real/db")
    yaml_text = VALID_YAML.replace(
        'url: "postgresql://u:p@localhost:5432/db"',
        'url: "${TEST_DB_URL:-postgresql://fallback/db}"',
    )
    name = _write_config(tmp_path, monkeypatch, yaml_text)
    model = get_config(name)
    assert model.database.url == "${TEST_DB_URL:-postgresql://fallback/db}"


def test_get_config_invalid_schema_returns_none(tmp_path, monkeypatch):
    """YAML 缺必填 section(Pydantic 驗證失敗)→ get_config 回 None (TC-config-24)"""
    name = _write_config(tmp_path, monkeypatch, "server:\n  host: only-host\n")
    assert get_config(name) is None
    assert Config.get_config_model() is None


def test_get_config_malformed_yaml_returns_none(tmp_path, monkeypatch):
    """YAML 語法錯誤 → 內部吞掉、_config 清空、回 None (TC-config-25)"""
    name = _write_config(tmp_path, monkeypatch, "server: [unclosed\n  :::")
    assert get_config(name) is None
    assert Config.get_config() == {}


def test_get_config_missing_file_returns_none(tmp_path, monkeypatch):
    """檔案不存在 → 回 None(FileNotFoundError 被 _load_config 的 catch-all 吞掉) (TC-config-26)

    註:_load_config docstring 宣稱會 raise FileNotFoundError,但實作中
    raise 在 try 區塊內、被 `except Exception` 捕捉,實際不會外拋。
    本測試固定住現行(實際)行為。
    """
    monkeypatch.chdir(tmp_path)
    assert get_config("no_such_file.yaml") is None
    assert Config.get_config() == {}


def test_set_config_loads_enabled_module_configs(tmp_path, monkeypatch):
    """enabled 模組的詳細配置進安全字典,get_module_model 可取;未啟用回 None (TC-config-27)"""
    yaml_text = VALID_YAML.replace(
        "modules:\n  enabled: []\n",
        "modules:\n"
        "  enabled: [demo]\n"
        "  demo:\n"
        "    api_router:\n"
        "      module: src.api.router.demo\n"
        "      router_name: router\n"
        "      prefix: /api/demo\n"
        "    mcp_tools: null\n"
        "    description: 示範模組\n",
    )
    name = _write_config(tmp_path, monkeypatch, yaml_text)
    Config.set_config(name)
    module = Config.get_module_model("demo")
    assert module is not None
    assert module.api_router.prefix == "/api/demo"
    assert module.mcp_tools is None
    assert module.description == "示範模組"
    assert Config.get_module_model("not_enabled") is None


def test_set_config_skips_invalid_module_config(tmp_path, monkeypatch):
    """單一模組配置缺必填欄位 → 該模組被跳過,主 config 仍載入成功 (TC-config-28)"""
    yaml_text = VALID_YAML.replace(
        "modules:\n  enabled: []\n",
        "modules:\n"
        "  enabled: [broken]\n"
        "  broken:\n"
        "    description: 缺 api_router 與 mcp_tools\n",
    )
    name = _write_config(tmp_path, monkeypatch, yaml_text)
    Config.set_config(name)
    assert Config.get_config_model() is not None  # 主 config 成功
    assert Config.get_module_model("broken") is None  # 壞模組被跳過


def test_getters_return_none_before_load():
    """尚未載入 config(model 為 None)時所有 getters 回 None (TC-config-29)"""
    assert Config.get_config_model() is None
    assert Config.get_server_config() is None
    assert Config.get_database_config() is None
    assert Config.get_auth_config() is None
    assert Config.get_logging_config() is None
    assert Config.get_app_config_model() is None
    assert Config.get_modules_config() is None
    assert Config.get_module_model("any") is None


def test_config_path_outside_allowed_dirs_rejected(tmp_path):
    """config 路徑安全檢查:允許目錄之外的路徑一律 ValueError(路徑穿越防禦)。"""
    evil = tmp_path / "evil.yaml"
    evil.write_text("server: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Security Error"):
        Config._load_config(str(evil))


def test_asr_config_defaults():
    """AsrConfig 最小欄位集:enabled + provider + 雲端三欄,別的沒有 (TC-config-16)

    刻意瘦身:每個 config 欄位都是永久維護面;裁切/過濾程式內恆開,
    FireRedASR 專用欄位等 BL-08 實作再加。"""
    from src.config.model import AsrConfig
    cfg = AsrConfig()
    assert cfg.enabled is True
    assert cfg.provider == "docling-whisper"
    assert cfg.base_url is None and cfg.api_key is None and cfg.model is None
    # 守住瘦身:不得偷偷長回被砍掉的欄位
    assert set(AsrConfig.model_fields) == {"enabled", "provider", "base_url", "api_key", "model"}


_RAG_REQUIRED = dict(
    embedding={"provider": "vllm", "model": "m", "dimension": 8},
    chunking={},
    retrieval={"default_top_k": 5, "default_similarity_cutoff": 0.2, "hybrid_search": True},
    vector_store={"type": "pgvector", "table_prefix": "rag_"},
)


def test_rag_config_asr_nested_assembly():
    """RAGConfig 巢狀組裝 asr 段;未給時預設 None(向下相容)(TC-config-17)"""
    from src.config.model import AsrConfig
    cfg = RAGConfig(
        **_RAG_REQUIRED,
        asr={"enabled": False, "provider": "openai-compatible", "base_url": "http://x:1/v1"},
    )
    assert isinstance(cfg.asr, AsrConfig)
    assert cfg.asr.enabled is False
    assert cfg.asr.provider == "openai-compatible"
    assert cfg.asr.base_url == "http://x:1/v1"
    assert RAGConfig(**_RAG_REQUIRED).asr is None
