# SPEC-auth:Token 模型與遠端 Token 驗證


| 項目 | 內容 |
|------|------|
| 模組 | `src/auth/model.py`、`src/auth/remote_auth.py` |
| 對應測試 | `tests/test_auth_unit.py` |
| 版本 | 0.1.0 |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

`src/auth/model.py` 定義 Token 管理 API 的 Pydantic 模型(TokenCreateRequest / TokenResponse / TokenInfo / TokenListResponse)。
`src/auth/remote_auth.py` 提供 `RemoteTokenVerifier`:透過 HTTP(持久化 **sync** `httpx.Client`;async 介面用 `asyncio.to_thread` 包裝)呼叫 Token Server `/auth/verify`,含 SHA-256 快取 key、TTL 記憶體快取、重試策略與全域單例管理。
不負責:Token 的簽發與儲存(Token Server 職責)。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-auth-01 | TokenCreateRequest 全欄位有預設值(user_name=generated_user、scopes=[read,write,admin]、length=24、expires_in_days=None) | 無參數建立成功且預設值正確 |
| REQ-auth-02 | TokenResponse / TokenInfo / TokenListResponse 欄位必填,巢狀 dict 自動轉 TokenInfo | 缺欄位拋 ValidationError;`tokens` dict 的 value 轉為 TokenInfo |
| REQ-auth-03 | `_get_cache_key` 以 SHA-256 產生快取 key,不含明文 token | 64 hex、確定性、不同 token 不同 key、key 不含原文 |
| REQ-auth-04 | 快取 TTL:TTL 內命中回傳原結果;過期回 None 並移除項目;clear_cache 清空 | 以假時鐘控制 time 可觀察上述行為 |
| REQ-auth-05 | `verify()` 收到 200 + valid:true → 回成功結果並寫入快取(第二次不再打 API) | 第二次 verify 後 `post` 呼叫次數仍為 1 |
| REQ-auth-06 | 只快取有效結果:200 + valid:false 不寫快取 | 第二次 verify 仍打 API |
| REQ-auth-07 | 4xx client error 不重試,立即回 `token_server_error_<code>` | `post` 恰被呼叫 1 次 |
| REQ-auth-08 | timeout / 5xx / 連線失敗屬 retryable:重試 retry_count+1 次後回對應 error(timeout / token_server_error_<code> / connection_error) | `post` 呼叫次數 = retry_count+1;error 字串正確 |
| REQ-auth-09 | `verify_sync` 提供同步路徑;請求 payload 帶 token 與 service_host/service_port(若有設定) | payload JSON 內容正確 |
| REQ-auth-10 | `get_remote_verifier` 首次呼叫必須給 URL(否則 ValueError),之後回同一單例;URL 尾斜線去除 | 現行行為可觀察 |

## 3. 非功能需求 (Non-Functional)

- 快取 key 不得保留明文 token(REQ-auth-03)。
- 快取存取需 thread-safe(實作以 `threading.Lock` 保護;單元測試不驗證併發)。
- 測試不得對真實網路發出任何請求(httpx client 全 mock)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| TokenCreateRequest 顯式傳 `expires_in_days=None` | ValidationError(欄位型別為 `int` 而非 `Optional[int]`;預設值 None 因不驗證預設而可用 — 疑似欄位宣告錯誤,詳見 §5) |
| Token Server 回 401 | valid=False、error=`token_server_error_401`、不重試 |
| Token Server 全程 timeout | 重試耗盡後 valid=False、error=`timeout` |
| Token Server 連不上 | valid=False、error=`connection_error` |
| 首次 `get_remote_verifier()` 未給 URL | ValueError |

## 5. 相依與假設 (Dependencies & Assumptions)

- 依賴 `httpx`(僅 sync Client;測試以 MagicMock 替換 `_sync_client`)、`asyncio.to_thread`、`src.log`。
- TTL 測試 monkeypatch `src.auth.remote_auth.time` 為假時鐘,不做 sleep。
- 全域單例測試前後呼叫 `reset_remote_verifier()` 復原狀態。
- **原始碼註記(疑似 bug)**:`TokenCreateRequest.expires_in_days: int = None` 應宣告為 `Optional[int] = None`;現況下顯式傳 None 會被拒。測試固定現行行為。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-auth-01 | TC-auth-01 | `tests/test_auth_unit.py::test_token_create_request_defaults` |
| REQ-auth-02 | TC-auth-02 ~ TC-auth-05 | `tests/test_auth_unit.py::test_token_create_request_explicit_none_rejected`、`::test_token_response_required_fields`、`::test_token_info_roundtrip`、`::test_token_list_response_nested_coercion` |
| REQ-auth-03 | TC-auth-06, TC-auth-07 | `tests/test_auth_unit.py::test_get_cache_key_is_sha256`、`::test_get_cache_key_no_plaintext_and_distinct` |
| REQ-auth-04 | TC-auth-08 ~ TC-auth-10 | `tests/test_auth_unit.py::test_cache_hit_within_ttl`、`::test_cache_expired_after_ttl`、`::test_clear_cache` |
| REQ-auth-05 | TC-auth-11 | `tests/test_auth_unit.py::test_verify_success_and_cached` |
| REQ-auth-06 | TC-auth-12 | `tests/test_auth_unit.py::test_verify_invalid_result_not_cached` |
| REQ-auth-07 | TC-auth-13 | `tests/test_auth_unit.py::test_verify_401_no_retry` |
| REQ-auth-08 | TC-auth-14 ~ TC-auth-16 | `tests/test_auth_unit.py::test_verify_timeout_retries_then_fails`、`::test_verify_5xx_retries_then_fails`、`::test_verify_connect_error` |
| REQ-auth-09 | TC-auth-17 | `tests/test_auth_unit.py::test_verify_sync_success_with_service_identity` |
| REQ-auth-10 | TC-auth-18 | `tests/test_auth_unit.py::test_get_remote_verifier_singleton_lifecycle` |
