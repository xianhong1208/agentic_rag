# Agentic RAG — Roadmap


本文件記錄 Agentic RAG MCP Server 的開發進度:**已交付**的能力,以及**規劃中**的工作與已知缺口。
版本以 `pyproject.toml` 為準。

---

## 已交付

### 檢索核心 (RAG Core)
- **階層式索引**:Docling chunks → SentenceSplitter → leaf + parent hierarchy;
  查詢命中 leaf 後 Auto-Merging 回 parent(精準度 × 上下文豐富度平衡)
- **Contextual Retrieval**(Anthropic 2024 做法):索引時 LLM 為每個 chunk 生成
  contextual prefix,含語系不匹配防禦(`_is_script_mismatch`)與 safe fallback
- **Hybrid 查詢**:向量 + BM25(`sparse_top_k` / `hybrid_alpha` 可調)+ cross-encoder rerank
- **Chunk 引用溯源(2026-09,BL-05)**:docling 解析的 headings / 頁碼隨 chunk
  入庫,search 與 REST query 結果帶 `page` / `headings` 引用欄位;node_id /
  file_id 皆可反查(單塊 / 全文重組),E2E 可追溯性整合測試釘死
- **Agentic 三模式查詢**(search / list / read)+ per-folder MCP 工具動態註冊
- 查詢預設值於 request-time 讀 `config.yaml`,請求可覆寫

### 跨模態解析 (Multi-modal)
- PDF / Office / 圖檔:Docling + OCR(RapidOCR;cuda / rocm / cpu 依部署選擇)
- 音檔:Whisper ASR(docling 2.119 `word_timestamps` 原生選項化,繞開 Triton 依賴,
  `PatchedAsrPipeline` 已退場)+ hallucination 防禦
- `.webm` 上傳支援:正規化副檔名 + docling 不友善容器自動轉 WAV
- xlsx 巨表:以 per-chunk tokenize 取代 HybridChunker,索引速度大幅改善
- 擴充檔案格式(v2):舊版 Office(.doc/.xls/.ppt)、.msg、yaml 等;
  文字檔 UTF-16 / Big5 編碼容錯
- **格式 v3(2026-09,對標 docling 2.124 官網全格式)**:OOXML 範本/巨集變體、
  OpenDocument(odt/ods/odp)、epub/tex/eml/vtt/qmd/rmd、音訊 6 種 — 逐格式
  冒煙實測(35 案)+ 程式化官網對標不變式(上游加格式測試自動紅);
  實測排除 ott/ots/otp/potx(docling backend 打不開,附理由)
- **ASR Provider 抽象(2026-09)**:音檔轉錄可換來源 — 本地 docling-whisper /
  本地 fireredasr / 雲端 openai-compatible,config `rag.asr.provider` 一鍵切換
- **FireRedASR-AED-L 為生產 ASR(2026-09-03 驗收)**:CV 22.0 zh-TW test
  200 段人工驗證句 — avg CER **6.11% vs whisper turbo 35.92%**、簡體率 0%
  (OpenCC s2twp)、CPU 快 1.8 倍;基線 `evals/baselines/`。管線:ffmpeg 16k
  重採樣 → silencedetect 切段 ≤55s(60s 硬上限)→ AED 推論 → s2twp 繁化。
  部署註記:目標機 `assets/fireredasr/` 需帶權重(~4.7GB),缺權重時音檔
  安全 fallback 不擋索引
- 無副檔名檔案保留原始檔名餵給 Docling
- docling 2.111→2.119 升級(xlsx 合併格 O(1)、Excel 圖表轉圖、表格編號修正)
- `docling.device` 支援 `cuda:N` 釘卡(解共用 GPU OOM)

### 索引可靠性 — IndexingJobManager
- Folder lock(同 folder 不重複跑 job,409)+ folder 忙碌時批次排隊
- Cancel / Watchdog(60s 掃描、10min 無心跳標 failed;`_ProgressKeepalive` 閒置
  補心跳,防慢檔落在盲區被誤殺)/ restart cleanup
- Per-file timeout + job-level timeout(預設均 10 天;慢機台大檔 OCR 用,可用 env 調降);
  逾時走 CancelledError 也會補寫 FileIndex failed 記錄,前端才有「失敗」tag
- `PARTIAL_SUCCESS` 狀態、file-existence 三道 gate、embedding exponential backoff 重試
- Content-hash idempotency(內容沒變 short-circuit,~60× 加速)
- Job state write-through 到 PostgreSQL(跨 restart 可查)+ SSE realtime 進度推播
- Per-file timing audit(`load_ms` / `index_ms` / `total_ms`)+ 頁級進度與索引 ETA
  推估(current-file / job 兩層)+ 排隊上傳各自帶 job_id

