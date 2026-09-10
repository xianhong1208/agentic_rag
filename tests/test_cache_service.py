
"""Unit tests for src/infrastructure/cache/cache_service.py

不依賴 DB / vLLM / 任何外部服務 — 純邏輯測試。
TTL 相關測試以 fake clock(monkeypatch 模組內 time)取代 sleep,零等待、可重現。
跑法:cd agentic_rag && uv run pytest tests/test_cache_service.py -v
"""

import pytest

import src.infrastructure.cache.cache_service as cache_mod
from src.infrastructure.cache.cache_service import (
    CacheKeys,
    CacheService,
    CacheTTL,
    InMemoryCache,
)


class _FakeTime:
    """替身 time 模組:只提供 time(),可手動 advance,不用 sleep"""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch) -> _FakeTime:
    """把 cache_service 模組內的 time 換成可控 fake clock"""
    ft = _FakeTime()
    monkeypatch.setattr(cache_mod, "time", ft)
    return ft


@pytest.fixture
def clean_singleton():
    """前後都 reset 全域單例,避免污染其他測試"""
    CacheService.reset_instance()
    yield
    CacheService.reset_instance()


# ---------------------------------------------------------------------------
# InMemoryCache 基本行為
# ---------------------------------------------------------------------------

def test_set_get_roundtrip():
    """set 後 get 應取回原值(TC-cache-01)"""
    cache = InMemoryCache()
    cache.set("k1", {"a": 1})
    assert cache.get("k1") == {"a": 1}


def test_get_missing_key_returns_none():
    """get 不存在的 key 應回 None 並記一次 miss(TC-cache-02)"""
    cache = InMemoryCache()
    assert cache.get("nope") is None
    assert cache.get_stats()["misses"] == 1


def test_set_overwrites_existing_key():
    """同 key 再 set 應覆寫舊值(TC-cache-03)"""
    cache = InMemoryCache()
    cache.set("k", "old")
    cache.set("k", "new")
    assert cache.get("k") == "new"


# ---------------------------------------------------------------------------
# TTL 過期
# ---------------------------------------------------------------------------

def test_get_after_ttl_expired_returns_none(fake_time):
    """超過 TTL 後 get 應回 None 且項目被移除(TC-cache-04)"""
    cache = InMemoryCache()
    cache.set("k", "v", ttl=10)
    fake_time.advance(11)
    assert cache.get("k") is None
    assert cache.get_stats()["size"] == 0


def test_get_at_exact_expiry_still_hits(fake_time):
    """恰好等於 expiry 時間仍算有效(過期判斷為嚴格大於)(TC-cache-05)"""
    cache = InMemoryCache()
    cache.set("k", "v", ttl=10)
    fake_time.advance(10)  # now == expiry_time
    assert cache.get("k") == "v"


def test_set_without_ttl_uses_default_ttl(fake_time):
    """未指定 ttl 時採用建構子的 default_ttl(TC-cache-06)"""
    cache = InMemoryCache(default_ttl=50)
    cache.set("k", "v")  # ttl=None → default 50
    fake_time.advance(49)
    assert cache.get("k") == "v"
    fake_time.advance(2)  # 總計 51 > 50
    assert cache.get("k") is None


# ---------------------------------------------------------------------------
# delete / clear_pattern / clear_all
# ---------------------------------------------------------------------------

def test_delete_existing_key():
    """delete 存在的 key 後 get 應回 None,deletes 計數 +1(TC-cache-07)"""
    cache = InMemoryCache()
    cache.set("k", "v")
    cache.delete("k")
    assert cache.get("k") is None
    assert cache.get_stats()["deletes"] == 1


def test_delete_missing_key_is_noop():
    """delete 不存在的 key 不拋錯,deletes 計數不變(TC-cache-08)"""
    cache = InMemoryCache()
    cache.delete("ghost")  # 不應拋例外
    assert cache.get_stats()["deletes"] == 0


def test_clear_pattern_star_wildcard():
    """clear_pattern("folder:*") 只清掉 folder: 前綴的 key(TC-cache-09)"""
    cache = InMemoryCache()
    cache.set("folder:t1:a", 1)
    cache.set("folder:t1:b", 2)
    cache.set("files:folder:9", 3)
    cache.clear_pattern("folder:*")
    assert cache.get("folder:t1:a") is None
    assert cache.get("folder:t1:b") is None
    assert cache.get("files:folder:9") == 3
    assert cache.get_stats()["deletes"] == 2


def test_clear_pattern_question_mark_single_char():
    """clear_pattern 的 ? 只匹配單一字元(TC-cache-10)"""
    cache = InMemoryCache()
    cache.set("k1", 1)
    cache.set("k2", 2)
    cache.set("k10", 3)
    cache.clear_pattern("k?")
    assert cache.get("k1") is None
    assert cache.get("k2") is None
    assert cache.get("k10") == 3


