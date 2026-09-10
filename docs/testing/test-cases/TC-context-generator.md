# TC-context-generator:Contextual Retrieval 上下文前綴產生器 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-context-generator](../specs/SPEC-context-generator.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_context_generator.py` |

> 全部案例不發網路請求;LLM 呼叫一律以 pytest-mock(`mocker`)或 stub client 取代。
> 跑法:`cd agentic_rag && uv run pytest tests/test_context_generator.py -v`

---

## TC-ctxgen-01:_detect_scripts — 純拉丁文字(含重音)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"Hello world"`、`"café résumé"` |
| **測試步驟** | 1. 呼叫 `_detect_scripts()` |
| **預期結果** | 兩者皆回 `{"Latin"}`(Latin Extended 亦歸 Latin) |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_latin` |

## TC-ctxgen-02:_detect_scripts — 純中文

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"這是一段中文"` |
| **測試步驟** | 1. 呼叫 `_detect_scripts()` |
| **預期結果** | 回 `{"CJK"}` |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_cjk` |

## TC-ctxgen-03:_detect_scripts — 日文假名與漢字

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"こんにちは"`、`"カタカナ"`、`"日本語のテスト"` |
| **測試步驟** | 1. 分別呼叫 `_detect_scripts()` |
| **預期結果** | 依序回 `{"Hiragana"}`、`{"Katakana"}`、`{"CJK", "Hiragana", "Katakana"}` |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_japanese_kana_and_kanji` |

## TC-ctxgen-04:_detect_scripts — 其他主流 script(參數化 6 組)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 韓文 / 俄文 / 阿拉伯文 / 希伯來文 / 泰文 / 天城文範例字串各一 |
| **測試步驟** | 1. 各自呼叫 `_detect_scripts()` |
| **預期結果** | 回傳集合分別含 Hangul / Cyrillic / Arabic / Hebrew / Thai / Devanagari |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_other_major_scripts`(parametrize 6 組) |

## TC-ctxgen-05:_detect_scripts — 忽略非字母與空字串

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"12345 !?,.()"`、`""` |
| **測試步驟** | 1. 分別呼叫 `_detect_scripts()` |
| **預期結果** | 兩者皆回 `set()` |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_ignores_non_alpha` |

## TC-ctxgen-06:_detect_scripts — 中英混合

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"公司 Q3 revenue 成長"` |
| **測試步驟** | 1. 呼叫 `_detect_scripts()` |
| **預期結果** | 回 `{"CJK", "Latin"}` |
| **實作** | `tests/test_context_generator.py::test_detect_scripts_mixed_text` |

## TC-ctxgen-07:_is_script_mismatch — 中文 chunk 配英文 prefix

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"這是中文段落"`,prefix=`"This chunk describes something"` |
| **測試步驟** | 1. 呼叫 `_is_script_mismatch()` |
| **預期結果** | 回 `True` |
| **實作** | `tests/test_context_generator.py::test_mismatch_cjk_chunk_latin_prefix` |

## TC-ctxgen-08:_is_script_mismatch — 中文 chunk 配中文 prefix(夾雜英數)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"這是中文段落"`,prefix=`"本段說明 Q3 財報重點"` |
| **測試步驟** | 1. 呼叫 `_is_script_mismatch()` |
| **預期結果** | 回 `False`(Latin 容差) |
| **實作** | `tests/test_context_generator.py::test_no_mismatch_cjk_chunk_cjk_prefix` |

## TC-ctxgen-09:_is_script_mismatch — 純英文 chunk 永不 mismatch

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 英文 chunk 分別配英文 prefix 與中文 prefix |
| **測試步驟** | 1. 兩組各呼叫 `_is_script_mismatch()` |
| **預期結果** | 兩組皆回 `False` |
| **實作** | `tests/test_context_generator.py::test_no_mismatch_pure_latin_chunk` |

