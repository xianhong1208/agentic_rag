# Agentic RAG — 測試環境 (Test Environments)


---

## 環境分離

| 環境 | 用途 | DB | 模型服務 |
|------|------|----|---------| 
| **Development(單元測試)** | `uv run pytest`——純邏輯測試,**不需任何外部服務** | 不需要 | 不需要(mock) |
| **Staging(整合/系統)** | 索引 pipeline、查詢、SSE 全流程驗證 | Postgres + pgvector(獨立測試庫) | vLLM embedding(5043)/ LLM(5020)/ reranker(8787) |
| **Production** | 正式服務 | 正式庫 | 正式模型端點 |

## 原則

1. **單元測試零外部依賴**:`tests/test_*.py` 必須能在沒有 DB、沒有 GPU、沒有網路的
   CI runner 上直接通過。任何需要外部服務的測試放整合層(ROADMAP)並以 marker 區隔。
2. **測試不落正式庫**:整合測試一律使用獨立的測試資料庫;禁止對 production DB 跑測試。
3. **模型服務可替換**:embedding / LLM / reranker 皆為 OpenAI-compatible endpoint,
   staging 可用小模型替身以降低資源需求(品質驗收除外)。
4. **測試資料**:代表性文件集(PDF / xlsx 巨表 / webm 音檔 / 圖檔)存放於測試環境,
   不進版控(見 `.gitignore` 的 `storage/`)。

## 單元測試執行(本機 / CI)

```bash
uv run --no-sync pytest                          # 全套
uv run --no-sync pytest --cov --cov-report=term-missing   # 附覆蓋率(低於門檻非零退出)
uv run --no-sync pytest tests/test_hierarchy.py -v         # 單檔
```

## 整合測試(tests/integration/ — 需真 PostgreSQL,opt-in)

```bash
RAG_RUN_DB_ITESTS=1 uv run --no-sync pytest tests/integration -v
```

- **opt-in**:沒設 `RAG_RUN_DB_ITESTS=1` 時整組自動 skip(單元 CI 不受影響,
  也防止在碰巧有 postgres 的機器上擅自建庫)。
- 連線資訊沿用 `config/config.yaml` 的 database url,但**絕不碰該庫**:每輪
  自建全新 `agentic_rag_itest` → 跑 alembic 全鏈建 schema(順帶重驗 migration
  鏈)→ 測畢 DROP。
- 目前涵蓋:IndexJobDB / FileIndexDB 真庫往返(job write-through、reindex
  idempotency、mark_failed 失敗 tag 路徑)。

> ⚠️ **GPU 機器請帶 `--no-sync`**:本專案 torch 依 GPU 走 PEP 735 dependency group
> (`uv sync --group cuda`(NVIDIA)/ `--group rocm-r714` 或 `--group rocm-r713`(AMD)…,
> 見 `pyproject.toml` 開頭對照表)。
> 不帶 group 的 `uv sync` 或裸 `uv run`(會隱式 sync)會把 venv 的 torch 三件套
> 換成預設解析版本,破壞已裝好的 GPU stack。修復方式:重跑
> `uv sync --inexact --group <你的 GPU group>`。
>
> ⚠️ **CI / 純 CPU 環境也一樣**:torch 三件套只由 `[dependency-groups]` 提供、
> 不在 `[project].dependencies` 內,而 `cpu` 並非 default group(pyproject 未設
> `default-groups`)。所以 `uv sync --group cpu` 之後若裸跑 `uv run pytest`,隱式
> sync 會以 exact 語意把剛裝好的 torch 當 extraneous 移除。CI 測試步驟務必帶
> `--no-sync`(CI 用 `uv run --no-sync pytest`)。
