"""Unit tests for src/domain/rag/context_generator.py — Contextual Retrieval 純邏輯

不依賴 DB / vLLM / GPU / 網路 — LLM 呼叫路徑以 pytest-mock stub 覆蓋,不發真實請求。
跑法:cd agentic_rag && uv run pytest tests/test_context_generator.py -v
對應文件:docs/testing/specs/SPEC-context-generator.md、docs/testing/test-cases/TC-context-generator.md
"""

import asyncio
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from src.domain.rag.context_generator import (
    ContextGenerator,
    _detect_scripts,
    _is_script_mismatch,
    _safe_fallback_prefix,
)


def _make_generator(**overrides) -> ContextGenerator:
    """建立不需真實 LLM config 的 ContextGenerator(單元測試用)"""
    kwargs = dict(llm_config=None, model="test-model")
    kwargs.update(overrides)
    return ContextGenerator(**kwargs)


# ============================================================================
# _detect_scripts
# ============================================================================

def test_detect_scripts_latin():
    """純英文(含 Latin Extended 重音字母)回 {'Latin'} (TC-ctxgen-01)"""
    assert _detect_scripts("Hello world") == {"Latin"}
    assert _detect_scripts("café résumé") == {"Latin"}


def test_detect_scripts_cjk():
    """純中文回 {'CJK'} (TC-ctxgen-02)"""
    assert _detect_scripts("這是一段中文") == {"CJK"}


def test_detect_scripts_japanese_kana_and_kanji():
    """日文平假名/片假名/漢字分別偵測為 Hiragana / Katakana / CJK (TC-ctxgen-03)"""
    assert _detect_scripts("こんにちは") == {"Hiragana"}
    assert _detect_scripts("カタカナ") == {"Katakana"}
    assert _detect_scripts("日本語のテスト") == {"CJK", "Hiragana", "Katakana"}


@pytest.mark.parametrize(
    "text, expected_script",
    [
        ("안녕하세요", "Hangul"),
        ("Привет", "Cyrillic"),
        ("مرحبا", "Arabic"),
        ("שלום", "Hebrew"),
        ("สวัสดี", "Thai"),
        ("नमस्ते", "Devanagari"),
    ],
    ids=["hangul", "cyrillic", "arabic", "hebrew", "thai", "devanagari"],
)
def test_detect_scripts_other_major_scripts(text, expected_script):
    """韓/俄/阿/希伯來/泰/天城文各自被正確歸類 (TC-ctxgen-04)"""
    assert expected_script in _detect_scripts(text)


def test_detect_scripts_ignores_non_alpha():
    """數字、標點、空白不計入;空字串回空集合 (TC-ctxgen-05)"""
    assert _detect_scripts("12345 !?,.()") == set()
    assert _detect_scripts("") == set()


def test_detect_scripts_mixed_text():
    """中英混合回傳兩個 script (TC-ctxgen-06)"""
    assert _detect_scripts("公司 Q3 revenue 成長") == {"CJK", "Latin"}


# ============================================================================
# _is_script_mismatch
# ============================================================================

def test_mismatch_cjk_chunk_latin_prefix():
    """中文 chunk 配純英文 prefix → mismatch=True (TC-ctxgen-07)"""
    assert _is_script_mismatch("這是中文段落", "This chunk describes something") is True


def test_no_mismatch_cjk_chunk_cjk_prefix():
    """中文 chunk 配中文 prefix(可夾雜英數)→ False (TC-ctxgen-08)"""
    assert _is_script_mismatch("這是中文段落", "本段說明 Q3 財報重點") is False


def test_no_mismatch_pure_latin_chunk():
    """純英文 chunk 不論 prefix 語言一律 False(Latin 容差)(TC-ctxgen-09)"""
    assert _is_script_mismatch("English chunk text", "English prefix") is False
    assert _is_script_mismatch("English chunk text", "中文前綴") is False


def test_mismatch_cjk_chunk_empty_or_numeric_prefix():
    """中文 chunk 配空字串或純數字 prefix(無任何非拉丁腳本)→ True (TC-ctxgen-10)"""
    assert _is_script_mismatch("中文內容", "") is True
    assert _is_script_mismatch("中文內容", "12345") is True


def test_mismatch_mixed_chunk_uses_non_latin_main_script():
    """中英混合 chunk 以非拉丁腳本為主判定:純英 prefix → True,中文 prefix → False (TC-ctxgen-11)"""
    assert _is_script_mismatch("中文 mixed with English", "english only prefix") is True
    assert _is_script_mismatch("中文 mixed with English", "中文前綴") is False


def test_mismatch_hangul_chunk_latin_prefix():
    """非中文的非拉丁腳本(韓文)同樣受保護 → True (TC-ctxgen-12)"""
    assert _is_script_mismatch("안녕하세요 문서입니다", "English prefix") is True


# ============================================================================
# _safe_fallback_prefix
# ============================================================================

