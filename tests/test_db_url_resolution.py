
"""database.port 欄位注入(2026-09-07 用戶部署 DB 在非預設 port 5444)。

坑:create_engine/create_async_engine 只吃 url,忽略 config 分開的 port
欄位 → url 沒寫 port 時預設 5432,連錯實例 → password failed。
_resolve_db_url 在 url 未帶 port 時補上欄位 port。
"""

from types import SimpleNamespace

from db.db import _resolve_db_url


def _cfg(url, port):
    return SimpleNamespace(url=url, port=port)


def test_injects_field_port_when_url_has_none():
    r = _resolve_db_url(_cfg("postgresql://postgres:pw@localhost/db", 5444))
    assert ":5444/" in r

def test_url_port_takes_precedence_over_field():
    r = _resolve_db_url(_cfg("postgresql://postgres:pw@localhost:5432/db", 5444))
    assert ":5432/" in r and ":5444" not in r

def test_no_port_anywhere_left_untouched():
    r = _resolve_db_url(_cfg("postgresql://postgres:pw@localhost/db", None))
    assert "localhost/db" in r and ":54" not in r

def test_password_preserved():
    # render_as_string(hide_password=False) — 連線用,不能遮
    r = _resolve_db_url(_cfg("postgresql://postgres:secret@localhost/db", 5444))
    assert "secret" in r
