# TC-config:配置模型與配置管理 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-config](../specs/SPEC-config.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_config.py` |

---

## TC-config-01:ServerConfig 必填齊全與型別轉換

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `host="0.0.0.0", port="8080", transport="sse"` |
| **測試步驟** | 1. 建立 ServerConfig<br>2. 檢查各欄位值 |
| **預期結果** | 建立成功;port 字串 "8080" 被轉為 int 8080 |
| **實作** | `tests/test_config.py::test_server_config_required_and_coercion` |

## TC-config-02:ServerConfig 缺必填欄位

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 只給 `host="0.0.0.0"` |
| **測試步驟** | 1. 建立 ServerConfig 並捕捉例外 |
| **預期結果** | ValidationError,缺漏欄位集合 = {port, transport} |
| **實作** | `tests/test_config.py::test_server_config_missing_required` |

## TC-config-03:DatabaseConfig 選填欄位預設 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 只給 url/echo/pool_size/max_overflow/pool_timeout/pool_recycle |
| **測試步驟** | 1. 建立 DatabaseConfig<br>2. 檢查選填欄位 |
| **預期結果** | host/port/database/user/password 皆為 None |
| **實作** | `tests/test_config.py::test_database_config_optional_defaults` |

## TC-config-04:AuthConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `enabled=True` |
| **預期結果** | token_server_url=None、cache_ttl=60、request_timeout=5.0、retry_count=2、dynamic_tools=None |
| **實作** | `tests/test_config.py::test_auth_config_defaults` |

## TC-config-05:AuthConfig 缺 enabled

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-03 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | ValidationError |
| **實作** | `tests/test_config.py::test_auth_config_missing_enabled` |

## TC-config-06:DynamicToolsConfig 預設停用

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-04 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | enabled 為 False |
| **實作** | `tests/test_config.py::test_dynamic_tools_config_default_disabled` |

## TC-config-07:AppConfig 全預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-05 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | name="Agentic RAG"、version="0.0.0"、title="Agentic RAG MCP Server"、lifespan=None、tool_prefix="Agentic" |
| **實作** | `tests/test_config.py::test_app_config_all_defaults` |

## TC-config-08:RAGChunkingConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | default_chunk_size/default_overlap/hierarchy_sizes=None、max_chunk_size=2000、chunk_overlap=50 |
| **實作** | `tests/test_config.py::test_rag_chunking_config_defaults` |

## TC-config-09:AutoMergingConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | enabled=True、merge_threshold=0.5 |
| **實作** | `tests/test_config.py::test_auto_merging_config_defaults` |

## TC-config-10:RAGRetrievalConfig 必填 + 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | `default_top_k=10, default_similarity_cutoff=0.25, hybrid_search=True` |
| **預期結果** | sparse_top_k=12、hybrid_alpha=0.75、text_search_config="jiebacfg"、return_resource_files=False、auto_merging=None、expand_context_default=True、expand_context_neighbors=2 |
| **實作** | `tests/test_config.py::test_rag_retrieval_config_required_and_defaults` |

## TC-config-11:ContextualRetrievalConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | enabled=False、max_context_length=150、max_concurrent=5、apply_to="all" |
| **實作** | `tests/test_config.py::test_contextual_retrieval_config_defaults` |

## TC-config-12:RerankConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | enabled=False、model="BAAI/bge-reranker-v2-m3"、base_url="http://localhost:8787"、top_n=None、score_threshold=0.0 |
| **實作** | `tests/test_config.py::test_rerank_config_defaults` |

## TC-config-13:IndexingConfig 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-06 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | max_concurrent_jobs=4(GPU 序列化,見 H2/M7)、per_file_timeout_seconds=864000、job_timeout_seconds=864000(均 10 天,慢機台大檔 OCR 用) |
| **實作** | `tests/test_config.py::test_indexing_config_defaults` |

## TC-config-14:RAGConfig 巢狀組裝

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-07 |
| **層級** | 單元 |
| **測試輸入** | embedding/chunking/retrieval/vector_store 以巢狀 dict 傳入,retrieval 內含 auto_merging dict |
| **預期結果** | 巢狀 dict 轉為對應子模型;llm/rerank/docling/indexing 未給時為 None;enabled 預設 True |
| **實作** | `tests/test_config.py::test_rag_config_nested_assembly` |

## TC-config-15:ConfigModel 主樹組裝

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-07 |
| **層級** | 單元 |
| **測試輸入** | server/database/auth/logging/app/modules 六區塊巢狀 dict |
| **預期結果** | 各區塊轉為對應子模型;rag 未給時為 None |
| **實作** | `tests/test_config.py::test_config_model_full_tree` |

## TC-config-16:ConfigModel 缺 server 區塊

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-08 |
| **層級** | 單元 |
| **測試輸入** | 缺 server 的五區塊 dict |
| **預期結果** | ValidationError 且錯誤 loc 含 "server" |
| **實作** | `tests/test_config.py::test_config_model_missing_section` |

## TC-config-17:ModulesConfig 允許額外欄位

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-09 |
| **層級** | 單元 |
| **測試輸入** | `enabled=["demo"], demo={"description": "x"}` |
| **預期結果** | 建立成功且 model_dump 保留 demo 區塊 |
| **實作** | `tests/test_config.py::test_modules_config_extra_allowed` |

