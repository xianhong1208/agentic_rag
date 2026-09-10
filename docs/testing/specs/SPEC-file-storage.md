# SPEC-file-storage:文件存儲管理


| 項目 | 內容 |
|------|------|
| 模組 | `src/storage/file_storage.py` |
| 對應測試 | `tests/test_file_storage.py` |
| 版本 | feat/rag-robustness |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

管理上傳文件在檔案系統中的存放,結構為 `storage/{user_token}/{folder_name}/{file_id}`。涵蓋:

- `_resolve_storage_root()`:決定 storage 根目錄(env override → `resolve_base_dir`)。
- `_validate_safe_name(name, kind)`:名稱白名單驗證,防 path traversal。
- `FileStorage`:save / read / delete / delete_folder / rename_folder / resolve_path。

不負責:檔案內容解析、DB metadata、權限控管(由上層 API / ACL 處理)。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-file-storage-01 | 合法名稱通過驗證 | 英數 / `_` / `-` / `.` / 空格 / 中文組成的名稱不拋例外 |
| REQ-file-storage-02 | 空值 / 非字串拒絕 | `""`、`None`、非 `str` 型別一律 `ValueError` |
| REQ-file-storage-03 | Path traversal 拒絕 | 含 `..`、`/`、`\`,或開頭為 `.` 的名稱一律 `ValueError` |
| REQ-file-storage-04 | 白名單外字元拒絕 | `* ? $ : \|`、控制字元、emoji 等一律 `ValueError` |
| REQ-file-storage-05 | env 顯式覆寫 storage root | 設定 `MIRAG_STORAGE_ROOT` 時 `_resolve_storage_root()` 回該路徑(resolve 後) |
| REQ-file-storage-06 | 預設 storage root | 未設 env 時回 `resolve_base_dir(dev_root=專案根)`(dev 模式即專案根目錄) |
| REQ-file-storage-07 | save_file 寫入並回相對路徑 | 檔案落在 `STORAGE_ROOT/{token}/{folder}/{file_id}`,回傳 `storage/{token}/{folder}/{file_id}` |
| REQ-file-storage-08 | save_file 失敗包裝 IOError | 任何內部錯誤(含名稱驗證的 ValueError)包裝為 `IOError` 拋出 |
| REQ-file-storage-09 | read_file 讀回內容 | 以 save_file 回傳的相對路徑讀回一模一樣的 bytes |
| REQ-file-storage-10 | read_file 不存在拋 FileNotFoundError | 路徑不存在時拋 `FileNotFoundError`(不吞為 IOError) |
| REQ-file-storage-11 | delete_file 回布林 | 成功刪除回 `True` 且檔案消失;檔案不存在回 `False` 不拋錯 |
| REQ-file-storage-12 | delete_folder 遞迴刪除 | 成功回 `True` 整夾消失;不存在回 `False`;非法名稱直接拋 `ValueError` |
| REQ-file-storage-13 | rename_folder 安全改名 | 成功回 `True`;來源不存在回 `False`;目標已存在回 `False` 且不覆蓋 |
| REQ-file-storage-14 | resolve_path 解析 DB 路徑 | 相對路徑接在 `STORAGE_FILE_ROOT` 下;絕對路徑依 `Path` 語意原樣回傳 |

## 3. 非功能需求

- 安全:名稱驗證為第一道防線,任何跨出 `STORAGE_ROOT` 的路徑組合必須被擋下(REQ-03/04/08/12)。
- 日誌不得輸出完整 user_token(僅前 8 碼)— 屬觀察性需求,不在單元測試強制驗證。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| 名稱為 `""` / `None` / `123` | `ValueError`(cannot be empty) |
| 名稱含 `..`、`/`、`\`、開頭 `.` | `ValueError`(illegal path characters) |
| 名稱含白名單外字元(emoji、`*` 等) | `ValueError`(illegal characters) |
| save_file 收到非法 folder_name | `IOError`(內部 ValueError 被統一包裝) |
| read_file 路徑不存在 | `FileNotFoundError` |
| delete_file 路徑不存在 | 回 `False` |
| rename_folder 目標已存在 | 回 `False`,來源與目標皆不變動 |

## 5. 相依與假設 (Dependencies & Assumptions)

- 模組 **import 時** 即執行 `_resolve_storage_root()` 決定 `FileStorage.STORAGE_ROOT` /
  `STORAGE_FILE_ROOT` class attribute;因此測試不重載模組,改以
  `monkeypatch.setattr(FileStorage, "STORAGE_ROOT"/"STORAGE_FILE_ROOT", tmp_path…)`
  把所有檔案操作導向 pytest `tmp_path`。
- `_resolve_storage_root()` 本身以 `monkeypatch.setenv/delenv("MIRAG_STORAGE_ROOT")` 直接呼叫測試。
- 依賴 `src.log`(loguru)與 `src.utils.runtime_paths`,皆無外部服務需求,不需 mock。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-file-storage-01 | TC-file-storage-01 | `tests/test_file_storage.py::test_validate_safe_name_accepts_legal_names` |
| REQ-file-storage-02 | TC-file-storage-02, TC-file-storage-03 | `::test_validate_safe_name_rejects_empty_string`、`::test_validate_safe_name_rejects_non_string` |
| REQ-file-storage-03 | TC-file-storage-04, TC-file-storage-05, TC-file-storage-06 | `::test_validate_safe_name_rejects_dotdot_traversal`、`::test_validate_safe_name_rejects_path_separators`、`::test_validate_safe_name_rejects_leading_dot` |
| REQ-file-storage-04 | TC-file-storage-07 | `::test_validate_safe_name_rejects_special_characters` |
| REQ-file-storage-05 | TC-file-storage-08 | `::test_resolve_storage_root_env_override` |
| REQ-file-storage-06 | TC-file-storage-09 | `::test_resolve_storage_root_defaults_to_base_dir` |
| REQ-file-storage-07 | TC-file-storage-10 | `::test_save_file_writes_content_and_returns_relative_path` |
| REQ-file-storage-08 | TC-file-storage-11 | `::test_save_file_illegal_folder_name_raises_ioerror` |
| REQ-file-storage-09 | TC-file-storage-12 | `::test_read_file_returns_saved_content` |
| REQ-file-storage-10 | TC-file-storage-13 | `::test_read_file_missing_raises_file_not_found` |
| REQ-file-storage-11 | TC-file-storage-14, TC-file-storage-15 | `::test_delete_file_success_returns_true`、`::test_delete_file_missing_returns_false` |
| REQ-file-storage-12 | TC-file-storage-16, TC-file-storage-17, TC-file-storage-18 | `::test_delete_folder_removes_recursively`、`::test_delete_folder_missing_returns_false`、`::test_delete_folder_illegal_name_raises_value_error` |
| REQ-file-storage-13 | TC-file-storage-19, TC-file-storage-20, TC-file-storage-21 | `::test_rename_folder_success`、`::test_rename_folder_source_missing_returns_false`、`::test_rename_folder_target_exists_returns_false` |
| REQ-file-storage-14 | TC-file-storage-22, TC-file-storage-23 | `::test_resolve_path_joins_relative_under_file_root`、`::test_resolve_path_absolute_input_kept_as_is` |

(測試腳本欄位省略共同前綴 `tests/test_file_storage.py`。)
