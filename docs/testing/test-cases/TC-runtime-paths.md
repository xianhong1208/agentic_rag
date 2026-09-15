# TC-runtime-paths: Deployment-Mode Path Resolution Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-runtime-paths](../specs/SPEC-runtime-paths.md) |
| Test level | Unit |
| Test script | `tests/test_runtime_paths.py` |

Shared precondition: directory names are always `res_{uuid}` to avoid colliding with real paths; the `no_nuitka_env` fixture removes `NUITKA_ONEFILE_PARENT`; `/proc`-related cases are guarded with `skipif(not linux)`.

---

## TC-runtime-paths-01: dev_root hit

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-01 |
| **Level** | Unit |
| **Preconditions** | `tmp_path/{name}` directory created; no Nuitka env |
| **Test input** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **Test steps** | 1. mkdir<br>2. Call |
| **Expected result** | Returns `tmp_path/{name}` |
| **Implementation** | `tests/test_runtime_paths.py::test_external_dir_found_under_dev_root` |

## TC-runtime-paths-02: returns None when no candidate exists

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-02 |
| **Level** | Unit |
| **Preconditions** | uuid directory name; none of the candidate locations exist |
| **Test input** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **Test steps** | 1. Call |
| **Expected result** | Returns `None` |
| **Implementation** | `tests/test_runtime_paths.py::test_external_dir_returns_none_when_nowhere` |

## TC-runtime-paths-03: same-named regular file is not a hit

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-03 |
| **Level** | Unit |
| **Preconditions** | `tmp_path/{name}` is a regular file |
| **Test input** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **Test steps** | 1. write_text<br>2. Call |
| **Expected result** | Returns `None` (filtered by `is_dir()`) |
| **Implementation** | `tests/test_runtime_paths.py::test_external_dir_ignores_plain_file` |

## TC-runtime-paths-04: beside sys.executable takes priority over dev_root

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-04 |
| **Level** | Unit |
| **Preconditions** | Both `tmp_path/bin/{name}` and `tmp_path/dev/{name}` exist; monkeypatch `sys.executable = tmp_path/bin/app.bin` |
| **Test input** | `resolve_external_dir(name, dev_root=tmp_path/dev)` |
| **Test steps** | 1. Create both candidate directories<br>2. patch sys.executable<br>3. Call |
| **Expected result** | Returns `tmp_path/bin/{name}` (binary side beats dev_root) |
| **Implementation** | `tests/test_runtime_paths.py::test_external_dir_sys_executable_beats_dev_root` |

## TC-runtime-paths-05: /tmp/onefile_* executable rejected

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-05 |
| **Level** | Unit |
| **Preconditions** | Actually create a `/tmp/onefile_XXXX/{name}` directory (cleaned up afterward); monkeypatch `sys.executable` to point inside it |
| **Test input** | `resolve_external_dir(name, dev_root=tmp_path/dev)` (a directory is also created on the dev side) |
| **Test steps** | 1. mkdtemp(prefix="onefile_")<br>2. patch sys.executable<br>3. Call |
| **Expected result** | Returns `dev_root/{name}` (the bundled copy in the onefile extraction directory is not used even if present) |
| **Implementation** | `tests/test_runtime_paths.py::test_external_dir_rejects_tmp_onefile_executable` |

## TC-runtime-paths-06: non-compiled returns dev_root

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-06 |
| **Level** | Unit |
| **Preconditions** | plain Python (no frozen / `__compiled__` / Nuitka env) |
| **Test input** | `resolve_base_dir(dev_root=tmp_path)` |
| **Test steps** | 1. Call |
| **Expected result** | Returns `tmp_path` (does not mistakenly use the python bin directory) |
| **Implementation** | `tests/test_runtime_paths.py::test_base_dir_dev_mode_returns_dev_root` |

## TC-runtime-paths-07: sys.frozen returns the executable directory

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-07 |
| **Level** | Unit (Linux only) |
| **Preconditions** | monkeypatch `sys.frozen = True`; no Nuitka env |
| **Test input** | `resolve_base_dir(dev_root=tmp_path)` |
| **Test steps** | 1. patch<br>2. Call |
| **Expected result** | Returns `Path("/proc/self/exe").resolve().parent`, and != `tmp_path` |
| **Implementation** | `tests/test_runtime_paths.py::test_base_dir_frozen_uses_real_executable_dir` |

## TC-runtime-paths-08: NUITKA_ONEFILE_PARENT points to a live process

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-08 |
| **Level** | Unit (Linux only) |
| **Preconditions** | `NUITKA_ONEFILE_PARENT="self"` (`/proc/self/exe` always exists) |
| **Test input** | `resolve_base_dir(dev_root=tmp_path)` |
| **Test steps** | 1. setenv<br>2. Call |
| **Expected result** | Returns the directory of `/proc/self/exe` (candidate 1 hit) |
| **Implementation** | `tests/test_runtime_paths.py::test_base_dir_nuitka_parent_pid_resolves_parent_exe` |

## TC-runtime-paths-09: invalid PID still treated as compiled and falls back

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-08 |
| **Level** | Unit (Linux only) |
| **Preconditions** | `NUITKA_ONEFILE_PARENT="999999999"` (dead PID) |
| **Test input** | `resolve_base_dir(dev_root=tmp_path)` |
| **Test steps** | 1. setenv<br>2. Call |
| **Expected result** | After candidate 1 misses, falls back to candidate 2 and returns the directory of `/proc/self/exe`; does not return `tmp_path` |
| **Implementation** | `tests/test_runtime_paths.py::test_base_dir_invalid_nuitka_pid_falls_back_to_self_exe` |

## TC-runtime-paths-10: __main__.__compiled__ marker triggers the compiled path

| Field | Content |
|-------|---------|
| **Requirement** | REQ-runtime-paths-09 |
| **Level** | Unit (Linux only) |
| **Preconditions** | monkeypatch `sys.modules["__main__"].__compiled__ = True`; no Nuitka env |
| **Test input** | `resolve_base_dir(dev_root=tmp_path)` |
| **Test steps** | 1. patch<br>2. Call |
| **Expected result** | Returns the directory of `/proc/self/exe` (the Nuitka marker is detected) |
| **Implementation** | `tests/test_runtime_paths.py::test_base_dir_nuitka_compiled_marker_detected` |
