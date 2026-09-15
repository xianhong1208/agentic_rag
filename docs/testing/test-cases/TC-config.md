# TC-config: Configuration Models and Configuration Management Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-config](../specs/SPEC-config.md) |
| Test level | Unit |
| Test script | `tests/test_config.py` |

---

## TC-config-01: ServerConfig required fields complete and type coercion

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `host="0.0.0.0", port="8080", transport="sse"` |
| **Test steps** | 1. Create ServerConfig<br>2. Check each field value |
| **Expected result** | Created successfully; the string port "8080" is coerced to int 8080 |
| **Implementation** | `tests/test_config.py::test_server_config_required_and_coercion` |

## TC-config-02: ServerConfig missing a required field

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | Only `host="0.0.0.0"` |
| **Test steps** | 1. Create ServerConfig and capture the exception |
| **Expected result** | ValidationError; the set of missing fields = {port, transport} |
| **Implementation** | `tests/test_config.py::test_server_config_missing_required` |

## TC-config-03: DatabaseConfig optional fields default to None

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | Only url/echo/pool_size/max_overflow/pool_timeout/pool_recycle |
| **Test steps** | 1. Create DatabaseConfig<br>2. Check the optional fields |
| **Expected result** | host/port/database/user/password are all None |
| **Implementation** | `tests/test_config.py::test_database_config_optional_defaults` |

## TC-config-04: AuthConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `enabled=True` |
| **Expected result** | token_server_url=None, cache_ttl=60, request_timeout=5.0, retry_count=2, dynamic_tools=None |
| **Implementation** | `tests/test_config.py::test_auth_config_defaults` |

## TC-config-05: AuthConfig missing enabled

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-03 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | ValidationError |
| **Implementation** | `tests/test_config.py::test_auth_config_missing_enabled` |

## TC-config-06: DynamicToolsConfig disabled by default

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-04 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | enabled is False |
| **Implementation** | `tests/test_config.py::test_dynamic_tools_config_default_disabled` |

## TC-config-07: AppConfig all defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-05 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | name="Agentic RAG", version="0.0.0", title="Agentic RAG MCP Server", lifespan=None, tool_prefix="Agentic" |
| **Implementation** | `tests/test_config.py::test_app_config_all_defaults` |

## TC-config-08: RAGChunkingConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | default_chunk_size/default_overlap/hierarchy_sizes=None, max_chunk_size=2000, chunk_overlap=50 |
| **Implementation** | `tests/test_config.py::test_rag_chunking_config_defaults` |

## TC-config-09: AutoMergingConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | enabled=True, merge_threshold=0.5 |
| **Implementation** | `tests/test_config.py::test_auto_merging_config_defaults` |

## TC-config-10: RAGRetrievalConfig required fields + defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | `default_top_k=10, default_similarity_cutoff=0.25, hybrid_search=True` |
| **Expected result** | sparse_top_k=12, hybrid_alpha=0.75, text_search_config="simple", return_resource_files=False, auto_merging=None, expand_context_default=True, expand_context_neighbors=2 |
| **Implementation** | `tests/test_config.py::test_rag_retrieval_config_required_and_defaults` |

## TC-config-11: ContextualRetrievalConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | enabled=False, max_context_length=150, max_concurrent=5, apply_to="all" |
| **Implementation** | `tests/test_config.py::test_contextual_retrieval_config_defaults` |

## TC-config-12: RerankConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | enabled=False, model="BAAI/bge-reranker-v2-m3", base_url="http://localhost:8787", top_n=None, score_threshold=0.0 |
| **Implementation** | `tests/test_config.py::test_rerank_config_defaults` |

## TC-config-13: IndexingConfig defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-06 |
| **Level** | Unit |
| **Test input** | No parameters |
| **Expected result** | max_concurrent_jobs=4 (GPU serialization), per_file_timeout_seconds=864000, job_timeout_seconds=864000 (both 10 days, to accommodate OCR of large files on slow machines) |
| **Implementation** | `tests/test_config.py::test_indexing_config_defaults` |

## TC-config-14: RAGConfig nested assembly

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-07 |
| **Level** | Unit |
| **Test input** | embedding/chunking/retrieval/vector_store passed as nested dicts, with retrieval containing an auto_merging dict |
| **Expected result** | Nested dicts are converted to the corresponding submodels; llm/rerank/docling/indexing are None when not provided; enabled defaults to True |
| **Implementation** | `tests/test_config.py::test_rag_config_nested_assembly` |

## TC-config-15: ConfigModel main-tree assembly

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-07 |
| **Level** | Unit |
| **Test input** | Nested dicts for the six sections server/database/auth/logging/app/modules |
| **Expected result** | Each section is converted to the corresponding submodel; rag is None when not provided |
| **Implementation** | `tests/test_config.py::test_config_model_full_tree` |

## TC-config-16: ConfigModel missing the server section

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-08 |
| **Level** | Unit |
| **Test input** | A five-section dict missing server |
| **Expected result** | ValidationError with an error loc containing "server" |
| **Implementation** | `tests/test_config.py::test_config_model_missing_section` |

## TC-config-17: ModulesConfig allows extra fields

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-09 |
| **Level** | Unit |
| **Test input** | `enabled=["demo"], demo={"description": "x"}` |
| **Expected result** | Created successfully and model_dump retains the demo section |
| **Implementation** | `tests/test_config.py::test_modules_config_extra_allowed` |