def test_safe_fallback_prefix_format():
    """回傳 '{file_name}\\n\\n{chunk_text}' 格式 (TC-ctxgen-13)"""
    assert _safe_fallback_prefix("chunk 內容", "報告.docx") == "報告.docx\n\nchunk 內容"


# ============================================================================
# ContextGenerator 建構 / from_config
# ============================================================================

def test_init_stores_params_and_defaults():
    """__init__ 保存必填參數並套用預設值 (TC-ctxgen-14)"""
    gen = _make_generator()
    assert gen._model == "test-model"
    assert gen._max_context_length == 150
    assert gen._max_concurrent == 50
    assert gen._max_doc_chars == 60000
    assert gen._max_tokens == 1024
    assert gen._reasoning_effort is None


def test_from_config_disabled_returns_none():
    """未設定或 enabled=False 時回 None (TC-ctxgen-15)"""
    assert ContextGenerator.from_config(SimpleNamespace()) is None
    cfg = SimpleNamespace(contextual_retrieval=SimpleNamespace(enabled=False))
    assert ContextGenerator.from_config(cfg) is None


def test_from_config_missing_llm_returns_none():
    """enabled=True 但缺 llm 設定時回 None (TC-ctxgen-16)"""
    cfg = SimpleNamespace(
        contextual_retrieval=SimpleNamespace(enabled=True, max_context_length=100),
        llm=None,
    )
    assert ContextGenerator.from_config(cfg) is None


def test_from_config_success_prefers_azure_deployment():
    """正常設定回傳 instance,model 優先取 azure_deployment (TC-ctxgen-17)"""
    cfg = SimpleNamespace(
        contextual_retrieval=SimpleNamespace(
            enabled=True,
            max_context_length=120,
            max_concurrent=8,
            max_doc_chars=1000,
            max_tokens=256,
            reasoning_effort="low",
        ),
        llm=SimpleNamespace(azure_deployment="gpt-4o-dep", model="gpt-4o"),
    )
    gen = ContextGenerator.from_config(cfg)
    assert isinstance(gen, ContextGenerator)
    assert gen._model == "gpt-4o-dep"
    assert gen._max_context_length == 120
    assert gen._max_concurrent == 8
    assert gen._max_doc_chars == 1000
    assert gen._max_tokens == 256
    assert gen._reasoning_effort == "low"


def test_from_config_model_fallback_and_optional_defaults():
    """azure_deployment 為 None 時 fallback 到 model;可選欄位缺時用預設值 (TC-ctxgen-18)"""
    cfg = SimpleNamespace(
        contextual_retrieval=SimpleNamespace(enabled=True, max_context_length=100),
        llm=SimpleNamespace(azure_deployment=None, model="qwen3"),
    )
    gen = ContextGenerator.from_config(cfg)
    assert gen._model == "qwen3"
    assert gen._max_concurrent == 50
    assert gen._max_doc_chars == 60000
    assert gen._max_tokens == 1024
    assert gen._reasoning_effort is None


def test_from_config_missing_required_field_returns_none():
    """缺必要欄位(max_context_length)時內部例外被吃掉並回 None (TC-ctxgen-19)"""
    cfg = SimpleNamespace(
        contextual_retrieval=SimpleNamespace(enabled=True),
        llm=SimpleNamespace(azure_deployment=None, model="m"),
    )
    assert ContextGenerator.from_config(cfg) is None


# ============================================================================
# _create_sync_client(僅測不需網路的錯誤與參數路徑)
# ============================================================================

def test_create_sync_client_unsupported_provider():
    """不支援的 provider 拋 ValueError (TC-ctxgen-20)"""
    llm = SimpleNamespace(provider="groq")
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        ContextGenerator._create_sync_client(llm)


def test_create_sync_client_vllm_requires_base_url():
    """vllm 缺 base_url 拋 ValueError (TC-ctxgen-21)"""
    llm = SimpleNamespace(provider="vllm", base_url=None, api_key=None)
    with pytest.raises(ValueError, match="requires base_url"):
        ContextGenerator._create_sync_client(llm)


def test_create_sync_client_vllm_builds_openai_client():
    """vllm 有 base_url 時建出指向該 URL 的 OpenAI client(無 api_key 用占位)(TC-ctxgen-22)"""
    llm = SimpleNamespace(provider="vllm", base_url="http://localhost:8000/v1", api_key=None)
    client = ContextGenerator._create_sync_client(llm)
    assert str(client.base_url).startswith("http://localhost:8000/v1")
    assert client.api_key == "not-needed"


# ============================================================================
# _call_llm_sync(stub client,不發真實請求)
# ============================================================================

class _StubClient:
    """最小 OpenAI client stub — 記錄 create() kwargs 並回傳預先給定的 message"""

    def __init__(self, message):
        self.captured_kwargs = None
        self._message = message
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.captured_kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self._message)])


