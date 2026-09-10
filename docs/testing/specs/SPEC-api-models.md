# SPEC-api-models:API Request/Response 模型


| 項目 | 內容 |
|------|------|
| 模組 | `src/api/router/response.py`(27 個 models,本 SPEC 涵蓋代表性 15+ 個) |
| 對應測試 | `tests/test_api_models.py` |
| 版本 | 0.1.0 |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

定義 REST API 的 request/response Pydantic 模型。涵蓋:QueryRequest / IndexRequest 的預設值與邊界(retrieval 調參欄位允許 None,由 config 補預設)、檔案/資料夾 request models、index job 回應、`from_attributes=True` 的 ORM 形狀輸入(FolderResource / FileResource)、envelope 模型(QueryResponse 等)。
不負責:endpoint 邏輯、config 預設值的實際套用(API 層職責)。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-api-01 | QueryRequest 僅 query/folder_name 必填;4 個調參欄位(top_k/similarity_cutoff/sparse_top_k/hybrid_alpha)預設 None | 只給必填可建立;缺必填拋 ValidationError |
| REQ-api-02 | QueryRequest.top_k 限 1~20 | 邊界值合法,越界拋 ValidationError |
| REQ-api-03 | QueryRequest 浮點調參限 0.0~1.0 | 邊界值合法,越界拋 ValidationError |
| REQ-api-04 | IndexRequest 允許空 body(兩欄位預設 None,由 config 補值) | `IndexRequest()` 合法 |
| REQ-api-05 | IndexRequest.chunk_size 限 100~2000、chunk_overlap 限 0~500 | 邊界值合法,越界拋 ValidationError |
| REQ-api-06 | UpdateFileRequest / UpdateFolderRequest 全欄位選填;BatchDeleteRequest 預設 delete_all=False 且 file_ids 字串自動轉 UUID;CreateFolderRequest.name 必填 | 各模型行為可觀察 |
| REQ-api-07 | IndexDocumentResponse 六欄位全必填 | 缺欄位拋 ValidationError |
| REQ-api-08 | IndexJobStatusResponse 預設值:skip_existing=True、file_timings=[]、scope_file_ids=[]、選填欄位 None | 只給必填時預設值正確 |
| REQ-api-09 | FolderResource / FileResource 支援 `from_attributes=True`,可直接由 ORM 形狀物件建立 | `model_validate(物件)` 成功 |
| REQ-api-10 | FileResource JSON 序列化時 UUID→str、datetime→ISO 字串 | `model_dump(mode="json")` 輸出正確 |
| REQ-api-11 | envelope / health 模型:HealthStatusResponse 必填;IndexJobListResponse.jobs 預設空 list;QueryResponse 巢狀組裝(data.results 預設空);ErrorDetailResponse.detail 必填 | 各模型行為可觀察 |

## 3. 非功能需求 (Non-Functional)

- 調參欄位以 None 表示「用 config 預設」,避免 Pydantic 寫死值與 config 不同步(設計約束,由 REQ-api-01/04 覆蓋)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| top_k=0 / 21 | ValidationError |
| similarity_cutoff=1.1 / hybrid_alpha=-0.1 | ValidationError |
| chunk_size=99 / 2001;chunk_overlap=-1 / 501 | ValidationError |
| QueryRequest 空 body | ValidationError(缺 query、folder_name) |
| IndexRequest 空 body | 合法(全部走 config 預設) |

## 5. 相依與假設 (Dependencies & Assumptions)

- 僅依賴 Pydantic v2;ORM 形狀輸入以 `types.SimpleNamespace` 模擬,無 DB 依賴。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-api-01 | TC-api-01, TC-api-02 | `tests/test_api_models.py::test_query_request_defaults`、`::test_query_request_missing_required` |
| REQ-api-02 | TC-api-03 | `tests/test_api_models.py::test_query_request_top_k_bounds` |
| REQ-api-03 | TC-api-04 | `tests/test_api_models.py::test_query_request_float_bounds` |
| REQ-api-04 | TC-api-05 | `tests/test_api_models.py::test_index_request_empty_body_ok` |
| REQ-api-05 | TC-api-06, TC-api-07 | `tests/test_api_models.py::test_index_request_chunk_size_bounds`、`::test_index_request_chunk_overlap_bounds` |
| REQ-api-06 | TC-api-08, TC-api-09, TC-api-10 | `tests/test_api_models.py::test_update_requests_all_optional`、`::test_batch_delete_request_defaults_and_uuid_coercion`、`::test_create_folder_request_name_required` |
| REQ-api-07 | TC-api-11 | `tests/test_api_models.py::test_index_document_response_required` |
| REQ-api-08 | TC-api-12 | `tests/test_api_models.py::test_index_job_status_response_defaults` |
| REQ-api-09 | TC-api-13, TC-api-14 | `tests/test_api_models.py::test_folder_resource_from_orm_shape`、`::test_file_resource_from_orm_shape_and_json` |
| REQ-api-10 | TC-api-14 | `tests/test_api_models.py::test_file_resource_from_orm_shape_and_json` |
| REQ-api-11 | TC-api-15 ~ TC-api-18 | `tests/test_api_models.py::test_health_status_response_required`、`::test_index_job_list_response_default_empty_jobs`、`::test_query_response_nested_assembly`、`::test_error_detail_response_required` |
