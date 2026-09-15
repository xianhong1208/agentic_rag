# SPEC-cache: In-Memory Cache Service


| Item | Content |
|------|------|
| Module | `src/infrastructure/cache/cache_service.py` |
| Test | `tests/test_cache_service.py` |
| Version | feat/rag-robustness |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Provides an in-process in-memory cache (`InMemoryCache`) to reduce DB load for read-heavy operations such as folder lookups, file listings, RAG query results, and auth token verification. Accompanied by:

- `CacheService`: a global singleton factory (`get_instance` / `reset_instance`).
- `CacheKeys`: standard cache-key generators per entity type, ensuring consistent key formats.
- `CacheTTL`: recommended TTL constants per entity type.

Out of scope: cross-process distributed caching (Redis) and persistence.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-cache-01 | `get` after `set` returns the original value | After `set(k, v)`, `get(k)` returns `v` (any serializable object) |
| REQ-cache-02 | A missing key returns `None` | `get` on a nonexistent key returns `None` and increments miss by one |
| REQ-cache-03 | Repeated `set` on the same key overwrites | After a second `set(k, v2)`, `get(k)` returns `v2` |
| REQ-cache-04 | Entries expire after TTL | After more than `ttl` seconds, `get(k)` returns `None` and the entry is evicted (size decreases) |
| REQ-cache-05 | Expiry check is strictly greater-than | When the current time exactly equals expiry, the entry is still valid (expired only when `time.time() > expiry`) |
| REQ-cache-06 | Unspecified ttl uses default_ttl | `set(k, v)` (ttl=None) has a lifetime equal to the constructor's `default_ttl` |
| REQ-cache-07 | `delete` removes the given key | After `delete(k)`, `get(k)` returns `None` and the deletes counter increments by 1 |
| REQ-cache-08 | `delete` on a nonexistent key is a no-op | No exception raised; the deletes counter is unchanged |
| REQ-cache-09 | `clear_pattern` bulk-clears via fnmatch | `*` matches any string, `?` matches a single character; only matching keys are deleted |
| REQ-cache-10 | `clear_all` empties the cache | After clearing, size = 0 |
| REQ-cache-11 | LRU eviction | When the cache reaches `max_size`, adding a **new key** evicts the entry with the oldest last_access; overwriting an existing key does not trigger eviction |
| REQ-cache-12 | `cleanup_expired` removes only expired entries | Expired entries are evicted; non-expired entries are retained |
| REQ-cache-13 | `get_stats` reports correctly | Returns size / max_size / hits / misses / sets / deletes / hit_rate; with zero requests, hit_rate = 0.0 (no division by zero) |
| REQ-cache-14 | Global singleton | `get_instance()` returns the same object across calls; `reset_instance()` produces a fresh instance |
| REQ-cache-15 | Fixed CacheKeys formats | Each staticmethod produces a fixed prefix format (`folder:`, `files:folder:`, `file:id:`, `query:`, `auth:`, `index:file:`) |
| REQ-cache-16 | CacheTTL constants | FOLDER=300, FILE_LIST=180, FILE_DETAIL=300, QUERY_RESULT=300, AUTH_TOKEN=3600, INDEX_STATUS=600 |

## 3. Non-Functional Requirements

- Thread safety: all read/write operations are guarded by a `threading.Lock` (these tests do no concurrency stress testing, which is outside the unit scope).
- Tests must not use long sleeps; TTL behavior is verified with a fake clock (monkeypatch the module's `time`).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| get a nonexistent key | returns `None`, counts a miss |
| get an already-expired key | returns `None`, evicting the entry in passing |
| delete a nonexistent key | silent no-op |
| cache full + new key | evicts the least-recently-accessed entry |
| cache full + overwrite existing key | evicts nothing |
| stats with no requests | hit_rate = 0.0 |

## 5. Dependencies & Assumptions

- Depends only on the standard library (`time`, `fnmatch`, `threading`) — no external service to mock.
- Tests inject a controllable clock via `monkeypatch.setattr(cache_mod, "time", fake)`.
- Tests involving the global singleton must call `CacheService.reset_instance()` before and after to avoid contamination.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-cache-01 | TC-cache-01 | `tests/test_cache_service.py::test_set_get_roundtrip` |
| REQ-cache-02 | TC-cache-02 | `tests/test_cache_service.py::test_get_missing_key_returns_none` |
| REQ-cache-03 | TC-cache-03 | `tests/test_cache_service.py::test_set_overwrites_existing_key` |
| REQ-cache-04 | TC-cache-04 | `tests/test_cache_service.py::test_get_after_ttl_expired_returns_none` |
| REQ-cache-05 | TC-cache-05 | `tests/test_cache_service.py::test_get_at_exact_expiry_still_hits` |
| REQ-cache-06 | TC-cache-06 | `tests/test_cache_service.py::test_set_without_ttl_uses_default_ttl` |
| REQ-cache-07 | TC-cache-07 | `tests/test_cache_service.py::test_delete_existing_key` |
| REQ-cache-08 | TC-cache-08 | `tests/test_cache_service.py::test_delete_missing_key_is_noop` |
| REQ-cache-09 | TC-cache-09, TC-cache-10 | `tests/test_cache_service.py::test_clear_pattern_star_wildcard`, `::test_clear_pattern_question_mark_single_char` |
| REQ-cache-10 | TC-cache-11 | `tests/test_cache_service.py::test_clear_all_empties_cache` |
| REQ-cache-11 | TC-cache-12, TC-cache-13 | `tests/test_cache_service.py::test_lru_eviction_removes_least_recently_used`, `::test_set_existing_key_when_full_does_not_evict` |
| REQ-cache-12 | TC-cache-14 | `tests/test_cache_service.py::test_cleanup_expired_removes_only_expired` |
| REQ-cache-13 | TC-cache-15, TC-cache-16 | `tests/test_cache_service.py::test_get_stats_counters_and_hit_rate`, `::test_get_stats_initial_hit_rate_zero` |
| REQ-cache-14 | TC-cache-17, TC-cache-18 | `tests/test_cache_service.py::test_cache_service_returns_same_instance`, `::test_reset_instance_creates_new_instance` |
| REQ-cache-15 | TC-cache-19 | `tests/test_cache_service.py::test_cache_keys_formats` |
| REQ-cache-16 | TC-cache-20 | `tests/test_cache_service.py::test_cache_ttl_constants` |
