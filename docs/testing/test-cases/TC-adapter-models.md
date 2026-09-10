# TC-adapter-models:Adapter 層 DTO 模型 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-adapter-models](../specs/SPEC-adapter-models.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_adapter_models.py` |

---

## TC-adapter-01:FileConfigData 型別強制轉換

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-01 |
| **層級** | 單元 |
| **測試輸入** | id 給 UUID 字串、upload_time/updated_time 給 ISO 字串 |
| **預期結果** | id 為 UUID 物件;upload_time 為 datetime(year=2026) |
| **實作** | `tests/test_adapter_models.py::test_file_config_data_coercion` |

## TC-adapter-02:FileConfigData 缺必填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-02 |
| **層級** | 單元 |
| **測試輸入** | 只給 id 與 folder_id |
| **預期結果** | ValidationError,缺漏含 file_name/file_path/file_size/upload_time/updated_time |
| **實作** | `tests/test_adapter_models.py::test_file_config_data_missing_required` |

## TC-adapter-03:FileConfigData 選填預設 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-03 |
| **層級** | 單元 |
| **測試輸入** | 只給必填欄位 |
| **預期結果** | mime_type/description/tags 皆為 None |
| **實作** | `tests/test_adapter_models.py::test_file_config_data_optional_defaults` |

## TC-adapter-04:FileDownloadData bytes 內容

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-04 |
| **層級** | 單元 |
| **測試輸入** | `file_content=b"\x00\x01binary"` |
| **預期結果** | file_content 為 bytes 且值不變 |
| **實作** | `tests/test_adapter_models.py::test_file_download_data_bytes_content` |

## TC-adapter-05:FolderConfigData 預設值

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-05 |
| **層級** | 單元 |
| **測試輸入** | 只給 id/name/created_at/updated_at |
| **預期結果** | file_count=0、total_size=0、user_token=None、description=None |
| **實作** | `tests/test_adapter_models.py::test_folder_config_data_defaults` |

## TC-adapter-06:RAGChunkMetadata folder_name 選填

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-06 |
| **層級** | 單元 |
| **測試輸入** | node_id(UUID 字串)/mcp_file_id/file_name |
| **預期結果** | 建立成功;node_id 轉為 UUID;folder_name=None |
| **實作** | `tests/test_adapter_models.py::test_rag_chunk_metadata_optional_folder` |

## TC-adapter-07:RAGSearchResult 巢狀組裝

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-07 |
| **層級** | 單元 |
| **測試輸入** | metadata 以 dict 傳入 |
| **預期結果** | metadata 轉為 RAGChunkMetadata;score ≈ 0.87 |
| **實作** | `tests/test_adapter_models.py::test_rag_search_result_nested_assembly` |

## TC-adapter-08:RAGQueryResult 預設與巢狀 list

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-07 |
| **層級** | 單元 |
| **測試輸入** | results 以 dict list 傳入,不給 retrieval_time_ms |
| **預期結果** | retrieval_time_ms=None;results[0] 為 RAGSearchResult |
| **實作** | `tests/test_adapter_models.py::test_rag_query_result_defaults_and_list` |

## TC-adapter-09:FileIndexData JSON 序列化

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-08 |
| **層級** | 單元 |
| **測試輸入** | 完整欄位;`model_dump(mode="json")` |
| **預期結果** | file_id 輸出為 UUID 字串;indexed_at 輸出為 ISO 字串 |
| **實作** | `tests/test_adapter_models.py::test_file_index_data_json_serialization` |

## TC-adapter-10:score 非數字被拒

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-adapter-09 |
| **層級** | 單元 |
| **測試輸入** | `score="not-a-number"` |
| **預期結果** | ValidationError |
| **實作** | `tests/test_adapter_models.py::test_rag_search_result_invalid_score_type` |

> 撰寫原則:一個案例只驗證一件事;正常路徑與例外路徑分開;預期結果必須是**可觀察、可判定**的。
