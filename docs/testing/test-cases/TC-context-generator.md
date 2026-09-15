# TC-context-generator: Contextual Retrieval Prefix Generator Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-context-generator](../specs/SPEC-context-generator.md) |
| Test level | Unit |
| Test script | `tests/test_context_generator.py` |

> No case makes a network request; LLM calls are always replaced with pytest-mock (`mocker`) or a stub client.
> Run: `cd agentic_rag && uv run pytest tests/test_context_generator.py -v`

---

## TC-ctxgen-01: _detect_scripts — pure Latin (including accents)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"Hello world"`, `"café résumé"` |
| **Test steps** | 1. Call `_detect_scripts()` |
| **Expected result** | Both return `{"Latin"}` (Latin Extended is also classified as Latin) |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_latin` |

## TC-ctxgen-02: _detect_scripts — pure Chinese

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"這是一段中文"` |
| **Test steps** | 1. Call `_detect_scripts()` |
| **Expected result** | Returns `{"CJK"}` |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_cjk` |

## TC-ctxgen-03: _detect_scripts — Japanese kana and kanji

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"こんにちは"`, `"カタカナ"`, `"日本語のテスト"` |
| **Test steps** | 1. Call `_detect_scripts()` on each |
| **Expected result** | Returns `{"Hiragana"}`, `{"Katakana"}`, `{"CJK", "Hiragana", "Katakana"}` respectively |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_japanese_kana_and_kanji` |

## TC-ctxgen-04: _detect_scripts — other major scripts (6 parametrized cases)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | One sample string each for Korean / Russian / Arabic / Hebrew / Thai / Devanagari |
| **Test steps** | 1. Call `_detect_scripts()` on each |
| **Expected result** | The returned sets contain Hangul / Cyrillic / Arabic / Hebrew / Thai / Devanagari respectively |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_other_major_scripts` (parametrized, 6 cases) |

## TC-ctxgen-05: _detect_scripts — ignores non-letters and empty string

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"12345 !?,.()"`, `""` |
| **Test steps** | 1. Call `_detect_scripts()` on each |
| **Expected result** | Both return `set()` |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_ignores_non_alpha` |

## TC-ctxgen-06: _detect_scripts — mixed Chinese and English

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"公司 Q3 revenue 成長"` |
| **Test steps** | 1. Call `_detect_scripts()` |
| **Expected result** | Returns `{"CJK", "Latin"}` |
| **Implementation** | `tests/test_context_generator.py::test_detect_scripts_mixed_text` |

## TC-ctxgen-07: _is_script_mismatch — Chinese chunk with English prefix

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"這是中文段落"`, prefix=`"This chunk describes something"` |
| **Test steps** | 1. Call `_is_script_mismatch()` |
| **Expected result** | Returns `True` |
| **Implementation** | `tests/test_context_generator.py::test_mismatch_cjk_chunk_latin_prefix` |

## TC-ctxgen-08: _is_script_mismatch — Chinese chunk with Chinese prefix (with embedded alphanumerics)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"這是中文段落"`, prefix=`"本段說明 Q3 財報重點"` |
| **Test steps** | 1. Call `_is_script_mismatch()` |
| **Expected result** | Returns `False` (Latin tolerance) |
| **Implementation** | `tests/test_context_generator.py::test_no_mismatch_cjk_chunk_cjk_prefix` |

## TC-ctxgen-09: _is_script_mismatch — pure-English chunk never mismatches

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | An English chunk paired with an English prefix and with a Chinese prefix |
| **Test steps** | 1. Call `_is_script_mismatch()` for each pair |
| **Expected result** | Both return `False` |
| **Implementation** | `tests/test_context_generator.py::test_no_mismatch_pure_latin_chunk` |

## TC-ctxgen-10: _is_script_mismatch — Chinese chunk with empty / numeric-only prefix

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"中文內容"`, prefix being `""` and `"12345"` |
| **Test steps** | 1. Call `_is_script_mismatch()` for each pair |
| **Expected result** | Both return `True` (the prefix has no non-Latin script) |
| **Implementation** | `tests/test_context_generator.py::test_mismatch_cjk_chunk_empty_or_numeric_prefix` |

## TC-ctxgen-11: _is_script_mismatch — mixed-language chunk judged by its non-Latin main script

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-04, REQ-ctxgen-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"中文 mixed with English"`, prefix being pure English and Chinese |
| **Test steps** | 1. Call `_is_script_mismatch()` for each pair |
| **Expected result** | Pure-English prefix -> `True`; Chinese prefix -> `False` |
| **Implementation** | `tests/test_context_generator.py::test_mismatch_mixed_chunk_uses_non_latin_main_script` |

