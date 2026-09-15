# SPEC-adapter-models: Adapter-Layer DTO Models


| Item | Content |
|------|------|
| Module | `src/adapter/model.py` |
| Test | `tests/test_adapter_models.py` |
| Version | 0.1.0 |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Defines the 7 adapter-layer Pydantic DTOs: FileConfigData, FileDownloadData, FolderConfigData, RAGChunkMetadata, RAGSearchResult, RAGQueryResult, FileIndexData.
Responsible for: type validation and coercion (UUID/datetime/bytes), default values, nested assembly, and JSON serialization. Contains no business logic and no DB access.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-adapter-01 | FileConfigData accepts string-form UUID / ISO datetime and coerces automatically | `id` is a UUID object; `upload_time` is a datetime |
| REQ-adapter-02 | FileConfigData rejects construction when required fields are missing | ValidationError lists every missing field |
| REQ-adapter-03 | FileConfigData optional fields (mime_type/description/tags) default to None | Omitted fields are all None |
| REQ-adapter-04 | FileDownloadData carries file content as bytes | `file_content` is bytes and its value is unchanged |
| REQ-adapter-05 | FolderConfigData statistics fields have defaults (file_count=0, total_size=0, user_token=None) | Defaults are correct when omitted |
| REQ-adapter-06 | RAGChunkMetadata.folder_name is optional; all other fields required | Constructing with only required fields succeeds and folder_name is None |
| REQ-adapter-07 | RAGSearchResult / RAGQueryResult support nested dict assembly; retrieval_time_ms defaults to None | Nested dicts are converted into the corresponding submodels |
| REQ-adapter-08 | FileIndexData JSON serialization renders UUID→str and datetime→ISO string | `model_dump(mode="json")` outputs string forms |
| REQ-adapter-09 | Type-mismatched input (e.g. a non-numeric score) is rejected | ValidationError |

## 3. Non-Functional Requirements

None (pure data models; no security or performance requirements).

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| UUID field given an illegal string | ValidationError (covered by Pydantic UUID validation; representative case is the inverse of REQ-adapter-01) |
| score given a string that cannot be coerced to float | ValidationError |
| Required field missing | ValidationError |

## 5. Dependencies & Assumptions

- Depends only on Pydantic v2; no DB / network / mock requirements.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-adapter-01 | TC-adapter-01 | `tests/test_adapter_models.py::test_file_config_data_coercion` |
| REQ-adapter-02 | TC-adapter-02 | `tests/test_adapter_models.py::test_file_config_data_missing_required` |
| REQ-adapter-03 | TC-adapter-03 | `tests/test_adapter_models.py::test_file_config_data_optional_defaults` |
| REQ-adapter-04 | TC-adapter-04 | `tests/test_adapter_models.py::test_file_download_data_bytes_content` |
| REQ-adapter-05 | TC-adapter-05 | `tests/test_adapter_models.py::test_folder_config_data_defaults` |
| REQ-adapter-06 | TC-adapter-06 | `tests/test_adapter_models.py::test_rag_chunk_metadata_optional_folder` |
| REQ-adapter-07 | TC-adapter-07, TC-adapter-08 | `tests/test_adapter_models.py::test_rag_search_result_nested_assembly`, `::test_rag_query_result_defaults_and_list` |
| REQ-adapter-08 | TC-adapter-09 | `tests/test_adapter_models.py::test_file_index_data_json_serialization` |
| REQ-adapter-09 | TC-adapter-10 | `tests/test_adapter_models.py::test_rag_search_result_invalid_score_type` |
