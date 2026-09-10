# SPEC-middleware:Request ID 中間件與錯誤處理


| 項目 | 內容 |
|------|------|
| 模組 | `src/middleware/request_id.py`、`src/middleware/error_handler.py`(搭配 `src/domain/exceptions.py`) |
| 對應測試 | `tests/test_middleware.py` |
| 版本 | 0.1.0 |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

`request_id.py`:純 ASGI 中間件,對每個 HTTP 請求產生短 request_id(UUID 前 8 碼)注入 contextvar,供全鏈路 log 串聯。
`error_handler.py`:FastAPI exception handlers — `domain_exception_handler` 將 DomainException 依 `get_http_status_for_exception` 映射為 HTTP 回應;`generic_exception_handler` 為 catch-all(HTTPException re-raise,其餘 500)。
不負責:log sink 設定、DomainException 的定義(domain 層)。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-middleware-01 | http scope 請求進入時產生新 request_id(8 碼)寫入 contextvar,下游可讀 | 下游 app 內 `get_request_id()` 回非 "-" 的 8 碼字串 |
| REQ-middleware-02 | 每個 http 請求的 request_id 唯一 | 連續兩請求 id 不同 |
| REQ-middleware-03 | 非 http scope(如 lifespan)不產生新 id | contextvar 維持原值 |
| REQ-middleware-04 | 中間件透傳 scope/receive/send 給下游 app | 下游收到同一組物件 |
| REQ-middleware-05 | DomainException → 對應 HTTP status(400/401/403/404/409/500)+ 統一 body 結構 `{error, message, timestamp, path[, details]}` | 各 exception 類型回應正確 |
| REQ-middleware-06 | `details` 為空 dict 時 body 省略 details 鍵 | InvalidTokenError 回應無 details |
| REQ-middleware-07 | 未知 error_code 的 DomainException fallback 為 500 | status_code=500 |
| REQ-middleware-08 | 一般例外 → 500 + `INTERNAL_SERVER_ERROR`,不洩漏內部錯誤訊息 | body 不含原始例外字串 |
| REQ-middleware-09 | HTTPException 由 generic handler 原樣 re-raise,不被吞成 500 | 拋出同一個 HTTPException 實例 |

## 3. 非功能需求 (Non-Functional)

- 500 回應不得暴露 traceback 或內部錯誤細節給 client(REQ-middleware-08)。
- request_id 注入不得依賴 FastAPI,純 ASGI 介面即可運作。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| scope["type"] == "lifespan" / "websocket" | 不產生 request_id,直接透傳 |
| DomainException.details 為空 | body 無 details 鍵 |
| error_code 不在 status 映射表 | 500 |
| generic handler 收到 HTTPException | re-raise |

## 5. 相依與假設 (Dependencies & Assumptions)

- error handler 只讀 `request.url.path`,測試以 `SimpleNamespace(url=SimpleNamespace(path=...))` 假物件替代 Request。
- ASGI scope/receive/send 以最小假物件模擬,不啟動真實 server。
- HTTP status 映射依 `src/domain/exceptions.py::get_http_status_for_exception`。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-middleware-01 | TC-middleware-01 | `tests/test_middleware.py::test_request_id_set_for_http_scope` |
| REQ-middleware-02 | TC-middleware-02 | `tests/test_middleware.py::test_request_id_unique_per_request` |
| REQ-middleware-03 | TC-middleware-03 | `tests/test_middleware.py::test_request_id_not_set_for_non_http_scope` |
| REQ-middleware-04 | TC-middleware-04 | `tests/test_middleware.py::test_middleware_passes_through_asgi_args` |
| REQ-middleware-05 | TC-middleware-05, TC-middleware-06, TC-middleware-08, TC-middleware-09, TC-middleware-11 | `tests/test_middleware.py::test_domain_handler_folder_not_found_404`、`::test_domain_handler_validation_error_400`、`::test_domain_handler_conflict_409`、`::test_domain_handler_rag_query_error_500`、`::test_status_mapping_file_index_not_found_404` |
| REQ-middleware-06 | TC-middleware-07 | `tests/test_middleware.py::test_domain_handler_invalid_token_401_no_details` |
| REQ-middleware-07 | TC-middleware-10 | `tests/test_middleware.py::test_domain_handler_unknown_code_falls_back_500` |
| REQ-middleware-08 | TC-middleware-12 | `tests/test_middleware.py::test_generic_handler_returns_500_without_leaking_internals` |
| REQ-middleware-09 | TC-middleware-13 | `tests/test_middleware.py::test_generic_handler_reraises_http_exception` |
