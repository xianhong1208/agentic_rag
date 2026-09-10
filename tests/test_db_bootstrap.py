
"""Unit tests for src/utils/db_bootstrap.py — 只測 _validate_dbname(純邏輯)

db_bootstrap 已對齊 MCP_Center a46a4b8 定案模式:全程 SQLAlchemy、憑證由
make_url 處理(不再有 _parse_db_url 憑證 dict)、CREATE DATABASE 前過
_validate_dbname 白名單 + `"` 加倍跳脫。可單元測試的純邏輯只剩白名單本身;
其餘(_ensure_database_exists / ensure_database_ready)需真實 DB,屬整合
測試範疇,不在此檔涵蓋。
跑法:cd agentic_rag && uv run pytest tests/test_db_bootstrap.py -v
"""

import pytest

from src.utils.db_bootstrap import _MAX_IDENTIFIER_BYTES, _validate_dbname


def test_validate_accepts_typical_dbname():
    """常規名稱(字母開頭+底線)原樣放行(TC-db-bootstrap-01)"""
    assert _validate_dbname("agentic_rag") == "agentic_rag"


def test_validate_accepts_allowed_special_chars():
    """允許字元集內的連字號/數字/$ 放行(TC-db-bootstrap-02)"""
    assert _validate_dbname("db-2026_$x") == "db-2026_$x"


def test_validate_rejects_leading_digit():
    """數字開頭違反白名單 → ValueError(TC-db-bootstrap-03)"""
    with pytest.raises(ValueError):
        _validate_dbname("1abc")


def test_validate_rejects_sql_injection_payload():
    """含引號/分號的注入 payload 必須擋下(TC-db-bootstrap-04)

    這是 CREATE DATABASE 白名單的核心價值:identifier 不能 bind param,
    白名單是第一道防線(第二道是 `"` 加倍跳脫)。
    """
    with pytest.raises(ValueError):
        _validate_dbname('evil"; DROP DATABASE x; --')


@pytest.mark.parametrize("bad", ["", "a b", "中文庫", "tab\tname"])
def test_validate_rejects_empty_whitespace_and_nonascii(bad):
    """空字串/空白/非 ASCII 一律拒絕(TC-db-bootstrap-05)"""
    with pytest.raises(ValueError):
        _validate_dbname(bad)


def test_validate_rejects_over_63_bytes():
    """超過 Postgres NAMEDATALEN-1(63 bytes)拒絕 — 否則會被靜默截斷(TC-db-bootstrap-06)"""
    with pytest.raises(ValueError):
        _validate_dbname("x" * (_MAX_IDENTIFIER_BYTES + 1))
    # 剛好 63 bytes 要放行(邊界)
    assert _validate_dbname("x" * _MAX_IDENTIFIER_BYTES) == "x" * _MAX_IDENTIFIER_BYTES