def test_call_llm_sync_returns_content_and_request_params():
    """回傳 message.content,且帶入 model / max_tokens / temperature=0 (TC-ctxgen-23)"""
    stub = _StubClient(SimpleNamespace(content="生成的上下文"))
    gen = _make_generator(max_tokens=256)

    result = gen._call_llm_sync("some prompt", stub)

    assert result == "生成的上下文"
    assert stub.captured_kwargs["model"] == "test-model"
    assert stub.captured_kwargs["max_tokens"] == 256
    assert stub.captured_kwargs["temperature"] == 0
    assert "reasoning_effort" not in stub.captured_kwargs  # 未設定時不得傳


def test_call_llm_sync_reasoning_content_fallback_and_effort_param():
    """content 為空時 fallback 到 reasoning_content;reasoning_effort 有設定時傳入 (TC-ctxgen-24)"""
    stub = _StubClient(SimpleNamespace(content="", reasoning_content="推理輸出"))
    gen = _make_generator(reasoning_effort="low")

    result = gen._call_llm_sync("prompt", stub)

    assert result == "推理輸出"
    assert stub.captured_kwargs["reasoning_effort"] == "low"


# ============================================================================
# _generate_one / generate_batch(LLM 以 mock 取代)
# ============================================================================

async def test_generate_one_success(mocker: MockerFixture):
    """LLM 正常回應 → '{context}\\n\\n{chunk}' (TC-ctxgen-25)"""
    gen = _make_generator()
    mocker.patch.object(gen, "_call_llm_sync", return_value="本段說明差旅費核銷規定")

    result = await gen._generate_one(
        "前項所述之情形,不適用本條規定。", "全文...", "差旅辦法.docx",
        client=None, semaphore=asyncio.Semaphore(1),
    )

    assert result == "本段說明差旅費核銷規定\n\n前項所述之情形,不適用本條規定。"


async def test_generate_one_truncates_long_context(mocker: MockerFixture):
    """context 超過 max_context_length 時截斷後再拼接 (TC-ctxgen-26)"""
    gen = _make_generator(max_context_length=5)
    mocker.patch.object(gen, "_call_llm_sync", return_value="A" * 20)

    result = await gen._generate_one(
        "english chunk", "doc", "f.txt", client=None, semaphore=asyncio.Semaphore(1),
    )

    assert result == "AAAAA\n\nenglish chunk"


async def test_generate_one_empty_llm_response_falls_back(mocker: MockerFixture):
    """LLM 回空字串 → safe fallback prefix (TC-ctxgen-27)"""
    gen = _make_generator()
    mocker.patch.object(gen, "_call_llm_sync", return_value="")

    result = await gen._generate_one(
        "chunk 內容", "doc", "報告.docx", client=None, semaphore=asyncio.Semaphore(1),
    )

    assert result == "報告.docx\n\nchunk 內容"


async def test_generate_one_script_mismatch_falls_back(mocker: MockerFixture):
    """中文 chunk 拿到純英文 prefix → 丟棄並用 fallback (TC-ctxgen-28)"""
    gen = _make_generator()
    mocker.patch.object(gen, "_call_llm_sync", return_value="This chunk is about travel policy")

    result = await gen._generate_one(
        "中文段落內容", "doc", "辦法.docx", client=None, semaphore=asyncio.Semaphore(1),
    )

    assert result == "辦法.docx\n\n中文段落內容"


async def test_generate_one_llm_exception_falls_back(mocker: MockerFixture):
    """LLM 拋例外 → 不外洩,回 fallback (TC-ctxgen-29)"""
    gen = _make_generator()
    mocker.patch.object(gen, "_call_llm_sync", side_effect=RuntimeError("connection refused"))

    result = await gen._generate_one(
        "chunk text", "doc", "f.txt", client=None, semaphore=asyncio.Semaphore(1),
    )

    assert result == "f.txt\n\nchunk text"


async def test_generate_one_truncates_long_document_in_prompt(mocker: MockerFixture):
    """full_document 超過 max_doc_chars 時 prompt 內文件被截斷並加註記 (TC-ctxgen-30)"""
    gen = _make_generator(max_doc_chars=10)
    mock_call = mocker.patch.object(gen, "_call_llm_sync", return_value="ctx")

    await gen._generate_one(
        "chunk", "D" * 100, "f.txt", client=None, semaphore=asyncio.Semaphore(1),
    )

    prompt = mock_call.call_args[0][0]
    assert "D" * 10 + "\n...(文件過長，已截斷)" in prompt
    assert "D" * 11 not in prompt


async def test_generate_batch_order_and_length(mocker: MockerFixture):
    """generate_batch 回傳與 chunks 等長且順序一一對應 (TC-ctxgen-31)"""
    gen = _make_generator()
    mocker.patch.object(ContextGenerator, "_create_sync_client", return_value=None)
    mocker.patch.object(gen, "_call_llm_sync", return_value="CTX")

    chunks = ["chunk one", "chunk two", "chunk three"]
    results = await gen.generate_batch(chunks, "full document", "file.txt")

    assert results == [f"CTX\n\n{c}" for c in chunks]
