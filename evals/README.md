# Evals — RAG 檢索與 ASR 評測(BL-01 / BL-02)


**目的**:所有模型/調參決策的驗收網。換 embedding(BL-12)、換 ASR
(BL-08 FireRedASR)、調 `ef_search`(BL-14)之前後各跑一次,用數據說話。

## 目錄

```
evals/
  metrics.py                  # 指標純函式(CER / 簡體率 / recall@k / MRR;有單測)
  rag/
    documents/                # ← 放代表性文件集(白名單內任何格式)
    golden_qa.yaml            # ← QA 集(格式見檔內註釋)
  asr/
    audio/                    # ← 放 3-5 段代表音檔(會議/簡報/含前導靜音)
    drafts/                   # 機器草稿(whisper 產;僅供校對起點,絕不拿來算分)
    golden_transcripts/       # ← 同名 .txt:**人工校對過**的繁中全文才能放
  baselines/                  # 跑分輸出(JSON;基線提交進 repo)
```

## 素材來源 A:Common Voice zh-TW(免校對,推薦)

Mozilla Common Voice Scripted Speech(zh-TW,CC0-1.0)自帶**人工驗證**
逐句文本 — 不需要校對。從 Mozilla Data Collective 登入下載 tar.gz 後:

```bash
uv run --no-sync python scripts/import_common_voice.py <tar.gz 路徑> --n 200
uv run --no-sync python scripts/run_asr_eval.py
```

抽樣 seed 固定(--seed 42)可重現;重跑自動清舊 cv_* 批。
限制:CV 是唸稿短句(語音學上乾淨),量得出模型基礎 CER,但不代表
會議/長音檔real-world 表現 — 自錄長音檔(素材來源 B)仍值得補。

## 素材來源 B:自有音檔 — 草稿→校對工作流

從零逐字打 20 分鐘音檔不現實 — 用機器草稿當起點:

1. 產草稿(whisper turbo → `drafts/*.txt`):
   `uv run --no-sync python scripts/make_asr_drafts.py`
2. **人工校對** `drafts/` 內容(聽音檔修錯字;FireRedASR 版草稿就緒時
   可並排對照,兩邊分歧處優先聽)
3. 校對完搬進 `golden_transcripts/` 同名檔

⚠️ `golden_transcripts/` 放未校對的機器輸出 = CER 在跟 whisper 自己的
錯誤比,兩個 ASR 的分數都失真 — 這條線是評測可信度的底線。

## 跑法

```bash
# RAG(需 PostgreSQL + embedding 服務可達;自建評測 folder,跑完自動清除)
uv run --no-sync python scripts/run_rag_eval.py
uv run --no-sync python scripts/run_rag_eval.py --baseline evals/baselines/rag_<date>.json

# ASR(對 config 的 provider;--provider 可覆蓋)
uv run --no-sync python scripts/run_asr_eval.py
uv run --no-sync python scripts/run_asr_eval.py --provider openai-compatible \
    --baseline evals/baselines/asr_docling-whisper_<date>.json
```

## 指標

| 腳本 | 指標 | 說明 |
|---|---|---|
| RAG | recall@5 / recall@10 | 期望檔案在 top-k 檢索結果中的命中比例 |
| RAG | MRR | 第一個命中檔案的排名倒數(排序品質) |
| ASR | CER | 字元錯誤率(去空白標點;normalize 見 metrics.py) |
| ASR | 簡體字比率 | 繁中輸出驗收 ≈0(FireRedASR 輸出簡體時此值會抓到) |
| ASR | 幻覺命中數 | audio_defense pattern 對 provider 原始輸出的命中計數 |

## 慣例

- **基線進 repo**:每次有意義的跑分把 `baselines/*.json` 提交,MR 描述附 diff。
- **素材不進 repo**(documents/audio 可能含內部資料):`.gitignore` 已排除,
  素材放共享儲存、README 記路徑即可。
- 檢索面有任何改動(embedding / chunking / 檢索參數 / ASR)→ 跑分後再合併。
