
"""error_handler — 統一錯誤格式(domain / generic)與註冊函式。"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException

from src.domain.exceptions import RAGFileNotFoundError, DomainException
from src.middleware.error_handler import (
    domain_exception_handler,
    generic_exception_handler,
    register_error_handlers,
)


def _req(path="/api/x"):
    r = MagicMock()
    r.url.path = path
    return r


async def test_domain_exception_maps_status_and_body():
    """DomainException → 對應 HTTP status + 結構化 body(error_code/message)。"""
    exc = RAGFileNotFoundError(file_id="f-123")
    resp = await domain_exception_handler(_req(), exc)
    assert resp.status_code == 404
    body = json.loads(resp.body)
    assert body.get("error") or body.get("error_code")


async def test_generic_exception_returns_500_without_leaking():
    """未預期例外 → 500 generic body,不外洩內部訊息。"""
    resp = await generic_exception_handler(_req("/api/y"), RuntimeError("secret detail"))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    assert "secret detail" not in resp.body.decode()
    assert body["path"] == "/api/y"


async def test_generic_handler_reraises_http_exception():
    """HTTPException 顯式 re-raise,讓 FastAPI 原生 handler 管 status(不吞成 500)。"""
    with pytest.raises(HTTPException):
        await generic_exception_handler(_req(), HTTPException(status_code=418))


def test_register_error_handlers_wires_both():
    """register_error_handlers 把 domain + generic 兩個 handler 掛上 app。"""
    app = FastAPI()
    register_error_handlers(app)
    assert app.exception_handlers.get(DomainException) is domain_exception_handler
    assert app.exception_handlers.get(Exception) is generic_exception_handler
