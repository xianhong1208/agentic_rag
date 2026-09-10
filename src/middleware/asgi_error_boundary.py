
"""最外層 ASGI 錯誤邊界(M15 後半)。

問題:error handlers(error_handler.register_error_handlers)註冊在內層
FastAPI,但 SelectiveAuthMiddleware / RequestIdMiddleware 包在 FastAPI
**外面** —— middleware 自身的未預期例外會冒過 FastAPI 直達 ASGI server,
client 拿到裸 500 / 斷線,無統一 JSON 格式。

此 wrapper 放在整個 ASGI stack 的最外層,是最後一道 catch-all:
- 回應尚未開始:log 完整 traceback,回統一 JSON 500(格式對齊
  error_handler.generic_exception_handler,不外洩內部細節)
- 回應已開始(headers 已送):無法補救,re-raise 讓 server 斷連 — 標準行為
- 非 http scope(lifespan / websocket):不包,原樣透傳

正常請求零開銷(只多一層 send 包裝);FastAPI 內部的例外仍由內層
exception handlers 處理,不會落到這裡。
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone

from src.log import get_api_logger

logger = get_api_logger()


class ASGIErrorBoundary:
    """整個 ASGI stack 的最外層 catch-all(組裝見 app.py)。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            # lifespan / websocket:不介入(lifespan 例外要讓 server 看到原樣)
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            path = scope.get("path", "?")
            logger.error(
                f"Unhandled exception escaped middleware stack: {exc}\n"
                f"Path: {path}\n"
                f"Traceback:\n{traceback.format_exc()}"
            )
            if response_started:
                # headers 已送出,無法再發合法回應 — re-raise 讓 server 斷連
                raise
            body = json.dumps({
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": path,
            }).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
