# SPEC-config: Configuration Models and Configuration Management


| Item | Content |
|------|------|
| Module | `src/config/model.py`, `src/config/config_manager.py` |
| Test | `tests/test_config.py` |
| Version | 0.1.0 |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

`src/config/model.py` defines 24 Pydantic v2 configuration models (this SPEC covers a representative 12+: the ConfigModel root tree, Server/Database/Auth/App/Modules, and the RAG-related submodels).
`src/config/config_manager.py` is responsible for: path-safety validation (allowlist + path-traversal defense), YAML loading, Pydantic parsing, and safe dictionary access to module configuration.
Out of scope: environment-variable expansion (the `${VAR:-default}` placeholder in YAML is **not** expanded and is kept verbatim), and hot config reload.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-config-01 | ServerConfig requires all three fields (host/port/transport) with automatic type coercion | A complete config is buildable and a port string coerces to int; a missing field raises ValidationError |
| REQ-config-02 | DatabaseConfig connection fields are required; host/port/database/user/password are optional and default to None | Building with only the six required fields succeeds; optional fields are all None |
| REQ-config-03 | AuthConfig requires only enabled; connection settings have defaults (cache_ttl=60, request_timeout=5.0, retry_count=2) | Building with only enabled succeeds and defaults are correct; missing enabled raises ValidationError |
| REQ-config-04 | DynamicToolsConfig.enabled defaults to False | Building with no arguments yields enabled=False |
| REQ-config-05 | AppConfig gives every field a default (name=Agentic RAG, version=0.0.0, tool_prefix=Agentic, etc.) | Building with no arguments succeeds and defaults are correct |
| REQ-config-06 | RAG-related submodel defaults are correct: Chunking (max_chunk_size=2000, chunk_overlap=50), AutoMerging (enabled=True, threshold=0.5), Retrieval (sparse=12, alpha=0.75, simple), ContextualRetrieval (apply_to=all), Rerank (disabled), Indexing (100/1800/21600) | Building each model with only required fields yields defaults matching the source |
| REQ-config-07 | RAGConfig / ConfigModel support nested dict assembly; optional subsections default to None | Nested dicts are converted into the corresponding submodels; rag/llm/rerank etc. are None when omitted |
| REQ-config-08 | ConfigModel rejects construction when any required section (e.g. server) is missing | Raises ValidationError localized to the missing section |
| REQ-config-09 | ModulesConfig is extra="allow", permitting dynamic module sections | Extra keys do not error and are preserved by model_dump |
| REQ-config-10 | `_validate_config_path` allows relative paths within cwd (root-level files, config/, any subdirectory) | Returns a Path without raising |
| REQ-config-11 | `_validate_config_path` rejects paths resolving outside cwd (`../`, external absolute paths) | Raises ValueError with a message containing "outside the allowed base directory" |
| REQ-config-12 | `_validate_config_path` allows only .yaml/.yml extensions | Other extensions raise ValueError |
| REQ-config-13 | `get_config(path)` loads valid YAML and returns a ConfigModel; the class getters retrieve each section | Each getter value matches the YAML content; omitted fields fall back to Pydantic defaults |
| REQ-config-14 | The `${VAR:-default}` placeholder in YAML is not expanded and is kept verbatim (current behavior) | Even when the environment variable is set, the loaded result is the literal string |
| REQ-config-15 | On invalid config (schema mismatch / YAML syntax error / missing file), `get_config` returns None without raising | All three scenarios return None; on syntax error and missing file, `Config.get_config()` is `{}` |
| REQ-config-16 | Detailed config for enabled modules loads into a safe dictionary queryable via `get_module_model`; disabled/failed loads return None | A valid module returns ModuleConfig; disabled returns None; a broken module is skipped without affecting the main config |
| REQ-config-17 | Before config is loaded, all getters return None | All 8 getters return None |

## 3. Non-Functional Requirements

