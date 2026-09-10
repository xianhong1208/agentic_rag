# Agentic RAG — 測試計畫書 (Test Plan)


| 項目 | 內容 |
|------|------|
| 專案 | Agentic RAG MCP Server |
| 版本 | 對齊 `pyproject.toml` |
| 文件狀態 | Living document(隨版本更新) |
| 方法論依據 | [FuSa Group 軟體測試方法論指南](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/)(見 [TEST_STRATEGY.md](TEST_STRATEGY.md)) |

---

## 1. 目的

確保 Agentic RAG 在每次變更後,**階層分塊、上下文生成、token 隔離、檔案安全、
索引任務可靠性、設定載入**等核心邏輯維持正確,且新程式碼不破壞既有行為(回歸防護)。

## 2. 範圍

### 納入測試(單元層,自動化)
- **分塊與階層**:leaf/parent hierarchy、token 估算、metadata 傳遞
- **上下文生成防禦**:語系偵測、script mismatch、safe fallback
- **例外對應**:DomainException 家族 → HTTP status
- **快取**:InMemoryCache TTL / pattern 清除、快取 key 生成(token 不留明文)
- **檔案安全**:檔名/資料夾名白名單驗證、路徑跳脫防護、檔案落地
- **設定**:YAML 載入、`${VAR:-default}` 展開、Pydantic 驗證、路徑安全
- **認證單元邏輯**:驗證結果快取(sha256 key、TTL)、request/response models
- **Middleware**:request_id 注入、錯誤處理器狀態碼與 body 結構
- **API schema**:request/response models 驗證與序列化

### 整合/系統層(部署環境驗證,自動化列於 ROADMAP)
- 索引 pipeline(Docling → chunk → embed → pgvector)、`IndexingJobManager` 生命週期
- API 路由 + adapter + DB 全鏈路、SSE 進度、MCP 工具
- 需要 Postgres / vLLM / GPU,暫以部署環境手動流程 + `scripts/` 驗證

### 暫不納入(本階段)
- RAG 回答品質自動評測(回歸問答集列於 ROADMAP)
- 效能 / 壓力測試(有 per-file timing 埋點,基準化列於 ROADMAP)
- 第三方相依套件內部行為(docling / llama_index / torch)

## 3. 測試類型(對應指南五層級)

| 類型 | 說明 | 現況 |
|------|------|------|
| 靜態分析 (Static) | 不執行程式檢缺陷 | 🔶 Pydantic import-time 驗證 + code review;linter/typing 列 ROADMAP |
| 單元測試 (Unit) | 純邏輯函式/類別,零外部依賴 | ✅ `tests/test_*.py` 自動化主力 |
| 整合測試 (Integration) | 模組間 + DB/模型服務 | 🔶 部署環境 + scripts/ 手動;自動化列 ROADMAP |
| 系統測試 (System) | 端到端黑箱(上傳→索引→查詢) | 🔶 手動 + MCP client 實測 |
| 驗收測試 (Acceptance) | RAG 品質、引用正確性 | 🔶 人工驗收;回歸問答集列 ROADMAP |

## 4. 進場 / 出場準則

**進場(開始測試前)**
- 需求規格(`specs/`)已定義且被審查。
- 待測程式碼可成功 import(單元層)或可在 staging 啟動(整合層)。

**出場(可合併 / 發布)——對應指南「測試結束條件」**
- 全套件通過(登記在案的例外除外)。
- 新增 / 變更的程式碼有對應 REQ → TC → 測試(可追溯性)。
- 覆蓋率不低於門檻(見第 5 節),且無新增未覆蓋的關鍵路徑。
- `defect-reports/` 無 Open 的 Blocker / Critical。
- 安全相關變更(token 隔離、檔名驗證、上傳路徑)經過對應測試。

## 5. 覆蓋率目標

**範圍定義**:覆蓋率統計**單元測試範疇**的模組(純邏輯,零外部依賴)。
需要 DB / vLLM / GPU 的 pipeline 模組屬整合測試範疇,列於 `pyproject.toml`
`[tool.coverage.run] omit`(逐檔明列並附理由),**不灌水也不拖低門檻**;
其品質由整合/系統層把關(ROADMAP)。

| 範圍 | 目標 |
|------|------|
| 單元範疇整體行覆蓋率 | ≥ 80%(`--cov=src`,omit 見 pyproject) |
| 安全關鍵模組(file_storage 檔名驗證、auth 快取、exceptions) | ≥ 90% |
| 新增程式碼 | 不得降低所屬模組既有覆蓋率 |

```bash
uv run pytest --cov --cov-report=term-missing   # 低於門檻以非零退出(pyproject fail_under)
```

> **實測(2026-07-09):274 項全數通過,單元範疇行覆蓋率 93%**,已達標並由
> `[tool.coverage.report] fail_under = 85` 把關。明細見 [TEST_SUMMARY_REPORT.md](TEST_SUMMARY_REPORT.md)。

## 6. 時程與里程碑

| 階段 | 內容 | 狀態 |
|------|------|------|
| M1(本階段) | 測試流程文件、範本、可追溯性;單元測試套件 + 覆蓋率門檻 | ✅ |
| M2 | CI pipeline(自動跑測試 + 覆蓋率門檻擋合併)+ linter/typing | ⏳ |
| M3 | 自動化整合測試(pgvector 測試庫 + 小模型替身) | ⏳ |
| M4 | 系統測試自動化 + RAG 品質回歸問答集 + 效能基準 | ⏳ |

## 7. 角色與責任(指南「責任分工」)

| 角色 | 責任 |
|------|------|
| 開發者 | 左移:寫功能同時寫 REQ/TC/測試;跑覆蓋率門檻後才提交 |
| 審查者 | code review(靜態層)+ 確認可追溯性完整 |
| AI 輔助 | 產生測試案例與腳本草稿;**產出一律經人工審查**(指南 AI 章節) |
| 維運 / 部署 | staging 整合驗證、正式環境健康監控 |