## TC-ctxgen-12: _is_script_mismatch — Korean chunk with English prefix

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"안녕하세요 문서입니다"`, prefix=`"English prefix"` |
| **Test steps** | 1. Call `_is_script_mismatch()` |
| **Expected result** | Returns `True` (non-Chinese non-Latin scripts are protected too) |
| **Implementation** | `tests/test_context_generator.py::test_mismatch_hangul_chunk_latin_prefix` |

## TC-ctxgen-13: _safe_fallback_prefix — output format

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-06 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | chunk=`"chunk 內容"`, file_name=`"報告.docx"` |
| **Test steps** | 1. Call `_safe_fallback_prefix()` |
| **Expected result** | Returns `"報告.docx\n\nchunk 內容"` (no wrapper text) |
| **Implementation** | `tests/test_context_generator.py::test_safe_fallback_prefix_format` |

## TC-ctxgen-14: __init__ — parameter storage and defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ContextGenerator(llm_config=None, model="test-model")` |
| **Test steps** | 1. Construct<br>2. Inspect the private attributes |
| **Expected result** | `_model=="test-model"`, `_max_context_length==150`, `_max_concurrent==50`, `_max_doc_chars==60000`, `_max_tokens==1024`, `_reasoning_effort is None` |
| **Implementation** | `tests/test_context_generator.py::test_init_stores_params_and_defaults` |

## TC-ctxgen-15: from_config — returns None when unset / enabled=False

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `SimpleNamespace()` (no contextual_retrieval attribute) and a config with `enabled=False` |
| **Test steps** | 1. Call `from_config()` for each |
| **Expected result** | Both return `None` without raising |
| **Implementation** | `tests/test_context_generator.py::test_from_config_disabled_returns_none` |

## TC-ctxgen-16: from_config — returns None when llm config is missing

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `contextual_retrieval.enabled=True` but `llm=None` |
| **Test steps** | 1. Call `from_config()` |
| **Expected result** | Returns `None` |
| **Implementation** | `tests/test_context_generator.py::test_from_config_missing_llm_returns_none` |

## TC-ctxgen-17: from_config — normal config, model prefers azure_deployment

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | Full cr config (120/8/1000/256/"low") + `llm.azure_deployment="gpt-4o-dep"`, `llm.model="gpt-4o"` |
| **Test steps** | 1. Call `from_config()`<br>2. Inspect the return type and attributes |
| **Expected result** | Returns a `ContextGenerator` instance; `_model=="gpt-4o-dep"`; remaining attributes equal the config values |
| **Implementation** | `tests/test_context_generator.py::test_from_config_success_prefers_azure_deployment` |

## TC-ctxgen-18: from_config — model fallback and optional-field defaults

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | cr has only `enabled=True, max_context_length=100`; `llm.azure_deployment=None, llm.model="qwen3"` |
| **Test steps** | 1. Call `from_config()`<br>2. Inspect the attributes |
| **Expected result** | `_model=="qwen3"`; `_max_concurrent==50`, `_max_doc_chars==60000`, `_max_tokens==1024`, `_reasoning_effort is None` (getattr defaults) |
| **Implementation** | `tests/test_context_generator.py::test_from_config_model_fallback_and_optional_defaults` |

## TC-ctxgen-19: from_config — returns None when required field is missing (no exception)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | cr has only `enabled=True` (missing `max_context_length`), llm is normal |
| **Test steps** | 1. Call `from_config()` |
| **Expected result** | The internal AttributeError is caught and `None` is returned |
| **Implementation** | `tests/test_context_generator.py::test_from_config_missing_required_field_returns_none` |

## TC-ctxgen-20: _create_sync_client — unsupported provider

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-09 |
| **Level** | Unit |
| **Preconditions** | None (no network needed) |
| **Test input** | `llm.provider="groq"` |
| **Test steps** | 1. Call `_create_sync_client()` |
| **Expected result** | Raises `ValueError` with a message containing `"Unsupported LLM provider"` |
| **Implementation** | `tests/test_context_generator.py::test_create_sync_client_unsupported_provider` |

## TC-ctxgen-21: _create_sync_client — vllm missing base_url

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `provider="vllm", base_url=None` |
| **Test steps** | 1. Call `_create_sync_client()` |
| **Expected result** | Raises `ValueError` with a message containing `"requires base_url"` |
| **Implementation** | `tests/test_context_generator.py::test_create_sync_client_vllm_requires_base_url` |

## TC-ctxgen-22: _create_sync_client — vllm builds client normally

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-09 |
| **Level** | Unit |
| **Preconditions** | None (constructing the client object makes no network request) |
| **Test input** | `provider="vllm", base_url="http://localhost:8000/v1", api_key=None` |
| **Test steps** | 1. Call `_create_sync_client()`<br>2. Inspect the client attributes |
| **Expected result** | `client.base_url` starts with that URL; `client.api_key == "not-needed"` |
| **Implementation** | `tests/test_context_generator.py::test_create_sync_client_vllm_builds_openai_client` |

