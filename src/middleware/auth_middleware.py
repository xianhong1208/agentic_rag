
"""純 ASGI 認證中間件

策略：
- initialize, notifications/initialized → 不需要認證
- 其他 MCP 方法（tools/list 等）→ 需要認證

注意：使用純 ASGI 實作以避免 BaseHTTPMiddleware 的 response buffering 問題，
這樣 SSE streaming 才能正常運作。
"""

import json as _json

from fastapi import HTTPException
from src.auth.dependencies import authenticate_request_remote


class SelectiveAuthMiddleware:
    """純 ASGI 認證中間件"""

    PUBLIC_METHODS = {"initialize", "notifications/initialized"}
    PROTECTED_PATHS = ["/mcp", "/messages", "/sse"]

    def __init__(self, app, config):
        self.app = app
        self.config = config
        auth_config = getattr(config, 'auth', None)
        self.auth_enabled = getattr(auth_config, 'enabled', False) if auth_config else False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        is_protected = any(path.startswith(p) for p in self.PROTECTED_PATHS)

        # 非保護路徑或認證未啟用，直接放行
        if not (is_protected and self.auth_enabled):
            await self.app(scope, receive, send)
            return

        # 讀取並快取 body
        body_chunks = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        body = b"".join(body_chunks)

        # 解析 JSON-RPC method
        method = ""
        try:
            if body:
                data = _json.loads(body.decode("utf-8"))
                method = data.get("method", "")
        except (_json.JSONDecodeError, UnicodeDecodeError):
            pass

        # 公開方法不需要認證
        if method in self.PUBLIC_METHODS:
            await self.app(scope, self._make_receive(body, receive), send)
            return

        # 檢查 Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")

        if not auth_header or not auth_header.startswith("Bearer "):
            await self._send_json_error(
                send,
                status_code=401,
                content={"error": "missing_token", "error_description": "Authorization header required"},
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        # 檢查 token 是否為空（避免無謂的遠端請求）
        token = auth_header[len("Bearer "):].strip()
        if not token:
            await self._send_json_error(
                send,
                status_code=401,
                content={"error": "missing_token", "error_description": "Bearer token is empty"},
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        # 驗證 token（建立 Request 物件）
        from starlette.requests import Request as StarletteRequest
        fake_scope = dict(scope)
        request = StarletteRequest(fake_scope, self._make_receive(body, receive))

        try:
            await authenticate_request_remote(request)
        except HTTPException as exc:
            extra_headers = []
            if exc.headers:
                for k, v in exc.headers.items():
                    extra_headers.append((k.lower().encode(), v.encode()))
            await self._send_json_error(send, exc.status_code, exc.detail, extra_headers)
            return

        # 認證通過，呼叫下層應用
        await self.app(scope, self._make_receive(body, receive), send)

    def _make_receive(self, body: bytes, original_receive):
        """建立一個 receive callable，返回快取的 body，然後代理原始 receive"""
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            # Body 已發送後，等待原始 receive（用於偵測 client disconnect）
            # 這對於 SSE 串流很重要，因為 app 會監聯 disconnect
            return await original_receive()

        return receive

    async def _send_json_error(self, send, status_code: int, content: dict, extra_headers: list = None):
        """發送 JSON 錯誤回應"""
        body = _json.dumps(content).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if extra_headers:
            headers.extend(extra_headers)

        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })
