# SPEC-config:配置模型與配置管理


| 項目 | 內容 |
|------|------|
| 模組 | `src/config/model.py`、`src/config/config_manager.py` |
| 對應測試 | `tests/test_config.py` |
| 版本 | 0.1.0 |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

`src/config/model.py` 定義 24 個 Pydantic v2 配置模型(本 SPEC 涵蓋代表性 12+ 個:ConfigModel 主樹、Server/Database/Auth/App/Modules、RAG 相關子模型)。
`src/config/config_manager.py` 負責:路徑安全驗證(白名單 + 防路徑穿越)、YAML 載入、Pydantic 解析、模組配置的安全字典存取。
不負責:環境變數展開(YAML 中的 `${VAR:-default}` 佔位符**不會**被展開,原樣保留)、配置熱重載。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-config-01 | ServerConfig 三欄位(host/port/transport)全必填,型別自動強制轉換 | 齊全可建立且 port 字串轉 int;缺欄位拋 ValidationError |
| REQ-config-02 | DatabaseConfig 連線欄位必填,host/port/database/user/password 選填預設 None | 只給必填六欄可建立,選填皆為 None |
| REQ-config-03 | AuthConfig 僅 enabled 必填,連線設定有預設值(cache_ttl=60、request_timeout=5.0、retry_count=2) | 只給 enabled 可建立且預設值正確;缺 enabled 拋 ValidationError |
| REQ-config-04 | DynamicToolsConfig.enabled 預設 False | 無參數建立時 enabled 為 False |
| REQ-config-05 | AppConfig 全欄位有預設值(name=Agentic RAG、version=0.0.0、tool_prefix=Agentic 等) | 無參數建立成功且預設值正確 |
| REQ-config-06 | RAG 相關子模型預設值正確:Chunking(max_chunk_size=2000、chunk_overlap=50)、AutoMerging(enabled=True、threshold=0.5)、Retrieval(sparse=12、alpha=0.75、jiebacfg)、ContextualRetrieval(apply_to=all)、Rerank(disabled)、Indexing(100/1800/21600) | 各模型只給必填欄位建立後,預設值與原始碼一致 |
| REQ-config-07 | RAGConfig / ConfigModel 支援巢狀 dict 組裝,optional 子區塊預設 None | 巢狀 dict 轉為對應子模型;rag/llm/rerank 等未給時為 None |
| REQ-config-08 | ConfigModel 缺任一必填 section(如 server)拒絕建立 | 拋 ValidationError 且錯誤定位到缺的 section |
| REQ-config-09 | ModulesConfig 為 extra="allow",允許動態模組區塊 | 額外 key 不報錯且 model_dump 保留 |
| REQ-config-10 | `_validate_config_path` 允許 cwd 內的相對路徑(根層檔案、config/、任意子目錄) | 回傳 Path 不拋例外 |
| REQ-config-11 | `_validate_config_path` 拒絕解析到 cwd 之外的路徑(`../`、外部絕對路徑) | 拋 ValueError,訊息含 "outside the allowed base directory" |
| REQ-config-12 | `_validate_config_path` 只允許 .yaml/.yml 副檔名 | 其他副檔名拋 ValueError |
| REQ-config-13 | `get_config(path)` 載入合法 YAML 後回傳 ConfigModel,類別 getters 可取各區塊 | 各 getter 值與 YAML 內容一致,未給的欄位補 Pydantic 預設值 |
| REQ-config-14 | YAML 中的 `${VAR:-default}` 佔位符不展開,原樣保留(現行行為) | 即使環境變數已設定,載入結果仍為字面字串 |
| REQ-config-15 | 非法配置(schema 不符 / YAML 語法錯誤 / 檔案不存在)時 `get_config` 回 None,不外拋例外 | 三種情境皆回 None;語法錯誤與檔案不存在時 `Config.get_config()` 為 `{}` |
| REQ-config-16 | enabled 模組的詳細配置載入安全字典,`get_module_model` 可查;未啟用/載入失敗回 None | 合法模組回 ModuleConfig;未啟用回 None;壞模組被跳過且主 config 不受影響 |
| REQ-config-17 | config 尚未載入時所有 getters 回 None | 8 個 getter 全回 None |

