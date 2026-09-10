
"""Unit tests for src/utils/text_io.py — 上傳文字檔的編碼容錯讀取

背景:使用者用 Windows 記事本存「Unicode」(= UTF-16 LE + BOM)的 .txt 上傳,
原本寫死 utf-8 的讀取直接 UnicodeDecodeError(2026-08-11 實際案例)。
跑法:cd agentic_rag && uv run pytest tests/test_text_io.py -v
"""

import pytest

from src.utils.text_io import read_text_robust

SAMPLE = "新興科技教育遠距示範服務計畫,Budget: 1,000 元。\n第二行內容。"


def _write(tmp_path, name: str, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_plain_utf8(tmp_path):
    """一般 UTF-8 檔原樣讀出(TC-text-io-01)"""
    p = _write(tmp_path, "a.txt", SAMPLE.encode("utf-8"))
    assert read_text_robust(p) == SAMPLE


def test_utf8_with_bom_stripped(tmp_path):
    """UTF-8 BOM(Excel 匯出常見)要剝除,不能殘留 \\ufeff(TC-text-io-02)"""
    p = _write(tmp_path, "a.csv", b"\xef\xbb\xbf" + SAMPLE.encode("utf-8"))
    out = read_text_robust(p)
    assert out == SAMPLE
    assert not out.startswith("﻿")


def test_utf16_le_bom(tmp_path):
    """UTF-16 LE + BOM(Windows 記事本「Unicode」)— 本次事故的重現(TC-text-io-03)"""
    p = _write(tmp_path, "notepad.txt", SAMPLE.encode("utf-16"))  # 帶 LE BOM
    assert read_text_robust(p) == SAMPLE


def test_utf16_be_bom(tmp_path):
    """UTF-16 BE + BOM 同樣可讀(TC-text-io-04)"""
    p = _write(tmp_path, "be.txt", codecs_encode_utf16_be(SAMPLE))
    assert read_text_robust(p) == SAMPLE


def codecs_encode_utf16_be(s: str) -> bytes:
    import codecs
    return codecs.BOM_UTF16_BE + s.encode("utf-16-be")


def test_utf32_le_bom_not_mistaken_for_utf16(tmp_path):
    """UTF-32 LE 的 BOM 前兩碼 = UTF-16 LE BOM — 順序敏感的回歸測試(TC-text-io-05)"""
    p = _write(tmp_path, "u32.txt", SAMPLE.encode("utf-32"))  # 帶 LE BOM
    assert read_text_robust(p) == SAMPLE


def test_big5_detected(tmp_path):
    """Big5/CP950(台灣舊 txt/csv)靠 charset 偵測讀出(TC-text-io-06)"""
    p = _write(tmp_path, "big5.csv", text.encode("cp950"))
    assert read_text_robust(p) == text


def test_undecodable_binary_raises_actionable_error(tmp_path):
    """隨機二進制無法辨識 → ValueError 帶處置指引,絕不回亂碼(TC-text-io-07)"""
    p = _write(tmp_path, "junk.txt", bytes(range(256)) * 8)
    with pytest.raises(ValueError, match="另存為 UTF-8"):
        read_text_robust(p)


def test_empty_file_returns_empty_string(tmp_path):
    """空檔案回空字串,不拋例外(交由上游的空內容檢查處理)(TC-text-io-08)"""
    p = _write(tmp_path, "empty.txt", b"")
    assert read_text_robust(p) == ""