## TC-ctxgen-10:_is_script_mismatch — 中文 chunk 配空 / 純數字 prefix

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"中文內容"`,prefix 分別為 `""` 與 `"12345"` |
| **測試步驟** | 1. 兩組各呼叫 `_is_script_mismatch()` |
| **預期結果** | 兩組皆回 `True`(prefix 無任何非拉丁腳本) |
| **實作** | `tests/test_context_generator.py::test_mismatch_cjk_chunk_empty_or_numeric_prefix` |

## TC-ctxgen-11:_is_script_mismatch — 中英混合 chunk 以非拉丁主腳本判定

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-04、REQ-ctxgen-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"中文 mixed with English"`,prefix 分別為純英文與中文 |
| **測試步驟** | 1. 兩組各呼叫 `_is_script_mismatch()` |
| **預期結果** | 純英 prefix → `True`;中文 prefix → `False` |
| **實作** | `tests/test_context_generator.py::test_mismatch_mixed_chunk_uses_non_latin_main_script` |

## TC-ctxgen-12:_is_script_mismatch — 韓文 chunk 配英文 prefix

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"안녕하세요 문서입니다"`,prefix=`"English prefix"` |
| **測試步驟** | 1. 呼叫 `_is_script_mismatch()` |
| **預期結果** | 回 `True`(非中文的非拉丁腳本同樣受保護) |
| **實作** | `tests/test_context_generator.py::test_mismatch_hangul_chunk_latin_prefix` |

## TC-ctxgen-13:_safe_fallback_prefix — 輸出格式

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-06 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | chunk=`"chunk 內容"`,file_name=`"報告.docx"` |
| **測試步驟** | 1. 呼叫 `_safe_fallback_prefix()` |
| **預期結果** | 回 `"報告.docx\n\nchunk 內容"`(無任何 wrapper 文字) |
| **實作** | `tests/test_context_generator.py::test_safe_fallback_prefix_format` |

## TC-ctxgen-14:__init__ — 參數保存與預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ContextGenerator(llm_config=None, model="test-model")` |
| **測試步驟** | 1. 建構<br>2. 檢查各私有屬性 |
| **預期結果** | `_model=="test-model"`、`_max_context_length==150`、`_max_concurrent==50`、`_max_doc_chars==60000`、`_max_tokens==1024`、`_reasoning_effort is None` |
| **實作** | `tests/test_context_generator.py::test_init_stores_params_and_defaults` |

## TC-ctxgen-15:from_config — 未設定 / enabled=False 回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `SimpleNamespace()`(無 contextual_retrieval 屬性)與 `enabled=False` 的設定 |
| **測試步驟** | 1. 兩組各呼叫 `from_config()` |
| **預期結果** | 兩組皆回 `None`,不拋例外 |
| **實作** | `tests/test_context_generator.py::test_from_config_disabled_returns_none` |

## TC-ctxgen-16:from_config — 缺 llm 設定回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `contextual_retrieval.enabled=True` 但 `llm=None` |
| **測試步驟** | 1. 呼叫 `from_config()` |
| **預期結果** | 回 `None` |
| **實作** | `tests/test_context_generator.py::test_from_config_missing_llm_returns_none` |

## TC-ctxgen-17:from_config — 正常設定,model 優先取 azure_deployment

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 完整 cr 設定(120/8/1000/256/"low")+ `llm.azure_deployment="gpt-4o-dep"`, `llm.model="gpt-4o"` |
| **測試步驟** | 1. 呼叫 `from_config()`<br>2. 檢查回傳型別與各屬性 |
| **預期結果** | 回 `ContextGenerator` 實例;`_model=="gpt-4o-dep"`;其餘屬性等於設定值 |
| **實作** | `tests/test_context_generator.py::test_from_config_success_prefers_azure_deployment` |

