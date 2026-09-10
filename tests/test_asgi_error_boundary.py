
"""M15 後半 — 最外層 ASGI 錯誤邊界。

背景:error handlers 註冊在內層 FastAPI,但 SelectiveAuthMiddleware /
RequestIdMiddleware 是包在 FastAPI **外面**的純 ASGI wrapper —— middleware
自身的未預期例外會冒過 FastAPI 直達 ASGI server,client 拿到裸 500/斷線,
無統一 JSON、無日誌關聯。ASGIErrorBoundary 補上最外層的 catch-all。

契約:
1. 正常請求透傳,不動 response
2. 回應開始前炸 → 500 + 統一 JSON(格式對齊 error_handler.generic_exception_handler)
3. 回應已開始才炸 → re-raise(headers 已送出,無法補救;讓 server 斷連是正確行為)
4. 非 http scope(lifespan/websocket)不包 — 原樣透傳
"""

import pytest
from starlette.testclient import TestClient

from src.middleware.asgi_error_boundary import ASGIErrorBoundary


def _ok_app():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})
    return app


def _boom_before_start():
    async def app(scope, receive, send):
        raise RuntimeError("middleware bug")
    return app


def _boom_after_start():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        raise RuntimeError("boom mid-stream")
    return app


def test_passthrough_on_success():
    client = TestClient(ASGIErrorBoundary(_ok_app()))
    r = client.get("/anything")
    assert r.status_code == 200
    assert r.text == "ok"


def test_unified_json_500_when_exception_before_response_start():
    client = TestClient(ASGIErrorBoundary(_boom_before_start()), raise_server_exceptions=False)
    r = client.get("/api/some/path")
    assert r.status_code == 500
    body = r.json()
    # 格式對齊 error_handler.generic_exception_handler
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    assert "message" in body and "timestamp" in body
    assert body["path"] == "/api/some/path"
    assert "middleware bug" not in r.text, "內部錯誤細節不得外洩"


def test_reraise_when_response_already_started():
    """headers 已送出無法補救 — 必須 re-raise,不得嘗試二次回應。"""
    client = TestClient(ASGIErrorBoundary(_boom_after_start()))
    with pytest.raises(RuntimeError, match="boom mid-stream"):
        client.get("/x")


async def test_non_http_scope_not_wrapped():
    """lifespan 等非 http scope 原樣透傳(異常照冒,不被包成 http 回應)。"""
    captured = {}

    async def inner(scope, receive, send):
        captured["scope_type"] = scope["type"]
        raise RuntimeError("lifespan boom")

    boundary = ASGIErrorBoundary(inner)
    with pytest.raises(RuntimeError, match="lifespan boom"):
        await boundary({"type": "lifespan"}, None, None)
    assert captured["scope_type"] == "lifespan"


async def test_non_http_scope_passthrough_on_success():
    """非 http scope 正常完成:原樣透傳、不加工。"""
    seen = {}

    async def inner(scope, receive, send):
        seen["type"] = scope["type"]

    await ASGIErrorBoundary(inner)({"type": "lifespan"}, None, None)
    assert seen["type"] == "lifespan"
