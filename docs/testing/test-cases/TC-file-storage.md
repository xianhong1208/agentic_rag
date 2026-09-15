# TC-file-storage: File Storage Management Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-file-storage](../specs/SPEC-file-storage.md) |
| Test level | Unit |
| Test script | `tests/test_file_storage.py` |

Shared precondition (FileStorage cases): the `storage_root` fixture uses monkeypatch to set
`FileStorage.STORAGE_ROOT` -> `tmp_path/storage` and `FileStorage.STORAGE_FILE_ROOT` -> `tmp_path`,
so every file operation stays within the pytest temporary directory.

---

## TC-file-storage-01: Legal names pass validation

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"abc"`, `"ABC-123_x"`, `"report.pdf"`, `"中文資料夾"`, `"財報 2026.xlsx"`, `"mixed中英-1.0"` (parametrized) |
| **Test steps** | 1. Call `_validate_safe_name(name, "folder")` for each |
| **Expected result** | None raise an exception |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_accepts_legal_names` |

## TC-file-storage-02: Empty string rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `""` |
| **Test steps** | 1. Call `_validate_safe_name("", "token")` |
| **Expected result** | `ValueError` with a message containing `cannot be empty` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_empty_string` |

## TC-file-storage-03: None / non-string rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `None`, `123`, `1.5`, `["a"]` (parametrized) |
| **Test steps** | 1. Call for each |
| **Expected result** | All raise `ValueError` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_non_string` |

## TC-file-storage-04: `..` path traversal rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `".."`, `"../etc/passwd"`, `"a..b"`, `"a/../b"` (parametrized) |
| **Test steps** | 1. Call for each |
| **Expected result** | All raise `ValueError` with a message containing `illegal path characters` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_dotdot_traversal` |

## TC-file-storage-05: Path separators rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"a/b"`, `"/abs"`, `"a\\b"`, `"\\\\share"` (parametrized) |
| **Test steps** | 1. Call for each |
| **Expected result** | All raise `ValueError` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_path_separators` |

## TC-file-storage-06: Leading `.` rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `".hidden"`, `".env"` (parametrized) |
| **Test steps** | 1. Call for each |
| **Expected result** | All raise `ValueError` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_leading_dot` |

## TC-file-storage-07: Special characters outside the allowlist rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `"a*b"`, `"a?b"`, `"a$b"`, `"a:b"`, `"a\|b"`, `"🚀rocket"`, `"a\tb"` (parametrized) |
| **Test steps** | 1. Call for each |
| **Expected result** | All raise `ValueError` with a message containing `illegal characters` |
| **Implementation** | `tests/test_file_storage.py::test_validate_safe_name_rejects_special_characters` |

## TC-file-storage-08: MIRAG_STORAGE_ROOT override

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-05 |
| **Level** | Unit |
| **Preconditions** | monkeypatch sets the env var |
| **Test input** | `MIRAG_STORAGE_ROOT = tmp_path/custom_root` |
| **Test steps** | 1. setenv<br>2. Call `_resolve_storage_root()` |
| **Expected result** | Returns `(tmp_path/custom_root).resolve()` |
| **Implementation** | `tests/test_file_storage.py::test_resolve_storage_root_env_override` |

## TC-file-storage-09: Falls back to resolve_base_dir when env is absent

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-06 |
| **Level** | Unit |
| **Preconditions** | Remove the `MIRAG_STORAGE_ROOT` and `NUITKA_ONEFILE_PARENT` env vars |
| **Test input** | None |
| **Test steps** | 1. delenv<br>2. Call `_resolve_storage_root()` |
| **Expected result** | Equals `resolve_base_dir(dev_root=project root)` |
| **Implementation** | `tests/test_file_storage.py::test_resolve_storage_root_defaults_to_base_dir` |

## TC-file-storage-10: save_file writes and returns a relative path

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-07 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture |
| **Test input** | token=`tok1`, folder=`月報`, file_id=`file-uuid-1`, content=`b"hello bytes"` |
| **Test steps** | 1. save_file<br>2. Check the return value<br>3. Read the physical file |
| **Expected result** | Returns `storage/tok1/月報/file-uuid-1`; the physical file content matches |
| **Implementation** | `tests/test_file_storage.py::test_save_file_writes_content_and_returns_relative_path` |

## TC-file-storage-11: save_file wraps an illegal folder_name as IOError

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-08 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture |
| **Test input** | folder=`"../escape"` |
| **Test steps** | 1. save_file<br>2. Check that nothing was left outside the tmp root |
| **Expected result** | Raises `IOError` (message contains `Failed to save file`); no escaped directory is created |
| **Implementation** | `tests/test_file_storage.py::test_save_file_illegal_folder_name_raises_ioerror` |

