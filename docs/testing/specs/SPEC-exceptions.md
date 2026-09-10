# SPEC-exceptions:Domain 例外階層與 HTTP 狀態映射


| 項目 | 內容 |
|------|------|
| 模組 | `src/domain/exceptions.py` |
| 對應測試 | `tests/test_exceptions.py` |
| 版本 | v1.0(feat/rag-robustness) |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

提供 domain 層統一的業務例外階層(`DomainException` 家族)與例外 → HTTP 狀態碼的純映射函式
`get_http_status_for_exception()`。此模組**不依賴** HTTP / FastAPI / DB,由 API error handler
middleware 捕捉並轉為 HTTP 回應。本 spec 只涵蓋純邏輯行為;middleware 的實際 HTTP 轉換屬整合測試範疇,不在此列。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-exceptions-01 | `DomainException` 保存 message / error_code / details;details 未給時預設空 dict;`str(exc)` 即 message;為標準 `Exception` 子類 | 建構後三屬性可讀且值正確;`str()` 回 message;`isinstance(exc, Exception)` 為 True |
| REQ-exceptions-02 | `to_dict()` 輸出 `{"error", "message"}`;details 非空時才附 `"details"` 鍵 | details 空 → dict 恰有 2 鍵;details 非空 → 3 鍵且內容一致 |
| REQ-exceptions-03 | `ResourceNotFoundError` 依 resource_type 自動組 message 與 `{TYPE}_NOT_FOUND` error_code,details 含 resource_type 與 str 化 identifier;可自訂 message | 給 `("folder", 42)` → message `"folder not found: 42"`、code `FOLDER_NOT_FOUND`、details identifier 為 `"42"`;有給 message 時採用自訂值 |
| REQ-exceptions-04 | `FolderNotFoundError` 以 folder_id 為優先 identifier,未給 id 時用 folder_name | 只給 id → identifier 為 id;只給 name → identifier 為 name |
| REQ-exceptions-05 | `FileNotFoundError`(domain 版)error_code 為 `FILE_NOT_FOUND`,identifier 為 file_id | 建構後 code / details 正確 |
| REQ-exceptions-06 | `FileIndexNotFoundError` error_code 為 `FILE_INDEX_NOT_FOUND`,message 為「尚未索引」語意 | message == `"File {id} has not been indexed yet"` |
| REQ-exceptions-07 | `UnauthorizedAccessError` code 為 `UNAUTHORIZED_ACCESS`;reason 有給時附加至 message 尾端 | 無 reason → `"Not authorized to access {type}: {id}"`;有 reason → 尾端 `" - {reason}"` |
| REQ-exceptions-08 | `InvalidTokenError` code 為 `INVALID_TOKEN`,reason 直接作為 message,預設 `"Invalid or expired token"` | 預設與自訂 reason 均反映於 message |
| REQ-exceptions-09 | `ValidationError` code 為 `VALIDATION_ERROR`,details 含 field;value 非 None 時另含 str 化 `invalid_value` | value 有給 → details 2 鍵;value 為 None → 僅 field 鍵 |
| REQ-exceptions-10 | `ConflictError` code 為 `CONFLICT`;resource 有給時進 details,未給時 details 為空 | 兩種建構方式 details 內容正確 |
| REQ-exceptions-11 | `RAGOperationError` 家族 error_code 為 `RAG_{OPERATION 大寫}_ERROR`;`FileIndexingError` details 含 file_id;`QueryExecutionError` details 含 query,folder_id 有給(且非 0)時才附 | 各子類 code / message / details 符合上述格式 |
| REQ-exceptions-12 | `get_http_status_for_exception()` 依 error_code 映射:VALIDATION_ERROR→400、INVALID_TOKEN→401、UNAUTHORIZED_ACCESS→403、三種 NOT_FOUND→404、CONFLICT→409、RAG_INDEXING/QUERY_ERROR→500;未知 code 一律 500 | 九個已知 code 各回對應值;任意未列 code 回 500 |
| REQ-exceptions-13 | 家族所有例外皆繼承 `DomainException`,可被單一 `except DomainException` 捕捉 | 每個具名例外 `isinstance(exc, DomainException)` 為 True |

