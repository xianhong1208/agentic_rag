
"""ACL — token 從 Authorization header 抽取 + folder 權限檢查

設計原則:
- 單一 entry point:工具呼叫的第一行永遠是 `token = extract_token()`,
  接著呼叫 `verify_folder_access(token, folder_name)` 拿 folder ORM 物件。
- ACL 失敗永遠丟 InvalidTokenError / UnauthorizedAccessError(domain exceptions),
  由 middleware 統一轉換成標準 MCP error response。
- 不快取 ACL 結果在這裡 — token server 那層已經有 cache_ttl 設定。

M6: verify_folder_access / list_accessible_folders 已搬進 domain
(src/domain/rag/folder_acl.py,無 fastmcp 依賴);此處 re-export 向下相容。
extract_token 讀 MCP HTTP request context,是真正的交付層邏輯,留在這裡。
"""

from __future__ import annotations

from fastmcp.server.dependencies import get_http_request

from src.domain.exceptions import InvalidTokenError
from src.domain.rag.folder_acl import (  # noqa: F401
    list_accessible_folders,
    verify_folder_access,
)
from src.log import get_mcptools_logger

logger = get_mcptools_logger()


def extract_token() -> str:
    """從 Authorization header 抽 Bearer token

    Raises:
        InvalidTokenError: header 缺失/格式錯誤
    """
    request = get_http_request()
    auth_header = request.headers.get("Authorization", "")

    if not auth_header:
        raise InvalidTokenError("Missing Authorization header")

    if not auth_header.startswith("Bearer "):
        raise InvalidTokenError(
            "Invalid Authorization header format. Expected: Bearer <token>"
        )

    parts = auth_header.split(" ")
    if len(parts) != 2 or not parts[1]:
        raise InvalidTokenError("Token is empty or malformed")

    return parts[1]
