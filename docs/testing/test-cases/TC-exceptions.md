# TC-exceptions:Domain 例外階層與 HTTP 狀態映射 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-exceptions](../specs/SPEC-exceptions.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_exceptions.py` |

> 全部案例皆為純邏輯,無前置條件、無 mock。跑法:`cd agentic_rag && uv run pytest tests/test_exceptions.py -v`

---

## TC-exceptions-01:DomainException 屬性保存與 details 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `DomainException(message="something broke", error_code="SOME_CODE")` |
| **測試步驟** | 1. 建構例外<br>2. 讀取 message / error_code / details |
| **預期結果** | `message == "something broke"`、`error_code == "SOME_CODE"`、`details == {}` |
| **實作** | `tests/test_exceptions.py::test_domain_exception_attributes_and_default_details` |

## TC-exceptions-02:DomainException str() 與 Exception 繼承

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `DomainException(message="msg here", error_code="X")` |
| **測試步驟** | 1. 建構例外<br>2. 取 `str(exc)`<br>3. 檢查 isinstance |
| **預期結果** | `str(exc) == "msg here"`;`isinstance(exc, Exception)` 為 True |
| **實作** | `tests/test_exceptions.py::test_domain_exception_str_and_inheritance` |

## TC-exceptions-03:to_dict — 無 details

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `DomainException(message="m", error_code="CODE")` |
| **測試步驟** | 1. 建構例外<br>2. 呼叫 `to_dict()` |
| **預期結果** | 回傳恰為 `{"error": "CODE", "message": "m"}`(不含 details 鍵) |
| **實作** | `tests/test_exceptions.py::test_to_dict_without_details` |

## TC-exceptions-04:to_dict — 有 details

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `DomainException(message="m", error_code="CODE", details={"k": "v"})` |
| **測試步驟** | 1. 建構例外<br>2. 呼叫 `to_dict()` |
| **預期結果** | 回傳 `{"error": "CODE", "message": "m", "details": {"k": "v"}}` |
| **實作** | `tests/test_exceptions.py::test_to_dict_with_details` |

## TC-exceptions-05:ResourceNotFoundError 預設 message / code / details

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ResourceNotFoundError(resource_type="folder", identifier=42)` |
| **測試步驟** | 1. 建構例外<br>2. 檢查三屬性 |
| **預期結果** | `message == "folder not found: 42"`、`error_code == "FOLDER_NOT_FOUND"`、`details == {"resource_type": "folder", "identifier": "42"}` |
| **實作** | `tests/test_exceptions.py::test_resource_not_found_default_message_and_code` |

## TC-exceptions-06:ResourceNotFoundError 自訂 message

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ResourceNotFoundError("file", "abc", message="custom words")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 message 與 code |
| **預期結果** | `message == "custom words"`(覆蓋預設);`error_code == "FILE_NOT_FOUND"` |
| **實作** | `tests/test_exceptions.py::test_resource_not_found_custom_message` |

## TC-exceptions-07:FolderNotFoundError 以 folder_id 建立

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `FolderNotFoundError(folder_id=7)` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code 與 details |
| **預期結果** | `error_code == "FOLDER_NOT_FOUND"`;`details["identifier"] == "7"` |
| **實作** | `tests/test_exceptions.py::test_folder_not_found_by_id` |

## TC-exceptions-08:FolderNotFoundError 以 folder_name 建立

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `FolderNotFoundError(folder_name="財報")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 identifier 與 message |
| **預期結果** | `details["identifier"] == "財報"`;message 含 `"財報"` |
| **實作** | `tests/test_exceptions.py::test_folder_not_found_by_name` |

## TC-exceptions-09:FileNotFoundError(domain 版)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `FileNotFoundError(file_id="f-123")`(測試中以 `DomainFileNotFoundError` 別名匯入) |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code 與 details |
| **預期結果** | `error_code == "FILE_NOT_FOUND"`;`details == {"resource_type": "file", "identifier": "f-123"}` |
| **實作** | `tests/test_exceptions.py::test_file_not_found` |

## TC-exceptions-10:FileIndexNotFoundError

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-06 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `FileIndexNotFoundError(file_id="f-9")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code / message / identifier |
| **預期結果** | `error_code == "FILE_INDEX_NOT_FOUND"`;`message == "File f-9 has not been indexed yet"`;`details["identifier"] == "f-9"` |
| **實作** | `tests/test_exceptions.py::test_file_index_not_found` |

## TC-exceptions-11:UnauthorizedAccessError — 無 reason

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `UnauthorizedAccessError(resource_type="folder", resource_id=5)` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code / message / details |
| **預期結果** | `error_code == "UNAUTHORIZED_ACCESS"`;`message == "Not authorized to access folder: 5"`;`details == {"resource_type": "folder", "resource_id": "5"}` |
| **實作** | `tests/test_exceptions.py::test_unauthorized_without_reason` |

## TC-exceptions-12:UnauthorizedAccessError — 有 reason

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-07 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `UnauthorizedAccessError("file", "x", reason="not owner")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 message |
| **預期結果** | `message == "Not authorized to access file: x - not owner"` |
| **實作** | `tests/test_exceptions.py::test_unauthorized_with_reason` |

