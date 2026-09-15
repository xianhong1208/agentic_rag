# SPEC-exceptions: Domain Exception Hierarchy and HTTP Status Mapping


| Item | Content |
|------|------|
| Module | `src/domain/exceptions.py` |
| Test | `tests/test_exceptions.py` |
| Version | v1.0 (feat/rag-robustness) |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Provides the domain layer's unified business-exception hierarchy (the `DomainException` family) and the pure exception-to-HTTP-status mapping function
`get_http_status_for_exception()`. This module **has no dependency** on HTTP / FastAPI / DB; the API error-handler
middleware catches these exceptions and converts them into HTTP responses. This spec covers only the pure logic; the middleware's actual HTTP conversion belongs to integration testing and is out of scope.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-exceptions-01 | `DomainException` stores message / error_code / details; details defaults to an empty dict when omitted; `str(exc)` is the message; it subclasses the standard `Exception` | The three attributes are readable and correct after construction; `str()` returns the message; `isinstance(exc, Exception)` is True |
| REQ-exceptions-02 | `to_dict()` outputs `{"error", "message"}`; the `"details"` key is added only when details is non-empty | empty details → dict has exactly 2 keys; non-empty details → 3 keys with matching content |
| REQ-exceptions-03 | `ResourceNotFoundError` auto-composes the message and a `{TYPE}_NOT_FOUND` error_code from resource_type, with details containing resource_type and the str-ified identifier; message can be overridden | `("folder", 42)` → message `"folder not found: 42"`, code `FOLDER_NOT_FOUND`, details identifier `"42"`; a provided message overrides the default |
| REQ-exceptions-04 | `FolderNotFoundError` prefers folder_id as the identifier, using folder_name when no id is given | id only → identifier is id; name only → identifier is name |
| REQ-exceptions-05 | `FileNotFoundError` (domain version) has error_code `FILE_NOT_FOUND` and identifier file_id | code / details are correct after construction |
| REQ-exceptions-06 | `FileIndexNotFoundError` has error_code `FILE_INDEX_NOT_FOUND` and a "not yet indexed" message | message == `"File {id} has not been indexed yet"` |
| REQ-exceptions-07 | `UnauthorizedAccessError` has code `UNAUTHORIZED_ACCESS`; when reason is given it is appended to the message | no reason → `"Not authorized to access {type}: {id}"`; with reason → trailing `" - {reason}"` |
| REQ-exceptions-08 | `InvalidTokenError` has code `INVALID_TOKEN` and uses reason directly as the message, defaulting to `"Invalid or expired token"` | both the default and a custom reason are reflected in the message |
| REQ-exceptions-09 | `ValidationError` has code `VALIDATION_ERROR` and details containing field; when value is not None it additionally contains the str-ified `invalid_value` | value given → details has 2 keys; value None → only the field key |
| REQ-exceptions-10 | `ConflictError` has code `CONFLICT`; resource, when given, goes into details, otherwise details is empty | details content is correct for both construction paths |
| REQ-exceptions-11 | The `RAGOperationError` family has error_code `RAG_{OPERATION uppercased}_ERROR`; `FileIndexingError` details contains file_id; `QueryExecutionError` details contains query, and folder_id is appended only when given (and non-zero) | each subclass's code / message / details match the above format |
| REQ-exceptions-12 | `get_http_status_for_exception()` maps by error_code: VALIDATION_ERROR→400, INVALID_TOKEN→401, UNAUTHORIZED_ACCESS→403, the three NOT_FOUND→404, CONFLICT→409, RAG_INDEXING/QUERY_ERROR→500; any unknown code → 500 | each of the nine known codes returns its mapped value; any unlisted code returns 500 |
| REQ-exceptions-13 | Every exception in the family inherits `DomainException` and can be caught by a single `except DomainException` | `isinstance(exc, DomainException)` is True for each named exception |

## 3. Non-Functional Requirements

- The module must not import HTTP / FastAPI / DB packages (domain-layer purity).
- `to_dict()` output must be directly JSON-serializable (identifier / invalid_value are str-ified first).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| `DomainException(details=None)` | details normalized to `{}` |
| `ValidationError(value=None)` | details excludes `invalid_value` |
| `ConflictError(resource=None)` | details is `{}` |
| `QueryExecutionError(folder_id=None)` | details excludes `folder_id` |
| unknown error_code passed to `get_http_status_for_exception` | returns 500 (safe default) |
| `FolderNotFoundError(folder_id=0)` | ⚠️ known implementation limitation: the truthiness check makes id=0 fall through to folder_name (see the §5 note) |

## 5. Dependencies & Assumptions

- No external dependency (pure Python stdlib); tests need no mocks.
- Note 1: the domain `FileNotFoundError` shadows the Python builtin of the same name; tests import it aliased as
  `DomainFileNotFoundError`, and callers should be mindful of this on import.
- Note 2: `FolderNotFoundError`'s `folder_id if folder_id else folder_name` and
  `QueryExecutionError`'s `if folder_id:` are both truthiness checks, so id=0 behaves inconsistently with the type annotation
  (a likely defect, already reported, not within the scope of these test assertions).

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-exceptions-01 | TC-exceptions-01, TC-exceptions-02 | `tests/test_exceptions.py::test_domain_exception_attributes_and_default_details`, `::test_domain_exception_str_and_inheritance` |
| REQ-exceptions-02 | TC-exceptions-03, TC-exceptions-04 | `tests/test_exceptions.py::test_to_dict_without_details`, `::test_to_dict_with_details` |
| REQ-exceptions-03 | TC-exceptions-05, TC-exceptions-06 | `tests/test_exceptions.py::test_resource_not_found_default_message_and_code`, `::test_resource_not_found_custom_message` |
| REQ-exceptions-04 | TC-exceptions-07, TC-exceptions-08 | `tests/test_exceptions.py::test_folder_not_found_by_id`, `::test_folder_not_found_by_name` |
| REQ-exceptions-05 | TC-exceptions-09 | `tests/test_exceptions.py::test_file_not_found` |
| REQ-exceptions-06 | TC-exceptions-10 | `tests/test_exceptions.py::test_file_index_not_found` |
| REQ-exceptions-07 | TC-exceptions-11, TC-exceptions-12 | `tests/test_exceptions.py::test_unauthorized_without_reason`, `::test_unauthorized_with_reason` |
| REQ-exceptions-08 | TC-exceptions-13 | `tests/test_exceptions.py::test_invalid_token_default_and_custom_reason` |
| REQ-exceptions-09 | TC-exceptions-14, TC-exceptions-15 | `tests/test_exceptions.py::test_validation_error_with_value`, `::test_validation_error_without_value` |
| REQ-exceptions-10 | TC-exceptions-16, TC-exceptions-17 | `tests/test_exceptions.py::test_conflict_with_resource`, `::test_conflict_without_resource` |
| REQ-exceptions-11 | TC-exceptions-18 ~ TC-exceptions-21 | `tests/test_exceptions.py::test_rag_operation_error_code_from_operation`, `::test_file_indexing_error`, `::test_query_execution_error_with_folder`, `::test_query_execution_error_without_folder` |
| REQ-exceptions-12 | TC-exceptions-22, TC-exceptions-23 | `tests/test_exceptions.py::test_http_status_mapping` (parametrized, 9 groups), `::test_http_status_unknown_code_defaults_to_500` |
| REQ-exceptions-13 | TC-exceptions-24 | `tests/test_exceptions.py::test_all_exceptions_inherit_domain_exception` |