- Path allowlist validation must run before file reads, preventing path-traversal attacks from reading arbitrary files.
- Module config must always be accessed through the `_module_configs` dictionary and never via `setattr` (attribute-injection defense).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| YAML file does not exist | `get_config` returns None (FileNotFoundError is swallowed by an internal catch-all, see §5 note) |
| YAML syntax error | `_config` is reset to `{}`, `get_config` returns None |
| YAML missing a required section | Pydantic validation failure is swallowed, `get_config` returns None |
| `../` path traversal | ValueError |
| Non-.yaml/.yml extension | ValueError |
| A single module config missing a required field | That module is skipped; the main config is unaffected |

## 5. Dependencies & Assumptions

- Depends on `yaml.safe_load` and Pydantic v2; no DB / network dependency.
- Tests control the base directory with `tmp_path` + `monkeypatch.chdir` (path validation is relative to cwd).
- `Config` holds class-level state; tests must reset `_config`/`_config_model`/`_module_configs` before and after.
- **Source notes (likely bugs; tests pin the current behavior)**:
  1. The `_load_config` docstring claims a missing file raises FileNotFoundError, but the raise sits inside the try block and is caught by `except Exception`, so it never propagates.
  2. If the project YAML uses the `${VAR:-default}` placeholder, the config layer does not expand it (no expandvars/envsubst logic).

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-config-01 | TC-config-01, TC-config-02 | `tests/test_config.py::test_server_config_required_and_coercion`, `::test_server_config_missing_required` |
| REQ-config-02 | TC-config-03 | `tests/test_config.py::test_database_config_optional_defaults` |
| REQ-config-03 | TC-config-04, TC-config-05 | `tests/test_config.py::test_auth_config_defaults`, `::test_auth_config_missing_enabled` |
| REQ-config-04 | TC-config-06 | `tests/test_config.py::test_dynamic_tools_config_default_disabled` |
| REQ-config-05 | TC-config-07 | `tests/test_config.py::test_app_config_all_defaults` |
| REQ-config-06 | TC-config-08 ~ TC-config-13 | `tests/test_config.py::test_rag_chunking_config_defaults`, `::test_auto_merging_config_defaults`, `::test_rag_retrieval_config_required_and_defaults`, `::test_contextual_retrieval_config_defaults`, `::test_rerank_config_defaults`, `::test_indexing_config_defaults` |
| REQ-config-07 | TC-config-14, TC-config-15 | `tests/test_config.py::test_rag_config_nested_assembly`, `::test_config_model_full_tree` |
| REQ-config-08 | TC-config-16 | `tests/test_config.py::test_config_model_missing_section` |
| REQ-config-09 | TC-config-17 | `tests/test_config.py::test_modules_config_extra_allowed` |
| REQ-config-10 | TC-config-18 | `tests/test_config.py::test_validate_config_path_allows_relative_paths` |
| REQ-config-11 | TC-config-19, TC-config-20 | `tests/test_config.py::test_validate_config_path_rejects_traversal`, `::test_validate_config_path_rejects_absolute_outside` |
| REQ-config-12 | TC-config-21 | `tests/test_config.py::test_validate_config_path_rejects_bad_extension` |
| REQ-config-13 | TC-config-22 | `tests/test_config.py::test_get_config_valid_yaml` |
| REQ-config-14 | TC-config-23 | `tests/test_config.py::test_get_config_env_var_placeholder_not_expanded` |
| REQ-config-15 | TC-config-24, TC-config-25, TC-config-26 | `tests/test_config.py::test_get_config_invalid_schema_returns_none`, `::test_get_config_malformed_yaml_returns_none`, `::test_get_config_missing_file_returns_none` |
| REQ-config-16 | TC-config-27, TC-config-28 | `tests/test_config.py::test_set_config_loads_enabled_module_configs`, `::test_set_config_skips_invalid_module_config` |
| REQ-config-17 | TC-config-29 | `tests/test_config.py::test_getters_return_none_before_load` |