## TC-config-18:路徑驗證允許 cwd 內相對路徑

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-10 |
| **層級** | 單元 |
| **前置條件** | `monkeypatch.chdir(tmp_path)` |
| **測試輸入** | `config.yaml`、`config/app.yaml`、`sub/dir/x.yml` |
| **預期結果** | 三者皆通過驗證回傳 Path |
| **實作** | `tests/test_config.py::test_validate_config_path_allows_relative_paths` |

## TC-config-19:路徑驗證拒絕 ../ 穿越

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-11 |
| **層級** | 單元 |
| **前置條件** | `monkeypatch.chdir(tmp_path)` |
| **測試輸入** | `../evil.yaml` |
| **預期結果** | ValueError,訊息含 "outside the allowed base directory" |
| **實作** | `tests/test_config.py::test_validate_config_path_rejects_traversal` |

## TC-config-20:路徑驗證拒絕外部絕對路徑

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-11 |
| **層級** | 單元 |
| **前置條件** | `monkeypatch.chdir(tmp_path)` |
| **測試輸入** | `/etc/passwd.yaml` |
| **預期結果** | ValueError,訊息含 "outside the allowed base directory" |
| **實作** | `tests/test_config.py::test_validate_config_path_rejects_absolute_outside` |

## TC-config-21:路徑驗證拒絕非 YAML 副檔名

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-12 |
| **層級** | 單元 |
| **測試輸入** | `config.txt` |
| **預期結果** | ValueError,訊息含 "extension" |
| **實作** | `tests/test_config.py::test_validate_config_path_rejects_bad_extension` |

## TC-config-22:get_config 載入合法 YAML

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-13 |
| **層級** | 單元 |
| **前置條件** | tmp_path 內寫入完整合法 config.yaml 並 chdir |
| **測試輸入** | `get_config("config.yaml")` |
| **測試步驟** | 1. 呼叫 get_config<br>2. 檢查回傳 ConfigModel<br>3. 逐一檢查 Config.get_server_config 等 getters |
| **預期結果** | 回傳 ConfigModel;server.port=8080;auth.cache_ttl 補預設 60;get_config() dict 與 YAML 一致 |
| **實作** | `tests/test_config.py::test_get_config_valid_yaml` |

## TC-config-23:${VAR:-default} 佔位符不展開

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-14 |
| **層級** | 單元 |
| **前置條件** | `monkeypatch.setenv("TEST_DB_URL", ...)`;YAML 的 database.url 寫成 `${TEST_DB_URL:-postgresql://fallback/db}` |
| **測試輸入** | `get_config("config.yaml")` |
| **預期結果** | `model.database.url` 為字面值 `${TEST_DB_URL:-postgresql://fallback/db}`(未展開) |
| **實作** | `tests/test_config.py::test_get_config_env_var_placeholder_not_expanded` |

## TC-config-24:schema 不符的 YAML 回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-15 |
| **層級** | 單元 |
| **測試輸入** | 只含 `server: {host: only-host}` 的 YAML |
| **預期結果** | get_config 回 None;get_config_model 亦為 None(例外被內部吞掉) |
| **實作** | `tests/test_config.py::test_get_config_invalid_schema_returns_none` |

## TC-config-25:YAML 語法錯誤回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-15 |
| **層級** | 單元 |
| **測試輸入** | `server: [unclosed\n  :::` |
| **預期結果** | get_config 回 None;`Config.get_config()` 為 `{}` |
| **實作** | `tests/test_config.py::test_get_config_malformed_yaml_returns_none` |

## TC-config-26:檔案不存在回 None(現行行為)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-15 |
| **層級** | 單元 |
| **測試輸入** | `get_config("no_such_file.yaml")` |
| **預期結果** | 回 None、不外拋 FileNotFoundError(被 `_load_config` 的 catch-all 吞掉;docstring 與實作不一致,見 SPEC §5) |
| **實作** | `tests/test_config.py::test_get_config_missing_file_returns_none` |

## TC-config-27:enabled 模組配置載入

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-16 |
| **層級** | 單元 |
| **前置條件** | YAML modules 區塊含 enabled=[demo] 與 demo 詳細配置(api_router + mcp_tools: null + description) |
| **測試步驟** | 1. Config.set_config<br>2. get_module_model("demo")<br>3. get_module_model("not_enabled") |
| **預期結果** | demo 回 ModuleConfig(prefix="/api/demo"、mcp_tools=None);未啟用模組回 None |
| **實作** | `tests/test_config.py::test_set_config_loads_enabled_module_configs` |

## TC-config-28:壞模組配置被跳過

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-16 |
| **層級** | 單元 |
| **前置條件** | YAML 內 broken 模組缺必填 api_router/mcp_tools |
| **預期結果** | 主 config 載入成功(get_config_model 非 None);get_module_model("broken") 回 None |
| **實作** | `tests/test_config.py::test_set_config_skips_invalid_module_config` |

## TC-config-29:未載入時 getters 全回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-config-17 |
| **層級** | 單元 |
| **前置條件** | Config 狀態已重置(autouse fixture) |
| **預期結果** | get_config_model / get_server_config / get_database_config / get_auth_config / get_logging_config / get_app_config_model / get_modules_config / get_module_model 全回 None |
| **實作** | `tests/test_config.py::test_getters_return_none_before_load` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