### 安全與隔離
- **Token-scoped 隔離**:每個 user_token 的 folders / files / vector tables 完全獨立
- Remote Token Server 認證(驗證結果 TTL 快取,token 以 sha256 做快取 key,不留明文)
- 檔名 / 資料夾名安全檢查(regex 白名單,防路徑跳脫)
- 日誌遮罩 user token;Checkmarx 稽核處置(config 路徑驗證、Object Access Violation 修復)

### 平台與基礎建設
- **設定主控台(2026-09,feat/runtime-settings)**:`/admin` 前端 + admin API —
  模型服務(embedding/LLM/rerank/ASR)與檢索參數執行期熱改,免重啟;
  白名單三級(live 即生效 / warn 附重建索引警告 / 名單外拒絕)、DB 持久化
  重啟不丟、單鍵還原出廠值、模型端點連線探測
- FastAPI + FastMCP 組裝;landing page(`/`)+ Swagger 完整 `response_model` 註記
- Alembic 自動 migration;`config.yaml` 設定載入(`${VAR:-default}` 展開尚未實作,
  見「規劃中」DEF-2026-003;實作前請直接寫值)
- PEP 735 dependency groups:rocm-r713 / rocm-r714(AMD multi-arch)/ cuda / cpu wheel 分流
- loguru 日誌(request_id contextvar、console/file 格式對齊)
- docstring 統一 Google style

### 測試工程(本階段)
- `docs/testing/` 測試流程文件(參照 [FuSa Group 測試方法論指南](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/)):
  TEST_PLAN / TEST_STRATEGY / ENVIRONMENTS / COVERAGE / TEST_SUMMARY_REPORT + 範本
- REQ → TC → pytest 三層可追溯性(specs / test-cases,13 模組全數登記)
- 純邏輯單元測試套件 **464 項全綠**(零外部依賴,CI-ready)+ 整合測試 53 項
  (opt-in:DB 持久化/索引 pipeline 含 E2E 可追溯性/migration 並發/格式冒煙 37 案);
  單元覆蓋率 **95%**,`fail_under = 95` + 逐檔 50% 雙門檻把關
- pyproject dependency-group 一致性守門測試(torch group 三份清單自動比對,
  防 conflicts / sources 漏加)
- 測試過程挖出並登記 4 個產品缺陷(1 Major / 3 Minor,見 `docs/testing/defect-reports/`)
- **CI pipeline(GitHub Actions)規劃中**:uv `--group cpu` 裝 CPU wheel → `pytest --cov`
  (fail_under 門檻擋合併)→ Checkmarx 弱掃

---

## 規劃中

> 📌 完整的 pipeline 欠缺盤點與可追溯工作底冊(BL-xx 編號、驗收標準、依賴關係)
> 見 [`docs/ENGINEERING_BACKLOG.md`](docs/ENGINEERING_BACKLOG.md)(2026-09-02 盤點)。
> 本節保留高層方向;逐項執行以 BACKLOG 為準。

### 高 — 已登記缺陷修復(docs/testing/defect-reports/)
- **DEF-2026-001(Major)**:`_parse_db_url` 補 percent-decoding(密碼含 `@`/`:` 的部署會登入失敗)
- DEF-2026-002:例外 `folder_id=0` truthiness;DEF-2026-003:`${VAR:-default}` 展開實作(或修文件);
  DEF-2026-004:`_load_config` 不再吞 FileNotFoundError

### 高 — 測試工程後續(見 docs/testing/TEST_PLAN.md 里程碑)
- **CI pipeline 深化**(基礎 pipeline 規劃中):加上 lint / type check gate、
  快取 uv 下載、PR 觸發與狀態回報
- **自動化整合測試**:Postgres(pgvector)測試庫 + 小模型替身,涵蓋
  索引 pipeline(Docling → chunk → embed → 寫入)與 `IndexingJobManager` 生命週期
- **系統測試自動化**:上傳 → 背景索引 → SSE → 查詢 → 引用,以 FastAPI TestClient / MCP client 走黑箱流程

### 中 — 品質與效能
- **RAG 品質回歸問答集**:代表性文件集 + 標準答案,驗收檢索品質不隨變更漂移
  (對應驗收測試自動化缺口)
- **效能基準自動化**:利用既有 per-file timing audit 埋點,建立索引吞吐 / 查詢延遲基準線
- 靜態分析工具導入(linter / type checker)納入 CI

### 中 — 安全
- 滲透測試排程(上傳路徑、SSE endpoint、MCP 工具面)
- 上傳檔案內容掃描(magic bytes 與副檔名一致性)

### 低 — 維運
- 索引任務 metrics 匯出(Prometheus 格式)
- 更完整的 job 歷史查詢 / 清理策略

---

## 未來探索

- GraphRAG / knowledge-graph 輔助檢索
- 多向量(ColBERT-style)檢索評估
- 增量索引(檔案部分變更只重索引受影響 chunks)
- 查詢意圖分類自動選擇 search / list / read 模式
