# Agentic RAG — Test Coverage Index


Generated from `uv run pytest --collect-only -q` and the `--cov` report; updated after each new test is added.
Run date: **2026-07-09**; total tests: **274**; unit-scope line coverage: **93%** (threshold 85, `pyproject.toml fail_under`).

---

## Test File ↔ Module ↔ Doc Mapping

| Test script | Tests | Module under test | Module coverage | Spec | Test Cases |
|---------|-------|---------|-----------|------|-----------|
| `test_file_storage.py` | 44 | `src/storage/file_storage.py` | 88% | [SPEC-file-storage](specs/SPEC-file-storage.md) | [TC-file-storage](test-cases/TC-file-storage.md) |
| `test_context_generator.py` | 36 | `src/domain/rag/context_generator.py` | 91% | [SPEC-context-generator](specs/SPEC-context-generator.md) | [TC-context-generator](test-cases/TC-context-generator.md) |
| `test_exceptions.py` | 32 | `src/domain/exceptions.py` | 100% | [SPEC-exceptions](specs/SPEC-exceptions.md) | [TC-exceptions](test-cases/TC-exceptions.md) |
| `test_config.py` | 29 | `src/config/model.py`, `config_manager.py` | 100% / 96% | [SPEC-config](specs/SPEC-config.md) | [TC-config](test-cases/TC-config.md) |
| `test_cache_service.py` | 26 | `src/infrastructure/cache/cache_service.py` | 95% | [SPEC-cache](specs/SPEC-cache.md) | [TC-cache](test-cases/TC-cache.md) |
| `test_auth_unit.py` | 18 | `src/auth/model.py`, `remote_auth.py` | 100% / 85% | [SPEC-auth](specs/SPEC-auth.md) | [TC-auth](test-cases/TC-auth.md) |
| `test_api_models.py` | 18 | `src/api/router/response.py` | 100% | [SPEC-api-models](specs/SPEC-api-models.md) | [TC-api-models](test-cases/TC-api-models.md) |
| `test_mcp_format_helpers.py` | 16 | `src/fastmcp_tools/agentic_tools.py` (formatting pure functions) | — (omit, integration-scope module) | [SPEC-mcp-format](specs/SPEC-mcp-format.md) | [TC-mcp-format](test-cases/TC-mcp-format.md) |
| `test_hierarchy.py` | 16 | `src/domain/rag/hierarchy.py` | 98% | [SPEC-hierarchy](specs/SPEC-hierarchy.md) | [TC-hierarchy](test-cases/TC-hierarchy.md) |
| `test_middleware.py` | 13 | `src/middleware/request_id.py`, `error_handler.py` | 100% / 89% | [SPEC-middleware](specs/SPEC-middleware.md) | [TC-middleware](test-cases/TC-middleware.md) |
| `test_runtime_paths.py` | 10 | `src/utils/runtime_paths.py` | 67% | [SPEC-runtime-paths](specs/SPEC-runtime-paths.md) | [TC-runtime-paths](test-cases/TC-runtime-paths.md) |
| `test_adapter_models.py` | 10 | `src/adapter/model.py` | 100% | [SPEC-adapter-models](specs/SPEC-adapter-models.md) | [TC-adapter-models](test-cases/TC-adapter-models.md) |
| `test_db_bootstrap.py` | 6 | `src/utils/db_bootstrap.py::_parse_db_url` | — (omit, connection-type functions are integration-scope) | [SPEC-db-bootstrap](specs/SPEC-db-bootstrap.md) | [TC-db-bootstrap](test-cases/TC-db-bootstrap.md) |

## Coverage Detail (`--cov` summary, 2026-07-09)

```
Name                                        Stmts   Miss  Cover
src/adapter/model.py                           59      0   100%
src/api/router/response.py                    188      0   100%
src/auth/model.py                              25      0   100%
src/auth/remote_auth.py                       132     20    85%
src/config/config_manager.py                  108      4    96%
src/config/model.py                           137      0   100%
src/domain/exceptions.py                       63      0   100%
src/domain/rag/context_generator.py           130     12    91%
src/domain/rag/hierarchy.py                    51      1    98%
src/infrastructure/cache/cache_service.py     129      7    95%
src/middleware/error_handler.py                28      3    89%
src/middleware/request_id.py                    9      0   100%
src/storage/file_storage.py                   120     14    88%
src/utils/runtime_paths.py                     60     20    67%
TOTAL                                        1243     81    93%
```

Uncovered-line notes (main categories):
- `remote_auth.py` 85%: the uncovered parts are deep error branches of real network calls (integration scope).
- `runtime_paths.py` 67%: Nuitka/frozen deployment-specific paths (`sys.frozen`, onefile parent-process detection),
  which a unit environment cannot genuinely trigger; the main branches are covered via mocks and the rest fall under deployment verification.
- `file_storage.py` 88%: physical-disk error (permission / IO error) branches.

> For the full list of omitted modules (integration/system scope) and the rationale, see `pyproject.toml [tool.coverage.run]`.