def test_clear_all_empties_cache():
    """clear_all 應清空整個 cache(TC-cache-11)"""
    cache = InMemoryCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear_all()
    assert cache.get_stats()["size"] == 0
    assert cache.get("a") is None


# ---------------------------------------------------------------------------
# LRU 淘汰
# ---------------------------------------------------------------------------

def test_lru_eviction_removes_least_recently_used(fake_time):
    """cache 滿時新增 key 應淘汰最久未存取的項目(TC-cache-12)"""
    cache = InMemoryCache(max_size=2)
    cache.set("a", 1)
    fake_time.advance(1)
    cache.set("b", 2)
    fake_time.advance(1)
    cache.get("a")  # 更新 a 的 last_access → b 變成最舊
    fake_time.advance(1)
    cache.set("c", 3)  # 觸發淘汰 b
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_set_existing_key_when_full_does_not_evict(fake_time):
    """cache 滿時覆寫既有 key 不應觸發淘汰(TC-cache-13)"""
    cache = InMemoryCache(max_size=2)
    cache.set("a", 1)
    fake_time.advance(1)
    cache.set("b", 2)
    fake_time.advance(1)
    cache.set("a", 99)  # key 已存在 → 不淘汰
    assert cache.get("a") == 99
    assert cache.get("b") == 2


# ---------------------------------------------------------------------------
# cleanup_expired / get_stats
# ---------------------------------------------------------------------------

def test_cleanup_expired_removes_only_expired(fake_time):
    """cleanup_expired 只清掉過期項,存活項保留(TC-cache-14)"""
    cache = InMemoryCache()
    cache.set("short", 1, ttl=5)
    cache.set("long", 2, ttl=100)
    fake_time.advance(6)
    cache.cleanup_expired()
    assert cache.get_stats()["size"] == 1
    assert cache.get("long") == 2


def test_get_stats_counters_and_hit_rate():
    """get_stats 應正確累計 hits/misses/sets/deletes 與 hit_rate(TC-cache-15)"""
    cache = InMemoryCache(max_size=7)
    cache.get("miss")          # miss 1
    cache.set("k", "v")        # set 1
    cache.get("k")             # hit 1
    cache.delete("k")          # delete 1
    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["sets"] == 1
    assert stats["deletes"] == 1
    assert stats["max_size"] == 7
    assert stats["hit_rate"] == 50.0


def test_get_stats_initial_hit_rate_zero():
    """沒有任何請求時 hit_rate 應為 0.0 而非除零錯誤(TC-cache-16)"""
    stats = InMemoryCache().get_stats()
    assert stats["hit_rate"] == 0.0
    assert stats["size"] == 0


# ---------------------------------------------------------------------------
# CacheService 單例
# ---------------------------------------------------------------------------

def test_cache_service_returns_same_instance(clean_singleton):
    """get_instance 兩次應回同一個物件(TC-cache-17)"""
    a = CacheService.get_instance()
    b = CacheService.get_instance()
    assert a is b


def test_reset_instance_creates_new_instance(clean_singleton):
    """reset_instance 後 get_instance 應回全新實例(TC-cache-18)"""
    a = CacheService.get_instance()
    a.set("k", "v")
    CacheService.reset_instance()
    b = CacheService.get_instance()
    assert a is not b
    assert b.get("k") is None


# ---------------------------------------------------------------------------
# CacheKeys / CacheTTL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "generated, expected",
    [
        (CacheKeys.folder_by_name("tok123", "月報"), "folder:tok123:月報"),
        (CacheKeys.folder_by_id(42), "folder:id:42"),
        (CacheKeys.files_in_folder(7), "files:folder:7"),
        (CacheKeys.file_by_id("uuid-1"), "file:id:uuid-1"),
        (CacheKeys.rag_query(3, "abcdef"), "query:3:abcdef"),
        (CacheKeys.auth_token("tok123"), "auth:tok123"),
        (CacheKeys.index_status("uuid-1"), "index:file:uuid-1"),
    ],
)
def test_cache_keys_formats(generated, expected):
    """CacheKeys 各 staticmethod 應產生固定格式的 key(TC-cache-19)"""
    assert generated == expected


def test_cache_ttl_constants():
    """CacheTTL 常數值應符合設計(秒)(TC-cache-20)"""
    assert CacheTTL.FOLDER == 300
    assert CacheTTL.FILE_LIST == 180
    assert CacheTTL.FILE_DETAIL == 300
    assert CacheTTL.QUERY_RESULT == 300
    assert CacheTTL.AUTH_TOKEN == 3600
    assert CacheTTL.INDEX_STATUS == 600
