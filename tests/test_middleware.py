"""Unit tests for src/middleware (request_id.py + error_handler.py)

不依賴 DB / 網路 / 真實 server — ASGI scope 與 FastAPI Request 全用假物件。
跑法:cd agentic_rag && uv run pytest tests/test_middleware.py -v
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.middleware.request_id import RequestIdMiddleware
from src.middleware.error_handler import (
    domain_exception_handler,
    generic_exception_handler,
)
from src.log import get_request_id, set_request_id
from src.domain.exceptions import (
    DomainException,
    FolderNotFoundError,
    FileIndexNotFoundError,
    InvalidTokenError,
    ValidationError as DomainValidationError,
    ConflictError,
    QueryExecutionError,
    get_http_status_for_exception,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _noop_receive():
    return {"type": "http.request"}


async def _noop_send(message):
    pass


def _make_capture_app(captured: dict):
    """假下游 ASGI app:記錄呼叫當下的 request_id 與參數"""
    async def app(scope, receive, send):
        captured["rid"] = get_request_id()
        captured["args"] = (scope, receive, send)
    return app


def _fake_request(path="/api/test"):
    """最小可用的假 Request(error handler 只讀 request.url.path)"""
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _body(response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# request_id.py — RequestIdMiddleware
# ---------------------------------------------------------------------------

async def test_request_id_set_for_http_scope():
    """http scope → 產生新 request_id 注入 contextvar,下游 app 可讀到 (TC-middleware-01)"""
    captured = {}
    middleware = RequestIdMiddleware(_make_capture_app(captured))
    await middleware({"type": "http", "path": "/x"}, _noop_receive, _noop_send)
    assert captured["rid"] != "-"
    assert len(captured["rid"]) == 8  # UUID 前 8 碼


async def test_request_id_unique_per_request():
    """兩個 http 請求各拿到不同的 request_id (TC-middleware-02)"""
    captured = {}
    middleware = RequestIdMiddleware(_make_capture_app(captured))
    await middleware({"type": "http"}, _noop_receive, _noop_send)
    first = captured["rid"]
    await middleware({"type": "http"}, _noop_receive, _noop_send)
    assert captured["rid"] != first


async def test_request_id_not_set_for_non_http_scope():
    """非 http scope(lifespan)→ 不產生新 id,contextvar 維持原值 (TC-middleware-03)"""
    set_request_id("sentinel1")
    captured = {}
    middleware = RequestIdMiddleware(_make_capture_app(captured))
    await middleware({"type": "lifespan"}, _noop_receive, _noop_send)
    assert captured["rid"] == "sentinel1"  # 沒被覆寫


async def test_middleware_passes_through_asgi_args():
    """middleware 原封不動把 scope/receive/send 傳給下游 app (TC-middleware-04)"""
    captured = {}
    middleware = RequestIdMiddleware(_make_capture_app(captured))
    scope = {"type": "http", "path": "/y"}
    await middleware(scope, _noop_receive, _noop_send)
    assert captured["args"] == (scope, _noop_receive, _noop_send)


# ---------------------------------------------------------------------------
# error_handler.py — domain_exception_handler
# ---------------------------------------------------------------------------

async def test_domain_handler_folder_not_found_404():
    """FolderNotFoundError → 404,body 含 error/message/timestamp/path/details (TC-middleware-05)"""
    request = _fake_request("/api/folders/99")
    response = await domain_exception_handler(request, FolderNotFoundError(folder_id=99))
    assert response.status_code == 404
    body = _body(response)
    assert body["error"] == "FOLDER_NOT_FOUND"
    assert "99" in body["message"]
    assert body["path"] == "/api/folders/99"
    assert "timestamp" in body
    assert body["details"] == {"resource_type": "folder", "identifier": "99"}


async def test_domain_handler_validation_error_400():
    """domain ValidationError → 400 + VALIDATION_ERROR,details 帶欄位資訊 (TC-middleware-06)"""
    exc = DomainValidationError(field="chunk_size", message="too small", value=1)
    response = await domain_exception_handler(_fake_request(), exc)
    assert response.status_code == 400
    body = _body(response)
    assert body["error"] == "VALIDATION_ERROR"
    assert body["details"] == {"field": "chunk_size", "invalid_value": "1"}


async def test_domain_handler_invalid_token_401_no_details():
    """InvalidTokenError → 401,details 為空時 body 不含 details 鍵 (TC-middleware-07)"""
    response = await domain_exception_handler(_fake_request(), InvalidTokenError())
    assert response.status_code == 401
    body = _body(response)
    assert body["error"] == "INVALID_TOKEN"
    assert "details" not in body


async def test_domain_handler_conflict_409():
    """ConflictError → 409 + CONFLICT (TC-middleware-08)"""
    response = await domain_exception_handler(
        _fake_request(), ConflictError("already indexing", resource="folder-1")
    )
    assert response.status_code == 409
    assert _body(response)["error"] == "CONFLICT"


async def test_domain_handler_rag_query_error_500():
    """QueryExecutionError → 500 + RAG_QUERY_ERROR,details 帶 query 與 folder_id (TC-middleware-09)"""
    exc = QueryExecutionError(query="q1", reason="vector store down", folder_id=3)
    response = await domain_exception_handler(_fake_request(), exc)
    assert response.status_code == 500
    body = _body(response)
    assert body["error"] == "RAG_QUERY_ERROR"
    assert body["details"] == {"query": "q1", "folder_id": 3}


async def test_domain_handler_unknown_code_falls_back_500():
    """未知 error_code 的 DomainException → fallback 500 (TC-middleware-10)"""
    exc = DomainException(message="odd", error_code="SOMETHING_WEIRD")
    assert get_http_status_for_exception(exc) == 500
    response = await domain_exception_handler(_fake_request(), exc)
    assert response.status_code == 500


async def test_status_mapping_file_index_not_found_404():
    """FileIndexNotFoundError 映射為 404(FILE_INDEX_NOT_FOUND) (TC-middleware-11)"""
    exc = FileIndexNotFoundError(file_id="f-1")
    assert get_http_status_for_exception(exc) == 404


# ---------------------------------------------------------------------------
# error_handler.py — generic_exception_handler
# ---------------------------------------------------------------------------

async def test_generic_handler_returns_500_without_leaking_internals():
    """一般例外 → 500 + INTERNAL_SERVER_ERROR,body 不洩漏內部錯誤字串 (TC-middleware-12)"""
    request = _fake_request("/api/boom")
    response = await generic_exception_handler(
        request, RuntimeError("secret db password leaked")
    )
    assert response.status_code == 500
    body = _body(response)
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    assert body["path"] == "/api/boom"
    assert "secret" not in json.dumps(body)  # 不外洩內部訊息


async def test_generic_handler_reraises_http_exception():
    """HTTPException → 原樣 re-raise 給 FastAPI 原生 handler,不被吞成 500 (TC-middleware-13)"""
    exc = HTTPException(status_code=404, detail="not found")
    with pytest.raises(HTTPException) as exc_info:
        await generic_exception_handler(_fake_request(), exc)
    assert exc_info.value is exc
