# TC-cache: In-Memory Cache Service Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-cache](../specs/SPEC-cache.md) |
| Test level | Unit |
| Test script | `tests/test_cache_service.py` |

Common precondition: TTL-related cases control time with a fake clock (monkeypatch the module-level `time`); no sleeping.

---

## TC-cache-01: get returns the value after set

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-01 |
| **Level** | Unit |
| **Preconditions** | New `InMemoryCache()` |
| **Test input** | `set("k1", {"a": 1})` |
| **Test steps** | 1. set<br>2. get the same key |
| **Expected result** | Returns `{"a": 1}` |
| **Implementation** | `tests/test_cache_service.py::test_set_get_roundtrip` |

## TC-cache-02: get a nonexistent key

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-02 |
| **Level** | Unit |
| **Preconditions** | Empty cache |
| **Test input** | `get("nope")` |
| **Test steps** | 1. get a nonexistent key<br>2. read get_stats |
| **Expected result** | Returns `None`; `misses` == 1 |
| **Implementation** | `tests/test_cache_service.py::test_get_missing_key_returns_none` |

## TC-cache-03: repeated set on the same key overwrites

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-03 |
| **Level** | Unit |
| **Preconditions** | Cache already has `("k", "old")` |
| **Test input** | `set("k", "new")` |
| **Test steps** | 1. set twice<br>2. get |
| **Expected result** | Returns `"new"` |
| **Implementation** | `tests/test_cache_service.py::test_set_overwrites_existing_key` |

## TC-cache-04: get is invalidated after TTL expiry

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-04 |
| **Level** | Unit |
| **Preconditions** | Fake clock injected |
| **Test input** | `set("k", "v", ttl=10)`, advance time by 11 seconds |
| **Test steps** | 1. set<br>2. advance(11)<br>3. get<br>4. read get_stats |
| **Expected result** | get returns `None`; `size` == 0 (the expired entry is removed) |
| **Implementation** | `tests/test_cache_service.py::test_get_after_ttl_expired_returns_none` |

## TC-cache-05: still a hit exactly at expiry

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-05 |
| **Level** | Unit |
| **Preconditions** | Fake clock injected |
| **Test input** | `set("k", "v", ttl=10)`, advance time by exactly 10 seconds |
| **Test steps** | 1. set<br>2. advance(10)<br>3. get |
| **Expected result** | Returns `"v"` (expiry check is strictly greater-than) |
| **Implementation** | `tests/test_cache_service.py::test_get_at_exact_expiry_still_hits` |

## TC-cache-06: default_ttl used when ttl is not specified

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-06 |
| **Level** | Unit |
| **Preconditions** | `InMemoryCache(default_ttl=50)` + fake clock |
| **Test input** | `set("k", "v")` (no ttl) |
| **Test steps** | 1. set<br>2. advance(49) -> get<br>3. advance(2) -> get |
| **Expected result** | Returns `"v"` at 49 s; returns `None` at 51 s |
| **Implementation** | `tests/test_cache_service.py::test_set_without_ttl_uses_default_ttl` |

## TC-cache-07: delete an existing key

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-07 |
| **Level** | Unit |
| **Preconditions** | Cache already has `("k", "v")` |
| **Test input** | `delete("k")` |
| **Test steps** | 1. set<br>2. delete<br>3. get + get_stats |
| **Expected result** | get returns `None`; `deletes` == 1 |
| **Implementation** | `tests/test_cache_service.py::test_delete_existing_key` |

## TC-cache-08: delete of a nonexistent key is a no-op

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-08 |
| **Level** | Unit |
| **Preconditions** | Empty cache |
| **Test input** | `delete("ghost")` |
| **Test steps** | 1. delete a nonexistent key<br>2. read get_stats |
| **Expected result** | No exception; `deletes` == 0 |
| **Implementation** | `tests/test_cache_service.py::test_delete_missing_key_is_noop` |

## TC-cache-09: clear_pattern with a star wildcard

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-09 |
| **Level** | Unit |
| **Preconditions** | Cache contains `folder:t1:a`, `folder:t1:b`, `files:folder:9` |
| **Test input** | `clear_pattern("folder:*")` |
| **Test steps** | 1. set the three keys<br>2. clear_pattern<br>3. get each |
| **Expected result** | The first two return `None`; `files:folder:9` is retained; `deletes` == 2 |
| **Implementation** | `tests/test_cache_service.py::test_clear_pattern_star_wildcard` |

## TC-cache-10: clear_pattern with a single-character question-mark match

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-09 |
| **Level** | Unit |
| **Preconditions** | Cache contains `k1`, `k2`, `k10` |
| **Test input** | `clear_pattern("k?")` |
| **Test steps** | 1. set the three keys<br>2. clear_pattern<br>3. get each |
| **Expected result** | `k1` and `k2` are cleared; `k10` is retained |
| **Implementation** | `tests/test_cache_service.py::test_clear_pattern_question_mark_single_char` |