## TC-ctxgen-18:from_config — model fallback 與可選欄位預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | cr 只有 `enabled=True, max_context_length=100`;`llm.azure_deployment=None, llm.model="qwen3"` |
| **測試步驟** | 1. 呼叫 `from_config()`<br>2. 檢查屬性 |
| **預期結果** | `_model=="qwen3"`;`_max_concurrent==50`、`_max_doc_chars==60000`、`_max_tokens==1024`、`_reasoning_effort is None`(getattr 預設) |
| **實作** | `tests/test_context_generator.py::test_from_config_model_fallback_and_optional_defaults` |

## TC-ctxgen-19:from_config — 缺必要欄位回 None(不拋例外)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | cr 只有 `enabled=True`(缺 `max_context_length`),llm 正常 |
| **測試步驟** | 1. 呼叫 `from_config()` |
| **預期結果** | 內部 AttributeError 被捕捉,回 `None` |
| **實作** | `tests/test_context_generator.py::test_from_config_missing_required_field_returns_none` |

## TC-ctxgen-20:_create_sync_client — 不支援的 provider

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-09 |
| **層級** | 單元 |
| **前置條件** | 無(不需網路) |
| **測試輸入** | `llm.provider="groq"` |
| **測試步驟** | 1. 呼叫 `_create_sync_client()` |
| **預期結果** | 拋 `ValueError`,訊息含 `"Unsupported LLM provider"` |
| **實作** | `tests/test_context_generator.py::test_create_sync_client_unsupported_provider` |

## TC-ctxgen-21:_create_sync_client — vllm 缺 base_url

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `provider="vllm", base_url=None` |
| **測試步驟** | 1. 呼叫 `_create_sync_client()` |
| **預期結果** | 拋 `ValueError`,訊息含 `"requires base_url"` |
| **實作** | `tests/test_context_generator.py::test_create_sync_client_vllm_requires_base_url` |

## TC-ctxgen-22:_create_sync_client — vllm 正常建 client

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-09 |
| **層級** | 單元 |
| **前置條件** | 無(建 client 物件不發網路請求) |
| **測試輸入** | `provider="vllm", base_url="http://localhost:8000/v1", api_key=None` |
| **測試步驟** | 1. 呼叫 `_create_sync_client()`<br>2. 檢查 client 屬性 |
| **預期結果** | `client.base_url` 以該 URL 開頭;`client.api_key == "not-needed"` |
| **實作** | `tests/test_context_generator.py::test_create_sync_client_vllm_builds_openai_client` |

## TC-ctxgen-23:_call_llm_sync — 回傳 content 與請求參數

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-10 |
| **層級** | 單元 |
| **前置條件** | stub client(`_StubClient`)捕捉 create() kwargs |
| **測試輸入** | generator(max_tokens=256, reasoning_effort=None);message.content=`"生成的上下文"` |
| **測試步驟** | 1. 呼叫 `_call_llm_sync("some prompt", stub)`<br>2. 檢查回傳值與 stub 捕捉的 kwargs |
| **預期結果** | 回 `"生成的上下文"`;kwargs 含 `model="test-model"`、`max_tokens=256`、`temperature=0`;不含 `reasoning_effort` |
| **實作** | `tests/test_context_generator.py::test_call_llm_sync_returns_content_and_request_params` |

## TC-ctxgen-24:_call_llm_sync — reasoning_content fallback 與 reasoning_effort 傳遞

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-10 |
| **層級** | 單元 |
| **前置條件** | stub client;message.content=`""`、message.reasoning_content=`"推理輸出"` |
| **測試輸入** | generator(reasoning_effort="low") |
| **測試步驟** | 1. 呼叫 `_call_llm_sync()`<br>2. 檢查回傳值與 kwargs |
| **預期結果** | 回 `"推理輸出"`;kwargs 含 `reasoning_effort="low"` |
| **實作** | `tests/test_context_generator.py::test_call_llm_sync_reasoning_content_fallback_and_effort_param` |

