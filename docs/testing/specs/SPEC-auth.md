# SPEC-auth: Token Models and Remote Token Verification


| Item | Content |
|------|------|
| Module | `src/auth/model.py`, `src/auth/remote_auth.py` |
| Test | `tests/test_auth_unit.py` |
| Version | 0.1.0 |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

`src/auth/model.py` defines the Pydantic models for the token-management API (TokenCreateRequest / TokenResponse / TokenInfo / TokenListResponse).
`src/auth/remote_auth.py` provides `RemoteTokenVerifier`: it calls the Token Server's `/auth/verify` over HTTP (a persistent **sync** `httpx.Client`; the async interface wraps it with `asyncio.to_thread`), with an SHA-256 cache key, a TTL in-memory cache, a retry policy, and global singleton management.
Out of scope: token issuance and storage (a Token Server responsibility).

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-auth-01 | TokenCreateRequest gives every field a default (user_name=generated_user, scopes=[read,write,admin], length=24, expires_in_days=None) | Constructing with no arguments succeeds and defaults are correct |
| REQ-auth-02 | TokenResponse / TokenInfo / TokenListResponse fields are required; nested dicts are auto-coerced to TokenInfo | Missing a field raises ValidationError; each value in the `tokens` dict is coerced to TokenInfo |
| REQ-auth-03 | `_get_cache_key` produces the cache key via SHA-256 and never contains the plaintext token | 64 hex chars, deterministic, distinct tokens yield distinct keys, and the key contains no plaintext |
| REQ-auth-04 | Cache TTL: a hit within TTL returns the original result; after expiry it returns None and evicts the entry; clear_cache empties the cache | With a fake clock controlling time, all of the above is observable |
| REQ-auth-05 | `verify()` receiving 200 + valid:true returns a success result and writes to the cache (the second call does not hit the API) | After a second verify, `post` call count is still 1 |
| REQ-auth-06 | Only valid results are cached: 200 + valid:false is not cached | The second verify still hits the API |
| REQ-auth-07 | A 4xx client error is not retried and immediately returns `token_server_error_<code>` | `post` is called exactly once |
| REQ-auth-08 | timeout / 5xx / connection failure are retryable: after retry_count+1 attempts, return the corresponding error (timeout / token_server_error_<code> / connection_error) | `post` call count = retry_count+1; the error string is correct |
| REQ-auth-09 | `verify_sync` provides a synchronous path; the request payload carries token plus service_host/service_port (when configured) | The payload JSON content is correct |
| REQ-auth-10 | `get_remote_verifier` requires a URL on its first call (otherwise ValueError), then returns the same singleton; the URL trailing slash is stripped | Current behavior is observable |

## 3. Non-Functional Requirements

- The cache key must not retain the plaintext token (REQ-auth-03).
- Cache access must be thread-safe (implemented with a `threading.Lock`; the unit tests do not verify concurrency).
- Tests must not make any real network requests (the httpx client is fully mocked).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| TokenCreateRequest explicitly passes `expires_in_days=None` | ValidationError (the field is typed `int`, not `Optional[int]`; the default None works because defaults are not validated — a likely field-declaration bug, see §5) |
| Token Server returns 401 | valid=False, error=`token_server_error_401`, no retry |
| Token Server times out throughout | After retries are exhausted, valid=False, error=`timeout` |
| Token Server unreachable | valid=False, error=`connection_error` |
| First `get_remote_verifier()` call without a URL | ValueError |

## 5. Dependencies & Assumptions

- Depends on `httpx` (sync Client only; tests replace `_sync_client` with a MagicMock), `asyncio.to_thread`, and `src.log`.
- TTL tests monkeypatch `src.auth.remote_auth.time` with a fake clock and never sleep.
- Global-singleton tests call `reset_remote_verifier()` before and after to restore state.
- **Source note (likely bug)**: `TokenCreateRequest.expires_in_days: int = None` should be declared `Optional[int] = None`; as-is, explicitly passing None is rejected. The test pins the current behavior.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-auth-01 | TC-auth-01 | `tests/test_auth_unit.py::test_token_create_request_defaults` |
| REQ-auth-02 | TC-auth-02 ~ TC-auth-05 | `tests/test_auth_unit.py::test_token_create_request_explicit_none_rejected`, `::test_token_response_required_fields`, `::test_token_info_roundtrip`, `::test_token_list_response_nested_coercion` |
| REQ-auth-03 | TC-auth-06, TC-auth-07 | `tests/test_auth_unit.py::test_get_cache_key_is_sha256`, `::test_get_cache_key_no_plaintext_and_distinct` |
| REQ-auth-04 | TC-auth-08 ~ TC-auth-10 | `tests/test_auth_unit.py::test_cache_hit_within_ttl`, `::test_cache_expired_after_ttl`, `::test_clear_cache` |
| REQ-auth-05 | TC-auth-11 | `tests/test_auth_unit.py::test_verify_success_and_cached` |
| REQ-auth-06 | TC-auth-12 | `tests/test_auth_unit.py::test_verify_invalid_result_not_cached` |
| REQ-auth-07 | TC-auth-13 | `tests/test_auth_unit.py::test_verify_401_no_retry` |
| REQ-auth-08 | TC-auth-14 ~ TC-auth-16 | `tests/test_auth_unit.py::test_verify_timeout_retries_then_fails`, `::test_verify_5xx_retries_then_fails`, `::test_verify_connect_error` |
| REQ-auth-09 | TC-auth-17 | `tests/test_auth_unit.py::test_verify_sync_success_with_service_identity` |
| REQ-auth-10 | TC-auth-18 | `tests/test_auth_unit.py::test_get_remote_verifier_singleton_lifecycle` |
