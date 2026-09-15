# SPEC-middleware: Request ID Middleware and Error Handling


| Item | Content |
|------|---------|
| Module | `src/middleware/request_id.py`, `src/middleware/error_handler.py` (with `src/domain/exceptions.py`) |
| Test | `tests/test_middleware.py` |
| Version | 0.1.0 |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

`request_id.py`: a pure ASGI middleware that generates a short request_id (first 8 characters of a UUID) for each HTTP request and injects it into a contextvar, so logs across the full call chain can be correlated.
`error_handler.py`: FastAPI exception handlers. `domain_exception_handler` maps a DomainException to an HTTP response via `get_http_status_for_exception`; `generic_exception_handler` is the catch-all (re-raises HTTPException, returns 500 for everything else).
Not responsible for: log-sink configuration or the definition of DomainException (which belongs to the domain layer).

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|-------------|-------------|-------------------------------------------|
| REQ-middleware-01 | On an http-scope request, generate a new request_id (8 chars) and write it to the contextvar; downstream can read it | Inside the downstream app, `get_request_id()` returns an 8-char string other than "-" |
| REQ-middleware-02 | request_id is unique per http request | Two consecutive requests have different ids |
| REQ-middleware-03 | Non-http scopes (e.g. lifespan) do not generate a new id | The contextvar retains its original value |
| REQ-middleware-04 | Middleware passes scope/receive/send through to the downstream app | The downstream receives the same objects |
| REQ-middleware-05 | DomainException maps to the corresponding HTTP status (400/401/403/404/409/500) with the unified body structure `{error, message, timestamp, path[, details]}` | Each exception type responds correctly |
| REQ-middleware-06 | When `details` is an empty dict, the body omits the details key | InvalidTokenError response has no details |
| REQ-middleware-07 | A DomainException with an unknown error_code falls back to 500 | status_code=500 |
| REQ-middleware-08 | A generic exception maps to 500 + `INTERNAL_SERVER_ERROR` without leaking internal error messages | The body contains no original exception string |
| REQ-middleware-09 | The generic handler re-raises HTTPException as-is, rather than swallowing it into a 500 | The same HTTPException instance is raised |

## 3. Non-Functional Requirements

- A 500 response must not expose tracebacks or internal error details to the client (REQ-middleware-08).
- request_id injection must not depend on FastAPI; it must work over the pure ASGI interface.

## 4. Edge Cases and Errors

| Scenario | Expected behavior |
|----------|-------------------|
| scope["type"] == "lifespan" / "websocket" | No request_id generated; pass through directly |
| DomainException.details is empty | Body has no details key |
| error_code not in the status mapping table | 500 |
| generic handler receives an HTTPException | Re-raise |

## 5. Dependencies and Assumptions

- The error handler reads only `request.url.path`; tests substitute the Request with a fake object `SimpleNamespace(url=SimpleNamespace(path=...))`.
- ASGI scope/receive/send are simulated with minimal fake objects; no real server is started.
- HTTP status mapping follows `src/domain/exceptions.py::get_http_status_for_exception`.

## 6. Traceability

| Requirement | Test Case | Test Script |
|-------------|-----------|-------------|
| REQ-middleware-01 | TC-middleware-01 | `tests/test_middleware.py::test_request_id_set_for_http_scope` |
| REQ-middleware-02 | TC-middleware-02 | `tests/test_middleware.py::test_request_id_unique_per_request` |
| REQ-middleware-03 | TC-middleware-03 | `tests/test_middleware.py::test_request_id_not_set_for_non_http_scope` |
| REQ-middleware-04 | TC-middleware-04 | `tests/test_middleware.py::test_middleware_passes_through_asgi_args` |
| REQ-middleware-05 | TC-middleware-05, TC-middleware-06, TC-middleware-08, TC-middleware-09, TC-middleware-11 | `tests/test_middleware.py::test_domain_handler_folder_not_found_404`, `::test_domain_handler_validation_error_400`, `::test_domain_handler_conflict_409`, `::test_domain_handler_rag_query_error_500`, `::test_status_mapping_file_index_not_found_404` |
| REQ-middleware-06 | TC-middleware-07 | `tests/test_middleware.py::test_domain_handler_invalid_token_401_no_details` |
| REQ-middleware-07 | TC-middleware-10 | `tests/test_middleware.py::test_domain_handler_unknown_code_falls_back_500` |
| REQ-middleware-08 | TC-middleware-12 | `tests/test_middleware.py::test_generic_handler_returns_500_without_leaking_internals` |
| REQ-middleware-09 | TC-middleware-13 | `tests/test_middleware.py::test_generic_handler_reraises_http_exception` |