## TC-cache-11: clear_all empties the cache

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-10 |
| **Level** | Unit |
| **Preconditions** | Cache contains two keys |
| **Test input** | `clear_all()` |
| **Test steps** | 1. set x2<br>2. clear_all<br>3. get_stats + get |
| **Expected result** | `size` == 0; get returns `None` |
| **Implementation** | `tests/test_cache_service.py::test_clear_all_empties_cache` |

## TC-cache-12: at capacity, LRU evicts the least recently accessed entry

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-11 |
| **Level** | Unit |
| **Preconditions** | `InMemoryCache(max_size=2)` + fake clock |
| **Test input** | set a -> set b -> get a -> set c |
| **Test steps** | 1. perform the operations in order, advancing time<br>2. get each |
| **Expected result** | `b` is evicted (returns `None`); `a` and `c` are retained |
| **Implementation** | `tests/test_cache_service.py::test_lru_eviction_removes_least_recently_used` |

## TC-cache-13: overwriting an existing key at capacity does not evict

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-11 |
| **Level** | Unit |
| **Preconditions** | `InMemoryCache(max_size=2)` is full (a, b) |
| **Test input** | `set("a", 99)` |
| **Test steps** | 1. set a, b<br>2. overwrite a<br>3. get a, b |
| **Expected result** | `a` == 99; `b` is still present |
| **Implementation** | `tests/test_cache_service.py::test_set_existing_key_when_full_does_not_evict` |

## TC-cache-14: cleanup_expired removes only expired entries

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-12 |
| **Level** | Unit |
| **Preconditions** | Fake clock; `short` (ttl=5), `long` (ttl=100) |
| **Test input** | `cleanup_expired()` after advance(6) |
| **Test steps** | 1. set x2<br>2. advance(6)<br>3. cleanup_expired<br>4. get_stats + get |
| **Expected result** | `size` == 1; `long` is still retrievable |
| **Implementation** | `tests/test_cache_service.py::test_cleanup_expired_removes_only_expired` |

## TC-cache-15: get_stats counters and hit_rate

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-13 |
| **Level** | Unit |
| **Preconditions** | `InMemoryCache(max_size=7)` |
| **Test input** | 1 miss + 1 set + 1 hit + 1 delete |
| **Test steps** | 1. perform the operations in order<br>2. read get_stats |
| **Expected result** | hits=1, misses=1, sets=1, deletes=1, max_size=7, hit_rate=50.0 |
| **Implementation** | `tests/test_cache_service.py::test_get_stats_counters_and_hit_rate` |

## TC-cache-16: hit_rate is 0.0 with zero requests

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-13 |
| **Level** | Unit |
| **Preconditions** | Brand-new cache |
| **Test input** | Call `get_stats()` directly |
| **Test steps** | 1. read get_stats |
| **Expected result** | hit_rate == 0.0 (no division by zero); size == 0 |
| **Implementation** | `tests/test_cache_service.py::test_get_stats_initial_hit_rate_zero` |

## TC-cache-17: get_instance returns the same singleton

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-14 |
| **Level** | Unit |
| **Preconditions** | `reset_instance()` before and after the test (fixture) |
| **Test input** | `get_instance()` x2 |
| **Test steps** | 1. get the instance twice |
| **Expected result** | Both `is` the same object |
| **Implementation** | `tests/test_cache_service.py::test_cache_service_returns_same_instance` |

## TC-cache-18: a brand-new instance after reset_instance

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-14 |
| **Level** | Unit |
| **Preconditions** | Same fixture as above |
| **Test input** | get_instance -> set -> reset_instance -> get_instance |
| **Test steps** | 1. get the instance and write a value<br>2. reset<br>3. get the instance again |
| **Expected result** | The new and old objects differ; get on the new instance returns `None` |
| **Implementation** | `tests/test_cache_service.py::test_reset_instance_creates_new_instance` |

## TC-cache-19: CacheKeys key formats

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-15 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | Seven staticmethods (including a Chinese folder name) |
| **Test steps** | 1. generate each key (parametrize) |
| **Expected result** | `folder:{token}:{name}`, `folder:id:{id}`, `files:folder:{id}`, `file:id:{id}`, `query:{fid}:{hash}`, `auth:{token}`, `index:file:{id}` |
| **Implementation** | `tests/test_cache_service.py::test_cache_keys_formats` |

## TC-cache-20: CacheTTL constant values

| Field | Content |
|-------|---------|
| **Requirement** | REQ-cache-16 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | Read the six constants |
| **Test steps** | 1. assert each |
| **Expected result** | FOLDER=300, FILE_LIST=180, FILE_DETAIL=300, QUERY_RESULT=300, AUTH_TOKEN=3600, INDEX_STATUS=600 |
| **Implementation** | `tests/test_cache_service.py::test_cache_ttl_constants` |
