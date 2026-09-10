# TC-auth:Token 模型與遠端 Token 驗證 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-auth](../specs/SPEC-auth.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_auth_unit.py` |

共用前置:所有 RemoteTokenVerifier 測試以假 URL(`http://token-server.invalid:1/`)建立,HTTP client 以 MagicMock 取代 `_sync_client`,**不打真實網路**;TTL 測試以 monkeypatch 假時鐘取代 `src.auth.remote_auth.time`。

---

## TC-auth-01:TokenCreateRequest 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-01 |
| **層級** | 單元 |
| **測試輸入** | 無參數 |
| **預期結果** | user_name="generated_user"、scopes=["read","write","admin"]、length=24、expires_in_days=None |
| **實作** | `tests/test_auth_unit.py::test_token_create_request_defaults` |

## TC-auth-02:expires_in_days 顯式 None 被拒(現行行為)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-02 |
| **層級** | 單元 |
| **測試輸入** | `TokenCreateRequest(expires_in_days=None)` |
| **預期結果** | ValidationError(欄位型別為 `int` 非 `Optional[int]`;疑似宣告錯誤,見 SPEC §5) |
| **實作** | `tests/test_auth_unit.py::test_token_create_request_explicit_none_rejected` |

## TC-auth-03:TokenResponse 必填驗證

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-02 |
| **層級** | 單元 |
| **測試輸入** | (a) 六欄位齊全 (b) 只給 token |
| **預期結果** | (a) 建立成功 (b) ValidationError,缺漏 = {user_name, scopes, expires_at, expires_at_readable, message} |
| **實作** | `tests/test_auth_unit.py::test_token_response_required_fields` |

## TC-auth-04:TokenInfo 建立與序列化

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-02 |
| **層級** | 單元 |
| **測試輸入** | 五欄位齊全 |
| **預期結果** | model_dump 保留全部欄位值(含 module list) |
| **實作** | `tests/test_auth_unit.py::test_token_info_roundtrip` |

## TC-auth-05:TokenListResponse 巢狀轉型

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-02 |
| **層級** | 單元 |
| **測試輸入** | `tokens={"tok-1": {...TokenInfo dict...}}` |
| **預期結果** | `tokens["tok-1"]` 為 TokenInfo 實例 |
| **實作** | `tests/test_auth_unit.py::test_token_list_response_nested_coercion` |

## TC-auth-06:快取 key 為 SHA-256

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-03 |
| **層級** | 單元 |
| **測試輸入** | `_get_cache_key("my-secret-token")` 呼叫兩次 |
| **預期結果** | 等於 `hashlib.sha256(...).hexdigest()`;64 hex;兩次結果相同 |
| **實作** | `tests/test_auth_unit.py::test_get_cache_key_is_sha256` |

## TC-auth-07:快取 key 不含明文且不同 token 不同 key

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-03 |
| **層級** | 單元 |
| **測試輸入** | 兩個不同 token |
| **預期結果** | key 不同;key 字串不包含原始 token |
| **實作** | `tests/test_auth_unit.py::test_get_cache_key_no_plaintext_and_distinct` |

## TC-auth-08:TTL 內快取命中

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-04 |
| **層級** | 單元 |
| **前置條件** | 假時鐘;cache_ttl=60 |
| **測試步驟** | 1. `_set_cache`<br>2. 時鐘 +59 秒<br>3. `_get_from_cache` |
| **預期結果** | 回傳原 TokenVerifyResult 實例 |
| **實作** | `tests/test_auth_unit.py::test_cache_hit_within_ttl` |

## TC-auth-09:TTL 過期後清除

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-04 |
| **層級** | 單元 |
| **前置條件** | 假時鐘;cache_ttl=60 |
| **測試步驟** | 1. `_set_cache`<br>2. 時鐘 +61 秒<br>3. `_get_from_cache` |
| **預期結果** | 回 None,且該 key 已從 `_cache` 移除 |
| **實作** | `tests/test_auth_unit.py::test_cache_expired_after_ttl` |

## TC-auth-10:clear_cache 清空

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-04 |
| **層級** | 單元 |
| **測試步驟** | 1. 寫入兩筆快取<br>2. clear_cache |
| **預期結果** | `_cache == {}` |
| **實作** | `tests/test_auth_unit.py::test_clear_cache` |

## TC-auth-11:verify 成功並快取

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-05 |
| **層級** | 單元 |
| **前置條件** | mock client `post` 回 200 + `{valid: true, user_name, scopes, expires_at}` |
| **測試步驟** | 1. `await verify("good-token")`<br>2. 再次 `await verify("good-token")` |
| **預期結果** | 結果 valid=True 且欄位正確;第二次後 `post.call_count` 仍為 1(走快取) |
| **實作** | `tests/test_auth_unit.py::test_verify_success_and_cached` |

## TC-auth-12:無效結果不快取

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-06 |
| **層級** | 單元 |
| **前置條件** | mock 回 200 + `{valid: false, error: "expired"}` |
| **測試步驟** | 連續 verify 兩次 |
| **預期結果** | valid=False、error="expired";`post.call_count == 2` |
| **實作** | `tests/test_auth_unit.py::test_verify_invalid_result_not_cached` |

## TC-auth-13:401 不重試

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-07 |
| **層級** | 單元 |
| **前置條件** | retry_count=2;mock 回 401 |
| **預期結果** | valid=False、error="token_server_error_401";`post.call_count == 1` |
| **實作** | `tests/test_auth_unit.py::test_verify_401_no_retry` |

## TC-auth-14:timeout 重試耗盡

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-08 |
| **層級** | 單元 |
| **前置條件** | retry_count=2;`post.side_effect = httpx.TimeoutException` |
| **預期結果** | valid=False、error="timeout";`post.call_count == 3` |
| **實作** | `tests/test_auth_unit.py::test_verify_timeout_retries_then_fails` |

## TC-auth-15:5xx 重試耗盡

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-08 |
| **層級** | 單元 |
| **前置條件** | retry_count=1;mock 回 503 |
| **預期結果** | valid=False、error="token_server_error_503";`post.call_count == 2` |
| **實作** | `tests/test_auth_unit.py::test_verify_5xx_retries_then_fails` |

## TC-auth-16:連線失敗

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-08 |
| **層級** | 單元 |
| **前置條件** | retry_count=0;`post.side_effect = httpx.ConnectError` |
| **預期結果** | valid=False、error="connection_error" |
| **實作** | `tests/test_auth_unit.py::test_verify_connect_error` |

## TC-auth-17:verify_sync 與 service 身分 payload

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-09 |
| **層級** | 單元 |
| **前置條件** | verifier 建立時給 service_host="10.0.0.1"、service_port=8080;mock 回 200 valid |
| **預期結果** | verify_sync 回 valid=True;post 的 json payload = `{token, service_host, service_port}` |
| **實作** | `tests/test_auth_unit.py::test_verify_sync_success_with_service_identity` |

## TC-auth-18:全域單例生命週期

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-auth-10 |
| **層級** | 單元 |
| **前置條件** | `reset_remote_verifier()`(測試後亦復原) |
| **測試步驟** | 1. 無 URL 呼叫 get_remote_verifier<br>2. 給 URL 呼叫<br>3. 再次無 URL 呼叫 |
| **預期結果** | 步驟 1 拋 ValueError;步驟 2、3 回同一實例;URL 尾斜線被去除 |
| **實作** | `tests/test_auth_unit.py::test_get_remote_verifier_singleton_lifecycle` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
