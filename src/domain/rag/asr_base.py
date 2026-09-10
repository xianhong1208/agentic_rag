
"""ASR 抽象底層 — AsrResult / AsrProvider(BL-07)。

獨立成底層模組的原因:工廠(asr_provider)要 lazy import 各實作,而實作
要 import 這兩個型別 — 型別若住在工廠模組就成
asr_provider ⇄ fireredasr_provider 執行期環(test_import_cycles 抓的)。
依賴方向:實作 → asr_base ← 工廠,單向。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class AsrResult:
    """轉錄結果。chunks = provider 已預切的分塊(docling 有;雲端/FireRedASR
    None → 交回 leaf_splitter 的純文字切分路徑)。"""
    text: str
    chunks: Optional[List[str]] = None


class AsrProvider(ABC):
    """音檔 → 文字。實作不得吞例外 — 失敗原樣 raise,由 index_document
    的既有失敗路徑寫 FileIndex failed tag。"""

    def available(self) -> bool:
        """此 provider 目前可服務嗎(模型在/端點設定齊)。
        False → document_loader 讓音檔走舊 fallback 路徑,不嘗試轉錄。"""
        return True

    @abstractmethod
    def transcribe(
        self,
        *,
        audio_path: str,
        file_name: str,
        max_tokens: Optional[int] = None,
        tokenizer: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> AsrResult:
        """轉錄一個音檔。max_tokens/tokenizer 供會預切 chunk 的 provider
        (docling)用;不預切的 provider 忽略即可。"""
