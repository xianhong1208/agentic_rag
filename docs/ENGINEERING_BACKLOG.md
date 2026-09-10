# Engineering Backlog — Pipeline 欠缺盤點與工作底冊


**定位**:對標業界 production RAG 服務,對整條 pipeline(文件解析 → ASR → chunking →
embedding → 檢索查詢 → 性能/平台)做的欠缺盤點。每項有編號(BL-xx)、現狀證據
(對得到程式碼)、欠缺、做法、**驗收標準**、依賴 —— 可追溯、可勾銷。
狀態欄隨進度更新;完成項移入文末「已完成」。盤點基準日:2026-09-02。

## 執行順序(總表)

| 波次 | 項目 | 理由 |
|---|---|---|
| **進行中**(feat/asr-provider) | BL-06 ASR config 化、BL-07 AsrProvider 介面、BL-21 import 環守門 | ASR 換裝的地基 |
| **第 1 波(P0)** | BL-01 RAG 評測網、BL-02 ASR 評測集 | **所有模型/調參決策的前提** — 沒有它,換 FireRedASR / A/B embedding / 調 ef_search 全都無法驗收 |
| **第 2 波** | BL-08 FireRedASR、BL-05 metadata 富化、BL-12 embedding A/B、BL-14 ef_search、BL-16 metrics、BL-18 佇列持久化 | P1,各自獨立可並行 |
| **第 3 波(P2)** | 其餘 | 有網、有量測後的優化與實驗 |

---

## H. 質量評測(橫切 — 最優先)

### BL-01 [P0·框架已就緒] RAG 檢索評測網(golden QA set + 跑分腳本)
- **2026-09-02 框架交付**:evals/ 結構 + scripts/run_rag_eval.py(索引→逐 QA→
  recall@5/10 + MRR→基線 JSON)+ 指標純函式單測 13 案。**待素材**:documents/
  文件集 + golden_qa.yaml 條目(見 evals/README.md)。
- **現狀**:檢索品質零量化。調 `merge_threshold`/`top_k`/`hybrid_alpha`、換 embedding
  全靠人工感覺;ROADMAP 掛「品質回歸問答集」已久未動。
- **欠缺**:業界標配的 golden set + 指標回歸(recall@k / MRR / faithfulness 抽樣)。
- **做法**:`evals/` 目錄:代表性文件集(PDF/xlsx/掃描件/音檔)+ 30-50 條 QA
  (問題、預期命中 file/chunk、參考答案)+ 一支跑分腳本(對 staging 庫索引後跑
  query,產出指標 JSON,與 repo 內基線比對)。
- **驗收**:一條命令出分;基線 JSON 進 repo;任何檢索面改動的 MR 附跑分 diff。
- **依賴**:staging DB(有)+ embedding 服務。

### BL-02 [P0·框架已就緒] ASR 評測集(golden transcripts)
- **2026-09-02 框架交付**:scripts/run_asr_eval.py(任一 AsrProvider → CER /
  簡體率 / 幻覺數 → 基線 JSON,--provider 覆蓋、--baseline 比較)。
  **待素材**:3-5 段音檔 + 人工校對繁中全文。
- **現狀**:換 ASR 模型無驗收依據。
- **做法**:3-5 段代表音檔(會議/簡報/含前導靜音)+ 人工校對繁中 transcript;
  指標:CER、繁中輸出率、幻覺片段數(沿用 audio_defense 的 pattern 統計)。
- **驗收**:腳本對任一 AsrProvider 跑出 CER 表;whisper turbo 基線入 repo。
- **依賴**:無。**BL-08 的前置。**

## A. 文件解析(docling)

### BL-05 [✅ 2026-09-02] Chunk metadata 富化 — 章節/頁碼進 metadata
- **交付**:`docling_convert_once` 回 chunk 記錄 `{text, headings, page_no}`
  (拆分繼承源塊 meta、合併取首塊、裸字串 None)→ leaf_splitter 注入 leaf
  metadata → PGVector node → `mode=search` 與 REST query 結果帶 `page`/
  `headings`(有才帶,舊索引資料零遷移)。embedding 用裸 text,溯源欄位
  不污染向量。
- **驗收已過**:單測 13 案(refine 記錄化契約/leaf 注入)+ 整合 2 案
  (真 docling md→headings、PDF→page_no,釘 docling meta schema);
  舊資料相容(欄位缺時 response 不出現該 key)。
- **註**:僅**新索引**的資料帶頁碼;既有 folder 重建索引後才有。

### BL-03 [P1] 解析質量抽樣基準(隨 BL-01 附帶)
- OCR 錯字率無量測(`ocr_model_scale` tiny/small/medium 的取捨無數據)。
  golden set 內放 2-3 份掃描件的人工校對文本,跑分腳本一併出 OCR CER。

