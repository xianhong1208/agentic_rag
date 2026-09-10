
"""整合測試 — migration 多實例並發防護(pg_advisory_lock,真 PostgreSQL)。

模擬多 worker / 滾動部署同時啟動 auto_migrate:兩個獨立 DatabaseMigrator
(各自 engine / 連線)同時 upgrade,advisory lock 保證序列化 —— 兩邊都回
成功、version 收斂到 head、不互炸(無鎖時 DROP/CREATE 類 DDL 並發跑會
一邊成功一邊炸)。
"""

import threading

from db.migrate import DatabaseMigrator


def test_concurrent_upgrade_serialized_by_advisory_lock(itest_db):
    """downgrade 一步後,兩執行緒同時 upgrade('head'):都成功、版本收斂。"""
    m0 = DatabaseMigrator()
    head = m0._get_head_revision()
    assert m0.downgrade("-1"), "前置:先退一步製造『有 migration 要套』的狀態"

    results = {}

    def _run(tag: str):
        try:
            # 各自獨立的 migrator(獨立 engine/連線)— 模擬兩個 process
            results[tag] = DatabaseMigrator().upgrade("head")
        except Exception as e:  # 不得互炸
            results[tag] = e

    t1 = threading.Thread(target=_run, args=("a",))
    t2 = threading.Thread(target=_run, args=("b",))
    t1.start(); t2.start()
    t1.join(timeout=60); t2.join(timeout=60)

    assert results.get("a") is True and results.get("b") is True, f"並發 upgrade 有一方失敗:{results}"
    assert m0._get_current_revision() == head, "版本必須收斂到 head"


def test_real_chain_passes_new_guards(itest_db):
    """真實 versions/ 鏈在新三重防護(可解析/單 head/無孤兒)下照常通過。"""
    chain = DatabaseMigrator._discover_revisions(DatabaseMigrator().versions_dir)
    assert len(chain) >= 3
    assert chain[-1][0] == "20260819cafe01"
