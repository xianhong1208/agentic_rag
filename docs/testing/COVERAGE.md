# Agentic RAG — 測試覆蓋索引 (Coverage Index)


由 `uv run pytest --collect-only -q` 與 `--cov` 報告產生;每次新增測試後更新。
執行日期:**2026-07-09**;測試總數:**274**;單元範疇行覆蓋率:**93%**(門檻 85,`pyproject.toml fail_under`)。

---

## 測試檔 ↔ 模組 ↔ 文件對應

| 測試腳本 | 測試數 | 受測模組 | 模組覆蓋率 | Spec | Test Cases |
|---------|-------|---------|-----------|------|-----------|
| `test_file_storage.py` | 44 | `src/storage/file_storage.py` | 88% | [SPEC-file-storage](specs/SPEC-file-storage.md) | [TC-file-storage](test-cases/TC-file-storage.md) |
| `test_context_generator.py` | 36 | `src/domain/rag/context_generator.py` | 91% | [SPEC-context-generator](specs/SPEC-context-generator.md) | [TC-context-generator](test-cases/TC-context-generator.md) |
| `test_exceptions.py` | 32 | `src/domain/exceptions.py` | 100% | [SPEC-exceptions](specs/SPEC-exceptions.md) | [TC-exceptions](test-cases/TC-exceptions.md) |
| `test_config.py` | 29 | `src/config/model.py`、`config_manager.py` | 100% / 96% | [SPEC-config](specs/SPEC-config.md) | [TC-config](test-cases/TC-config.md) |
| `test_cache_service.py` | 26 | `src/infrastructure/cache/cache_service.py` | 95% | [SPEC-cache](specs/SPEC-cache.md) | [TC-cache](test-cases/TC-cache.md) |
| `test_auth_unit.py` | 18 | `src/auth/model.py`、`remote_auth.py` | 100% / 85% | [SPEC-auth](specs/SPEC-auth.md) | [TC-auth](test-cases/TC-auth.md) |
| `test_api_models.py` | 18 | `src/api/router/response.py` | 100% | [SPEC-api-models](specs/SPEC-api-models.md) | [TC-api-models](test-cases/TC-api-models.md) |
| `test_mcp_format_helpers.py` | 16 | `src/fastmcp_tools/agentic_tools.py`(格式化純函式) | —(omit,整合範疇模組) | [SPEC-mcp-format](specs/SPEC-mcp-format.md) | [TC-mcp-format](test-cases/TC-mcp-format.md) |
| `test_hierarchy.py` | 16 | `src/domain/rag/hierarchy.py` | 98% | [SPEC-hierarchy](specs/SPEC-hierarchy.md) | [TC-hierarchy](test-cases/TC-hierarchy.md) |
| `test_middleware.py` | 13 | `src/middleware/request_id.py`、`error_handler.py` | 100% / 89% | [SPEC-middleware](specs/SPEC-middleware.md) | [TC-middleware](test-cases/TC-middleware.md) |
| `test_runtime_paths.py` | 10 | `src/utils/runtime_paths.py` | 67% | [SPEC-runtime-paths](specs/SPEC-runtime-paths.md) | [TC-runtime-paths](test-cases/TC-runtime-paths.md) |
| `test_adapter_models.py` | 10 | `src/adapter/model.py` | 100% | [SPEC-adapter-models](specs/SPEC-adapter-models.md) | [TC-adapter-models](test-cases/TC-adapter-models.md) |
| `test_db_bootstrap.py` | 6 | `src/utils/db_bootstrap.py::_parse_db_url` | —(omit,連線類函式屬整合範疇) | [SPEC-db-bootstrap](specs/SPEC-db-bootstrap.md) | [TC-db-bootstrap](test-cases/TC-db-bootstrap.md) |

## 覆蓋率明細(`--cov` 摘要,2026-07-09)

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

未覆蓋行說明(主要類別):
- `remote_auth.py` 85%:未覆蓋處為真實網路呼叫的深層錯誤分支(整合範疇)。
- `runtime_paths.py` 67%:Nuitka/frozen 部署專屬路徑(`sys.frozen`、onefile 父程序偵測),
  單元環境無法真實觸發,已以 mock 涵蓋主要分支,其餘屬部署驗證範疇。
- `file_storage.py` 88%:實體磁碟錯誤(權限/IO error)分支。

> omit 模組(整合/系統範疇)完整清單與理由見 `pyproject.toml [tool.coverage.run]`。
