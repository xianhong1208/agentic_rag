
"""media STT 後端跟隨 `rag.asr.provider`(設定一處、索引與 /v1/transcriptions 兩邊生效)。

契約:
- docling-whisper(或 config 缺省/disabled)→ 走原 whisper-direct 路徑(回 None)
- fireredasr / openai-compatible 且 available → 回同一個 AsrProvider
- provider 不可用 / config 炸 → 安全回 None(fallback whisper,不擋端點)
- docling warmup 的 AUDIO 條件與掛載條件一致(asr_wants_local_whisper)—
  provider 非 docling-whisper 時,warmup 不得去暖 docling 預設 audio pipeline
  (那條會觸發執行期下載,離線/SSL 攔截環境直接炸)
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.router.media import _get_config_asr_provider
from src.domain.rag.docling_loader import asr_wants_local_whisper

_CFG = "src.config.config_manager.Config.get_config_model"


def _cfg(asr):
    return SimpleNamespace(rag=SimpleNamespace(asr=asr))


def _asr(provider="fireredasr", enabled=True):
    return SimpleNamespace(enabled=enabled, provider=provider,
                           base_url=None, api_key=None, model=None)


# ---- media 端點的 provider 選擇 ---------------------------------------------

class TestMediaProviderSelection:
    def test_config_missing_falls_back_whisper(self):
        with patch(_CFG, return_value=None):
            assert _get_config_asr_provider() == (None, None)

    def test_disabled_falls_back_whisper(self):
        with patch(_CFG, return_value=_cfg(_asr(enabled=False))):
            assert _get_config_asr_provider() == (None, None)

    def test_docling_whisper_uses_original_path(self):
        with patch(_CFG, return_value=_cfg(_asr("docling-whisper"))):
            assert _get_config_asr_provider() == (None, None)

    def test_fireredasr_returns_provider(self):
        fake = MagicMock()
        with patch(_CFG, return_value=_cfg(_asr("fireredasr"))), \
             patch("src.domain.rag.asr_provider.create_asr_provider",
                   return_value=fake):
            provider, name = _get_config_asr_provider()
        assert provider is fake
        assert name == "fireredasr"

    def test_fireredasr_unavailable_still_returned_no_silent_swap(self):
        # 權重不在(如打包漏帶)→ 仍回設定的 provider,由端點回 503 —
        # **絕不**因不可用就靜默換回 whisper(config 選了誰就是誰)
        fake = MagicMock()
        fake.available.return_value = False
        with patch(_CFG, return_value=_cfg(_asr("fireredasr"))), \
             patch("src.domain.rag.asr_provider.create_asr_provider",
                   return_value=fake):
            provider, name = _get_config_asr_provider()
        assert provider is fake and name == "fireredasr"

    def test_config_error_treated_as_default(self):
        with patch(_CFG, side_effect=RuntimeError("boom")):
            assert _get_config_asr_provider() == (None, None)


# ---- warmup 條件與掛載條件一致 ----------------------------------------------

class TestWarmupCondition:
    def test_docling_whisper_wants_local(self):
        with patch(_CFG, return_value=_cfg(_asr("docling-whisper"))):
            assert asr_wants_local_whisper() is True

    def test_fireredasr_does_not_want_local(self):
        # ← 修掉的 bug:舊 warmup 只看權重檔在不在,provider 切 fireredasr
        #   且機器殘留 whisper .pt 時仍去暖 docling 預設 audio pipeline
        with patch(_CFG, return_value=_cfg(_asr("fireredasr"))):
            assert asr_wants_local_whisper() is False

    def test_disabled_does_not_want_local(self):
        with patch(_CFG, return_value=_cfg(_asr("docling-whisper", enabled=False))):
            assert asr_wants_local_whisper() is False

    def test_config_missing_keeps_auto_discover(self):
        # config 缺省 → 舊 auto-discover 語義(要)— 向下相容
        with patch(_CFG, return_value=None):
            assert asr_wants_local_whisper() is True
