# Agentic RAG — 測試策略:方法論、層級與工具


> 本策略參照 [FuSa Group《軟體測試方法論完整指南》](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/)
> 之框架制定:開發方法論 → 測試層級 → 功能/非功能分類 → 手動 vs 自動化 → AI 輔助 → 測試結束條件。

---

## 1. 開發方法論定位 (Development Methodology)

指南列出四大方法論:瀑布式 (Waterfall)、敏捷 (Agile)、迭代式 (Iterative)、DevOps 持續測試。

**本專案採「敏捷 + DevOps 持續測試」**:

| 指南概念 | 本專案落地 |
|----------|-----------|
| 敏捷:測試是持續進行的活動 | 每個 feature/fix 分支都伴隨對應測試;不留到「測試階段」才補 |
| DevOps:自動化測試整合於 CI/CD | `pytest --cov` + `fail_under` 門檻作為合併把關(CI pipeline 見 ROADMAP) |
| **左移測試 (Shift-Left)** | 新功能先在 `specs/` 寫需求與驗收準則,再寫測試案例,最後實作 |
| 迭代回饋 | 缺陷回報(`defect-reports/`)驅動下一輪測試補強 |

## 2. 測試層級 (Testing Levels) — 指南五層級

指南定義五個測試類型層級:**靜態分析 → 單元 → 整合 → 系統 → 驗收**。本專案對應:

### 2.1 靜態分析 (Static Analysis)
- **定義**(指南):「在不執行程式的情況下檢測程式碼中的缺陷」。
- **本專案**:Pydantic 型別模型(config / adapter model)提供 import-time 驗證;
  程式審查(code review)為每次合併必經;linter/型別檢查工具導入列於 ROADMAP。

### 2.2 單元測試 (Unit Testing)
- **對象**:最小單位——純邏輯函式 / 類別(如 `hierarchy.build_hierarchy`、token 估算、
  檔名正規化、設定展開)。
- **原則**:**不依賴 DB / vLLM / GPU / 網路**;外部相依以 mock 隔離。
- **範例**:`tests/test_hierarchy.py` 等 `tests/test_*.py`。

### 2.3 整合測試 (Integration Testing)
- **對象**:多模組協同——API 路由 + adapter + DB、索引 pipeline(Docling → chunking →
  embedding → pgvector 寫入)、`IndexingJobManager` 生命週期。
- **基礎設施**:需要 Postgres(pgvector)測試庫與模型服務;**目前以 `scripts/` 手動腳本
  與部署環境驗證為主**,自動化整合測試列於 ROADMAP。

### 2.4 系統測試 (System Testing)
- **對象**:端到端(黑箱):上傳檔案 → 背景索引 → SSE 進度 → 查詢 → 引用來源。
- **現況**:部署環境手動走流程 + MCP client(如 Claude)實測;自動化列於 ROADMAP。

### 2.5 驗收測試 (Acceptance Testing)
- **對象**:使用者角度確認符合商業需求——RAG 回答品質、引用正確性、跨模態檔案支援。
- **現況**:人工驗收(檢索品質本質上需人判);搭配代表性文件集的回歸問答集列於 ROADMAP。

## 3. 功能性 vs 非功能性測試 (指南 5+5 分類)

### 3.1 功能性測試(指南列 5 種)

| 種類 | 本專案應用 |
|------|-----------|
| 單元測試 | 純邏輯層(見 2.2),為目前自動化主力 |
| 整合測試 | 索引/查詢 pipeline 與 DB 層(見 2.3) |
| 系統測試 | 端到端 API + MCP 流程(見 2.4) |
| 驗收測試 | RAG 品質人工驗收(見 2.5) |
| **回歸測試** | 每次變更跑全套 pytest;`fail_under` 覆蓋率門檻防止保護網變薄 |

### 3.2 非功能性測試(指南列 5 種)

| 種類 | 本專案應用 | 現況 |
|------|-----------|------|
| 效能測試 | 索引吞吐(per-file timing audit:`load_ms`/`index_ms`)、查詢延遲 | 🔶 有量測埋點,無自動化基準 |
| 安全性測試 | Token-scoped 隔離(folders/files/vector tables 跨 token 不可見)、上傳檔名/路徑安全 | 🔶 單元層部分涵蓋,滲透測試未排程 |
| 可用性測試 | Landing page / Swagger / SSE 進度可讀性 | 手動 |
| 相容性測試 | 多格式檔案(PDF/Office/音檔/圖檔)、GPU 變體(cuda/rocm/cpu wheel 群組) | 部署環境驗證 |
| 可靠度測試 | Watchdog、restart cleanup、cancel、PARTIAL_SUCCESS、embedding retry | ✅ 為設計核心,單元測試逐步涵蓋 |

## 4. 測試方法 (Methods)

| 方法 | 應用 |
|------|------|
| 黑箱測試 | API 契約(狀態碼 / 回應結構);系統流程 |
| 白箱測試 | 分支覆蓋、錯誤路徑、邊界條件(依 `--cov-report=term-missing` 補洞) |
| 灰箱測試 | 知悉內部結構但以外部行為斷言(如 job 狀態機轉移) |
| 邊界值分析 | chunk token 上限、空文件、單字元、巨表 xlsx、超長檔名 |
| 等價分割 | 合法 / 非法輸入分類(檔案格式白名單、audio container 變體) |

## 5. 手動 vs 自動化測試

指南:「自動化適合回歸測試,手動測試適合可用性與探索式測試,兩者應結合使用。」

| 類型 | 本專案應用 |
|------|-----------|
| 自動化 | **回歸主力**:pytest 單元測試套件 + 覆蓋率門檻;CI 導入後每次提交自動執行 |
| 手動 | RAG 回答品質驗收、跨模態檔案探索式測試、SSE/前端整合體感 |

## 6. AI 在測試中的角色

指南:「AI 是人類能力的倍增器……但 AI 產出的結果必須始終經過審查、驗證與文件化。」

- 本專案測試案例與腳本大量由 AI 輔助生成,**一律經人工審查後合併**。
- AI 依變更範圍建議受影響測試(test selection)。
- 所有 AI 產出的測試都必須在 `test-cases/` 登記(可追溯性),不允許「只有程式碼沒有文件」。

## 7. 測試結束條件 (Exit Criteria) — 指南定義

| 指南條件 | 本專案落地 |
|----------|-----------|
| 所有規劃測試案例執行完成 | `uv run pytest` 全套通過(登記在案例外除外) |
| 需求可追溯性建立 | REQ → TC → `test_*.py` 三層對應(見 README 矩陣) |
| 程式碼覆蓋率達標 | `[tool.coverage.report] fail_under` 門檻(見 TEST_PLAN 第 5 節) |
| 關鍵缺陷修復完成 | `defect-reports/` 無 Open 的 Blocker/Critical |
| 錯誤率降至指定門檻 | 產品缺陷 0 才可發布;測試缺陷須登記 |

## 8. 工具與框架 (Tools & Frameworks)

| 用途 | 工具 | 說明 |
|------|------|------|
| 測試框架 | pytest + pytest-asyncio | `asyncio_mode = "auto"` |
| Mock | pytest-mock / unittest.mock | 外部相依(DB/LLM/embedding)隔離 |
| 覆蓋率 | pytest-cov(coverage.py) | `--cov=src --cov-report=term-missing`,`fail_under` 把關 |
| 型別/驗證 | Pydantic v2 | config 與 API model 的 import-time 靜態把關 |
| 手動驗證 | Swagger UI / curl / MCP client | 整合與系統層(自動化前的過渡) |