### BL-04 [P2] 圖片語義(VLM caption 實驗)
- 圖片現在只有 OCR 文字;docling VLM pipeline(GraniteDocling)可產圖片描述。
  GPU 成本高,評測網就緒後做小規模實驗再決定。

## B. ASR(feat/asr-provider 分支進行中)

### BL-06 [P0·進行中] ASR config 化
- **現狀**:audio pipeline 純 auto-discover(`docling_loader:586`「無 config 開關」);
  裁切/幻覺過濾無開關。
- **做法**:`rag.asr` 段:`enabled / provider / model_path / trim_leading_silence /
  filter_hallucinations / segment_seconds / to_traditional`(後兩項為 FireRedASR 預留)。

### BL-07 [P0·進行中] AsrProvider 介面 + docling default
- `document_loader` 的 audio 分流走注入的 provider(H6 同模式);
  `DoclingWhisperAsrProvider` 封裝現行為 = 零行為變化。`audio_defense`
  (裁切/過濾)留在 provider 外層,模型無關。

### BL-08 [✅ 2026-09-03 已驗收並切為生產 provider] FireRedASRProvider
- **已交付**:`fireredasr_provider.py` — ① 60s 硬上限:ffmpeg silencedetect
  找靜音、貪婪切 ≤55s 段(切點取靜音中點;無靜音硬切 — silero-vad 會把
  torchaudio 拖進 base resolution 與 GPU group 切換衝突,棄用);② ffmpeg
  16kHz mono 重採樣;③ OpenCC s2twp 簡→繁(台灣用語);④ AED 無標點 →
  chunks=None 走 leaf_splitter 純文字路徑。工廠 `provider: "fireredasr"`
  已接;lazy singleton 載模型。程式碼 vendor 自官方 repo
  (`vendor/fireredasr_src/`,Apache-2.0;PyPI 的 fireredasr 是第三方 fork)。
- **驗收已過(2026-09-03,CV22 zh-TW test 200 段人工驗證句)**:
  avg CER **6.11% vs whisper turbo 35.92%**(簡繁灌水扣除後仍 ~29%,差近
  5 倍)、簡體率 0%、CPU 快 1.8 倍;基線 evals/baselines/asr_*_2026-09-03.json。
  config 已切 `rag.asr.provider: "fireredasr"`。
- **殘留**:①部署機要帶 assets/fireredasr/FireRedASR-AED-L/ 權重(~4.7GB,
  不進 repo)。vendored 程式碼**已成 uv path dependency 隨依賴編進 binary**
  (Nuitka),部署不需外帶 vendor/;
  ②真實會議長音檔驗收待 custom/ 三段人工校對;③標點恢復後續另評。

### BL-09 [✅ 2026-09-02] ASR 雲端 provider(OpenAI-compatible)
- 隨 BL-07 一併交付:`OpenAICompatibleAsrProvider`(multipart POST
  /audio/transcriptions,Bearer 可選;OpenAI / Groq / vLLM whisper 相容)。

### BL-22 [P2] 影片格式支援(mp4/avi/mov/mkv/webm)
- docling 2.124 官網支援影片(經 ASR + 代表關鍵影格,需 ffmpeg)。
- **2026-09-02 管線實測已通**:default DocumentConverter 直接 convert mp4 →
  SUCCESS(無需另掛 pipeline,先前估計過重);樣本為純音調無語音,故
  **內容級驗證待 BL-02 語音樣本**到位後做,通過即收進白名單。
  .webm 現行「轉 WAV 當音檔」路徑維持不動。

## C. Chunking

### BL-10 [P2] Chunk 統計報表(長度分佈/過短率/表格塊佔比;timing audit 延伸)
### BL-11 [P2] 語義 chunking 實驗(embedding-based split;等 BL-01 網)

## D. Embedding

### BL-12 [P1] e5-large vs bge-m3 A/B(懸置多時的決策)
- 現行 `intfloat/multilingual-e5-large` + query/passage prefix;bge-m3 為回退。
  用 BL-01 網跑兩者 recall/MRR,數據定案。~28 個舊 folder 的全量重索引隨決策執行。

### BL-13 [P2] Chunk 級 embedding cache
- 現有檔級 content-hash 跳過;檔內小改動仍全檔重 embed。chunk-hash → vector
  cache 可省大檔重索引的 GPU 時間。規模上來再做。

## E. 檢索 / 查詢

### BL-14 [P1] `hnsw.ef_search` 調優
- **現狀**:建索引 `m=16, ef_construction=64`(`db_bootstrap:159`,合理);
  但查詢期 `ef_search` 用 pgvector 預設 **40** — top_k 調大時召回受限。