## 3. 非功能需求 (Non-Functional)

- 模組不得 import HTTP / FastAPI / DB 相關套件(domain 層純淨性)。
- `to_dict()` 輸出必須可直接 JSON 序列化(identifier / invalid_value 均先 str 化)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| `DomainException(details=None)` | details 正規化為 `{}` |
| `ValidationError(value=None)` | details 不含 `invalid_value` |
| `ConflictError(resource=None)` | details 為 `{}` |
| `QueryExecutionError(folder_id=None)` | details 不含 `folder_id` |
| 未知 error_code 傳入 `get_http_status_for_exception` | 回 500(安全預設) |
| `FolderNotFoundError(folder_id=0)` | ⚠️ 已知實作限制:truthiness 判斷使 id=0 落到 folder_name(見 §5 備註) |

## 5. 相依與假設 (Dependencies & Assumptions)

- 無任何外部相依(純 Python stdlib),測試無需 mock。
- 備註 1:domain 的 `FileNotFoundError` 遮蔽 Python builtin 同名例外,測試中以
  `DomainFileNotFoundError` 別名匯入;呼叫端 import 時亦應留意。
- 備註 2:`FolderNotFoundError` 的 `folder_id if folder_id else folder_name` 與
  `QueryExecutionError` 的 `if folder_id:` 均為 truthiness 判斷,id=0 時行為與型別註記不符
  (疑似缺陷,已回報,不在本次測試斷言範圍)。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-exceptions-01 | TC-exceptions-01、TC-exceptions-02 | `tests/test_exceptions.py::test_domain_exception_attributes_and_default_details`、`::test_domain_exception_str_and_inheritance` |
| REQ-exceptions-02 | TC-exceptions-03、TC-exceptions-04 | `tests/test_exceptions.py::test_to_dict_without_details`、`::test_to_dict_with_details` |
| REQ-exceptions-03 | TC-exceptions-05、TC-exceptions-06 | `tests/test_exceptions.py::test_resource_not_found_default_message_and_code`、`::test_resource_not_found_custom_message` |
| REQ-exceptions-04 | TC-exceptions-07、TC-exceptions-08 | `tests/test_exceptions.py::test_folder_not_found_by_id`、`::test_folder_not_found_by_name` |
| REQ-exceptions-05 | TC-exceptions-09 | `tests/test_exceptions.py::test_file_not_found` |
| REQ-exceptions-06 | TC-exceptions-10 | `tests/test_exceptions.py::test_file_index_not_found` |
| REQ-exceptions-07 | TC-exceptions-11、TC-exceptions-12 | `tests/test_exceptions.py::test_unauthorized_without_reason`、`::test_unauthorized_with_reason` |
| REQ-exceptions-08 | TC-exceptions-13 | `tests/test_exceptions.py::test_invalid_token_default_and_custom_reason` |
| REQ-exceptions-09 | TC-exceptions-14、TC-exceptions-15 | `tests/test_exceptions.py::test_validation_error_with_value`、`::test_validation_error_without_value` |
| REQ-exceptions-10 | TC-exceptions-16、TC-exceptions-17 | `tests/test_exceptions.py::test_conflict_with_resource`、`::test_conflict_without_resource` |
| REQ-exceptions-11 | TC-exceptions-18 ~ TC-exceptions-21 | `tests/test_exceptions.py::test_rag_operation_error_code_from_operation`、`::test_file_indexing_error`、`::test_query_execution_error_with_folder`、`::test_query_execution_error_without_folder` |
| REQ-exceptions-12 | TC-exceptions-22、TC-exceptions-23 | `tests/test_exceptions.py::test_http_status_mapping`(參數化 9 組)、`::test_http_status_unknown_code_defaults_to_500` |
| REQ-exceptions-13 | TC-exceptions-24 | `tests/test_exceptions.py::test_all_exceptions_inherit_domain_exception` |
