# SPEC-cache:記憶體快取服務


| 項目 | 內容 |
|------|------|
| 模組 | `src/infrastructure/cache/cache_service.py` |
| 對應測試 | `tests/test_cache_service.py` |
| 版本 | feat/rag-robustness |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

提供 process 內的 in-memory 快取(`InMemoryCache`),降低 folder 查詢、檔案列表、RAG 查詢結果、auth token 驗證等讀取密集操作的 DB 負載。附帶:

- `CacheService`:全域單例工廠(`get_instance` / `reset_instance`)。
- `CacheKeys`:各實體類型的標準 cache key 產生器,保證 key 格式一致。
- `CacheTTL`:各實體類型建議 TTL 常數。

不負責:跨 process 的分散式快取(Redis)、持久化。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-cache-01 | `set` 後 `get` 取回原值 | `set(k, v)` 後 `get(k)` 回傳 `v`(任意可序列化物件) |
| REQ-cache-02 | 查無 key 回 `None` | `get` 不存在的 key 回 `None`,並累計一次 miss |
| REQ-cache-03 | 同 key 重複 `set` 覆寫 | 第二次 `set(k, v2)` 後 `get(k)` 回 `v2` |
| REQ-cache-04 | TTL 過期後失效 | 超過 `ttl` 秒後 `get(k)` 回 `None`,且該項自 cache 移除(size 減少) |
| REQ-cache-05 | 過期判斷為嚴格大於 | 當前時間恰等於 expiry 時仍視為有效(`time.time() > expiry` 才過期) |
| REQ-cache-06 | 未指定 ttl 用 default_ttl | `set(k, v)`(ttl=None)之有效期 = 建構子 `default_ttl` |
| REQ-cache-07 | `delete` 移除指定 key | `delete(k)` 後 `get(k)` 回 `None`,deletes 計數 +1 |
| REQ-cache-08 | `delete` 不存在的 key 為 no-op | 不拋例外,deletes 計數不變 |
| REQ-cache-09 | `clear_pattern` 以 fnmatch 批次清除 | `*` 匹配任意字串、`?` 匹配單一字元;僅刪除匹配的 key |
| REQ-cache-10 | `clear_all` 清空 | 清空後 size = 0 |
| REQ-cache-11 | LRU 淘汰 | cache 達 `max_size` 時,新增**新 key** 淘汰 last_access 最舊的項;覆寫既有 key 不觸發淘汰 |
| REQ-cache-12 | `cleanup_expired` 只清過期項 | 過期項被移除,未過期項保留 |
| REQ-cache-13 | `get_stats` 統計正確 | 回傳 size / max_size / hits / misses / sets / deletes / hit_rate;零請求時 hit_rate = 0.0(不除零) |
| REQ-cache-14 | 全域單例 | `get_instance()` 多次呼叫回同一物件;`reset_instance()` 後回全新實例 |
| REQ-cache-15 | CacheKeys 格式固定 | 各 staticmethod 產生固定前綴格式(`folder:`、`files:folder:`、`file:id:`、`query:`、`auth:`、`index:file:`) |
| REQ-cache-16 | CacheTTL 常數 | FOLDER=300、FILE_LIST=180、FILE_DETAIL=300、QUERY_RESULT=300、AUTH_TOKEN=3600、INDEX_STATUS=600 |

## 3. 非功能需求

- 執行緒安全:所有讀寫操作以 `threading.Lock` 保護(本測試不做並發壓測,屬單元範疇外)。
- 測試不得使用長 sleep;TTL 行為以 fake clock(monkeypatch 模組內 `time`)驗證。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| get 不存在的 key | 回 `None`,計 miss |
| get 已過期的 key | 回 `None`,順手移除該項 |
| delete 不存在的 key | 靜默 no-op |
| cache 滿 + 新 key | 淘汰最久未存取項 |
| cache 滿 + 既有 key 覆寫 | 不淘汰任何項 |
| 統計無任何請求 | hit_rate = 0.0 |

## 5. 相依與假設 (Dependencies & Assumptions)

- 僅依賴標準庫(`time`、`fnmatch`、`threading`)— 無需 mock 外部服務。
- 測試以 `monkeypatch.setattr(cache_mod, "time", fake)` 注入可控時鐘。
- 涉及全域單例的測試前後必須 `CacheService.reset_instance()`,避免污染。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-cache-01 | TC-cache-01 | `tests/test_cache_service.py::test_set_get_roundtrip` |
| REQ-cache-02 | TC-cache-02 | `tests/test_cache_service.py::test_get_missing_key_returns_none` |
| REQ-cache-03 | TC-cache-03 | `tests/test_cache_service.py::test_set_overwrites_existing_key` |
| REQ-cache-04 | TC-cache-04 | `tests/test_cache_service.py::test_get_after_ttl_expired_returns_none` |
| REQ-cache-05 | TC-cache-05 | `tests/test_cache_service.py::test_get_at_exact_expiry_still_hits` |
| REQ-cache-06 | TC-cache-06 | `tests/test_cache_service.py::test_set_without_ttl_uses_default_ttl` |
| REQ-cache-07 | TC-cache-07 | `tests/test_cache_service.py::test_delete_existing_key` |
| REQ-cache-08 | TC-cache-08 | `tests/test_cache_service.py::test_delete_missing_key_is_noop` |
| REQ-cache-09 | TC-cache-09, TC-cache-10 | `tests/test_cache_service.py::test_clear_pattern_star_wildcard`、`::test_clear_pattern_question_mark_single_char` |
| REQ-cache-10 | TC-cache-11 | `tests/test_cache_service.py::test_clear_all_empties_cache` |
| REQ-cache-11 | TC-cache-12, TC-cache-13 | `tests/test_cache_service.py::test_lru_eviction_removes_least_recently_used`、`::test_set_existing_key_when_full_does_not_evict` |
| REQ-cache-12 | TC-cache-14 | `tests/test_cache_service.py::test_cleanup_expired_removes_only_expired` |
| REQ-cache-13 | TC-cache-15, TC-cache-16 | `tests/test_cache_service.py::test_get_stats_counters_and_hit_rate`、`::test_get_stats_initial_hit_rate_zero` |
| REQ-cache-14 | TC-cache-17, TC-cache-18 | `tests/test_cache_service.py::test_cache_service_returns_same_instance`、`::test_reset_instance_creates_new_instance` |
| REQ-cache-15 | TC-cache-19 | `tests/test_cache_service.py::test_cache_keys_formats` |
| REQ-cache-16 | TC-cache-20 | `tests/test_cache_service.py::test_cache_ttl_constants` |
