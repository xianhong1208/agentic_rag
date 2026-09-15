# TC-adapter-models: Adapter-Layer DTO Models Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-adapter-models](../specs/SPEC-adapter-models.md) |
| Test level | Unit |
| Test script | `tests/test_adapter_models.py` |

---

## TC-adapter-01: FileConfigData type coercion

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-01 |
| **Level** | Unit |
| **Test input** | id as a UUID string; upload_time/updated_time as ISO strings |
| **Expected result** | id is a UUID object; upload_time is a datetime(year=2026) |
| **Implementation** | `tests/test_adapter_models.py::test_file_config_data_coercion` |

## TC-adapter-02: FileConfigData missing required fields

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-02 |
| **Level** | Unit |
| **Test input** | Only id and folder_id provided |
| **Expected result** | ValidationError; missing fields include file_name/file_path/file_size/upload_time/updated_time |
| **Implementation** | `tests/test_adapter_models.py::test_file_config_data_missing_required` |

## TC-adapter-03: FileConfigData optional fields default to None

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-03 |
| **Level** | Unit |
| **Test input** | Only required fields provided |
| **Expected result** | mime_type/description/tags are all None |
| **Implementation** | `tests/test_adapter_models.py::test_file_config_data_optional_defaults` |

## TC-adapter-04: FileDownloadData bytes content

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-04 |
| **Level** | Unit |
| **Test input** | `file_content=b"\x00\x01binary"` |
| **Expected result** | file_content is bytes and its value is unchanged |
| **Implementation** | `tests/test_adapter_models.py::test_file_download_data_bytes_content` |

## TC-adapter-05: FolderConfigData default values

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-05 |
| **Level** | Unit |
| **Test input** | Only id/name/created_at/updated_at provided |
| **Expected result** | file_count=0, total_size=0, user_token=None, description=None |
| **Implementation** | `tests/test_adapter_models.py::test_folder_config_data_defaults` |

## TC-adapter-06: RAGChunkMetadata optional folder_name

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-06 |
| **Level** | Unit |
| **Test input** | node_id (UUID string) / mcp_file_id / file_name |
| **Expected result** | Created successfully; node_id coerced to UUID; folder_name=None |
| **Implementation** | `tests/test_adapter_models.py::test_rag_chunk_metadata_optional_folder` |

## TC-adapter-07: RAGSearchResult nested assembly

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-07 |
| **Level** | Unit |
| **Test input** | metadata passed in as a dict |
| **Expected result** | metadata coerced to RAGChunkMetadata; score ~ 0.87 |
| **Implementation** | `tests/test_adapter_models.py::test_rag_search_result_nested_assembly` |

## TC-adapter-08: RAGQueryResult defaults and nested list

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-07 |
| **Level** | Unit |
| **Test input** | results passed in as a list of dicts; retrieval_time_ms omitted |
| **Expected result** | retrieval_time_ms=None; results[0] is a RAGSearchResult |
| **Implementation** | `tests/test_adapter_models.py::test_rag_query_result_defaults_and_list` |

## TC-adapter-09: FileIndexData JSON serialization

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-08 |
| **Level** | Unit |
| **Test input** | Full fields; `model_dump(mode="json")` |
| **Expected result** | file_id serialized as a UUID string; indexed_at serialized as an ISO string |
| **Implementation** | `tests/test_adapter_models.py::test_file_index_data_json_serialization` |

## TC-adapter-10: Non-numeric score is rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-adapter-09 |
| **Level** | Unit |
| **Test input** | `score="not-a-number"` |
| **Expected result** | ValidationError |
| **Implementation** | `tests/test_adapter_models.py::test_rag_search_result_invalid_score_type` |

> Authoring principle: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable**.
