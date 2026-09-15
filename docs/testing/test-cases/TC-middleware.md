# TC-middleware: Request ID Middleware and Error Handling Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-middleware](../specs/SPEC-middleware.md) |
| Test level | Unit |
| Test script | `tests/test_middleware.py` |

Shared precondition: the ASGI scope/receive/send and the FastAPI Request are all fake objects (`SimpleNamespace`); no server is started and there is no dependency on DB / network.

---

## TC-middleware-01: http scope injects request_id

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-01 |
| **Level** | Unit |
| **Test input** | `scope={"type": "http", "path": "/x"}` |
| **Test steps** | 1. Wrap a fake app that records `get_request_id()` with RequestIdMiddleware<br>2. await middleware(scope, receive, send) |
| **Expected result** | The rid read inside the fake app != "-" and has length 8 |
| **Implementation** | `tests/test_middleware.py::test_request_id_set_for_http_scope` |

## TC-middleware-02: request_id unique per request

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-02 |
| **Level** | Unit |
| **Test steps** | Call the middleware twice in a row, recording both rids |
| **Expected result** | The two rids differ |
| **Implementation** | `tests/test_middleware.py::test_request_id_unique_per_request` |

## TC-middleware-03: non-http scope does not generate a new id

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-03 |
| **Level** | Unit |
| **Preconditions** | First `set_request_id("sentinel1")` |
| **Test input** | `scope={"type": "lifespan"}` |
| **Expected result** | The fake app reads rid == "sentinel1" (not overwritten) |
| **Implementation** | `tests/test_middleware.py::test_request_id_not_set_for_non_http_scope` |

## TC-middleware-04: pass ASGI arguments through

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-04 |
| **Level** | Unit |
| **Expected result** | The (scope, receive, send) received by the downstream app are the same objects that were passed in |
| **Implementation** | `tests/test_middleware.py::test_middleware_passes_through_asgi_args` |

## TC-middleware-05: FolderNotFoundError -> 404 with a full body

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-05 |
| **Level** | Unit |
| **Test input** | `FolderNotFoundError(folder_id=99)`, path="/api/folders/99" |
| **Expected result** | status 404; body.error="FOLDER_NOT_FOUND"; message contains "99"; path correct; timestamp present; details={"resource_type": "folder", "identifier": "99"} |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_folder_not_found_404` |

## TC-middleware-06: domain ValidationError -> 400

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-05 |
| **Level** | Unit |
| **Test input** | `ValidationError(field="chunk_size", message="too small", value=1)` |
| **Expected result** | status 400; error="VALIDATION_ERROR"; details={"field": "chunk_size", "invalid_value": "1"} |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_validation_error_400` |

## TC-middleware-07: InvalidTokenError -> 401 with no details

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-06 |
| **Level** | Unit |
| **Test input** | `InvalidTokenError()` (details is an empty dict) |
| **Expected result** | status 401; error="INVALID_TOKEN"; body has no details key |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_invalid_token_401_no_details` |

## TC-middleware-08: ConflictError -> 409

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-05 |
| **Level** | Unit |
| **Test input** | `ConflictError("already indexing", resource="folder-1")` |
| **Expected result** | status 409; error="CONFLICT" |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_conflict_409` |

## TC-middleware-09: QueryExecutionError -> 500

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-05 |
| **Level** | Unit |
| **Test input** | `QueryExecutionError(query="q1", reason="vector store down", folder_id=3)` |
| **Expected result** | status 500; error="RAG_QUERY_ERROR"; details={"query": "q1", "folder_id": 3} |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_rag_query_error_500` |

## TC-middleware-10: unknown error_code falls back to 500

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-07 |
| **Level** | Unit |
| **Test input** | `DomainException(message="odd", error_code="SOMETHING_WEIRD")` |
| **Expected result** | `get_http_status_for_exception` returns 500; the handler responds with status 500 |
| **Implementation** | `tests/test_middleware.py::test_domain_handler_unknown_code_falls_back_500` |

## TC-middleware-11: FileIndexNotFoundError maps to 404

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-05 |
| **Level** | Unit |
| **Test input** | `FileIndexNotFoundError(file_id="f-1")` |
| **Expected result** | `get_http_status_for_exception` returns 404 (error_code=FILE_INDEX_NOT_FOUND) |
| **Implementation** | `tests/test_middleware.py::test_status_mapping_file_index_not_found_404` |

## TC-middleware-12: generic exception -> 500 without leaking internal messages

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-08 |
| **Level** | Unit |
| **Test input** | `RuntimeError("secret db password leaked")`, path="/api/boom" |
| **Expected result** | status 500; error="INTERNAL_SERVER_ERROR"; no field in the body contains the string "secret" |
| **Implementation** | `tests/test_middleware.py::test_generic_handler_returns_500_without_leaking_internals` |

## TC-middleware-13: HTTPException re-raised as-is

| Field | Content |
|-------|---------|
| **Requirement** | REQ-middleware-09 |
| **Level** | Unit |
| **Test input** | `HTTPException(status_code=404, detail="not found")` |
| **Expected result** | The generic handler raises the **same** HTTPException instance (handing it back to FastAPI's native handler) |
| **Implementation** | `tests/test_middleware.py::test_generic_handler_reraises_http_exception` |

> Authoring principle: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