## TC-file-storage-12: read_file returns the content

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-09 |
| **Level** | Unit |
| **Preconditions** | Binary content `b"\x00\x01binary"` already saved via save_file |
| **Test input** | The relative path returned by save_file |
| **Test steps** | 1. save<br>2. read |
| **Expected result** | The bytes match exactly what was written |
| **Implementation** | `tests/test_file_storage.py::test_read_file_returns_saved_content` |

## TC-file-storage-13: read_file raises FileNotFoundError when missing

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-10 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture (empty) |
| **Test input** | `storage/tok1/docs/ghost` |
| **Test steps** | 1. read_file |
| **Expected result** | `FileNotFoundError` |
| **Implementation** | `tests/test_file_storage.py::test_read_file_missing_raises_file_not_found` |

## TC-file-storage-14: delete_file returns True on success

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-11 |
| **Level** | Unit |
| **Preconditions** | One file already saved via save_file |
| **Test input** | That file's relative path |
| **Test steps** | 1. delete_file<br>2. Check the file |
| **Expected result** | Returns `True`; the file is gone |
| **Implementation** | `tests/test_file_storage.py::test_delete_file_success_returns_true` |

## TC-file-storage-15: delete_file returns False when missing

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-11 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture (empty) |
| **Test input** | `storage/tok1/docs/ghost` |
| **Test steps** | 1. delete_file |
| **Expected result** | Returns `False`, no exception raised |
| **Implementation** | `tests/test_file_storage.py::test_delete_file_missing_returns_false` |

## TC-file-storage-16: delete_folder removes recursively

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-12 |
| **Level** | Unit |
| **Preconditions** | The folder already contains two files |
| **Test input** | token=`tok1`, folder=`docs` |
| **Test steps** | 1. save x2<br>2. delete_folder<br>3. Check the directory |
| **Expected result** | Returns `True`; the entire folder is gone |
| **Implementation** | `tests/test_file_storage.py::test_delete_folder_removes_recursively` |

## TC-file-storage-17: delete_folder returns False when missing

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-12 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture (empty) |
| **Test input** | folder=`ghost` |
| **Test steps** | 1. delete_folder |
| **Expected result** | Returns `False` |
| **Implementation** | `tests/test_file_storage.py::test_delete_folder_missing_returns_false` |

## TC-file-storage-18: delete_folder raises ValueError on an illegal name

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-12 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture |
| **Test input** | folder=`"../../etc"` |
| **Test steps** | 1. delete_folder |
| **Expected result** | Raises `ValueError` (not swallowed into a `False` return) |
| **Implementation** | `tests/test_file_storage.py::test_delete_folder_illegal_name_raises_value_error` |

## TC-file-storage-19: rename_folder succeeds

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-13 |
| **Level** | Unit |
| **Preconditions** | The `old_name` folder contains one file |
| **Test input** | `old_name` -> `new_name` |
| **Test steps** | 1. save<br>2. rename_folder<br>3. Check the old and new paths |
| **Expected result** | Returns `True`; the old path is gone; the file content under the new path is unchanged |
| **Implementation** | `tests/test_file_storage.py::test_rename_folder_success` |

## TC-file-storage-20: rename_folder returns False when the source is missing

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-13 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture (empty) |
| **Test input** | `ghost` -> `new` |
| **Test steps** | 1. rename_folder |
| **Expected result** | Returns `False` |
| **Implementation** | `tests/test_file_storage.py::test_rename_folder_source_missing_returns_false` |

## TC-file-storage-21: rename_folder returns False when the target already exists

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-13 |
| **Level** | Unit |
| **Preconditions** | `src_dir` and `dst_dir` each contain one file |
| **Test input** | `src_dir` -> `dst_dir` |
| **Test steps** | 1. save x2<br>2. rename_folder<br>3. Check the files on both sides |
| **Expected result** | Returns `False`; the contents of both folders are unchanged |
| **Implementation** | `tests/test_file_storage.py::test_rename_folder_target_exists_returns_false` |

## TC-file-storage-22: resolve_path resolves a relative path

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-14 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture |
| **Test input** | `"storage/t/f/id"` |
| **Test steps** | 1. resolve_path |
| **Expected result** | Returns `STORAGE_FILE_ROOT/storage/t/f/id` |
| **Implementation** | `tests/test_file_storage.py::test_resolve_path_joins_relative_under_file_root` |

## TC-file-storage-23: resolve_path keeps an absolute path as-is

| Field | Content |
|-------|---------|
| **Requirement** | REQ-file-storage-14 |
| **Level** | Unit |
| **Preconditions** | `storage_root` fixture |
| **Test input** | `"/abs/x/y"` |
| **Test steps** | 1. resolve_path |
| **Expected result** | Returns `Path("/abs/x/y")` (`Path` join semantics discard the left side) |
| **Implementation** | `tests/test_file_storage.py::test_resolve_path_absolute_input_kept_as_is` |
