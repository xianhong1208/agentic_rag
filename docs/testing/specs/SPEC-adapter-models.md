# SPEC-adapter-models:Adapter 層 DTO 模型


| 項目 | 內容 |
|------|------|
| 模組 | `src/adapter/model.py` |
| 對應測試 | `tests/test_adapter_models.py` |
| 版本 | 0.1.0 |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

定義 adapter 層 7 個 Pydantic DTO:FileConfigData、FileDownloadData、FolderConfigData、RAGChunkMetadata、RAGSearchResult、RAGQueryResult、FileIndexData。
負責:型別驗證與強制轉換(UUID/datetime/bytes)、預設值、巢狀組裝與 JSON 序列化。不含任何業務邏輯與 DB 存取。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-adapter-01 | FileConfigData 接受字串形式的 UUID / ISO datetime 並自動轉型 | `id` 為 UUID 物件、`upload_time` 為 datetime |
| REQ-adapter-02 | FileConfigData 必填欄位缺漏時拒絕建立 | ValidationError 列出全部缺漏欄位 |
| REQ-adapter-03 | FileConfigData 選填欄位(mime_type/description/tags)預設 None | 未給時皆為 None |
| REQ-adapter-04 | FileDownloadData 攜帶 bytes 型別的檔案內容 | `file_content` 為 bytes 且值不變 |
| REQ-adapter-05 | FolderConfigData 統計欄位有預設值(file_count=0、total_size=0、user_token=None) | 未給時預設值正確 |
| REQ-adapter-06 | RAGChunkMetadata 的 folder_name 選填,其餘必填 | 只給必填可建立,folder_name 為 None |
| REQ-adapter-07 | RAGSearchResult / RAGQueryResult 支援巢狀 dict 組裝;retrieval_time_ms 預設 None | 巢狀 dict 轉為對應子模型 |
| REQ-adapter-08 | FileIndexData JSON 序列化時 UUID→str、datetime→ISO 字串 | `model_dump(mode="json")` 輸出字串形式 |
| REQ-adapter-09 | 型別不符的輸入(如 score 給非數字)拒絕 | ValidationError |

## 3. 非功能需求 (Non-Functional)

無(純資料模型;不涉及安全與效能要求)。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| UUID 欄位給非法字串 | ValidationError(由 Pydantic UUID 驗證涵蓋;代表案例見 REQ-adapter-01 反向) |
| score 給無法轉 float 的字串 | ValidationError |
| 必填欄位缺漏 | ValidationError |

## 5. 相依與假設 (Dependencies & Assumptions)

- 僅依賴 Pydantic v2;無 DB / 網路 / mock 需求。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-adapter-01 | TC-adapter-01 | `tests/test_adapter_models.py::test_file_config_data_coercion` |
| REQ-adapter-02 | TC-adapter-02 | `tests/test_adapter_models.py::test_file_config_data_missing_required` |
| REQ-adapter-03 | TC-adapter-03 | `tests/test_adapter_models.py::test_file_config_data_optional_defaults` |
| REQ-adapter-04 | TC-adapter-04 | `tests/test_adapter_models.py::test_file_download_data_bytes_content` |
| REQ-adapter-05 | TC-adapter-05 | `tests/test_adapter_models.py::test_folder_config_data_defaults` |
| REQ-adapter-06 | TC-adapter-06 | `tests/test_adapter_models.py::test_rag_chunk_metadata_optional_folder` |
| REQ-adapter-07 | TC-adapter-07, TC-adapter-08 | `tests/test_adapter_models.py::test_rag_search_result_nested_assembly`、`::test_rag_query_result_defaults_and_list` |
| REQ-adapter-08 | TC-adapter-09 | `tests/test_adapter_models.py::test_file_index_data_json_serialization` |
| REQ-adapter-09 | TC-adapter-10 | `tests/test_adapter_models.py::test_rag_search_result_invalid_score_type` |
