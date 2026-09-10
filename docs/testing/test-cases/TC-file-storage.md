# TC-file-storage:文件存儲管理 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-file-storage](../specs/SPEC-file-storage.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_file_storage.py` |

共同前置(FileStorage 案例):fixture `storage_root` 以 monkeypatch 把
`FileStorage.STORAGE_ROOT` → `tmp_path/storage`、`FileStorage.STORAGE_FILE_ROOT` → `tmp_path`,
所有檔案操作只落在 pytest 暫存目錄。

---

## TC-file-storage-01:合法名稱通過驗證

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"abc"`、`"ABC-123_x"`、`"report.pdf"`、`"中文資料夾"`、`"財報 2026.xlsx"`、`"mixed中英-1.0"`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 `_validate_safe_name(name, "folder")` |
| **預期結果** | 全部不拋例外 |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_accepts_legal_names` |

## TC-file-storage-02:空字串拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `""` |
| **測試步驟** | 1. 呼叫 `_validate_safe_name("", "token")` |
| **預期結果** | `ValueError`,訊息含 `cannot be empty` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_empty_string` |

## TC-file-storage-03:None / 非字串拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `None`、`123`、`1.5`、`["a"]`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 |
| **預期結果** | 全部 `ValueError` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_non_string` |

## TC-file-storage-04:`..` path traversal 拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `".."`、`"../etc/passwd"`、`"a..b"`、`"a/../b"`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 |
| **預期結果** | 全部 `ValueError`,訊息含 `illegal path characters` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_dotdot_traversal` |

## TC-file-storage-05:路徑分隔符拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"a/b"`、`"/abs"`、`"a\\b"`、`"\\\\share"`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 |
| **預期結果** | 全部 `ValueError` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_path_separators` |

## TC-file-storage-06:開頭 `.` 拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `".hidden"`、`".env"`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 |
| **預期結果** | 全部 `ValueError` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_leading_dot` |

## TC-file-storage-07:白名單外特殊字元拒絕

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `"a*b"`、`"a?b"`、`"a$b"`、`"a:b"`、`"a\|b"`、`"🚀rocket"`、`"a\tb"`(parametrize) |
| **測試步驟** | 1. 逐一呼叫 |
| **預期結果** | 全部 `ValueError`,訊息含 `illegal characters` |
| **實作** | `tests/test_file_storage.py::test_validate_safe_name_rejects_special_characters` |

## TC-file-storage-08:MIRAG_STORAGE_ROOT 覆寫

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-05 |
| **層級** | 單元 |
| **前置條件** | monkeypatch 設定 env |
| **測試輸入** | `MIRAG_STORAGE_ROOT = tmp_path/custom_root` |
| **測試步驟** | 1. setenv<br>2. 呼叫 `_resolve_storage_root()` |
| **預期結果** | 回傳 `(tmp_path/custom_root).resolve()` |
| **實作** | `tests/test_file_storage.py::test_resolve_storage_root_env_override` |

## TC-file-storage-09:無 env 時採 resolve_base_dir

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-06 |
| **層級** | 單元 |
| **前置條件** | 刪除 `MIRAG_STORAGE_ROOT`、`NUITKA_ONEFILE_PARENT` env |
| **測試輸入** | 無 |
| **測試步驟** | 1. delenv<br>2. 呼叫 `_resolve_storage_root()` |
| **預期結果** | 等於 `resolve_base_dir(dev_root=專案根目錄)` |
| **實作** | `tests/test_file_storage.py::test_resolve_storage_root_defaults_to_base_dir` |

## TC-file-storage-10:save_file 寫入並回相對路徑

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-07 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root` |
| **測試輸入** | token=`tok1`、folder=`月報`、file_id=`file-uuid-1`、content=`b"hello bytes"` |
| **測試步驟** | 1. save_file<br>2. 檢查回傳值<br>3. 讀實體檔案 |
| **預期結果** | 回 `storage/tok1/月報/file-uuid-1`;實體檔內容一致 |
| **實作** | `tests/test_file_storage.py::test_save_file_writes_content_and_returns_relative_path` |

## TC-file-storage-11:save_file 非法 folder_name 包裝 IOError

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-08 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root` |
| **測試輸入** | folder=`"../escape"` |
| **測試步驟** | 1. save_file<br>2. 檢查 tmp 根外無殘留 |
| **預期結果** | 拋 `IOError`(訊息含 `Failed to save file`);未建立任何跳脫目錄 |
| **實作** | `tests/test_file_storage.py::test_save_file_illegal_folder_name_raises_ioerror` |

## TC-file-storage-12:read_file 讀回內容

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-09 |
| **層級** | 單元 |
| **前置條件** | 已 save_file 二進制內容 `b"\x00\x01binary"` |
| **測試輸入** | save_file 回傳的相對路徑 |
| **測試步驟** | 1. save<br>2. read |
| **預期結果** | bytes 與寫入時完全一致 |
| **實作** | `tests/test_file_storage.py::test_read_file_returns_saved_content` |

