
"""上傳文字檔(.txt/.json/.csv)的編碼容錯讀取。

背景:索引路徑原本寫死 ``open(..., encoding='utf-8')``,但實務上:
- Windows 記事本的「Unicode」= UTF-16 LE(含 BOM)— 2026-08 實際使用者中招
- 台灣企業環境的舊 txt/csv 常是 Big5/CP950
- Excel 匯出 csv 依地區設定可能是 cp950 或 utf-8-sig

策略(嚴格 → 寬鬆,絕不靜默輸出亂碼):
1. BOM 嗅探(UTF-32 要在 UTF-16 之前查 — UTF-32 LE BOM 的前兩碼就是 UTF-16 LE BOM)
2. 嚴格 UTF-8
3. charset_normalizer 偵測(requests 的既有依賴,零新增)— 命中即用並 log 實際編碼
4. 全部失敗 → raise ValueError 給出可行動訊息(請另存 UTF-8)
   寧可索引失敗留下明確錯誤,也不把 mojibake 餵進向量庫(.doc 的教訓)。
"""

from __future__ import annotations

import codecs
from pathlib import Path

from src.log import get_api_logger

logger = get_api_logger()

# 順序敏感:UTF-32 LE 的 BOM(FF FE 00 00)以 UTF-16 LE 的 BOM(FF FE)開頭,
# 先比對長的,否則 UTF-32 檔會被誤判成 UTF-16
_BOM_TABLE = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def read_text_robust(path: str | Path, file_name: str = "") -> str:
    """讀取文字檔,自動處理 UTF-8 / UTF-16 / UTF-32 / Big5 等常見編碼。

    Args:
        path: 檔案路徑。
        file_name: log / 錯誤訊息用的顯示名(預設用 path 檔名)。

    Returns:
        解碼後的文字(BOM 已剝除)。

    Raises:
        ValueError: 無法辨識編碼 — 訊息含處置指引,會進 FileIndex.error_message。
    """
    label = file_name or Path(path).name
    data = Path(path).read_bytes()

    # 1. BOM 嗅探 — 有 BOM 就是明確宣告,直接信
    for bom, enc in _BOM_TABLE:
        if data.startswith(bom):
            text = data.decode(enc)
            if enc != "utf-8-sig":
                logger.info(f"[TEXT_IO] '{label}' decoded as {enc} (BOM detected)")
            return text

    # 2. 嚴格 UTF-8(絕大多數檔案在這裡返回,零額外成本)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # 3. charset_normalizer 偵測(Big5/CP950、無 BOM 的 UTF-16 等)
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
    except Exception as e:  # pragma: no cover - 防禦性
        logger.warning(f"[TEXT_IO] charset detection failed for '{label}': {e}")
        best = None

    if best is not None:
        logger.info(
            f"[TEXT_IO] '{label}' is not UTF-8; decoded as detected "
            f"encoding '{best.encoding}'"
        )
        return str(best)

    # 4. 大聲失敗 — 不把亂碼餵進向量庫
    raise ValueError(
        f"無法辨識 '{label}' 的文字編碼(非 UTF-8/UTF-16/Big5 等常見編碼)。"
        f"請將檔案另存為 UTF-8 後重新上傳。"
    )
