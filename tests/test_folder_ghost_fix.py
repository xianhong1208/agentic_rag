
"""幽靈 folder 修復(2026-09-07 用戶回報「XSS 測試名稱的 folder 刪不掉」)。

根因鏈:
① create:DB row 先建、storage 名稱驗證後炸 → 422 回呼叫端但幽靈 row 留下
② delete:storage 清理對非法名稱 raise ValueError → 一路炸出 → row 永生

契約:
- create 對非法名稱 fail-fast:ValueError 且 **FolderDB.create 不得被呼叫**
- delete 的 storage 清理 best-effort:ValueError 不阻斷 FolderDB.delete
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.adapter.folder import FolderAdapter

_F = "src.adapter.folder"


class TestCreateFailFast:
    def test_illegal_name_never_touches_db(self):
        with patch(f"{_F}.FolderDB") as db:
            with pytest.raises(ValueError, match="illegal characters"):
                FolderAdapter.create_folder(
                    name='x"><img src=x onerror=1>', user_token="tok-a")
        db.get.assert_not_called()
        db.create.assert_not_called()

    def test_illegal_token_never_touches_db(self):
        with patch(f"{_F}.FolderDB") as db:
            with pytest.raises(ValueError):
                FolderAdapter.create_folder(name="ok-name", user_token="../etc")
        db.create.assert_not_called()


class TestDeleteGhostRow:
    async def test_storage_valueerror_does_not_block_db_delete(self):
        folder = SimpleNamespace(
            id=99, name='x"><img>', user_token="tok-a",
            vector_table_uuid="u-1")
        with patch(f"{_F}.FolderDB") as db, \
             patch(f"{_F}.FileDB") as filedb, \
             patch(f"{_F}.FileStorage") as storage, \
             patch(f"{_F}.VectorStoreManager") as vsm, \
             patch(f"{_F}.notify_folder_deleted"):
            db.get.return_value = [folder]
            filedb.get.return_value = []
            storage.delete_folder.side_effect = ValueError("illegal characters")
            ok = await FolderAdapter.delete_folder(99, user_token="tok-a")
        assert ok is True
        db.delete.assert_called_once_with(id=99)  # row 一定要刪掉

    async def test_normal_delete_still_cleans_storage(self):
        folder = SimpleNamespace(id=7, name="good", user_token="tok-a",
                                 vector_table_uuid="u-2")
        with patch(f"{_F}.FolderDB") as db, \
             patch(f"{_F}.FileDB") as filedb, \
             patch(f"{_F}.FileStorage") as storage, \
             patch(f"{_F}.VectorStoreManager"), \
             patch(f"{_F}.notify_folder_deleted"):
            db.get.return_value = [folder]
            filedb.get.return_value = []
            ok = await FolderAdapter.delete_folder(7, user_token="tok-a")
        assert ok is True
        storage.delete_folder.assert_called_once_with("tok-a", "good")
        db.delete.assert_called_once_with(id=7)
