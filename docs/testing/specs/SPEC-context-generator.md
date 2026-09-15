# SPEC-context-generator: Contextual Retrieval Context-Prefix Generator


| Item | Content |
|------|------|
| Module | `src/domain/rag/context_generator.py` |
| Test | `tests/test_context_generator.py` |
| Version | v1.0 (feat/rag-robustness) |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Generates a context prefix for each chunk (the Anthropic Contextual Retrieval strategy), comprising three pure functions
(`_detect_scripts` / `_is_script_mismatch` / `_safe_fallback_prefix`) and the `ContextGenerator` class.
This spec covers: the full behavior of the pure functions; class construction / `from_config` / client parameter validation; and, with the LLM replaced by a mock, the control flow of
`_call_llm_sync` / `_generate_one` / `generate_batch`. **Real-LLM output quality** (how good the generated content is)
belongs to integration / system testing and is out of scope.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-ctxgen-01 | `_detect_scripts` classifies letters by Unicode block into Latin / CJK / Hiragana / Katakana / Hangul / Cyrillic / Arabic / Hebrew / Thai / Devanagari | Sample text in each script returns a set containing the corresponding script name; Latin Extended (é, etc.) is classified as Latin |
| REQ-ctxgen-02 | `_detect_scripts` ignores non-letter characters (digits, punctuation, whitespace); an empty string returns an empty set | `"12345 !?,.()"` and `""` both return `set()` |
| REQ-ctxgen-03 | Mixed text returns multiple scripts | Mixed Chinese/English → `{"CJK", "Latin"}` |
| REQ-ctxgen-04 | `_is_script_mismatch`: chunk contains a non-Latin main script while the prefix contains no non-Latin script at all (including an empty / digits-only prefix) → True | Chinese chunk + English / empty / digits prefix → True; Korean chunk + English prefix → True; mixed Chinese/English chunk + pure-English prefix → True |
| REQ-ctxgen-05 | `_is_script_mismatch`: a pure-Latin chunk is always False; if the prefix contains any non-Latin script it is also False (Latin tolerance) | English chunk + any prefix → False; Chinese chunk + Chinese (may include English/digits) prefix → False |
| REQ-ctxgen-06 | `_safe_fallback_prefix` returns `"{file_name}\n\n{chunk_text}"` with no natural-language wrapper | Output is character-for-character equal to that format |
| REQ-ctxgen-07 | `ContextGenerator.__init__` stores parameters and applies defaults (max_context_length=150, max_concurrent=50, max_doc_chars=60000, max_tokens=1024, reasoning_effort=None) | The corresponding private attributes are correct after construction |
| REQ-ctxgen-08 | `from_config`: not configured / enabled=False / missing llm / missing a required field → returns None without raising; a valid config → returns an instance, with model preferring `azure_deployment` and otherwise `model`; missing optional fields use defaults | Each config combination returns None or an instance with correct attributes |
| REQ-ctxgen-09 | `_create_sync_client`: an unsupported provider raises ValueError; vllm/ollama without base_url raises ValueError; a valid vllm config builds an OpenAI client pointing at base_url (with `"not-needed"` as the placeholder when there is no api_key) | Error paths raise a descriptive ValueError; the valid path has correct client.base_url / api_key |
| REQ-ctxgen-10 | `_call_llm_sync` calls chat.completions.create with model / max_tokens / temperature=0; reasoning_effort is passed only when set; when content is empty it falls back to reading `reasoning_content` | The kwargs captured by the stub client are correct; the return value follows the fallback rule |
| REQ-ctxgen-11 | `_generate_one`: on a valid LLM response → `"{context}\n\n{chunk}"`; a context exceeding max_context_length is truncated; on an empty LLM response / script mismatch / raised exception → always returns the safe fallback without leaking the exception; when full_document exceeds max_doc_chars, it is truncated inside the prompt with a note | Each path's output is precisely assertable; exceptions do not bubble up |
| REQ-ctxgen-12 | `generate_batch` returns a list the same length as chunks with a one-to-one order correspondence | 3 chunks → 3 results, each ending with the original text of its chunk |

## 3. Non-Functional Requirements

