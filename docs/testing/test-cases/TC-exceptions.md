# TC-exceptions: Domain Exception Hierarchy and HTTP Status Mapping Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-exceptions](../specs/SPEC-exceptions.md) |
| Test level | Unit |
| Test script | `tests/test_exceptions.py` |

> All cases are pure logic, with no preconditions and no mocks. Run: `cd agentic_rag && uv run pytest tests/test_exceptions.py -v`

---

## TC-exceptions-01: DomainException attribute storage and default details

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `DomainException(message="something broke", error_code="SOME_CODE")` |
| **Test steps** | 1. Construct the exception<br>2. Read message / error_code / details |
| **Expected result** | `message == "something broke"`, `error_code == "SOME_CODE"`, `details == {}` |
| **Implementation** | `tests/test_exceptions.py::test_domain_exception_attributes_and_default_details` |

## TC-exceptions-02: DomainException str() and Exception inheritance

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `DomainException(message="msg here", error_code="X")` |
| **Test steps** | 1. Construct the exception<br>2. Get `str(exc)`<br>3. Check isinstance |
| **Expected result** | `str(exc) == "msg here"`; `isinstance(exc, Exception)` is True |
| **Implementation** | `tests/test_exceptions.py::test_domain_exception_str_and_inheritance` |

## TC-exceptions-03: to_dict — without details

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `DomainException(message="m", error_code="CODE")` |
| **Test steps** | 1. Construct the exception<br>2. Call `to_dict()` |
| **Expected result** | Returns exactly `{"error": "CODE", "message": "m"}` (no details key) |
| **Implementation** | `tests/test_exceptions.py::test_to_dict_without_details` |

## TC-exceptions-04: to_dict — with details

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `DomainException(message="m", error_code="CODE", details={"k": "v"})` |
| **Test steps** | 1. Construct the exception<br>2. Call `to_dict()` |
| **Expected result** | Returns `{"error": "CODE", "message": "m", "details": {"k": "v"}}` |
| **Implementation** | `tests/test_exceptions.py::test_to_dict_with_details` |

## TC-exceptions-05: ResourceNotFoundError default message / code / details

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ResourceNotFoundError(resource_type="folder", identifier=42)` |
| **Test steps** | 1. Construct the exception<br>2. Check the three attributes |
| **Expected result** | `message == "folder not found: 42"`, `error_code == "FOLDER_NOT_FOUND"`, `details == {"resource_type": "folder", "identifier": "42"}` |
| **Implementation** | `tests/test_exceptions.py::test_resource_not_found_default_message_and_code` |

## TC-exceptions-06: ResourceNotFoundError custom message

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ResourceNotFoundError("file", "abc", message="custom words")` |
| **Test steps** | 1. Construct the exception<br>2. Check message and code |
| **Expected result** | `message == "custom words"` (overrides the default); `error_code == "FILE_NOT_FOUND"` |
| **Implementation** | `tests/test_exceptions.py::test_resource_not_found_custom_message` |

## TC-exceptions-07: FolderNotFoundError constructed by folder_id

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `FolderNotFoundError(folder_id=7)` |
| **Test steps** | 1. Construct the exception<br>2. Check code and details |
| **Expected result** | `error_code == "FOLDER_NOT_FOUND"`; `details["identifier"] == "7"` |
| **Implementation** | `tests/test_exceptions.py::test_folder_not_found_by_id` |

## TC-exceptions-08: FolderNotFoundError constructed by folder_name

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `FolderNotFoundError(folder_name="財報")` |
| **Test steps** | 1. Construct the exception<br>2. Check identifier and message |
| **Expected result** | `details["identifier"] == "財報"`; message contains `"財報"` |
| **Implementation** | `tests/test_exceptions.py::test_folder_not_found_by_name` |

## TC-exceptions-09: FileNotFoundError (domain version)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `FileNotFoundError(file_id="f-123")` (imported in the test under the alias `DomainFileNotFoundError`) |
| **Test steps** | 1. Construct the exception<br>2. Check code and details |
| **Expected result** | `error_code == "FILE_NOT_FOUND"`; `details == {"resource_type": "file", "identifier": "f-123"}` |
| **Implementation** | `tests/test_exceptions.py::test_file_not_found` |

## TC-exceptions-10: FileIndexNotFoundError

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-06 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `FileIndexNotFoundError(file_id="f-9")` |
| **Test steps** | 1. Construct the exception<br>2. Check code / message / identifier |
| **Expected result** | `error_code == "FILE_INDEX_NOT_FOUND"`; `message == "File f-9 has not been indexed yet"`; `details["identifier"] == "f-9"` |
| **Implementation** | `tests/test_exceptions.py::test_file_index_not_found` |

## TC-exceptions-11: UnauthorizedAccessError — without reason

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `UnauthorizedAccessError(resource_type="folder", resource_id=5)` |
| **Test steps** | 1. Construct the exception<br>2. Check code / message / details |
| **Expected result** | `error_code == "UNAUTHORIZED_ACCESS"`; `message == "Not authorized to access folder: 5"`; `details == {"resource_type": "folder", "resource_id": "5"}` |
| **Implementation** | `tests/test_exceptions.py::test_unauthorized_without_reason` |

## TC-exceptions-12: UnauthorizedAccessError — with reason

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-07 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `UnauthorizedAccessError("file", "x", reason="not owner")` |
| **Test steps** | 1. Construct the exception<br>2. Check message |
| **Expected result** | `message == "Not authorized to access file: x - not owner"` |
| **Implementation** | `tests/test_exceptions.py::test_unauthorized_with_reason` |

