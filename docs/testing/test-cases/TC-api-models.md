# TC-api-models:API Request/Response 模型 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-api-models](../specs/SPEC-api-models.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_api_models.py` |

---

## TC-api-01:QueryRequest 調參欄位預設 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-01 |
| **層級** | 單元 |
| **測試輸入** | 只給 query 與 folder_name |
| **預期結果** | top_k/similarity_cutoff/sparse_top_k/hybrid_alpha 皆為 None |
| **實作** | `tests/test_api_models.py::test_query_request_defaults` |

## TC-api-02:QueryRequest 缺必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-01 |
| **層級** | 單元 |
| **測試輸入** | 空 body |
| **預期結果** | ValidationError,缺漏 = {query, folder_name} |
| **實作** | `tests/test_api_models.py::test_query_request_missing_required` |

## TC-api-03:top_k 邊界 1~20

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-02 |
| **層級** | 單元 |
| **測試輸入** | top_k = 1、20(合法);0、21(非法) |
| **預期結果** | 邊界值建立成功;越界拋 ValidationError |
| **實作** | `tests/test_api_models.py::test_query_request_top_k_bounds` |

## TC-api-04:浮點調參邊界 0.0~1.0

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-03 |
| **層級** | 單元 |
| **測試輸入** | similarity_cutoff=0.0、hybrid_alpha=1.0(合法);similarity_cutoff=1.1、hybrid_alpha=-0.1(非法) |
| **預期結果** | 邊界值建立成功;越界拋 ValidationError |
| **實作** | `tests/test_api_models.py::test_query_request_float_bounds` |

## TC-api-05:IndexRequest 空 body 合法

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-04 |
| **層級** | 單元 |
| **測試輸入** | `IndexRequest()` |
| **預期結果** | 建立成功;chunk_size/chunk_overlap 皆為 None(改由 config 預設) |
| **實作** | `tests/test_api_models.py::test_index_request_empty_body_ok` |

## TC-api-06:chunk_size 邊界 100~2000

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-05 |
| **層級** | 單元 |
| **測試輸入** | chunk_size = 100、2000(合法);99、2001(非法) |
| **預期結果** | 邊界值建立成功;越界拋 ValidationError |
| **實作** | `tests/test_api_models.py::test_index_request_chunk_size_bounds` |

## TC-api-07:chunk_overlap 邊界 0~500

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-05 |
| **層級** | 單元 |
| **測試輸入** | chunk_overlap = 0、500(合法);-1、501(非法) |
| **預期結果** | 邊界值建立成功;越界拋 ValidationError |
| **實作** | `tests/test_api_models.py::test_index_request_chunk_overlap_bounds` |

## TC-api-08:Update requests 全選填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-06 |
| **層級** | 單元 |
| **測試輸入** | `UpdateFileRequest()`、`UpdateFolderRequest()` |
| **預期結果** | 建立成功且全欄位 None |
| **實作** | `tests/test_api_models.py::test_update_requests_all_optional` |

## TC-api-09:BatchDeleteRequest 預設與 UUID 轉型

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-06 |
| **層級** | 單元 |
| **測試輸入** | (a) 無參數 (b) `file_ids=[UUID字串]` |
| **預期結果** | (a) delete_all=False、file_ids=None (b) 字串轉為 UUID 物件 |
| **實作** | `tests/test_api_models.py::test_batch_delete_request_defaults_and_uuid_coercion` |

## TC-api-10:CreateFolderRequest name 必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-06 |
| **層級** | 單元 |
| **測試輸入** | (a) `name="my-folder"` (b) 只給 description |
| **預期結果** | (a) 成功且 description=None (b) ValidationError |
| **實作** | `tests/test_api_models.py::test_create_folder_request_name_required` |

## TC-api-11:IndexDocumentResponse 必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-07 |
| **層級** | 單元 |
| **測試輸入** | (a) 六欄位齊全 (b) 只給 file_id |
| **預期結果** | (a) 成功 (b) ValidationError |
| **實作** | `tests/test_api_models.py::test_index_document_response_required` |

## TC-api-12:IndexJobStatusResponse 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-08 |
| **層級** | 單元 |
| **測試輸入** | 只給必填(job_id/folder_id/status/total_files/processed_files/current_index/started_at) |
| **預期結果** | skip_existing=True、file_timings=[]、scope_file_ids=[]、completed_at=None、result_summary=None |
| **實作** | `tests/test_api_models.py::test_index_job_status_response_defaults` |

## TC-api-13:FolderResource 從 ORM 形狀建立

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-09 |
| **層級** | 單元 |
| **測試輸入** | `SimpleNamespace`(模擬 ORM row,含 datetime 欄位) |
| **預期結果** | `model_validate` 成功;欄位值與輸入一致 |
| **實作** | `tests/test_api_models.py::test_folder_resource_from_orm_shape` |

## TC-api-14:FileResource ORM 輸入與 JSON 序列化

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-09、REQ-api-10 |
| **層級** | 單元 |
| **測試輸入** | `SimpleNamespace`(id 為 UUID、時間為 datetime);`model_dump(mode="json")` |
| **預期結果** | 建立成功;json 輸出 id 為 UUID 字串、upload_time 為 "2026-01-02T03:04:05" |
| **實作** | `tests/test_api_models.py::test_file_resource_from_orm_shape_and_json` |

## TC-api-15:HealthStatusResponse 必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-11 |
| **層級** | 單元 |
| **測試輸入** | (a) status+timestamp (b) 只給 status |
| **預期結果** | (a) 成功 (b) ValidationError |
| **實作** | `tests/test_api_models.py::test_health_status_response_required` |

## TC-api-16:IndexJobListResponse jobs 預設空

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-11 |
| **層級** | 單元 |
| **測試輸入** | (a) 只給 counts (b) 空 body |
| **預期結果** | (a) jobs == [] (b) ValidationError(counts 必填) |
| **實作** | `tests/test_api_models.py::test_index_job_list_response_default_empty_jobs` |

## TC-api-17:QueryResponse 巢狀組裝

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-11 |
| **層級** | 單元 |
| **測試輸入** | `data={"query": "q", "total_results": 0}` + message |
| **預期結果** | data.results 預設 [];data.retrieval_time_ms=None |
| **實作** | `tests/test_api_models.py::test_query_response_nested_assembly` |

## TC-api-18:ErrorDetailResponse detail 必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-api-11 |
| **層級** | 單元 |
| **測試輸入** | (a) `detail="folder not found"` (b) 空 body |
| **預期結果** | (a) 成功 (b) ValidationError |
| **實作** | `tests/test_api_models.py::test_error_detail_response_required` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
