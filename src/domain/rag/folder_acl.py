
"""Folder ACL — token 對 folder 的權限檢查(domain 層)。

M6: 從 src/fastmcp_tools/acl.py **逐字搬入**。這兩個函式只依賴 FolderDB +
domain exceptions,不含 fastmcp;`extract_token`(讀 MCP HTTP request context)
才是真正的交付層邏輯,留在 fastmcp_tools/acl.py。acl.py 對這兩個函式保留
re-export 向下相容。

設計原則(沿用原檔):
- 隔離在 DB 查詢層:FolderDB.get 必帶 user_token,別人的 folder 用你的 token
  查回空 → 拒絕。不是「先撈再比對」。
- ACL 失敗永遠丟 UnauthorizedAccessError(domain exception),由 caller 的
  middleware 統一轉換成標準 error response。
- 故意不區分「folder 不存在」vs「token 沒權限」— 避免資訊洩漏。
- 不快取 ACL 結果在這裡 — token server 那層已經有 cache_ttl 設定。
"""

from __future__ import annotations

from db.folderdb import FolderDB
from src.domain.exceptions import UnauthorizedAccessError
from src.log import get_mcptools_logger

logger = get_mcptools_logger()


def verify_folder_access(token: str, folder_name: str):
    """確認 token 有權存取此 folder,回傳 Folder ORM 物件

    Raises:
        UnauthorizedAccessError: token 不能存取此 folder
    """
    folders = FolderDB.get(name=folder_name, user_token=token)
    if not folders:
        # 故意不區分「folder 不存在」vs「token 沒權限」— 避免資訊洩漏
        raise UnauthorizedAccessError(
            resource_type="folder",
            resource_id=folder_name,
            reason="Folder not found or token lacks access",
        )
    return folders[0]


def list_accessible_folders(token: str):
    """列出該 token 可存取的所有 folders(供 MCP server 啟動時動態註冊工具用)"""
    return FolderDB.get(user_token=token)
