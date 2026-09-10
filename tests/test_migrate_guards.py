
"""db/migrate.py 運行時防護 — chain 完整性 / 多 head / advisory lock。

背景(三個真實風險,2026-08 評估):
1. revision 用 regex 解析,id 含 [a-f0-9] 以外字元的 migration 會被**靜默跳過**
   (寫了等於沒寫,schema 靜默漂移)→ 現在必須大聲失敗
2. 多 head / 多 base / 斷鏈原本只 warning → 只走其中一條鏈,另一條靜默不套用
3. 多實例同時啟動會並發跑同一 migration(無鎖)→ pg_advisory_lock

單測部分:_discover_revisions 純函式(tmp versions 目錄,零 DB);
advisory lock 用假 engine 驗證取鎖/解鎖/double-check 順序。
並發實測見 tests/integration/test_migrate_concurrency.py。
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from db.migrate import DatabaseMigrator, MigrationChainError


def _write_migration(d: Path, fname: str, rev, down):
    down_repr = "None" if down is None else f"'{down}'"
    (d / fname).write_text(
        f"revision: str = '{rev}'\ndown_revision = {down_repr}\n"
        f"def upgrade():\n    pass\n",
        encoding="utf-8",
    )


# ---- _discover_revisions:chain 完整性 ------------------------------------------

class TestDiscoverRevisions:
    def test_valid_linear_chain(self, tmp_path):
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_b.py", "bbb222", "aaa111")
        _write_migration(tmp_path, "003_c.py", "ccc333", "bbb222")
        chain = DatabaseMigrator._discover_revisions(tmp_path)
        assert [rev for rev, _, _ in chain] == ["aaa111", "bbb222", "ccc333"]

    def test_empty_dir_ok(self, tmp_path):
        assert DatabaseMigrator._discover_revisions(tmp_path) == []

    def test_dunder_files_ignored(self, tmp_path):
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        assert len(DatabaseMigrator._discover_revisions(tmp_path)) == 1

    def test_unparseable_revision_id_fails_loud(self, tmp_path):
        """regex 抓不到的 revision id(含 [a-f0-9] 以外字元)必須報錯,
        不得靜默跳過 —— 這是「migration 寫了等於沒寫」的根源。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_bad.py", "20261001_add_xyz", "aaa111")  # 含底線
        with pytest.raises(MigrationChainError, match="002_bad.py"):
            DatabaseMigrator._discover_revisions(tmp_path)

    def test_multiple_heads_fail(self, tmp_path):
        """分叉(兩檔同 down_revision)→ 兩個 head → 報錯,不得只走一條。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_b.py", "bbb222", "aaa111")
        _write_migration(tmp_path, "003_c.py", "ccc333", "aaa111")  # 也接在 a 後 → 分叉
        with pytest.raises(MigrationChainError, match="head"):
            DatabaseMigrator._discover_revisions(tmp_path)

    def test_multiple_bases_fail(self, tmp_path):
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_b.py", "bbb222", None)  # 第二個 base
        with pytest.raises(MigrationChainError, match="base"):
            DatabaseMigrator._discover_revisions(tmp_path)

    def test_dangling_down_revision_fails(self, tmp_path):
        """down_revision 指向不存在的 rev:兩節點都不被指 → 表現為多 head,
        一樣大聲失敗(分類不同、結果相同:不得靜默)。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_b.py", "bbb222", "deadbeef")  # 不存在
        with pytest.raises(MigrationChainError):
            DatabaseMigrator._discover_revisions(tmp_path)

    def test_orphan_cycle_fails(self, tmp_path):
        """孤兒環(c↔d 互指):不增 base/head,但主鏈涵蓋不到 → 斷鏈報錯。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        _write_migration(tmp_path, "002_b.py", "bbb222", "aaa111")
        _write_migration(tmp_path, "003_c.py", "ccc333", "ddd444")
        _write_migration(tmp_path, "004_d.py", "ddd444", "ccc333")
        with pytest.raises(MigrationChainError, match="orphan"):
            DatabaseMigrator._discover_revisions(tmp_path)


# ---- advisory lock:取鎖 / 解鎖 / double-check ----------------------------------

_LOCK_SQL = "pg_advisory_lock"
_UNLOCK_SQL = "pg_advisory_unlock"


def _bare_migrator(tmp_path) -> DatabaseMigrator:
    """繞過 __init__(要 Config/DB)手工組裝,只填 upgrade 需要的欄位。"""
    m = object.__new__(DatabaseMigrator)
    m._engine = MagicMock()
    m.versions_dir = tmp_path
    return m


def _lock_calls(conn) -> list:
    """從假 connection 的 execute 呼叫序列抽出 lock/unlock 事件。"""
    events = []
    for c in conn.execute.call_args_list:
        sql = str(c.args[0])
        if _LOCK_SQL in sql and _UNLOCK_SQL not in sql:
            events.append("lock")
        elif _UNLOCK_SQL in sql:
            events.append("unlock")
    return events


class TestAdvisoryLock:
    def test_noop_when_already_at_target_takes_no_lock(self, tmp_path):
        """已在 head:短路 return,完全不碰 advisory lock。"""
        m = _bare_migrator(tmp_path)
        with patch.object(DatabaseMigrator, "_get_current_revision", return_value="aaa111"), \
             patch.object(DatabaseMigrator, "_get_head_revision", return_value="aaa111"):
            assert m.upgrade("head") is True
        m._engine.connect.assert_not_called()

    def test_apply_path_locks_and_unlocks(self, tmp_path):
        """實際 apply:先取鎖 → 套 migration → 解鎖(finally 保證)。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        m = _bare_migrator(tmp_path)
        conn = MagicMock()
        m._engine.connect.return_value.__enter__.return_value = conn

        with patch.object(DatabaseMigrator, "_get_current_revision", return_value=None), \
             patch.object(DatabaseMigrator, "_get_head_revision", return_value="aaa111"), \
             patch.object(DatabaseMigrator, "_execute_upgrade", return_value=True) as ex:
            assert m.upgrade("head") is True
        assert _lock_calls(conn) == ["lock", "unlock"]
        ex.assert_called_once()

    def test_double_check_after_lock_skips_if_peer_already_upgraded(self, tmp_path):
        """等鎖期間別的 instance 已升到 head:取鎖後重讀 current → 不重跑。"""
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        m = _bare_migrator(tmp_path)
        conn = MagicMock()
        m._engine.connect.return_value.__enter__.return_value = conn

        # 鎖前 current=None(看似要升),鎖後 current=head(對手已升完)
        with patch.object(DatabaseMigrator, "_get_current_revision",
                          side_effect=[None, "aaa111"]), \
             patch.object(DatabaseMigrator, "_get_head_revision", return_value="aaa111"), \
             patch.object(DatabaseMigrator, "_execute_upgrade") as ex:
            assert m.upgrade("head") is True
        ex.assert_not_called()
        assert _lock_calls(conn) == ["lock", "unlock"]

    def test_unlock_even_when_migration_fails(self, tmp_path):
        _write_migration(tmp_path, "001_a.py", "aaa111", None)
        m = _bare_migrator(tmp_path)
        conn = MagicMock()
        m._engine.connect.return_value.__enter__.return_value = conn

        with patch.object(DatabaseMigrator, "_get_current_revision", return_value=None), \
             patch.object(DatabaseMigrator, "_get_head_revision", return_value="aaa111"), \
             patch.object(DatabaseMigrator, "_execute_upgrade", return_value=False):
            assert m.upgrade("head") is False
        assert _lock_calls(conn)[-1] == "unlock", "失敗路徑也必須解鎖"
