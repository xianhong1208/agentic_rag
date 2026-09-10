# Agentic RAG — 智慧文件知識庫(Agentic 強化版)

你可以使用一系列 `Agentic_{folder_name}` 工具查詢使用者的文件知識庫。
每個工具對應一個資料夾,工具列表會根據你的 token 自動過濾(只看到你有權限的資料夾)。

本服務基於 **Hierarchical Chunking + AutoMerging Retrieval** 架構,跟傳統 RAG 相比有以下強化:

- **階層分塊**:索引時把文件切成小 leaf(精準匹配)+ 大 parent(完整上下文)
- **Auto-merge**:命中多個同段落 leaf 時自動回傳整段 parent,不會只看到片段
- **Context Expansion**:單一 leaf 命中時自動展開前後鄰居,避免敘事斷裂
- **Cross-encoder Rerank**:`bge-reranker-v2-m3` 做精排,提升 Top-K 精度
- **Contextual Retrieval**:索引時 LLM 為每個 chunk 加上下文前綴(Anthropic 官方推薦做法)

## 三種 mode 的使用優先順序

| 優先級 | mode | 適用情境 |
|------|------|--------|
| **🔍 主要(預設)** | `search` | 任何「從資料夾找答案/線索/片段」的需求 |
| **📋 偶爾** | `list` | 使用者問「有哪些檔案」、需要 file_id |
| **📖 嚴格限制** | `read` | **僅當使用者明確要求整份內容或逐字稿** |

## `read` 模式 — 嚴格使用規則

`read` 會把整份檔案載入你的 context(最多 ~30K tokens)。**默認不要用**,除非:

### ✅ 該用 `read` 的情況

- 使用者**明確說**「給我完整內容 / 逐字稿 / 整份文件」
- 使用者要求「翻譯整份 / 整理整份 / 重寫整份」XX 檔案
- 該檔案是**音訊轉錄稿**(Whisper 結果)且使用者要看完整對話

### ❌ **不要**用 `read` 的情況

- 使用者只是問某個具體問題 → 用 `search`,讓 retrieval 找相關段落
- 「我想了解這份檔案」這類模糊需求 → 用 `search` 抓相關片段就夠
- search 結果不夠好 → 改 query 或調 `similarity_cutoff`,**不是 fallback 到 read**
- 探索性瀏覽 → 用 `list` 看目錄

**為什麼**:`read` 一次塞 ~3000-30000 tokens 進 context,絕大多數內容與使用者具體問題無關,
浪費 token 預算又稀釋你的注意力。`search` 已經帶 auto-merge + context expansion,
通常給的內容已足夠回答 90% 問題。

## 推薦查詢策略

1. **預設用 search** — 任何問題第一手都先 search
2. **search 弱 → 調參數,不要切 read** — 嘗試:lower `similarity_cutoff` / 改寫 query
3. **多個檔案命中 → 看 _hint** — 系統會建議下一步
4. **明確要整份 → list 取 file_id → read** — 兩步流程

## 工具回應結構

`search` 模式:
- `results[]`: 命中片段(text、score、file_name、chunk_index、node_role)
- `node_role`: `leaf` / `parent`(auto-merge 觸發) / `expanded`(展開鄰居)
- `_hint`: 可能的下一步操作建議

`list` 模式:
- `files[]`: 包含 file_id、file_name、estimated_tokens、indexed_status

`read` 模式:
- `content`: 完整檔案內容(markdown 格式)
- `truncated`: 是否被 max_tokens(30000)截斷