- Unit tests must not make any network request — the LLM call is always replaced by a pytest-mock stub.
- `_generate_one` must degrade (fall back) on any LLM-side error rather than interrupting the whole indexing batch.

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| `_detect_scripts("")` / digits-and-punctuation only | returns an empty set |
| Chinese chunk with an empty-string prefix | mismatch=True (triggers fallback) |
| LLM returns an empty string or None | returns the `_safe_fallback_prefix` result |
| LLM raises an exception (connection failure, etc.) | caught, logged, returns fallback, does not bubble up |
| context length exceeds max_context_length | hard-truncated to the limit before concatenation |
| full_document length exceeds max_doc_chars | truncated inside the prompt with a `...(文件過長，已截斷)` note appended |
| provider name not in the supported list | `ValueError` (lists the supported set) |

## 5. Dependencies & Assumptions

- `src.log.get_api_logger` — logging only, no mock needed.
- The `openai` package is lazy-imported inside `_create_sync_client`; constructing the client object makes no network request, so error paths and parameter validation are directly testable. `chat.completions.create` is always replaced by a stub / mocker.
- The Azure / OpenAI provider paths depend on environment variables (`AZURE_OPENAI_API_KEY`, etc.); to keep tests free of environment contamination, the unit tests cover only vllm and the error paths.
- Known limitation (not a defect, recorded on file): letters not covered by `_detect_scripts` (e.g. Greek, or µ/ª in U+0080–U+00BF) are not classified into any script, so mismatch detection for such text leans toward "uncertain → do not fall back".

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-ctxgen-01 | TC-ctxgen-01 ~ TC-ctxgen-04 | `tests/test_context_generator.py::test_detect_scripts_latin`, `::test_detect_scripts_cjk`, `::test_detect_scripts_japanese_kana_and_kanji`, `::test_detect_scripts_other_major_scripts` (parametrized, 6 groups) |
| REQ-ctxgen-02 | TC-ctxgen-05 | `tests/test_context_generator.py::test_detect_scripts_ignores_non_alpha` |
| REQ-ctxgen-03 | TC-ctxgen-06 | `tests/test_context_generator.py::test_detect_scripts_mixed_text` |
| REQ-ctxgen-04 | TC-ctxgen-07, TC-ctxgen-10, TC-ctxgen-11, TC-ctxgen-12 | `tests/test_context_generator.py::test_mismatch_cjk_chunk_latin_prefix`, `::test_mismatch_cjk_chunk_empty_or_numeric_prefix`, `::test_mismatch_mixed_chunk_uses_non_latin_main_script`, `::test_mismatch_hangul_chunk_latin_prefix` |
| REQ-ctxgen-05 | TC-ctxgen-08, TC-ctxgen-09 | `tests/test_context_generator.py::test_no_mismatch_cjk_chunk_cjk_prefix`, `::test_no_mismatch_pure_latin_chunk` |
| REQ-ctxgen-06 | TC-ctxgen-13 | `tests/test_context_generator.py::test_safe_fallback_prefix_format` |
| REQ-ctxgen-07 | TC-ctxgen-14 | `tests/test_context_generator.py::test_init_stores_params_and_defaults` |
| REQ-ctxgen-08 | TC-ctxgen-15 ~ TC-ctxgen-19 | `tests/test_context_generator.py::test_from_config_disabled_returns_none`, `::test_from_config_missing_llm_returns_none`, `::test_from_config_success_prefers_azure_deployment`, `::test_from_config_model_fallback_and_optional_defaults`, `::test_from_config_missing_required_field_returns_none` |
| REQ-ctxgen-09 | TC-ctxgen-20 ~ TC-ctxgen-22 | `tests/test_context_generator.py::test_create_sync_client_unsupported_provider`, `::test_create_sync_client_vllm_requires_base_url`, `::test_create_sync_client_vllm_builds_openai_client` |
| REQ-ctxgen-10 | TC-ctxgen-23, TC-ctxgen-24 | `tests/test_context_generator.py::test_call_llm_sync_returns_content_and_request_params`, `::test_call_llm_sync_reasoning_content_fallback_and_effort_param` |
| REQ-ctxgen-11 | TC-ctxgen-25 ~ TC-ctxgen-30 | `tests/test_context_generator.py::test_generate_one_success`, `::test_generate_one_truncates_long_context`, `::test_generate_one_empty_llm_response_falls_back`, `::test_generate_one_script_mismatch_falls_back`, `::test_generate_one_llm_exception_falls_back`, `::test_generate_one_truncates_long_document_in_prompt` |
| REQ-ctxgen-12 | TC-ctxgen-31 | `tests/test_context_generator.py::test_generate_batch_order_and_length` |