## TC-exceptions-13:InvalidTokenError — 預設與自訂 reason

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-08 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `InvalidTokenError()` 與 `InvalidTokenError(reason="token revoked")` |
| **測試步驟** | 1. 分別建構<br>2. 檢查 code 與 message |
| **預期結果** | code 均為 `INVALID_TOKEN`;預設 message `"Invalid or expired token"`;自訂時為 `"token revoked"` |
| **實作** | `tests/test_exceptions.py::test_invalid_token_default_and_custom_reason` |

## TC-exceptions-14:ValidationError — 有 value

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ValidationError(field="top_k", message="must be positive", value=-3)` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code / message / details |
| **預期結果** | `error_code == "VALIDATION_ERROR"`;`message == "Validation failed for top_k: must be positive"`;`details == {"field": "top_k", "invalid_value": "-3"}` |
| **實作** | `tests/test_exceptions.py::test_validation_error_with_value` |

## TC-exceptions-15:ValidationError — 無 value

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-09 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ValidationError(field="query", message="empty")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 details |
| **預期結果** | `details == {"field": "query"}`;不含 `invalid_value` 鍵 |
| **實作** | `tests/test_exceptions.py::test_validation_error_without_value` |

## TC-exceptions-16:ConflictError — 有 resource

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-10 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ConflictError(message="already indexing", resource="file f-1")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code 與 details |
| **預期結果** | `error_code == "CONFLICT"`;`details == {"resource": "file f-1"}` |
| **實作** | `tests/test_exceptions.py::test_conflict_with_resource` |

## TC-exceptions-17:ConflictError — 無 resource

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-10 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `ConflictError(message="state conflict")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 details |
| **預期結果** | `details == {}` |
| **實作** | `tests/test_exceptions.py::test_conflict_without_resource` |

## TC-exceptions-18:RAGOperationError — error_code 組合規則

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-11 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `RAGOperationError(operation="indexing", reason="disk full")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code / message / details |
| **預期結果** | `error_code == "RAG_INDEXING_ERROR"`;`message == "RAG indexing failed: disk full"`;`details == {}` |
| **實作** | `tests/test_exceptions.py::test_rag_operation_error_code_from_operation` |

## TC-exceptions-19:FileIndexingError

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-11 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `FileIndexingError(file_id="f-7", reason="parse failed")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code / details / message |
| **預期結果** | `error_code == "RAG_INDEXING_ERROR"`;`details == {"file_id": "f-7"}`;message 含 `"parse failed"` |
| **實作** | `tests/test_exceptions.py::test_file_indexing_error` |

## TC-exceptions-20:QueryExecutionError — 有 folder_id

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-11 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `QueryExecutionError(query="財報重點", reason="timeout", folder_id=3)` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 code 與 details |
| **預期結果** | `error_code == "RAG_QUERY_ERROR"`;`details == {"query": "財報重點", "folder_id": 3}` |
| **實作** | `tests/test_exceptions.py::test_query_execution_error_with_folder` |

## TC-exceptions-21:QueryExecutionError — 無 folder_id

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-11 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `QueryExecutionError(query="q", reason="r")` |
| **測試步驟** | 1. 建構例外<br>2. 檢查 details |
| **預期結果** | `details == {"query": "q"}`;不含 `folder_id` 鍵 |
| **實作** | `tests/test_exceptions.py::test_query_execution_error_without_folder` |

## TC-exceptions-22:get_http_status_for_exception — 已知 code 映射(參數化 9 組)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-12 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | ValidationError / InvalidTokenError / UnauthorizedAccessError / FolderNotFoundError / FileNotFoundError / FileIndexNotFoundError / ConflictError / FileIndexingError / QueryExecutionError 各一實例 |
| **測試步驟** | 1. 依序建構九種例外<br>2. 各自傳入 `get_http_status_for_exception()` |
| **預期結果** | 依序回 400 / 401 / 403 / 404 / 404 / 404 / 409 / 500 / 500 |
| **實作** | `tests/test_exceptions.py::test_http_status_mapping`(pytest.mark.parametrize 9 組) |

## TC-exceptions-23:get_http_status_for_exception — 未知 code 預設 500

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-12 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `DomainException("m", "TOTALLY_UNKNOWN")` 與 `RAGOperationError("embedding", "r")`(產生未列表的 `RAG_EMBEDDING_ERROR`) |
| **測試步驟** | 1. 建構兩個未知 code 例外<br>2. 傳入映射函式 |
| **預期結果** | 兩者皆回 500 |
| **實作** | `tests/test_exceptions.py::test_http_status_unknown_code_defaults_to_500` |

## TC-exceptions-24:全家族繼承 DomainException

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-exceptions-13 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | 模組內 11 個具名例外各一實例 |
| **測試步驟** | 1. 建構全部具名例外<br>2. 逐一檢查 isinstance |
| **預期結果** | 每個實例 `isinstance(exc, DomainException)` 均為 True |
| **實作** | `tests/test_exceptions.py::test_all_exceptions_inherit_domain_exception` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
