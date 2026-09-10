
"""Request ID 中間件

為每個 HTTP 請求產生唯一 request_id，注入 contextvars。
所有後續的 logger 呼叫（任何層）都會自動帶上這個 ID。
用法：grep "rid=abc12345" logs/*/info_*.log → 串聯整條請求鏈路
"""

from src.log import set_request_id, generate_request_id


class RequestIdMiddleware:
    """為每個 HTTP 請求產生唯一 request_id"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            rid = generate_request_id()
            set_request_id(rid)
        await self.app(scope, receive, send)