## TC-exceptions-13: InvalidTokenError — default and custom reason

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-08 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `InvalidTokenError()` and `InvalidTokenError(reason="token revoked")` |
| **Test steps** | 1. Construct each<br>2. Check code and message |
| **Expected result** | code is `INVALID_TOKEN` for both; default message `"Invalid or expired token"`; when custom, `"token revoked"` |
| **Implementation** | `tests/test_exceptions.py::test_invalid_token_default_and_custom_reason` |

## TC-exceptions-14: ValidationError — with value

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ValidationError(field="top_k", message="must be positive", value=-3)` |
| **Test steps** | 1. Construct the exception<br>2. Check code / message / details |
| **Expected result** | `error_code == "VALIDATION_ERROR"`; `message == "Validation failed for top_k: must be positive"`; `details == {"field": "top_k", "invalid_value": "-3"}` |
| **Implementation** | `tests/test_exceptions.py::test_validation_error_with_value` |

## TC-exceptions-15: ValidationError — without value

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-09 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ValidationError(field="query", message="empty")` |
| **Test steps** | 1. Construct the exception<br>2. Check details |
| **Expected result** | `details == {"field": "query"}`; no `invalid_value` key |
| **Implementation** | `tests/test_exceptions.py::test_validation_error_without_value` |

## TC-exceptions-16: ConflictError — with resource

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-10 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ConflictError(message="already indexing", resource="file f-1")` |
| **Test steps** | 1. Construct the exception<br>2. Check code and details |
| **Expected result** | `error_code == "CONFLICT"`; `details == {"resource": "file f-1"}` |
| **Implementation** | `tests/test_exceptions.py::test_conflict_with_resource` |

## TC-exceptions-17: ConflictError — without resource

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-10 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `ConflictError(message="state conflict")` |
| **Test steps** | 1. Construct the exception<br>2. Check details |
| **Expected result** | `details == {}` |
| **Implementation** | `tests/test_exceptions.py::test_conflict_without_resource` |

## TC-exceptions-18: RAGOperationError — error_code composition rule

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-11 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `RAGOperationError(operation="indexing", reason="disk full")` |
| **Test steps** | 1. Construct the exception<br>2. Check code / message / details |
| **Expected result** | `error_code == "RAG_INDEXING_ERROR"`; `message == "RAG indexing failed: disk full"`; `details == {}` |
| **Implementation** | `tests/test_exceptions.py::test_rag_operation_error_code_from_operation` |

## TC-exceptions-19: FileIndexingError

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-11 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `FileIndexingError(file_id="f-7", reason="parse failed")` |
| **Test steps** | 1. Construct the exception<br>2. Check code / details / message |
| **Expected result** | `error_code == "RAG_INDEXING_ERROR"`; `details == {"file_id": "f-7"}`; message contains `"parse failed"` |
| **Implementation** | `tests/test_exceptions.py::test_file_indexing_error` |

## TC-exceptions-20: QueryExecutionError — with folder_id

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-11 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `QueryExecutionError(query="財報重點", reason="timeout", folder_id=3)` |
| **Test steps** | 1. Construct the exception<br>2. Check code and details |
| **Expected result** | `error_code == "RAG_QUERY_ERROR"`; `details == {"query": "財報重點", "folder_id": 3}` |
| **Implementation** | `tests/test_exceptions.py::test_query_execution_error_with_folder` |

## TC-exceptions-21: QueryExecutionError — without folder_id

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-11 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `QueryExecutionError(query="q", reason="r")` |
| **Test steps** | 1. Construct the exception<br>2. Check details |
| **Expected result** | `details == {"query": "q"}`; no `folder_id` key |
| **Implementation** | `tests/test_exceptions.py::test_query_execution_error_without_folder` |

## TC-exceptions-22: get_http_status_for_exception — known code mapping (9 parametrized cases)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-12 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | One instance each of ValidationError / InvalidTokenError / UnauthorizedAccessError / FolderNotFoundError / FileNotFoundError / FileIndexNotFoundError / ConflictError / FileIndexingError / QueryExecutionError |
| **Test steps** | 1. Construct the nine exceptions in order<br>2. Pass each to `get_http_status_for_exception()` |
| **Expected result** | Returns 400 / 401 / 403 / 404 / 404 / 404 / 409 / 500 / 500 respectively |
| **Implementation** | `tests/test_exceptions.py::test_http_status_mapping` (pytest.mark.parametrize, 9 cases) |

## TC-exceptions-23: get_http_status_for_exception — unknown code defaults to 500

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-12 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `DomainException("m", "TOTALLY_UNKNOWN")` and `RAGOperationError("embedding", "r")` (which produces the unlisted `RAG_EMBEDDING_ERROR`) |
| **Test steps** | 1. Construct the two unknown-code exceptions<br>2. Pass them to the mapping function |
| **Expected result** | Both return 500 |
| **Implementation** | `tests/test_exceptions.py::test_http_status_unknown_code_defaults_to_500` |

## TC-exceptions-24: the whole family inherits DomainException

| Field | Content |
|-------|---------|
| **Requirement** | REQ-exceptions-13 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | One instance each of the 11 named exceptions in the module |
| **Test steps** | 1. Construct all named exceptions<br>2. Check isinstance one by one |
| **Expected result** | For every instance, `isinstance(exc, DomainException)` is True |
| **Implementation** | `tests/test_exceptions.py::test_all_exceptions_inherit_domain_exception` |

> Authoring principles: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
