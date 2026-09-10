# TC-cache:記憶體快取服務 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-cache](../specs/SPEC-cache.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_cache_service.py` |

共同前置:TTL 相關案例以 fake clock(monkeypatch 模組內 `time`)控制時間,不 sleep。

---

## TC-cache-01:set 後 get 取回原值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-01 |
| **層級** | 單元 |
| **前置條件** | 新建 `InMemoryCache()` |
| **測試輸入** | `set("k1", {"a": 1})` |
| **測試步驟** | 1. set<br>2. get 同 key |
| **預期結果** | 回傳 `{"a": 1}` |
| **實作** | `tests/test_cache_service.py::test_set_get_roundtrip` |

## TC-cache-02:get 不存在的 key

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-02 |
| **層級** | 單元 |
| **前置條件** | 空 cache |
| **測試輸入** | `get("nope")` |
| **測試步驟** | 1. get 不存在 key<br>2. 讀 get_stats |
| **預期結果** | 回 `None`;`misses` == 1 |
| **實作** | `tests/test_cache_service.py::test_get_missing_key_returns_none` |

## TC-cache-03:同 key 重複 set 覆寫

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-03 |
| **層級** | 單元 |
| **前置條件** | cache 已有 `("k", "old")` |
| **測試輸入** | `set("k", "new")` |
| **測試步驟** | 1. set 兩次<br>2. get |
| **預期結果** | 回 `"new"` |
| **實作** | `tests/test_cache_service.py::test_set_overwrites_existing_key` |

## TC-cache-04:TTL 過期後 get 失效

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-04 |
| **層級** | 單元 |
| **前置條件** | fake clock 注入 |
| **測試輸入** | `set("k", "v", ttl=10)`,時間推進 11 秒 |
| **測試步驟** | 1. set<br>2. advance(11)<br>3. get<br>4. 讀 get_stats |
| **預期結果** | get 回 `None`;`size` == 0(過期項被移除) |
| **實作** | `tests/test_cache_service.py::test_get_after_ttl_expired_returns_none` |

## TC-cache-05:恰等於 expiry 時仍命中

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-05 |
| **層級** | 單元 |
| **前置條件** | fake clock 注入 |
| **測試輸入** | `set("k", "v", ttl=10)`,時間推進恰 10 秒 |
| **測試步驟** | 1. set<br>2. advance(10)<br>3. get |
| **預期結果** | 回 `"v"`(過期判斷為嚴格大於) |
| **實作** | `tests/test_cache_service.py::test_get_at_exact_expiry_still_hits` |

## TC-cache-06:未指定 ttl 採 default_ttl

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-06 |
| **層級** | 單元 |
| **前置條件** | `InMemoryCache(default_ttl=50)` + fake clock |
| **測試輸入** | `set("k", "v")`(不帶 ttl) |
| **測試步驟** | 1. set<br>2. advance(49) → get<br>3. advance(2) → get |
| **預期結果** | 49 秒時回 `"v"`;51 秒時回 `None` |
| **實作** | `tests/test_cache_service.py::test_set_without_ttl_uses_default_ttl` |

## TC-cache-07:delete 存在的 key

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-07 |
| **層級** | 單元 |
| **前置條件** | cache 已有 `("k", "v")` |
| **測試輸入** | `delete("k")` |
| **測試步驟** | 1. set<br>2. delete<br>3. get + get_stats |
| **預期結果** | get 回 `None`;`deletes` == 1 |
| **實作** | `tests/test_cache_service.py::test_delete_existing_key` |

## TC-cache-08:delete 不存在的 key 為 no-op

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-08 |
| **層級** | 單元 |
| **前置條件** | 空 cache |
| **測試輸入** | `delete("ghost")` |
| **測試步驟** | 1. delete 不存在 key<br>2. 讀 get_stats |
| **預期結果** | 不拋例外;`deletes` == 0 |
| **實作** | `tests/test_cache_service.py::test_delete_missing_key_is_noop` |

## TC-cache-09:clear_pattern 星號匹配

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-09 |
| **層級** | 單元 |
| **前置條件** | cache 含 `folder:t1:a`、`folder:t1:b`、`files:folder:9` |
| **測試輸入** | `clear_pattern("folder:*")` |
| **測試步驟** | 1. set 三個 key<br>2. clear_pattern<br>3. 逐一 get |
| **預期結果** | 前兩個回 `None`;`files:folder:9` 保留;`deletes` == 2 |
| **實作** | `tests/test_cache_service.py::test_clear_pattern_star_wildcard` |

## TC-cache-10:clear_pattern 問號單字元匹配

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-09 |
| **層級** | 單元 |
| **前置條件** | cache 含 `k1`、`k2`、`k10` |
| **測試輸入** | `clear_pattern("k?")` |
| **測試步驟** | 1. set 三個 key<br>2. clear_pattern<br>3. 逐一 get |
| **預期結果** | `k1`、`k2` 被清;`k10` 保留 |
| **實作** | `tests/test_cache_service.py::test_clear_pattern_question_mark_single_char` |

