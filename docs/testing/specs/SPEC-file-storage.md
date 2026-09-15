# SPEC-file-storage: File Storage Management


| Item | Content |
|------|------|
| Module | `src/storage/file_storage.py` |
| Test | `tests/test_file_storage.py` |
| Version | feat/rag-robustness |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Manages where uploaded files live on the filesystem, under the structure `storage/{user_token}/{folder_name}/{file_id}`. Covers:

- `_resolve_storage_root()`: determines the storage root directory (env override → `resolve_base_dir`).
- `_validate_safe_name(name, kind)`: allowlist name validation to prevent path traversal.
- `FileStorage`: save / read / delete / delete_folder / rename_folder / resolve_path.

Out of scope: file-content parsing, DB metadata, and access control (handled by the upper API / ACL layers).

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-file-storage-01 | Valid names pass validation | Names made of alphanumerics / `_` / `-` / `.` / space / Chinese characters do not raise |
| REQ-file-storage-02 | Empty / non-string values are rejected | `""`, `None`, and any non-`str` type all raise `ValueError` |
| REQ-file-storage-03 | Path traversal is rejected | Names containing `..`, `/`, `\`, or starting with `.` all raise `ValueError` |
| REQ-file-storage-04 | Characters outside the allowlist are rejected | `* ? $ : \|`, control characters, emoji, etc. all raise `ValueError` |
| REQ-file-storage-05 | env explicitly overrides the storage root | When `MIRAG_STORAGE_ROOT` is set, `_resolve_storage_root()` returns that path (after resolve) |
| REQ-file-storage-06 | Default storage root | With no env set, returns `resolve_base_dir(dev_root=project root)` (in dev mode, the project root directory) |
| REQ-file-storage-07 | save_file writes and returns a relative path | The file lands at `STORAGE_ROOT/{token}/{folder}/{file_id}` and returns `storage/{token}/{folder}/{file_id}` |
| REQ-file-storage-08 | save_file wraps failures as IOError | Any internal error (including a name-validation ValueError) is wrapped and raised as `IOError` |
| REQ-file-storage-09 | read_file returns the content | Reading with the relative path returned by save_file yields the exact same bytes |
| REQ-file-storage-10 | read_file raises FileNotFoundError when missing | A nonexistent path raises `FileNotFoundError` (not swallowed into IOError) |
| REQ-file-storage-11 | delete_file returns a boolean | A successful delete returns `True` and the file is gone; a nonexistent file returns `False` without raising |
| REQ-file-storage-12 | delete_folder deletes recursively | Success returns `True` and the whole folder is gone; nonexistent returns `False`; an illegal name raises `ValueError` directly |
| REQ-file-storage-13 | rename_folder renames safely | Success returns `True`; a missing source returns `False`; an existing target returns `False` without overwriting |
| REQ-file-storage-14 | resolve_path resolves a DB path | A relative path is joined under `STORAGE_FILE_ROOT`; an absolute path is returned as-is per `Path` semantics |

## 3. Non-Functional Requirements

- Security: name validation is the first line of defense; any path combination that escapes `STORAGE_ROOT` must be blocked (REQ-03/04/08/12).
- Logs must not output the full user_token (only the first 8 characters) — an observability requirement, not enforced by the unit tests.

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| name is `""` / `None` / `123` | `ValueError` (cannot be empty) |
| name contains `..`, `/`, `\`, or starts with `.` | `ValueError` (illegal path characters) |
| name contains characters outside the allowlist (emoji, `*`, etc.) | `ValueError` (illegal characters) |
| save_file receives an illegal folder_name | `IOError` (the internal ValueError is uniformly wrapped) |
| read_file path does not exist | `FileNotFoundError` |
| delete_file path does not exist | returns `False` |
| rename_folder target already exists | returns `False`; source and target are both unchanged |

## 5. Dependencies & Assumptions

- The module runs `_resolve_storage_root()` **at import time** to set the `FileStorage.STORAGE_ROOT` /
  `STORAGE_FILE_ROOT` class attributes; tests therefore do not reload the module and instead use
  `monkeypatch.setattr(FileStorage, "STORAGE_ROOT"/"STORAGE_FILE_ROOT", tmp_path…)`
  to redirect all file operations into pytest's `tmp_path`.
- `_resolve_storage_root()` itself is tested by calling it directly with `monkeypatch.setenv/delenv("MIRAG_STORAGE_ROOT")`.
- Depends on `src.log` (loguru) and `src.utils.runtime_paths`, neither of which needs an external service or a mock.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-file-storage-01 | TC-file-storage-01 | `tests/test_file_storage.py::test_validate_safe_name_accepts_legal_names` |
| REQ-file-storage-02 | TC-file-storage-02, TC-file-storage-03 | `::test_validate_safe_name_rejects_empty_string`, `::test_validate_safe_name_rejects_non_string` |
| REQ-file-storage-03 | TC-file-storage-04, TC-file-storage-05, TC-file-storage-06 | `::test_validate_safe_name_rejects_dotdot_traversal`, `::test_validate_safe_name_rejects_path_separators`, `::test_validate_safe_name_rejects_leading_dot` |
| REQ-file-storage-04 | TC-file-storage-07 | `::test_validate_safe_name_rejects_special_characters` |
| REQ-file-storage-05 | TC-file-storage-08 | `::test_resolve_storage_root_env_override` |
| REQ-file-storage-06 | TC-file-storage-09 | `::test_resolve_storage_root_defaults_to_base_dir` |
| REQ-file-storage-07 | TC-file-storage-10 | `::test_save_file_writes_content_and_returns_relative_path` |
| REQ-file-storage-08 | TC-file-storage-11 | `::test_save_file_illegal_folder_name_raises_ioerror` |
| REQ-file-storage-09 | TC-file-storage-12 | `::test_read_file_returns_saved_content` |
| REQ-file-storage-10 | TC-file-storage-13 | `::test_read_file_missing_raises_file_not_found` |
| REQ-file-storage-11 | TC-file-storage-14, TC-file-storage-15 | `::test_delete_file_success_returns_true`, `::test_delete_file_missing_returns_false` |
| REQ-file-storage-12 | TC-file-storage-16, TC-file-storage-17, TC-file-storage-18 | `::test_delete_folder_removes_recursively`, `::test_delete_folder_missing_returns_false`, `::test_delete_folder_illegal_name_raises_value_error` |
| REQ-file-storage-13 | TC-file-storage-19, TC-file-storage-20, TC-file-storage-21 | `::test_rename_folder_success`, `::test_rename_folder_source_missing_returns_false`, `::test_rename_folder_target_exists_returns_false` |
| REQ-file-storage-14 | TC-file-storage-22, TC-file-storage-23 | `::test_resolve_path_joins_relative_under_file_root`, `::test_resolve_path_absolute_input_kept_as_is` |

(The test-script column omits the common prefix `tests/test_file_storage.py`.)
