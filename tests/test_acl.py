
"""M6 前置 harness — MCP 三模式查詢的租戶隔離閘(verify_folder_access)。

M6(把三模式編排從 fastmcp_tools 搬進 domain)最怕碰壞的就是租戶邊界:
token A 不能查到 token B 的 folder。這份測試鎖住「隔離發生在 DB 查詢層」
(FolderDB.get 必帶 user_token),重構搬動鑑權邏輯時有網可依。

純 mock,零外部依賴。
"""

from unittest.mock import patch

import pytest

from src.domain.exceptions import UnauthorizedAccessError
from src.domain.rag.folder_acl import verify_folder_access

# M6 後 ACL 住在 domain(folder_acl);fastmcp_tools/acl.py 只是 re-export shim
_ACL = "src.domain.rag.folder_acl"


def test_owned_folder_returned_and_query_is_token_scoped():
    """自己的 folder → 回傳;且 DB 查詢必帶 user_token(隔離在查詢層,非事後比對)。"""
    fake_folder = object()
    with patch(f"{_ACL}.FolderDB.get", return_value=[fake_folder]) as m:
        got = verify_folder_access(token="tokA", folder_name="f1")
    assert got is fake_folder
    m.assert_called_once_with(name="f1", user_token="tokA")


def test_cross_tenant_denied():
    """別的租戶的 folder:以呼叫者 token 查回空 → 拒絕(不洩漏 folder 是否存在)。"""
    with patch(f"{_ACL}.FolderDB.get", return_value=[]):
        with pytest.raises(UnauthorizedAccessError):
            verify_folder_access(token="tokA", folder_name="tokB_folder")


def test_none_result_denied_fail_closed():
    """DB 回 None(異常/無主)也一律拒絕 —— fail-closed。"""
    with patch(f"{_ACL}.FolderDB.get", return_value=None):
        with pytest.raises(UnauthorizedAccessError):
            verify_folder_access(token="tokA", folder_name="f")


def test_legacy_import_path_still_works():
    """M6 向下相容:fastmcp_tools/acl 的舊 import 路徑必須 re-export 同一個函式。"""
    from src.fastmcp_tools import acl as legacy
    assert legacy.verify_folder_access is verify_folder_access


def test_list_accessible_folders_scoped_by_token():
    """啟動時的 per-token folder 列舉:同樣必須帶 user_token 過濾。"""
    with patch(f"{_ACL}.FolderDB.get", return_value=["f1", "f2"]) as m:
        from src.domain.rag.folder_acl import list_accessible_folders
        assert list_accessible_folders("tokA") == ["f1", "f2"]
    m.assert_called_once_with(user_token="tokA")
