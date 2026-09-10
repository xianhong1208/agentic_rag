
"""ASR Provider — 音檔轉錄來源抽象(BL-07)。

音檔轉錄從「寫死 docling whisper」改為可替換的 provider(config `rag.asr`
選擇),H6 的注入模式:DocumentLoader 收注入的 provider,不自己挑實作。

實作:
- DoclingWhisperAsrProvider:封裝 docling_convert_once(本地 whisper turbo,
  預設;零行為變化)。回傳含 docling chunker 預切的 chunks。
- OpenAICompatibleAsrProvider:POST {base_url}/audio/transcriptions
  (multipart)— OpenAI / Groq / 自架 vLLM whisper / faster-whisper-server
  皆相容此介面。無預切 chunks(交回 leaf_splitter 的純文字路徑)。
- FireRedAsrProvider(BL-08,fireredasr_provider.py):本地 FireRedASR-AED-L
  (silencedetect 切段 ≤55s / 16k 重採樣 / OpenCC s2twp 簡→繁)。

模型無關的前後處理(前導靜音裁切、幻覺過濾)不在 provider 內 —
留在 document_loader 的 audio 分流層(audio_defense)。
"""

from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

import httpx

from src.log import get_api_logger
from src.domain.rag.asr_base import AsrProvider, AsrResult  # noqa: F401(re-export)
from src.domain.rag.docling_loader import docling_convert_once

if TYPE_CHECKING:
    from src.config.model import AsrConfig

logger = get_api_logger()


class DoclingWhisperAsrProvider(AsrProvider):
    """本地 docling whisper(預設)— 封裝 docling_convert_once,零行為變化。"""

    def available(self) -> bool:
        # 沿用舊 auto-discover 語義:assets/whisper_models/*.pt 在才可服務
        from src.domain.rag.docling_loader import _resolve_whisper_path
        return _resolve_whisper_path() is not None

    def transcribe(
        self, *, audio_path: str, file_name: str,
        max_tokens: Optional[int] = None, tokenizer: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> AsrResult:
        # max_tokens=None 直傳會蓋掉 convert_once 的預設 512 → refine 內
        # None//2 TypeError(evals 草稿腳本踩到;生產路徑恆有值沒事)
        full_text, chunk_records = docling_convert_once(
            file_path=audio_path, file_name=file_name,
            max_tokens=max_tokens if max_tokens is not None else 512,
            tokenizer=tokenizer,
            progress_cb=progress_cb,
        )
        # BL-05 後 convert_once 回 chunk 記錄;音檔無 heading/頁碼,取純文字
        chunks = [r["text"] if isinstance(r, dict) else r for r in chunk_records]
        return AsrResult(text=full_text, chunks=chunks)


class OpenAICompatibleAsrProvider(AsrProvider):
    """雲端/自架 HTTP ASR:POST {base_url}/audio/transcriptions(multipart)。"""

    def __init__(
        self, *, base_url: str, api_key: Optional[str] = None,
        model: Optional[str] = None, request_timeout: float = 300.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = request_timeout

    def transcribe(
        self, *, audio_path: str, file_name: str,
        max_tokens: Optional[int] = None, tokenizer: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> AsrResult:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        data = {}
        if self._model:
            data["model"] = self._model

        url = f"{self._base_url}/audio/transcriptions"
        logger.info(f"[ASR] cloud transcribe: {file_name} → {url}")
        with open(audio_path, "rb") as fh:
            with httpx.Client(headers=headers, timeout=self._timeout) as client:
                resp = client.post(url, data=data, files={"file": (file_name, fh)})
        resp.raise_for_status()
        text = resp.json().get("text", "")
        return AsrResult(text=text, chunks=None)


def create_asr_provider(asr_cfg: "Optional[AsrConfig]") -> AsrProvider:
    """工廠:依 config `rag.asr.provider` 建 provider。

    - None(config 未設)→ 預設 docling-whisper(向下相容)
    - openai-compatible 缺 base_url → 立刻 ValueError(啟動期就炸,
      不留到第一次轉錄才發現)
    - 未知 provider → ValueError 列出可用值
    """
    if asr_cfg is None:
        return DoclingWhisperAsrProvider()

    provider = asr_cfg.provider
    if provider == "docling-whisper":
        return DoclingWhisperAsrProvider()
    if provider == "openai-compatible":
        if not asr_cfg.base_url:
            raise ValueError(
                "rag.asr.provider=openai-compatible 需要 base_url"
                "(如 http://host:8000/v1)"
            )
        return OpenAICompatibleAsrProvider(
            base_url=asr_cfg.base_url,
            api_key=asr_cfg.api_key,
            model=asr_cfg.model,
        )
    if provider == "fireredasr":
        # lazy import:FireRedASR 鏈(torch/kaldi)只在選用時載
        from src.domain.rag.fireredasr_provider import FireRedAsrProvider
        return FireRedAsrProvider()
    raise ValueError(
        f"未知的 rag.asr.provider: {provider!r} — "
        "可用:docling-whisper / openai-compatible / fireredasr"
    )