- **做法**:BL-01 網就緒後,對 ef_search 40/100/200 掃 recall-延遲曲線,定值後
  在 session/連線層設定。
- **依賴**:BL-01。

### BL-15 [P2] Query 側增強實驗(rewrite / multi-query;agentic 場景已由 caller LLM 部分彌補,量測後再決定)

## F. 性能 / 可觀測

### BL-16 [P1] Prometheus metrics
- **現狀**:僅結構化日誌 + per-file timing audit(原始數據在,無出口)。
- **做法**:`/metrics` endpoint:索引吞吐(檔/chunk/s)、查詢延遲 P50/P95、
  job 佇列深度、cache 命中率、embedding 批延遲。timing audit 直接餵。
- **驗收**:Prometheus 抓得到;README 列指標清單。

### BL-17 [P2] 查詢壓測基線(k6/locust 一次性,並發查詢 P95 與 GPU 佔用)

## G. 平台 / 擴展性

### BL-18 [P1] Pending 批次持久化
- **現狀**:`_pending_file_batches` 純記憶體 — 重啟即丟排隊上傳(restart cleanup
  翻 failed,使用者要重傳)。job 狀態有 DB write-through,佇列沒有。
- **做法**:排隊批次落 IndexJobs(status=queued 已有 row)+ 重啟時從 DB 重建佇列。
- **驗收**:整合測試:排隊中 kill/重啟 manager → 佇列恢復、job 以同 id 繼續。

### BL-19 [P2] Job 狀態外置(PG advisory lock + SKip LOCKED)→ 多實例索引
- 現 folder lock / TTLCache 皆單進程記憶體 — 索引服務只能單實例。
  等橫向擴展需求明確再做;migrate 層的 advisory lock 模式可沿用。**依賴 BL-18。**

### BL-20 [P2] 解析/嵌入服務化評估(docling-serve;GPU 隔離已由 cuda:N + INFER_LOCK 解,擴展時再評)

### BL-21 [P0·進行中] Import 環自動守門
- 現只有 grep 斷言(domain 不反向);做成 AST 級 import 圖零環單測,
  「A call B、B 回 call A」永久阻斷於 CI。

---

## 管線審查殘項(2026-09-07 全鏈審查;C1/C2/H1-H4/M3/M4 已修)

### BL-23 [P1] 上傳成功但 auto-index 啟動失敗 → 檔案無任何記錄(M1)
- trigger_auto_index 吞例外只回 warning message;File row 有、FileIndex 無,
  前端顯示 not_indexed 無法與「排隊中」區分,無重試。應寫 failed 記錄或重試。

### BL-24 [P2] 刪檔順序:實體檔先刪、DB row 後刪(M2)
- 中間出錯留「有 row 無檔案」;FileIndex.file_id FK 無 ondelete cascade。

### BL-25 [P2] delete_document_index 例外時跳過快取失效(M5)
- chunks 已刪但 FileIndexNotFound 翻 False → query cache 未清,TTL 內回已刪內容。

### BL-26 [P2] folder 改名 storage rename 與 file_path 更新非原子(M6)
### BL-27 [P2] reindex cancel 30s 逾時後殘存 thread 可能重建剛 DROP 的表(H5-B)
- hierarchical_indexer 檔頭已記載此風險;需 job 硬終止或寫入前 folder 世代檢查。

### BL-28 [P3] 同 folder 同名檔無 unique 約束(L1);save_file 後 DB create 失敗留孤兒檔(L2);
單檔上傳 metadata None 訊息不一致(L3);delete_folder_index results 語義混雜(L4)。

## 已完成(可追溯歸檔)

- 2026-08~09:架構審查 35 項(H1-H6 / M1-M15 / Low)、M6/M14 重構、
  migrate 三重防護、覆蓋率 95%/50% 雙門檻、整合測試基座(見 git log
  `chore/bump-v1.1.9-rocm` 分支與 ROADMAP「已交付」)。
- 2026-09-02:docling 2.119 → 2.124(BL 前置)。
- 2026-09-02(feat/asr-provider):**BL-06** rag.asr config 化(最小 5 欄);
  **BL-07** AsrProvider 介面 + docling-whisper default(零行為)+ 分流接線;
  **BL-09** 雲端 openai-compatible provider;**BL-21** import 環自動守門
  (AST 兩級零環釘死 CI);格式 v3 官網對標(音訊 6 種 + odt/ods/odp/epub/
  tex/eml/xlsm);死碼掃描(vulture:7 報全誤報/框架契約,零真死碼)。
- 2026-09-02(feat/asr-provider):**BL-05** chunk 引用溯源(headings/page_no
  進 node metadata,search/query 回傳頁碼與章節鏈;僅新索引資料)。
