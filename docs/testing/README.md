# Agentic RAG — 測試流程與文件


本目錄定義 Agentic RAG MCP Server 的**測試流程、文件規範與可追溯性**。目標:每一個測試案例
都能回溯到一條明確的功能需求,每一次程式變更都有對應的測試把關。

測試方法論參照 [FuSa Group《軟體測試方法論完整指南》](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/)
(左移測試、五層測試類型、功能/非功能分類、測試結束條件)。

---

## 文件地圖

| 文件 | 用途 |
|------|------|
| [TEST_PLAN.md](TEST_PLAN.md) | 測試計畫書:範圍、時程、測試類型、進出場準則、覆蓋率目標 |
| [TEST_STRATEGY.md](TEST_STRATEGY.md) | 測試策略:開發方法論定位、**指南五層級**(靜態分析/單元/整合/系統/驗收)、功能/非功能 5+5 分類、手動 vs 自動化、AI 角色、**測試結束條件** |
| [TEST_SUMMARY_REPORT.md](TEST_SUMMARY_REPORT.md) | **測試總報告**:執行結果、覆蓋摘要、缺陷與允收例外、結論 |
| [ENVIRONMENTS.md](ENVIRONMENTS.md) | 測試環境分離(Development / Staging / Production) |
| [COVERAGE.md](COVERAGE.md) | **測試覆蓋索引**:全部測試項對應模組與文件狀態(由 `pytest --collect-only` 產生) |
| [defect-reports/](defect-reports/) | **缺陷報告**:每份缺陷一單(含範本) |
| [templates/SPEC_TEMPLATE.md](templates/SPEC_TEMPLATE.md) | 需求規格書(Spec)範本 |
| [templates/TEST_CASE_TEMPLATE.md](templates/TEST_CASE_TEMPLATE.md) | 測試案例(Test Case)範本 |
| [templates/DEFECT_REPORT_TEMPLATE.md](templates/DEFECT_REPORT_TEMPLATE.md) | 缺陷報告(Defect Report)範本 |
| [specs/](specs/) | 各模組需求規格書 |
| [test-cases/](test-cases/) | 各模組測試案例(對應 specs/) |
| [../../ROADMAP.md](../../ROADMAP.md) | 開發進度與測試工程里程碑 |

---

## 流程總覽(左移:需求 → 案例 → 腳本 → 把關)

```
需求 (Spec)  ──►  測試案例 (Test Case)  ──►  測試腳本 (pytest)  ──►  覆蓋率門檻
   REQ-xxx           TC-xxx                    test_*.py           fail_under(CI 規劃中)
     │                  │                          │
     └──────────────────┴──────────────────────────┘
              可追溯性 (Traceability)
```

1. **需求先行(左移)**:任何功能都先在 `specs/` 有一條 `REQ-<模組>-<編號>` 的需求。
2. **案例基於需求**:`test-cases/` 的每個 `TC-<模組>-<編號>` 標註它驗證哪條 `REQ`。
3. **腳本實作案例**:`tests/test_*.py` 的測試函式 docstring 標註 `TC` 編號。
4. **覆蓋率把關**:`uv run pytest --cov` 低於門檻非零退出;CI pipeline 見 ROADMAP。

---

## 可追溯性矩陣(Traceability Matrix)

| 模組 | Spec | Test Cases | 測試腳本 | 狀態 |
|------|------|-----------|---------|------|
| hierarchy(階層分塊 / token 估算) | [SPEC-hierarchy](specs/SPEC-hierarchy.md) | [TC-hierarchy](test-cases/TC-hierarchy.md) | `test_hierarchy.py` | ✅ |
| exceptions(Domain 例外 → HTTP) | [SPEC-exceptions](specs/SPEC-exceptions.md) | [TC-exceptions](test-cases/TC-exceptions.md) | `test_exceptions.py` | ✅ |
| context-generator(語系防禦 / fallback) | [SPEC-context-generator](specs/SPEC-context-generator.md) | [TC-context-generator](test-cases/TC-context-generator.md) | `test_context_generator.py` | ✅ |
| cache(InMemoryCache / CacheKeys) | [SPEC-cache](specs/SPEC-cache.md) | [TC-cache](test-cases/TC-cache.md) | `test_cache_service.py` | ✅ |
| file-storage(檔名安全 / 落地) | [SPEC-file-storage](specs/SPEC-file-storage.md) | [TC-file-storage](test-cases/TC-file-storage.md) | `test_file_storage.py` | ✅ |
| runtime-paths(部署路徑解析) | [SPEC-runtime-paths](specs/SPEC-runtime-paths.md) | [TC-runtime-paths](test-cases/TC-runtime-paths.md) | `test_runtime_paths.py` | ✅ |
| db-bootstrap(DB URL 解析) | [SPEC-db-bootstrap](specs/SPEC-db-bootstrap.md) | [TC-db-bootstrap](test-cases/TC-db-bootstrap.md) | `test_db_bootstrap.py` | ✅ |
| mcp-format(MCP 輸出格式化) | [SPEC-mcp-format](specs/SPEC-mcp-format.md) | [TC-mcp-format](test-cases/TC-mcp-format.md) | `test_mcp_format_helpers.py` | ✅ |
| config(YAML 載入 / Pydantic models) | [SPEC-config](specs/SPEC-config.md) | [TC-config](test-cases/TC-config.md) | `test_config.py` | ✅ |
| auth(Token 驗證快取 / models) | [SPEC-auth](specs/SPEC-auth.md) | [TC-auth](test-cases/TC-auth.md) | `test_auth_unit.py` | ✅ |
| middleware(request_id / error handler) | [SPEC-middleware](specs/SPEC-middleware.md) | [TC-middleware](test-cases/TC-middleware.md) | `test_middleware.py` | ✅ |
| adapter-models(adapter DTO) | [SPEC-adapter-models](specs/SPEC-adapter-models.md) | [TC-adapter-models](test-cases/TC-adapter-models.md) | `test_adapter_models.py` | ✅ |
| api-models(request/response schema) | [SPEC-api-models](specs/SPEC-api-models.md) | [TC-api-models](test-cases/TC-api-models.md) | `test_api_models.py` | ✅ |
| RAG pipeline(indexer / query / job manager) | — | — | 整合測試範疇(ROADMAP) | ⏳ |
| API routes / adapter 業務層 | — | — | 整合測試範疇(ROADMAP) | ⏳ |

> 標 ⏳ 的模組需要 Postgres(pgvector)/ vLLM / GPU,屬**整合/系統測試**範疇
> (見 [TEST_STRATEGY.md](TEST_STRATEGY.md) 2.3-2.4 與 ROADMAP),目前以部署環境
> 手動驗證 + `scripts/` 腳本涵蓋,不納入單元覆蓋率統計(`pyproject.toml` omit 清單)。

---

## 新增測試的標準流程

1. 在 `specs/SPEC-<模組>.md` 新增或更新 `REQ-<模組>-<編號>`(用範本)。
2. 在 `test-cases/TC-<模組>.md` 寫對應 `TC-<模組>-<編號>`(輸入 / 步驟 / 預期結果)。
3. 在 `tests/test_<模組>.py` 實作,docstring 標 TC 編號。
4. `uv run pytest --cov` 確認全綠且覆蓋率不降。
5. 更新本 README 矩陣與 [COVERAGE.md](COVERAGE.md)。
