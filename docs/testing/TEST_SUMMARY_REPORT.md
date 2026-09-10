# Agentic RAG — 測試總報告 (Test Summary Report)


| 項目 | 內容 |
|------|------|
| 專案 / 版本 | Agentic RAG MCP Server(`pyproject.toml` 0.1.0) |
| 分支 | `feat/rag-robustness` |
| 執行日期 | 2026-07-09 |
| 測試環境 | 單元層:零外部依賴(無 DB / vLLM / GPU / 網路);pytest + pytest-asyncio + pytest-mock + pytest-cov |
| 方法論依據 | [FuSa Group 軟體測試方法論指南](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/) |

---

## 1. 執行摘要

| 指標 | 數量 |
|------|------|
| 測試項總數 | **274** |
| 通過 (Passed) | **274** |
| 失敗 (Failed) | 0 |
| 通過率 | **100%** |
| 文件登記率 | 100%(13 模組 REQ → TC → pytest 三層對應,見 [COVERAGE.md](COVERAGE.md)) |
| **行覆蓋率 (Line Coverage)** | **93%**(單元範疇,`--cov=src` + omit 清單;門檻 85% 由 pyproject `fail_under` 把關) |

```
274 passed in 17.97s   (uv run pytest --cov -q)
```

## 2. 覆蓋範圍

**單元層(本報告)**:分塊階層 / token 估算、上下文生成語系防禦、Domain 例外 → HTTP 對應、
InMemoryCache 與快取 key、檔名安全驗證與檔案落地、部署路徑解析、DB URL 解析、
YAML 設定載入與 Pydantic models、Token 驗證快取(sha256、TTL、mock httpx)、
middleware(request_id / error handler)、adapter DTO、API request/response schema、
MCP 輸出格式化(CJK 寬度)。

**整合 / 系統層(不在本報告)**:RAG pipeline(Docling / embedding / pgvector)、
API 路由全鏈路、`IndexingJobManager`、MCP 工具註冊——需外部服務,以部署環境
驗證,自動化列於 [ROADMAP](../../ROADMAP.md);omit 清單見 `pyproject.toml`。

## 3. 覆蓋率目標達成情況(TEST_PLAN 第 5 節)

| 目標 | 實測 | 判定 |
|------|------|------|
| 單元範疇整體 ≥ 80% | **93%** | ✅(門檻已上調至 85 並留 8% 緩衝) |
| exceptions(安全關鍵)≥ 90% | 100% | ✅ |
| 檔名驗證邏輯(安全關鍵)≥ 90% | `_validate_safe_name` 全分支覆蓋;file_storage 全檔 88%(缺實體 IO 錯誤分支) | ✅(驗證邏輯達標;IO 分支屬整合範疇) |
| auth 快取(安全關鍵)≥ 90% | remote_auth 85%(缺真實網路深層錯誤分支) | 🔶 未達 90 — 登記為改善項,缺口屬整合範疇行為 |
| runtime_paths | 67%(Nuitka/frozen 部署路徑無法於單元環境真實觸發) | 🔶 已知限制,部署驗證涵蓋 |

## 4. 缺陷與允收例外

**產品缺陷(測試過程發現,均已登記,見 [defect-reports/](defect-reports/README.md)):**

| 編號 | 摘要 | 嚴重度 | 狀態 |
|------|------|--------|------|
| [DEF-2026-001](defect-reports/DEF-2026-001.md) | `_parse_db_url` 未對帳密 percent-decoding(密碼含 `@`/`:` 的部署會登入失敗) | Major | Open |
| [DEF-2026-002](defect-reports/DEF-2026-002.md) | 例外類別 truthiness 判斷 `folder_id=0` 誤當未提供 | Minor | Open |
| [DEF-2026-003](defect-reports/DEF-2026-003.md) | `${VAR:-default}` 環境變數展開未實作,與 README 宣稱不符 | Minor | Open |
| [DEF-2026-004](defect-reports/DEF-2026-004.md) | `_load_config` 吞 FileNotFoundError,設定檔路徑錯誤時靜默啟動 | Minor | Open |

四者皆以「現行行為快照」測試鎖定,修復時翻轉斷言(出場準則:無 Open 的 Blocker/Critical——目前符合)。

**設計風險觀察(非缺陷,見各 DEF 附錄):**
- domain `FileNotFoundError` 遮蔽 Python builtin 同名例外。
- `estimate_tokens` docstring 與實作不一致(0.3 token/char,非 1.3 token/word)。
- `_detect_scripts` 未涵蓋希臘文與 U+0080–U+00BF 字母(mismatch 偵測偏向不 fallback,安全方向)。
- `TokenCreateRequest.expires_in_days: int = None` 應為 `Optional[int]`(顯式傳 None 會 ValidationError)。

**允收例外:** 無(全數通過)。

## 5. 結論

- 單元層 274 項全綠、覆蓋率 93% ≥ 門檻 85%,符合 TEST_PLAN 出場準則,**可合併**。
- 測試過程挖出 2 個真實產品缺陷(1 Major / 1 Minor),證明左移策略有效;
  Major 項(DEF-2026-001)建議於下一個修復週期優先處理。
- 下一步(ROADMAP):CI pipeline 自動把關 → 整合測試自動化 → RAG 品質回歸問答集。
