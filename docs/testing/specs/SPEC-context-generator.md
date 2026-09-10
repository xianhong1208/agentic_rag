# SPEC-context-generator:Contextual Retrieval 上下文前綴產生器


| 項目 | 內容 |
|------|------|
| 模組 | `src/domain/rag/context_generator.py` |
| 對應測試 | `tests/test_context_generator.py` |
| 版本 | v1.0(feat/rag-robustness) |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

為每個 chunk 產生上下文前綴(Anthropic Contextual Retrieval 策略),含三個純函式
(`_detect_scripts` / `_is_script_mismatch` / `_safe_fallback_prefix`)與 `ContextGenerator` 類別。
本 spec 涵蓋:純函式全行為、類別建構 / `from_config` / client 參數驗證、以及以 mock 取代 LLM 後的
`_call_llm_sync` / `_generate_one` / `generate_batch` 控制流程。**真實 LLM 呼叫品質**(生成內容好壞)
屬整合 / 系統測試範疇,不在此列。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-ctxgen-01 | `_detect_scripts` 依 Unicode 區段將字母歸類至 Latin / CJK / Hiragana / Katakana / Hangul / Cyrillic / Arabic / Hebrew / Thai / Devanagari | 各語系範例文字回傳集合含對應 script 名稱;Latin Extended(é 等)歸 Latin |
| REQ-ctxgen-02 | `_detect_scripts` 忽略非字母字元(數字、標點、空白);空字串回空集合 | `"12345 !?,.()"` 與 `""` 均回 `set()` |
| REQ-ctxgen-03 | 混合文字回傳多個 script | 中英混合 → `{"CJK", "Latin"}` |
| REQ-ctxgen-04 | `_is_script_mismatch`:chunk 含非拉丁主腳本、而 prefix 完全沒有任何非拉丁腳本(含空字串 / 純數字 prefix)→ True | 中文 chunk + 英文 / 空 / 數字 prefix → True;韓文 chunk + 英文 prefix → True;中英混合 chunk + 純英 prefix → True |
| REQ-ctxgen-05 | `_is_script_mismatch`:純 Latin chunk 一律 False;prefix 含任一非拉丁腳本亦 False(Latin 容差) | 英文 chunk + 任意 prefix → False;中文 chunk + 中文(可夾英數)prefix → False |
| REQ-ctxgen-06 | `_safe_fallback_prefix` 回 `"{file_name}\n\n{chunk_text}"`,不加自然語言 wrapper | 輸出逐字元等於該格式 |
| REQ-ctxgen-07 | `ContextGenerator.__init__` 保存參數並套用預設值(max_context_length=150、max_concurrent=50、max_doc_chars=60000、max_tokens=1024、reasoning_effort=None) | 建構後對應私有屬性值正確 |
| REQ-ctxgen-08 | `from_config`:未設定 / enabled=False / 缺 llm / 缺必要欄位 → 回 None 不拋例外;正常設定 → 回 instance,model 優先取 `azure_deployment`,否則 `model`;可選欄位缺時用預設值 | 各設定組合回傳 None 或屬性正確的 instance |
| REQ-ctxgen-09 | `_create_sync_client`:不支援的 provider 拋 ValueError;vllm/ollama 缺 base_url 拋 ValueError;vllm 正常時建出指向 base_url 的 OpenAI client(無 api_key 用 `"not-needed"` 占位) | 錯誤路徑拋含說明的 ValueError;正常路徑 client.base_url / api_key 正確 |
| REQ-ctxgen-10 | `_call_llm_sync` 以 model / max_tokens / temperature=0 呼叫 chat.completions.create;reasoning_effort 有設定才傳;content 為空時 fallback 讀 `reasoning_content` | stub client 捕捉到的 kwargs 正確;回傳值符合 fallback 規則 |
| REQ-ctxgen-11 | `_generate_one`:LLM 正常 → `"{context}\n\n{chunk}"`;context 超過 max_context_length 截斷;LLM 回空 / script mismatch / 拋例外 → 一律回 safe fallback,不外洩例外;full_document 超過 max_doc_chars 時 prompt 內截斷並加註記 | 各路徑輸出可精確斷言;例外不冒泡 |
| REQ-ctxgen-12 | `generate_batch` 回傳與 chunks 等長且順序一一對應的 list | 3 個 chunk → 3 個結果,各自尾端為對應 chunk 原文 |

## 3. 非功能需求 (Non-Functional)