## TC-file-storage-13:read_file 不存在拋 FileNotFoundError

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-10 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root`(空) |
| **測試輸入** | `storage/tok1/docs/ghost` |
| **測試步驟** | 1. read_file |
| **預期結果** | `FileNotFoundError` |
| **實作** | `tests/test_file_storage.py::test_read_file_missing_raises_file_not_found` |

## TC-file-storage-14:delete_file 成功回 True

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-11 |
| **層級** | 單元 |
| **前置條件** | 已 save_file 一個檔案 |
| **測試輸入** | 該檔相對路徑 |
| **測試步驟** | 1. delete_file<br>2. 檢查檔案 |
| **預期結果** | 回 `True`;檔案消失 |
| **實作** | `tests/test_file_storage.py::test_delete_file_success_returns_true` |

## TC-file-storage-15:delete_file 不存在回 False

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-11 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root`(空) |
| **測試輸入** | `storage/tok1/docs/ghost` |
| **測試步驟** | 1. delete_file |
| **預期結果** | 回 `False`,不拋例外 |
| **實作** | `tests/test_file_storage.py::test_delete_file_missing_returns_false` |

## TC-file-storage-16:delete_folder 遞迴刪除

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-12 |
| **層級** | 單元 |
| **前置條件** | 資料夾內已有兩個檔案 |
| **測試輸入** | token=`tok1`、folder=`docs` |
| **測試步驟** | 1. save ×2<br>2. delete_folder<br>3. 檢查目錄 |
| **預期結果** | 回 `True`;整個資料夾消失 |
| **實作** | `tests/test_file_storage.py::test_delete_folder_removes_recursively` |

## TC-file-storage-17:delete_folder 不存在回 False

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-12 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root`(空) |
| **測試輸入** | folder=`ghost` |
| **測試步驟** | 1. delete_folder |
| **預期結果** | 回 `False` |
| **實作** | `tests/test_file_storage.py::test_delete_folder_missing_returns_false` |

## TC-file-storage-18:delete_folder 非法名稱拋 ValueError

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-12 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root` |
| **測試輸入** | folder=`"../../etc"` |
| **測試步驟** | 1. delete_folder |
| **預期結果** | 拋 `ValueError`(不吞成回 `False`) |
| **實作** | `tests/test_file_storage.py::test_delete_folder_illegal_name_raises_value_error` |

## TC-file-storage-19:rename_folder 成功

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-13 |
| **層級** | 單元 |
| **前置條件** | `old_name` 資料夾含一個檔案 |
| **測試輸入** | `old_name` → `new_name` |
| **測試步驟** | 1. save<br>2. rename_folder<br>3. 檢查新舊路徑 |
| **預期結果** | 回 `True`;舊路徑消失;新路徑下檔案內容不變 |
| **實作** | `tests/test_file_storage.py::test_rename_folder_success` |

## TC-file-storage-20:rename_folder 來源不存在回 False

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-13 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root`(空) |
| **測試輸入** | `ghost` → `new` |
| **測試步驟** | 1. rename_folder |
| **預期結果** | 回 `False` |
| **實作** | `tests/test_file_storage.py::test_rename_folder_source_missing_returns_false` |

## TC-file-storage-21:rename_folder 目標已存在回 False

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-13 |
| **層級** | 單元 |
| **前置條件** | `src_dir`、`dst_dir` 各含一檔 |
| **測試輸入** | `src_dir` → `dst_dir` |
| **測試步驟** | 1. save ×2<br>2. rename_folder<br>3. 檢查兩邊檔案 |
| **預期結果** | 回 `False`;兩個資料夾內容皆未變動 |
| **實作** | `tests/test_file_storage.py::test_rename_folder_target_exists_returns_false` |

## TC-file-storage-22:resolve_path 相對路徑解析

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-14 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root` |
| **測試輸入** | `"storage/t/f/id"` |
| **測試步驟** | 1. resolve_path |
| **預期結果** | 回 `STORAGE_FILE_ROOT/storage/t/f/id` |
| **實作** | `tests/test_file_storage.py::test_resolve_path_joins_relative_under_file_root` |

## TC-file-storage-23:resolve_path 絕對路徑原樣

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-file-storage-14 |
| **層級** | 單元 |
| **前置條件** | fixture `storage_root` |
| **測試輸入** | `"/abs/x/y"` |
| **測試步驟** | 1. resolve_path |
| **預期結果** | 回 `Path("/abs/x/y")`(`Path` join 語意丟棄左側) |
| **實作** | `tests/test_file_storage.py::test_resolve_path_absolute_input_kept_as_is` |