## TC-cache-11:clear_all 清空

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-10 |
| **層級** | 單元 |
| **前置條件** | cache 含兩個 key |
| **測試輸入** | `clear_all()` |
| **測試步驟** | 1. set ×2<br>2. clear_all<br>3. get_stats + get |
| **預期結果** | `size` == 0;get 回 `None` |
| **實作** | `tests/test_cache_service.py::test_clear_all_empties_cache` |

## TC-cache-12:LRU 滿載淘汰最久未存取項

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-11 |
| **層級** | 單元 |
| **前置條件** | `InMemoryCache(max_size=2)` + fake clock |
| **測試輸入** | set a → set b → get a → set c |
| **測試步驟** | 1. 依序操作並推進時間<br>2. 逐一 get |
| **預期結果** | `b` 被淘汰(回 `None`);`a`、`c` 保留 |
| **實作** | `tests/test_cache_service.py::test_lru_eviction_removes_least_recently_used` |

## TC-cache-13:滿載時覆寫既有 key 不淘汰

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-11 |
| **層級** | 單元 |
| **前置條件** | `InMemoryCache(max_size=2)` 已滿(a、b) |
| **測試輸入** | `set("a", 99)` |
| **測試步驟** | 1. set a、b<br>2. 覆寫 a<br>3. get a、b |
| **預期結果** | `a` == 99;`b` 仍在 |
| **實作** | `tests/test_cache_service.py::test_set_existing_key_when_full_does_not_evict` |

## TC-cache-14:cleanup_expired 只清過期項

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-12 |
| **層級** | 單元 |
| **前置條件** | fake clock;`short`(ttl=5)、`long`(ttl=100) |
| **測試輸入** | advance(6) 後 `cleanup_expired()` |
| **測試步驟** | 1. set ×2<br>2. advance(6)<br>3. cleanup_expired<br>4. get_stats + get |
| **預期結果** | `size` == 1;`long` 仍可取回 |
| **實作** | `tests/test_cache_service.py::test_cleanup_expired_removes_only_expired` |

## TC-cache-15:get_stats 計數與 hit_rate

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-13 |
| **層級** | 單元 |
| **前置條件** | `InMemoryCache(max_size=7)` |
| **測試輸入** | 1 miss + 1 set + 1 hit + 1 delete |
| **測試步驟** | 1. 依序操作<br>2. 讀 get_stats |
| **預期結果** | hits=1、misses=1、sets=1、deletes=1、max_size=7、hit_rate=50.0 |
| **實作** | `tests/test_cache_service.py::test_get_stats_counters_and_hit_rate` |

## TC-cache-16:零請求時 hit_rate 為 0.0

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-13 |
| **層級** | 單元 |
| **前置條件** | 全新 cache |
| **測試輸入** | 直接 `get_stats()` |
| **測試步驟** | 1. 讀 get_stats |
| **預期結果** | hit_rate == 0.0(不發生除零);size == 0 |
| **實作** | `tests/test_cache_service.py::test_get_stats_initial_hit_rate_zero` |

## TC-cache-17:get_instance 回同一單例

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-14 |
| **層級** | 單元 |
| **前置條件** | 測試前後 `reset_instance()`(fixture) |
| **測試輸入** | `get_instance()` ×2 |
| **測試步驟** | 1. 取兩次 instance |
| **預期結果** | 兩者 `is` 同一物件 |
| **實作** | `tests/test_cache_service.py::test_cache_service_returns_same_instance` |

## TC-cache-18:reset_instance 後為全新實例

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-14 |
| **層級** | 單元 |
| **前置條件** | 同上 fixture |
| **測試輸入** | get_instance → set → reset_instance → get_instance |
| **測試步驟** | 1. 取 instance 並寫值<br>2. reset<br>3. 再取 instance |
| **預期結果** | 新舊物件不同;新實例 get 回 `None` |
| **實作** | `tests/test_cache_service.py::test_reset_instance_creates_new_instance` |

## TC-cache-19:CacheKeys 各 key 格式

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-15 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 七個 staticmethod(含中文 folder 名) |
| **測試步驟** | 1. 逐一產生 key(parametrize) |
| **預期結果** | `folder:{token}:{name}`、`folder:id:{id}`、`files:folder:{id}`、`file:id:{id}`、`query:{fid}:{hash}`、`auth:{token}`、`index:file:{id}` |
| **實作** | `tests/test_cache_service.py::test_cache_keys_formats` |

## TC-cache-20:CacheTTL 常數值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-cache-16 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 讀六個常數 |
| **測試步驟** | 1. 逐一斷言 |
| **預期結果** | FOLDER=300、FILE_LIST=180、FILE_DETAIL=300、QUERY_RESULT=300、AUTH_TOKEN=3600、INDEX_STATUS=600 |
| **實作** | `tests/test_cache_service.py::test_cache_ttl_constants` |