- 單元測試不得發出任何網路請求 — LLM 呼叫一律以 pytest-mock stub 取代。
- `_generate_one` 對任何 LLM 端錯誤必須降級(fallback)而非中斷整批索引。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| `_detect_scripts("")` / 純數字標點 | 回空集合 |
| 中文 chunk 配空字串 prefix | mismatch=True(觸發 fallback) |
| LLM 回空字串或 None | 回 `_safe_fallback_prefix` 結果 |
| LLM 拋例外(連線失敗等) | 捕捉、記 log、回 fallback,不冒泡 |
| context 長度超過 max_context_length | 硬截斷至上限後拼接 |
| full_document 長度超過 max_doc_chars | prompt 內截斷並附 `...(文件過長，已截斷)` 註記 |
| provider 名稱不在支援清單 | `ValueError`(列出支援清單) |

## 5. 相依與假設 (Dependencies & Assumptions)

- `src.log.get_api_logger` — 僅寫 log,無需 mock。
- `openai` 套件 — 僅於 `_create_sync_client` 內 lazy import;建構 client 物件不發網路請求,
  錯誤路徑與參數驗證可直接測。`chat.completions.create` 一律以 stub / mocker 取代。
- Azure / OpenAI provider 路徑依賴環境變數(`AZURE_OPENAI_API_KEY` 等),為避免測試受環境污染,
  單元測試僅覆蓋 vllm 與錯誤路徑。
- 已知限制(非缺陷、記錄於案):`_detect_scripts` 未涵蓋的字母(如希臘文、U+0080–U+00BF 的 µ/ª)
  不會歸入任何 script,故該類文字的 mismatch 偵測會偏向「不確定 → 不 fallback」。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-ctxgen-01 | TC-ctxgen-01 ~ TC-ctxgen-04 | `tests/test_context_generator.py::test_detect_scripts_latin`、`::test_detect_scripts_cjk`、`::test_detect_scripts_japanese_kana_and_kanji`、`::test_detect_scripts_other_major_scripts`(參數化 6 組) |
| REQ-ctxgen-02 | TC-ctxgen-05 | `tests/test_context_generator.py::test_detect_scripts_ignores_non_alpha` |
| REQ-ctxgen-03 | TC-ctxgen-06 | `tests/test_context_generator.py::test_detect_scripts_mixed_text` |
| REQ-ctxgen-04 | TC-ctxgen-07、TC-ctxgen-10、TC-ctxgen-11、TC-ctxgen-12 | `tests/test_context_generator.py::test_mismatch_cjk_chunk_latin_prefix`、`::test_mismatch_cjk_chunk_empty_or_numeric_prefix`、`::test_mismatch_mixed_chunk_uses_non_latin_main_script`、`::test_mismatch_hangul_chunk_latin_prefix` |
| REQ-ctxgen-05 | TC-ctxgen-08、TC-ctxgen-09 | `tests/test_context_generator.py::test_no_mismatch_cjk_chunk_cjk_prefix`、`::test_no_mismatch_pure_latin_chunk` |
| REQ-ctxgen-06 | TC-ctxgen-13 | `tests/test_context_generator.py::test_safe_fallback_prefix_format` |
| REQ-ctxgen-07 | TC-ctxgen-14 | `tests/test_context_generator.py::test_init_stores_params_and_defaults` |
| REQ-ctxgen-08 | TC-ctxgen-15 ~ TC-ctxgen-19 | `tests/test_context_generator.py::test_from_config_disabled_returns_none`、`::test_from_config_missing_llm_returns_none`、`::test_from_config_success_prefers_azure_deployment`、`::test_from_config_model_fallback_and_optional_defaults`、`::test_from_config_missing_required_field_returns_none` |
| REQ-ctxgen-09 | TC-ctxgen-20 ~ TC-ctxgen-22 | `tests/test_context_generator.py::test_create_sync_client_unsupported_provider`、`::test_create_sync_client_vllm_requires_base_url`、`::test_create_sync_client_vllm_builds_openai_client` |
| REQ-ctxgen-10 | TC-ctxgen-23、TC-ctxgen-24 | `tests/test_context_generator.py::test_call_llm_sync_returns_content_and_request_params`、`::test_call_llm_sync_reasoning_content_fallback_and_effort_param` |
| REQ-ctxgen-11 | TC-ctxgen-25 ~ TC-ctxgen-30 | `tests/test_context_generator.py::test_generate_one_success`、`::test_generate_one_truncates_long_context`、`::test_generate_one_empty_llm_response_falls_back`、`::test_generate_one_script_mismatch_falls_back`、`::test_generate_one_llm_exception_falls_back`、`::test_generate_one_truncates_long_document_in_prompt` |
| REQ-ctxgen-12 | TC-ctxgen-31 | `tests/test_context_generator.py::test_generate_batch_order_and_length` |