## 3. 非功能需求 (Non-Functional)

- 路徑白名單驗證必須先於檔案讀取執行,防止路徑穿越攻擊讀取任意檔案。
- 模組配置一律走 `_module_configs` 字典存取,不得使用 `setattr`(防屬性注入)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| YAML 檔不存在 | `get_config` 回 None(FileNotFoundError 被內部 catch-all 吞掉,詳見 §5 註記) |
| YAML 語法錯誤 | `_config` 清為 `{}`,`get_config` 回 None |
| YAML 缺必填 section | Pydantic 驗證失敗被吞,`get_config` 回 None |
| `../` 路徑穿越 | ValueError |
| 非 .yaml/.yml 副檔名 | ValueError |
| 單一模組配置缺必填欄位 | 該模組跳過,主 config 正常 |

## 5. 相依與假設 (Dependencies & Assumptions)

- 依賴 `yaml.safe_load` 與 Pydantic v2;無 DB / 網路依賴。
- 測試以 `tmp_path` + `monkeypatch.chdir` 控制基準目錄(路徑驗證以 cwd 為基準)。
- `Config` 為類別層級狀態,測試前後需重置 `_config`/`_config_model`/`_module_configs`。
- **原始碼註記(疑似 bug,測試固定現行行為)**:
  1. `_load_config` docstring 宣稱檔案不存在會 raise FileNotFoundError,但 raise 位於 try 區塊內、被 `except Exception` 捕捉,實際不會外拋。
  2. 專案 YAML 若使用 `${VAR:-default}` 佔位符,config 層不會展開(無 expandvars/envsubst 邏輯)。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-config-01 | TC-config-01, TC-config-02 | `tests/test_config.py::test_server_config_required_and_coercion`、`::test_server_config_missing_required` |
| REQ-config-02 | TC-config-03 | `tests/test_config.py::test_database_config_optional_defaults` |
| REQ-config-03 | TC-config-04, TC-config-05 | `tests/test_config.py::test_auth_config_defaults`、`::test_auth_config_missing_enabled` |
| REQ-config-04 | TC-config-06 | `tests/test_config.py::test_dynamic_tools_config_default_disabled` |
| REQ-config-05 | TC-config-07 | `tests/test_config.py::test_app_config_all_defaults` |
| REQ-config-06 | TC-config-08 ~ TC-config-13 | `tests/test_config.py::test_rag_chunking_config_defaults`、`::test_auto_merging_config_defaults`、`::test_rag_retrieval_config_required_and_defaults`、`::test_contextual_retrieval_config_defaults`、`::test_rerank_config_defaults`、`::test_indexing_config_defaults` |
| REQ-config-07 | TC-config-14, TC-config-15 | `tests/test_config.py::test_rag_config_nested_assembly`、`::test_config_model_full_tree` |
| REQ-config-08 | TC-config-16 | `tests/test_config.py::test_config_model_missing_section` |
| REQ-config-09 | TC-config-17 | `tests/test_config.py::test_modules_config_extra_allowed` |
| REQ-config-10 | TC-config-18 | `tests/test_config.py::test_validate_config_path_allows_relative_paths` |
| REQ-config-11 | TC-config-19, TC-config-20 | `tests/test_config.py::test_validate_config_path_rejects_traversal`、`::test_validate_config_path_rejects_absolute_outside` |
| REQ-config-12 | TC-config-21 | `tests/test_config.py::test_validate_config_path_rejects_bad_extension` |
| REQ-config-13 | TC-config-22 | `tests/test_config.py::test_get_config_valid_yaml` |
| REQ-config-14 | TC-config-23 | `tests/test_config.py::test_get_config_env_var_placeholder_not_expanded` |
| REQ-config-15 | TC-config-24, TC-config-25, TC-config-26 | `tests/test_config.py::test_get_config_invalid_schema_returns_none`、`::test_get_config_malformed_yaml_returns_none`、`::test_get_config_missing_file_returns_none` |
| REQ-config-16 | TC-config-27, TC-config-28 | `tests/test_config.py::test_set_config_loads_enabled_module_configs`、`::test_set_config_skips_invalid_module_config` |
| REQ-config-17 | TC-config-29 | `tests/test_config.py::test_getters_return_none_before_load` |