## TC-ctxgen-25:_generate_one — LLM 正常回應

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | `mocker.patch.object(gen, "_call_llm_sync", return_value="本段說明差旅費核銷規定")` |
| **測試輸入** | 中文 chunk、file_name=`"差旅辦法.docx"`、`asyncio.Semaphore(1)` |
| **測試步驟** | 1. `await gen._generate_one(...)` |
| **預期結果** | 回 `"本段說明差旅費核銷規定\n\n{chunk}"` |
| **實作** | `tests/test_context_generator.py::test_generate_one_success` |

## TC-ctxgen-26:_generate_one — context 超長截斷

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | generator(max_context_length=5);mock LLM 回 `"A"*20` |
| **測試輸入** | 英文 chunk `"english chunk"` |
| **測試步驟** | 1. `await gen._generate_one(...)` |
| **預期結果** | 回 `"AAAAA\n\nenglish chunk"`(截斷至 5 字元) |
| **實作** | `tests/test_context_generator.py::test_generate_one_truncates_long_context` |

## TC-ctxgen-27:_generate_one — LLM 回空字串 fallback

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | mock LLM 回 `""` |
| **測試輸入** | chunk=`"chunk 內容"`,file_name=`"報告.docx"` |
| **測試步驟** | 1. `await gen._generate_one(...)` |
| **預期結果** | 回 `"報告.docx\n\nchunk 內容"`(safe fallback) |
| **實作** | `tests/test_context_generator.py::test_generate_one_empty_llm_response_falls_back` |

## TC-ctxgen-28:_generate_one — script mismatch fallback

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | mock LLM 回純英文 prefix `"This chunk is about travel policy"` |
| **測試輸入** | 中文 chunk `"中文段落內容"`,file_name=`"辦法.docx"` |
| **預期結果** | prefix 被丟棄,回 `"辦法.docx\n\n中文段落內容"` |
| **測試步驟** | 1. `await gen._generate_one(...)` |
| **實作** | `tests/test_context_generator.py::test_generate_one_script_mismatch_falls_back` |

## TC-ctxgen-29:_generate_one — LLM 拋例外 fallback,不冒泡

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | mock LLM `side_effect=RuntimeError("connection refused")` |
| **測試輸入** | chunk=`"chunk text"`,file_name=`"f.txt"` |
| **測試步驟** | 1. `await gen._generate_one(...)` |
| **預期結果** | 不拋例外;回 `"f.txt\n\nchunk text"` |
| **實作** | `tests/test_context_generator.py::test_generate_one_llm_exception_falls_back` |

## TC-ctxgen-30:_generate_one — full_document 超長時 prompt 內截斷

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-11 |
| **層級** | 單元 |
| **前置條件** | generator(max_doc_chars=10);mock `_call_llm_sync` 捕捉 prompt |
| **測試輸入** | full_document=`"D"*100` |
| **測試步驟** | 1. `await gen._generate_one(...)`<br>2. 讀取 mock 捕捉到的 prompt(`call_args[0][0]`) |
| **預期結果** | prompt 含 `"D"*10 + "\n...(文件過長，已截斷)"`;不含 `"D"*11` |
| **實作** | `tests/test_context_generator.py::test_generate_one_truncates_long_document_in_prompt` |

## TC-ctxgen-31:generate_batch — 等長且順序對應

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-ctxgen-12 |
| **層級** | 單元 |
| **前置條件** | `mocker.patch.object(ContextGenerator, "_create_sync_client", return_value=None)`;mock `_call_llm_sync` 回 `"CTX"` |
| **測試輸入** | chunks=`["chunk one", "chunk two", "chunk three"]` |
| **測試步驟** | 1. `await gen.generate_batch(chunks, "full document", "file.txt")` |
| **預期結果** | 回傳 list 恰為 `["CTX\n\nchunk one", "CTX\n\nchunk two", "CTX\n\nchunk three"]`(等長、順序一致) |
| **實作** | `tests/test_context_generator.py::test_generate_batch_order_and_length` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