## TC-ctxgen-23: _call_llm_sync — returned content and request parameters

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-10 |
| **Level** | Unit |
| **Preconditions** | A stub client (`_StubClient`) captures the create() kwargs |
| **Test input** | generator(max_tokens=256, reasoning_effort=None); message.content=`"生成的上下文"` |
| **Test steps** | 1. Call `_call_llm_sync("some prompt", stub)`<br>2. Inspect the return value and the kwargs captured by the stub |
| **Expected result** | Returns `"生成的上下文"`; kwargs contain `model="test-model"`, `max_tokens=256`, `temperature=0`; do not contain `reasoning_effort` |
| **Implementation** | `tests/test_context_generator.py::test_call_llm_sync_returns_content_and_request_params` |

## TC-ctxgen-24: _call_llm_sync — reasoning_content fallback and reasoning_effort passthrough

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-10 |
| **Level** | Unit |
| **Preconditions** | Stub client; message.content=`""`, message.reasoning_content=`"推理輸出"` |
| **Test input** | generator(reasoning_effort="low") |
| **Test steps** | 1. Call `_call_llm_sync()`<br>2. Inspect the return value and kwargs |
| **Expected result** | Returns `"推理輸出"`; kwargs contain `reasoning_effort="low"` |
| **Implementation** | `tests/test_context_generator.py::test_call_llm_sync_reasoning_content_fallback_and_effort_param` |

## TC-ctxgen-25: _generate_one — normal LLM response

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | `mocker.patch.object(gen, "_call_llm_sync", return_value="本段說明差旅費核銷規定")` |
| **Test input** | A Chinese chunk, file_name=`"差旅辦法.docx"`, `asyncio.Semaphore(1)` |
| **Test steps** | 1. `await gen._generate_one(...)` |
| **Expected result** | Returns `"本段說明差旅費核銷規定\n\n{chunk}"` |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_success` |

## TC-ctxgen-26: _generate_one — overlong context is truncated

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | generator(max_context_length=5); mock LLM returns `"A"*20` |
| **Test input** | English chunk `"english chunk"` |
| **Test steps** | 1. `await gen._generate_one(...)` |
| **Expected result** | Returns `"AAAAA\n\nenglish chunk"` (truncated to 5 characters) |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_truncates_long_context` |

## TC-ctxgen-27: _generate_one — falls back when LLM returns empty string

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | mock LLM returns `""` |
| **Test input** | chunk=`"chunk 內容"`, file_name=`"報告.docx"` |
| **Test steps** | 1. `await gen._generate_one(...)` |
| **Expected result** | Returns `"報告.docx\n\nchunk 內容"` (safe fallback) |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_empty_llm_response_falls_back` |

## TC-ctxgen-28: _generate_one — script mismatch fallback

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | mock LLM returns a pure-English prefix `"This chunk is about travel policy"` |
| **Test input** | Chinese chunk `"中文段落內容"`, file_name=`"辦法.docx"` |
| **Expected result** | The prefix is discarded; returns `"辦法.docx\n\n中文段落內容"` |
| **Test steps** | 1. `await gen._generate_one(...)` |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_script_mismatch_falls_back` |

## TC-ctxgen-29: _generate_one — falls back when LLM raises, without propagating

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | mock LLM `side_effect=RuntimeError("connection refused")` |
| **Test input** | chunk=`"chunk text"`, file_name=`"f.txt"` |
| **Test steps** | 1. `await gen._generate_one(...)` |
| **Expected result** | No exception raised; returns `"f.txt\n\nchunk text"` |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_llm_exception_falls_back` |

## TC-ctxgen-30: _generate_one — overlong full_document is truncated within the prompt

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-11 |
| **Level** | Unit |
| **Preconditions** | generator(max_doc_chars=10); mock `_call_llm_sync` captures the prompt |
| **Test input** | full_document=`"D"*100` |
| **Test steps** | 1. `await gen._generate_one(...)`<br>2. Read the prompt captured by the mock (`call_args[0][0]`) |
| **Expected result** | The prompt contains `"D"*10 + "\n...(文件過長，已截斷)"`; it does not contain `"D"*11` |
| **Implementation** | `tests/test_context_generator.py::test_generate_one_truncates_long_document_in_prompt` |

## TC-ctxgen-31: generate_batch — equal length and order-preserving

| Field | Content |
|-------|---------|
| **Requirement** | REQ-ctxgen-12 |
| **Level** | Unit |
| **Preconditions** | `mocker.patch.object(ContextGenerator, "_create_sync_client", return_value=None)`; mock `_call_llm_sync` returns `"CTX"` |
| **Test input** | chunks=`["chunk one", "chunk two", "chunk three"]` |
| **Test steps** | 1. `await gen.generate_batch(chunks, "full document", "file.txt")` |
| **Expected result** | The returned list is exactly `["CTX\n\nchunk one", "CTX\n\nchunk two", "CTX\n\nchunk three"]` (equal length, order preserved) |
| **Implementation** | `tests/test_context_generator.py::test_generate_batch_order_and_length` |

> Authoring principles: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
