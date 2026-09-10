# TC-middleware:Request ID 中間件與錯誤處理 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-middleware](../specs/SPEC-middleware.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_middleware.py` |

共用前置:ASGI scope/receive/send 與 FastAPI Request 全用假物件(`SimpleNamespace`),不啟動 server、不依賴 DB / 網路。

---

## TC-middleware-01:http scope 注入 request_id

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-01 |
| **層級** | 單元 |
| **測試輸入** | `scope={"type": "http", "path": "/x"}` |
| **測試步驟** | 1. 以會記錄 `get_request_id()` 的假 app 包 RequestIdMiddleware<br>2. await middleware(scope, receive, send) |
| **預期結果** | 假 app 內讀到的 rid != "-" 且長度為 8 |
| **實作** | `tests/test_middleware.py::test_request_id_set_for_http_scope` |

## TC-middleware-02:request_id 每請求唯一

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-02 |
| **層級** | 單元 |
| **測試步驟** | 連續呼叫 middleware 兩次,記錄兩次 rid |
| **預期結果** | 兩次 rid 不同 |
| **實作** | `tests/test_middleware.py::test_request_id_unique_per_request` |

## TC-middleware-03:非 http scope 不產生新 id

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-03 |
| **層級** | 單元 |
| **前置條件** | 先 `set_request_id("sentinel1")` |
| **測試輸入** | `scope={"type": "lifespan"}` |
| **預期結果** | 假 app 內讀到 rid == "sentinel1"(未被覆寫) |
| **實作** | `tests/test_middleware.py::test_request_id_not_set_for_non_http_scope` |

## TC-middleware-04:透傳 ASGI 參數

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-04 |
| **層級** | 單元 |
| **預期結果** | 下游 app 收到的 (scope, receive, send) 與傳入者為同一組物件 |
| **實作** | `tests/test_middleware.py::test_middleware_passes_through_asgi_args` |

## TC-middleware-05:FolderNotFoundError → 404 與完整 body

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-05 |
| **層級** | 單元 |
| **測試輸入** | `FolderNotFoundError(folder_id=99)`,path="/api/folders/99" |
| **預期結果** | status 404;body.error="FOLDER_NOT_FOUND";message 含 "99";path 正確;含 timestamp;details={"resource_type": "folder", "identifier": "99"} |
| **實作** | `tests/test_middleware.py::test_domain_handler_folder_not_found_404` |

## TC-middleware-06:domain ValidationError → 400

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-05 |
| **層級** | 單元 |
| **測試輸入** | `ValidationError(field="chunk_size", message="too small", value=1)` |
| **預期結果** | status 400;error="VALIDATION_ERROR";details={"field": "chunk_size", "invalid_value": "1"} |
| **實作** | `tests/test_middleware.py::test_domain_handler_validation_error_400` |

## TC-middleware-07:InvalidTokenError → 401 且無 details

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-06 |
| **層級** | 單元 |
| **測試輸入** | `InvalidTokenError()`(details 為空 dict) |
| **預期結果** | status 401;error="INVALID_TOKEN";body 不含 details 鍵 |
| **實作** | `tests/test_middleware.py::test_domain_handler_invalid_token_401_no_details` |

## TC-middleware-08:ConflictError → 409

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-05 |
| **層級** | 單元 |
| **測試輸入** | `ConflictError("already indexing", resource="folder-1")` |
| **預期結果** | status 409;error="CONFLICT" |
| **實作** | `tests/test_middleware.py::test_domain_handler_conflict_409` |

## TC-middleware-09:QueryExecutionError → 500

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-05 |
| **層級** | 單元 |
| **測試輸入** | `QueryExecutionError(query="q1", reason="vector store down", folder_id=3)` |
| **預期結果** | status 500;error="RAG_QUERY_ERROR";details={"query": "q1", "folder_id": 3} |
| **實作** | `tests/test_middleware.py::test_domain_handler_rag_query_error_500` |

## TC-middleware-10:未知 error_code fallback 500

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-07 |
| **層級** | 單元 |
| **測試輸入** | `DomainException(message="odd", error_code="SOMETHING_WEIRD")` |
| **預期結果** | `get_http_status_for_exception` 回 500;handler 回應 status 500 |
| **實作** | `tests/test_middleware.py::test_domain_handler_unknown_code_falls_back_500` |

## TC-middleware-11:FileIndexNotFoundError 映射 404

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-05 |
| **層級** | 單元 |
| **測試輸入** | `FileIndexNotFoundError(file_id="f-1")` |
| **預期結果** | `get_http_status_for_exception` 回 404(error_code=FILE_INDEX_NOT_FOUND) |
| **實作** | `tests/test_middleware.py::test_status_mapping_file_index_not_found_404` |

## TC-middleware-12:一般例外 → 500 不洩漏內部訊息

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-08 |
| **層級** | 單元 |
| **測試輸入** | `RuntimeError("secret db password leaked")`,path="/api/boom" |
| **預期結果** | status 500;error="INTERNAL_SERVER_ERROR";body 任何欄位皆不含 "secret" 字串 |
| **實作** | `tests/test_middleware.py::test_generic_handler_returns_500_without_leaking_internals` |

## TC-middleware-13:HTTPException 原樣 re-raise

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-middleware-09 |
| **層級** | 單元 |
| **測試輸入** | `HTTPException(status_code=404, detail="not found")` |
| **預期結果** | generic handler 拋出**同一個** HTTPException 實例(交還 FastAPI 原生 handler) |
| **實作** | `tests/test_middleware.py::test_generic_handler_reraises_http_exception` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
