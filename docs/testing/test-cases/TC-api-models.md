# TC-api-models: API Request/Response Models Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-api-models](../specs/SPEC-api-models.md) |
| Test level | Unit |
| Test script | `tests/test_api_models.py` |

---

## TC-api-01: QueryRequest tuning fields default to None

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-01 |
| **Level** | Unit |
| **Test input** | Only query and folder_name provided |
| **Expected result** | top_k/similarity_cutoff/sparse_top_k/hybrid_alpha are all None |
| **Implementation** | `tests/test_api_models.py::test_query_request_defaults` |

## TC-api-02: QueryRequest missing required fields

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-01 |
| **Level** | Unit |
| **Test input** | Empty body |
| **Expected result** | ValidationError; missing = {query, folder_name} |
| **Implementation** | `tests/test_api_models.py::test_query_request_missing_required` |

## TC-api-03: top_k bounds 1-20

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-02 |
| **Level** | Unit |
| **Test input** | top_k = 1, 20 (valid); 0, 21 (invalid) |
| **Expected result** | Boundary values succeed; out-of-range raises ValidationError |
| **Implementation** | `tests/test_api_models.py::test_query_request_top_k_bounds` |

## TC-api-04: Float tuning bounds 0.0-1.0

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-03 |
| **Level** | Unit |
| **Test input** | similarity_cutoff=0.0, hybrid_alpha=1.0 (valid); similarity_cutoff=1.1, hybrid_alpha=-0.1 (invalid) |
| **Expected result** | Boundary values succeed; out-of-range raises ValidationError |
| **Implementation** | `tests/test_api_models.py::test_query_request_float_bounds` |

## TC-api-05: IndexRequest empty body is valid

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-04 |
| **Level** | Unit |
| **Test input** | `IndexRequest()` |
| **Expected result** | Created successfully; chunk_size/chunk_overlap are None (defaulted from config instead) |
| **Implementation** | `tests/test_api_models.py::test_index_request_empty_body_ok` |

## TC-api-06: chunk_size bounds 100-2000

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-05 |
| **Level** | Unit |
| **Test input** | chunk_size = 100, 2000 (valid); 99, 2001 (invalid) |
| **Expected result** | Boundary values succeed; out-of-range raises ValidationError |
| **Implementation** | `tests/test_api_models.py::test_index_request_chunk_size_bounds` |

## TC-api-07: chunk_overlap bounds 0-500

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-05 |
| **Level** | Unit |
| **Test input** | chunk_overlap = 0, 500 (valid); -1, 501 (invalid) |
| **Expected result** | Boundary values succeed; out-of-range raises ValidationError |
| **Implementation** | `tests/test_api_models.py::test_index_request_chunk_overlap_bounds` |

## TC-api-08: Update requests fully optional

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-06 |
| **Level** | Unit |
| **Test input** | `UpdateFileRequest()`, `UpdateFolderRequest()` |
| **Expected result** | Created successfully with all fields None |
| **Implementation** | `tests/test_api_models.py::test_update_requests_all_optional` |

## TC-api-09: BatchDeleteRequest defaults and UUID coercion

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-06 |
| **Level** | Unit |
| **Test input** | (a) no arguments (b) `file_ids=[UUID string]` |
| **Expected result** | (a) delete_all=False, file_ids=None (b) strings coerced to UUID objects |
| **Implementation** | `tests/test_api_models.py::test_batch_delete_request_defaults_and_uuid_coercion` |

## TC-api-10: CreateFolderRequest name required

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-06 |
| **Level** | Unit |
| **Test input** | (a) `name="my-folder"` (b) only description provided |
| **Expected result** | (a) succeeds with description=None (b) ValidationError |
| **Implementation** | `tests/test_api_models.py::test_create_folder_request_name_required` |

## TC-api-11: IndexDocumentResponse required fields

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-07 |
| **Level** | Unit |
| **Test input** | (a) all six fields present (b) only file_id provided |
| **Expected result** | (a) succeeds (b) ValidationError |
| **Implementation** | `tests/test_api_models.py::test_index_document_response_required` |

## TC-api-12: IndexJobStatusResponse default values

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-08 |
| **Level** | Unit |
| **Test input** | Only required fields provided (job_id/folder_id/status/total_files/processed_files/current_index/started_at) |
| **Expected result** | skip_existing=True, file_timings=[], scope_file_ids=[], completed_at=None, result_summary=None |
| **Implementation** | `tests/test_api_models.py::test_index_job_status_response_defaults` |

## TC-api-13: FolderResource built from an ORM shape

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-09 |
| **Level** | Unit |
| **Test input** | `SimpleNamespace` (simulated ORM row with datetime fields) |
| **Expected result** | `model_validate` succeeds; field values match the input |
| **Implementation** | `tests/test_api_models.py::test_folder_resource_from_orm_shape` |

## TC-api-14: FileResource ORM input and JSON serialization

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-09, REQ-api-10 |
| **Level** | Unit |
| **Test input** | `SimpleNamespace` (id as UUID, times as datetime); `model_dump(mode="json")` |
| **Expected result** | Created successfully; JSON output has id as a UUID string and upload_time as "2026-01-02T03:04:05" |
| **Implementation** | `tests/test_api_models.py::test_file_resource_from_orm_shape_and_json` |

## TC-api-15: HealthStatusResponse required fields

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-11 |
| **Level** | Unit |
| **Test input** | (a) status+timestamp (b) only status provided |
| **Expected result** | (a) succeeds (b) ValidationError |
| **Implementation** | `tests/test_api_models.py::test_health_status_response_required` |

## TC-api-16: IndexJobListResponse jobs default to empty

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-11 |
| **Level** | Unit |
| **Test input** | (a) only counts provided (b) empty body |
| **Expected result** | (a) jobs == [] (b) ValidationError (counts required) |
| **Implementation** | `tests/test_api_models.py::test_index_job_list_response_default_empty_jobs` |

## TC-api-17: QueryResponse nested assembly

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-11 |
| **Level** | Unit |
| **Test input** | `data={"query": "q", "total_results": 0}` + message |
| **Expected result** | data.results defaults to []; data.retrieval_time_ms=None |
| **Implementation** | `tests/test_api_models.py::test_query_response_nested_assembly` |

## TC-api-18: ErrorDetailResponse detail required

| Field | Content |
|-------|---------|
| **Requirement** | REQ-api-11 |
| **Level** | Unit |
| **Test input** | (a) `detail="folder not found"` (b) empty body |
| **Expected result** | (a) succeeds (b) ValidationError |
| **Implementation** | `tests/test_api_models.py::test_error_detail_response_required` |

> Authoring principle: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
