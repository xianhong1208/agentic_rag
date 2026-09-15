# TC-auth: Token Models and Remote Token Verification Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-auth](../specs/SPEC-auth.md) |
| Test level | Unit |
| Test script | `tests/test_auth_unit.py` |

Shared preconditions: all RemoteTokenVerifier tests are constructed with a fake URL (`http://token-server.invalid:1/`), the HTTP client `_sync_client` is replaced with a MagicMock, and **no real network calls are made**; TTL tests replace `src.auth.remote_auth.time` with a fake clock via monkeypatch.

---

## TC-auth-01: TokenCreateRequest default values

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-01 |
| **Level** | Unit |
| **Test input** | No arguments |
| **Expected result** | user_name="generated_user", scopes=["read","write","admin"], length=24, expires_in_days=None |
| **Implementation** | `tests/test_auth_unit.py::test_token_create_request_defaults` |

## TC-auth-02: Explicit None for expires_in_days is rejected (current behavior)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-02 |
| **Level** | Unit |
| **Test input** | `TokenCreateRequest(expires_in_days=None)` |
| **Expected result** | ValidationError (the field type is `int`, not `Optional[int]`; likely a declaration error, see SPEC §5) |
| **Implementation** | `tests/test_auth_unit.py::test_token_create_request_explicit_none_rejected` |

## TC-auth-03: TokenResponse required-field validation

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-02 |
| **Level** | Unit |
| **Test input** | (a) all six fields present (b) only token provided |
| **Expected result** | (a) created successfully (b) ValidationError; missing = {user_name, scopes, expires_at, expires_at_readable, message} |
| **Implementation** | `tests/test_auth_unit.py::test_token_response_required_fields` |

## TC-auth-04: TokenInfo creation and serialization

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-02 |
| **Level** | Unit |
| **Test input** | All five fields present |
| **Expected result** | model_dump preserves all field values (including the module list) |
| **Implementation** | `tests/test_auth_unit.py::test_token_info_roundtrip` |

## TC-auth-05: TokenListResponse nested coercion

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-02 |
| **Level** | Unit |
| **Test input** | `tokens={"tok-1": {...TokenInfo dict...}}` |
| **Expected result** | `tokens["tok-1"]` is a TokenInfo instance |
| **Implementation** | `tests/test_auth_unit.py::test_token_list_response_nested_coercion` |

## TC-auth-06: Cache key is SHA-256

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-03 |
| **Level** | Unit |
| **Test input** | `_get_cache_key("my-secret-token")` called twice |
| **Expected result** | Equals `hashlib.sha256(...).hexdigest()`; 64 hex chars; identical on both calls |
| **Implementation** | `tests/test_auth_unit.py::test_get_cache_key_is_sha256` |

## TC-auth-07: Cache key contains no plaintext and differs per token

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-03 |
| **Level** | Unit |
| **Test input** | Two different tokens |
| **Expected result** | Keys differ; the key string does not contain the original token |
| **Implementation** | `tests/test_auth_unit.py::test_get_cache_key_no_plaintext_and_distinct` |

## TC-auth-08: Cache hit within TTL

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-04 |
| **Level** | Unit |
| **Preconditions** | Fake clock; cache_ttl=60 |
| **Test steps** | 1. `_set_cache`<br>2. Advance clock +59 seconds<br>3. `_get_from_cache` |
| **Expected result** | Returns the original TokenVerifyResult instance |
| **Implementation** | `tests/test_auth_unit.py::test_cache_hit_within_ttl` |

## TC-auth-09: Cache cleared after TTL expiry

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-04 |
| **Level** | Unit |
| **Preconditions** | Fake clock; cache_ttl=60 |
| **Test steps** | 1. `_set_cache`<br>2. Advance clock +61 seconds<br>3. `_get_from_cache` |
| **Expected result** | Returns None, and the key has been removed from `_cache` |
| **Implementation** | `tests/test_auth_unit.py::test_cache_expired_after_ttl` |

## TC-auth-10: clear_cache empties the cache

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-04 |
| **Level** | Unit |
| **Test steps** | 1. Write two cache entries<br>2. clear_cache |
| **Expected result** | `_cache == {}` |
| **Implementation** | `tests/test_auth_unit.py::test_clear_cache` |

## TC-auth-11: verify succeeds and caches

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-05 |
| **Level** | Unit |
| **Preconditions** | mock client `post` returns 200 + `{valid: true, user_name, scopes, expires_at}` |
| **Test steps** | 1. `await verify("good-token")`<br>2. `await verify("good-token")` again |
| **Expected result** | Result valid=True with correct fields; after the second call `post.call_count` is still 1 (served from cache) |
| **Implementation** | `tests/test_auth_unit.py::test_verify_success_and_cached` |

## TC-auth-12: Invalid results are not cached

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-06 |
| **Level** | Unit |
| **Preconditions** | mock returns 200 + `{valid: false, error: "expired"}` |
| **Test steps** | verify twice in a row |
| **Expected result** | valid=False, error="expired"; `post.call_count == 2` |
| **Implementation** | `tests/test_auth_unit.py::test_verify_invalid_result_not_cached` |

## TC-auth-13: 401 is not retried

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-07 |
| **Level** | Unit |
| **Preconditions** | retry_count=2; mock returns 401 |
| **Expected result** | valid=False, error="token_server_error_401"; `post.call_count == 1` |
| **Implementation** | `tests/test_auth_unit.py::test_verify_401_no_retry` |

## TC-auth-14: Timeout exhausts retries

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-08 |
| **Level** | Unit |
| **Preconditions** | retry_count=2; `post.side_effect = httpx.TimeoutException` |
| **Expected result** | valid=False, error="timeout"; `post.call_count == 3` |
| **Implementation** | `tests/test_auth_unit.py::test_verify_timeout_retries_then_fails` |

## TC-auth-15: 5xx exhausts retries

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-08 |
| **Level** | Unit |
| **Preconditions** | retry_count=1; mock returns 503 |
| **Expected result** | valid=False, error="token_server_error_503"; `post.call_count == 2` |
| **Implementation** | `tests/test_auth_unit.py::test_verify_5xx_retries_then_fails` |

## TC-auth-16: Connection failure

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-08 |
| **Level** | Unit |
| **Preconditions** | retry_count=0; `post.side_effect = httpx.ConnectError` |
| **Expected result** | valid=False, error="connection_error" |
| **Implementation** | `tests/test_auth_unit.py::test_verify_connect_error` |

## TC-auth-17: verify_sync and the service-identity payload

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-09 |
| **Level** | Unit |
| **Preconditions** | verifier constructed with service_host="10.0.0.1", service_port=8080; mock returns 200 valid |
| **Expected result** | verify_sync returns valid=True; the post json payload = `{token, service_host, service_port}` |
| **Implementation** | `tests/test_auth_unit.py::test_verify_sync_success_with_service_identity` |

## TC-auth-18: Global singleton lifecycle

| Field | Content |
|-------|---------|
| **Requirement** | REQ-auth-10 |
| **Level** | Unit |
| **Preconditions** | `reset_remote_verifier()` (also restored after the test) |
| **Test steps** | 1. Call get_remote_verifier without a URL<br>2. Call with a URL<br>3. Call again without a URL |
| **Expected result** | Step 1 raises ValueError; steps 2 and 3 return the same instance; the trailing slash on the URL is stripped |
| **Implementation** | `tests/test_auth_unit.py::test_get_remote_verifier_singleton_lifecycle` |

> Authoring principle: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
