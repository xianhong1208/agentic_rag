# SPEC-api-models: API Request/Response Models


| Item | Content |
|------|------|
| Module | `src/api/router/response.py` (27 models; this SPEC covers a representative 15+) |
| Test | `tests/test_api_models.py` |
| Version | 0.1.0 |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Defines the request/response Pydantic models for the REST API. Covers: defaults and bounds for QueryRequest / IndexRequest (retrieval-tuning fields allow None, with defaults supplied by config), file/folder request models, index-job responses, ORM-shaped input via `from_attributes=True` (FolderResource / FileResource), and envelope models (QueryResponse and others).
Out of scope: endpoint logic and the actual application of config defaults (an API-layer responsibility).

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-api-01 | QueryRequest requires only query/folder_name; the 4 tuning fields (top_k/similarity_cutoff/sparse_top_k/hybrid_alpha) default to None | Constructing with only required fields succeeds; missing required fields raise ValidationError |
| REQ-api-02 | QueryRequest.top_k is limited to 1–20 | Boundary values are valid; out-of-range raises ValidationError |
| REQ-api-03 | QueryRequest float tuning fields are limited to 0.0–1.0 | Boundary values are valid; out-of-range raises ValidationError |
| REQ-api-04 | IndexRequest allows an empty body (both fields default to None, filled by config) | `IndexRequest()` is valid |
| REQ-api-05 | IndexRequest.chunk_size is limited to 100–2000; chunk_overlap to 0–500 | Boundary values are valid; out-of-range raises ValidationError |
| REQ-api-06 | UpdateFileRequest / UpdateFolderRequest have all fields optional; BatchDeleteRequest defaults delete_all=False and coerces file_ids strings to UUID; CreateFolderRequest.name is required | Each model's behavior is observable |
| REQ-api-07 | IndexDocumentResponse requires all six fields | Missing a field raises ValidationError |
| REQ-api-08 | IndexJobStatusResponse defaults: skip_existing=True, file_timings=[], scope_file_ids=[], optional fields None | Defaults are correct when only required fields are given |
| REQ-api-09 | FolderResource / FileResource support `from_attributes=True` and can be built directly from ORM-shaped objects | `model_validate(obj)` succeeds |
| REQ-api-10 | FileResource JSON serialization renders UUID→str and datetime→ISO string | `model_dump(mode="json")` output is correct |
| REQ-api-11 | Envelope / health models: HealthStatusResponse required; IndexJobListResponse.jobs defaults to empty list; QueryResponse nested assembly (data.results defaults to empty); ErrorDetailResponse.detail required | Each model's behavior is observable |

## 3. Non-Functional Requirements

- Tuning fields use None to mean "use the config default", avoiding hard-coded Pydantic values that drift out of sync with config (a design constraint, covered by REQ-api-01/04).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| top_k=0 / 21 | ValidationError |
| similarity_cutoff=1.1 / hybrid_alpha=-0.1 | ValidationError |
| chunk_size=99 / 2001; chunk_overlap=-1 / 501 | ValidationError |
| QueryRequest empty body | ValidationError (missing query, folder_name) |
| IndexRequest empty body | Valid (everything falls back to config defaults) |

## 5. Dependencies & Assumptions

- Depends only on Pydantic v2; ORM-shaped input is simulated with `types.SimpleNamespace`, no DB dependency.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-api-01 | TC-api-01, TC-api-02 | `tests/test_api_models.py::test_query_request_defaults`, `::test_query_request_missing_required` |
| REQ-api-02 | TC-api-03 | `tests/test_api_models.py::test_query_request_top_k_bounds` |
| REQ-api-03 | TC-api-04 | `tests/test_api_models.py::test_query_request_float_bounds` |
| REQ-api-04 | TC-api-05 | `tests/test_api_models.py::test_index_request_empty_body_ok` |
| REQ-api-05 | TC-api-06, TC-api-07 | `tests/test_api_models.py::test_index_request_chunk_size_bounds`, `::test_index_request_chunk_overlap_bounds` |
| REQ-api-06 | TC-api-08, TC-api-09, TC-api-10 | `tests/test_api_models.py::test_update_requests_all_optional`, `::test_batch_delete_request_defaults_and_uuid_coercion`, `::test_create_folder_request_name_required` |
| REQ-api-07 | TC-api-11 | `tests/test_api_models.py::test_index_document_response_required` |
| REQ-api-08 | TC-api-12 | `tests/test_api_models.py::test_index_job_status_response_defaults` |
| REQ-api-09 | TC-api-13, TC-api-14 | `tests/test_api_models.py::test_folder_resource_from_orm_shape`, `::test_file_resource_from_orm_shape_and_json` |
| REQ-api-10 | TC-api-14 | `tests/test_api_models.py::test_file_resource_from_orm_shape_and_json` |
| REQ-api-11 | TC-api-15 ~ TC-api-18 | `tests/test_api_models.py::test_health_status_response_required`, `::test_index_job_list_response_default_empty_jobs`, `::test_query_response_nested_assembly`, `::test_error_detail_response_required` |
