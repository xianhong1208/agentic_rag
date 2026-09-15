# SPEC-runtime-paths: Deployment-Mode Path Resolution


| Item | Content |
|------|---------|
| Module | `src/utils/runtime_paths.py` |
| Test | `tests/test_runtime_paths.py` |
| Version | feat/rag-robustness |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

Provides a unified way to locate resource directories across the four deployment modes (dev / Nuitka onefile / Nuitka standalone / Docker),
avoiding the case where `Path(__file__)` under the onefile extraction directory (`/tmp/onefile_*`) reads a stale snapshot from build time:

- `resolve_external_dir(name, dev_root)`: finds an **existing** read-only resource directory
  (config / assets / nltk_data). Candidate order: (1) beside the parent-process executable in NUITKA_ONEFILE_PARENT
  -> (2) beside `/proc/self/exe` -> (3) beside `sys.executable` -> (4) `/app/{name}` -> (5) `dev_root/name`;
  returns `None` if none exist.
- `resolve_base_dir(dev_root)`: returns the writable base directory (the parent of storage / cache),
  **without requiring the subdirectory to already exist**. It only tries the binary-side candidates (1)-(3) when compiled
  (sys.frozen / `__main__.__compiled__` / NUITKA_ONEFILE_PARENT); otherwise it returns `dev_root` directly and never returns `None`.

Not responsible for: creating directories or validating their contents.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|-------------|-------------|-------------------------------------------|
| REQ-runtime-paths-01 | dev mode hits dev_root | With no Nuitka signal and `dev_root/name` being an existing directory, returns it |
| REQ-runtime-paths-02 | Returns None when not found | `resolve_external_dir` returns `None` when none of the candidate locations exist |
| REQ-runtime-paths-03 | Accepts directories only, not files | A candidate path that exists but is a regular file is not a hit (filtered by `is_dir()`) |
| REQ-runtime-paths-04 | Binary side takes priority over dev_root | When a same-named directory exists beside `sys.executable`, it is returned in preference to `dev_root/name` |
| REQ-runtime-paths-05 | Rejects the onefile extraction directory | When `sys.executable` is under `/tmp/onefile_*`, that candidate is discarded and resolution falls back to later candidates |
| REQ-runtime-paths-06 | Non-compiled returns dev_root | For plain Python (no frozen / `__compiled__` / env signal), `resolve_base_dir` returns `dev_root` directly |
| REQ-runtime-paths-07 | Compiled returns the binary directory | When `sys.frozen` is true, returns the directory of `/proc/self/exe` rather than `dev_root` |
| REQ-runtime-paths-08 | NUITKA_ONEFILE_PARENT resolution | When env points to a live process, returns its executable directory; when the PID is invalid, it is still treated as compiled and falls back to `/proc/self/exe` |
| REQ-runtime-paths-09 | Nuitka `__compiled__` detection | The presence of `__main__.__compiled__` triggers the compiled path |

## 3. Non-Functional Requirements

- Any resolution failure (`OSError` / `ValueError`) must be swallowed and the next candidate tried; it must not crash the startup flow.
- Tests must not depend on a real Nuitka build environment; env / `sys` state is simulated with monkeypatch.

## 4. Edge Cases and Errors

| Scenario | Expected behavior |
|----------|-------------------|
| None of the candidates exist | `resolve_external_dir` -> `None`; `resolve_base_dir` -> `dev_root` |
| Candidate is a regular file | Skipped (not treated as a hit) |
| `NUITKA_ONEFILE_PARENT` points to a dead PID | `/proc/{pid}/exe` does not exist -> skip, continue with the next candidate |
| Executable located under `/tmp/onefile_*` | That candidate is rejected (even if the directory truly exists) |

## 5. Dependencies and Assumptions

- Depends only on the standard library (`os` / `sys` / `pathlib`).
- Cases involving `/proc/self/exe` are only meaningful on Linux; tests are guarded with `skipif(not linux)`.
- Test directory names always carry a uuid to avoid accidentally matching a real python bin directory or a same-named directory under `/app`
  (the REQ-04 priority test must still hold when `/app` exists on the machine).

## 6. Traceability

| Requirement | Test Case | Test Script |
|-------------|-----------|-------------|
| REQ-runtime-paths-01 | TC-runtime-paths-01 | `tests/test_runtime_paths.py::test_external_dir_found_under_dev_root` |
| REQ-runtime-paths-02 | TC-runtime-paths-02 | `::test_external_dir_returns_none_when_nowhere` |
| REQ-runtime-paths-03 | TC-runtime-paths-03 | `::test_external_dir_ignores_plain_file` |
| REQ-runtime-paths-04 | TC-runtime-paths-04 | `::test_external_dir_sys_executable_beats_dev_root` |
| REQ-runtime-paths-05 | TC-runtime-paths-05 | `::test_external_dir_rejects_tmp_onefile_executable` |
| REQ-runtime-paths-06 | TC-runtime-paths-06 | `::test_base_dir_dev_mode_returns_dev_root` |
| REQ-runtime-paths-07 | TC-runtime-paths-07 | `::test_base_dir_frozen_uses_real_executable_dir` |
| REQ-runtime-paths-08 | TC-runtime-paths-08, TC-runtime-paths-09 | `::test_base_dir_nuitka_parent_pid_resolves_parent_exe`, `::test_base_dir_invalid_nuitka_pid_falls_back_to_self_exe` |
| REQ-runtime-paths-09 | TC-runtime-paths-10 | `::test_base_dir_nuitka_compiled_marker_detected` |

(The test-script column omits the common prefix `tests/test_runtime_paths.py`.)