## TC-config-18: path validation allows relative paths within cwd

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-10 |
| **Level** | Unit |
| **Preconditions** | `monkeypatch.chdir(tmp_path)` |
| **Test input** | `config.yaml`, `config/app.yaml`, `sub/dir/x.yml` |
| **Expected result** | All three pass validation and return a Path |
| **Implementation** | `tests/test_config.py::test_validate_config_path_allows_relative_paths` |

## TC-config-19: path validation rejects ../ traversal

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-11 |
| **Level** | Unit |
| **Preconditions** | `monkeypatch.chdir(tmp_path)` |
| **Test input** | `../evil.yaml` |
| **Expected result** | ValueError, message containing "outside the allowed base directory" |
| **Implementation** | `tests/test_config.py::test_validate_config_path_rejects_traversal` |

## TC-config-20: path validation rejects external absolute paths

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-11 |
| **Level** | Unit |
| **Preconditions** | `monkeypatch.chdir(tmp_path)` |
| **Test input** | `/etc/passwd.yaml` |
| **Expected result** | ValueError, message containing "outside the allowed base directory" |
| **Implementation** | `tests/test_config.py::test_validate_config_path_rejects_absolute_outside` |

## TC-config-21: path validation rejects non-YAML extensions

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-12 |
| **Level** | Unit |
| **Test input** | `config.txt` |
| **Expected result** | ValueError, message containing "extension" |
| **Implementation** | `tests/test_config.py::test_validate_config_path_rejects_bad_extension` |

## TC-config-22: get_config loads a valid YAML

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-13 |
| **Level** | Unit |
| **Preconditions** | A complete, valid config.yaml is written into tmp_path and chdir'd |
| **Test input** | `get_config("config.yaml")` |
| **Test steps** | 1. Call get_config<br>2. Check the returned ConfigModel<br>3. Check each getter such as Config.get_server_config |
| **Expected result** | Returns a ConfigModel; server.port=8080; auth.cache_ttl filled with the default 60; the get_config() dict matches the YAML |
| **Implementation** | `tests/test_config.py::test_get_config_valid_yaml` |

## TC-config-23: ${VAR:-default} placeholder is not expanded

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-14 |
| **Level** | Unit |
| **Preconditions** | `monkeypatch.setenv("TEST_DB_URL", ...)`; the YAML's database.url is written as `${TEST_DB_URL:-postgresql://fallback/db}` |
| **Test input** | `get_config("config.yaml")` |
| **Expected result** | `model.database.url` is the literal value `${TEST_DB_URL:-postgresql://fallback/db}` (not expanded) |
| **Implementation** | `tests/test_config.py::test_get_config_env_var_placeholder_not_expanded` |

## TC-config-24: schema-mismatched YAML returns None

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-15 |
| **Level** | Unit |
| **Test input** | YAML containing only `server: {host: only-host}` |
| **Expected result** | get_config returns None; get_config_model is also None (the exception is swallowed internally) |
| **Implementation** | `tests/test_config.py::test_get_config_invalid_schema_returns_none` |

## TC-config-25: malformed YAML returns None

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-15 |
| **Level** | Unit |
| **Test input** | `server: [unclosed\n  :::` |
| **Expected result** | get_config returns None; `Config.get_config()` is `{}` |
| **Implementation** | `tests/test_config.py::test_get_config_malformed_yaml_returns_none` |

## TC-config-26: nonexistent file returns None (current behavior)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-15 |
| **Level** | Unit |
| **Test input** | `get_config("no_such_file.yaml")` |
| **Expected result** | Returns None and does not raise FileNotFoundError (swallowed by the catch-all in `_load_config`; the docstring and implementation are inconsistent, see SPEC section 5) |
| **Implementation** | `tests/test_config.py::test_get_config_missing_file_returns_none` |

## TC-config-27: enabled module config loading

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-16 |
| **Level** | Unit |
| **Preconditions** | The YAML modules section contains enabled=[demo] and the demo detailed config (api_router + mcp_tools: null + description) |
| **Test steps** | 1. Config.set_config<br>2. get_module_model("demo")<br>3. get_module_model("not_enabled") |
| **Expected result** | demo returns ModuleConfig(prefix="/api/demo", mcp_tools=None); a non-enabled module returns None |
| **Implementation** | `tests/test_config.py::test_set_config_loads_enabled_module_configs` |

## TC-config-28: broken module config is skipped

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-16 |
| **Level** | Unit |
| **Preconditions** | The broken module in the YAML is missing the required api_router/mcp_tools |
| **Expected result** | The main config loads successfully (get_config_model is not None); get_module_model("broken") returns None |
| **Implementation** | `tests/test_config.py::test_set_config_skips_invalid_module_config` |

## TC-config-29: getters all return None before loading

| Field | Content |
|-------|---------|
| **Requirement** | REQ-config-17 |
| **Level** | Unit |
| **Preconditions** | Config state has been reset (autouse fixture) |
| **Expected result** | get_config_model / get_server_config / get_database_config / get_auth_config / get_logging_config / get_app_config_model / get_modules_config / get_module_model all return None |
| **Implementation** | `tests/test_config.py::test_getters_return_none_before_load` |

> Authoring principles: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
