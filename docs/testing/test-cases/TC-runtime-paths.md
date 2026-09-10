# TC-runtime-paths:部署模式路徑解析 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-runtime-paths](../specs/SPEC-runtime-paths.md) |
| 測試層級 | 單元 |
| 測試腳本 | `tests/test_runtime_paths.py` |

共同前置:目錄名一律 `res_{uuid}` 避免撞真實路徑;fixture `no_nuitka_env`
移除 `NUITKA_ONEFILE_PARENT`;`/proc` 相關案例掛 `skipif(not linux)`。

---

## TC-runtime-paths-01:dev_root 命中

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-01 |
| **層級** | 單元 |
| **前置條件** | `tmp_path/{name}` 目錄已建立;無 Nuitka env |
| **測試輸入** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **測試步驟** | 1. mkdir<br>2. 呼叫 |
| **預期結果** | 回 `tmp_path/{name}` |
| **實作** | `tests/test_runtime_paths.py::test_external_dir_found_under_dev_root` |

## TC-runtime-paths-02:全部候選不存在回 None

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-02 |
| **層級** | 單元 |
| **前置條件** | uuid 目錄名,任何候選位置皆不存在 |
| **測試輸入** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 回 `None` |
| **實作** | `tests/test_runtime_paths.py::test_external_dir_returns_none_when_nowhere` |

## TC-runtime-paths-03:同名一般檔案不算命中

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-03 |
| **層級** | 單元 |
| **前置條件** | `tmp_path/{name}` 為一般檔案 |
| **測試輸入** | `resolve_external_dir(name, dev_root=tmp_path)` |
| **測試步驟** | 1. write_text<br>2. 呼叫 |
| **預期結果** | 回 `None`(`is_dir()` 過濾) |
| **實作** | `tests/test_runtime_paths.py::test_external_dir_ignores_plain_file` |

## TC-runtime-paths-04:sys.executable 旁優先於 dev_root

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-04 |
| **層級** | 單元 |
| **前置條件** | `tmp_path/bin/{name}` 與 `tmp_path/dev/{name}` 皆存在;monkeypatch `sys.executable = tmp_path/bin/app.bin` |
| **測試輸入** | `resolve_external_dir(name, dev_root=tmp_path/dev)` |
| **測試步驟** | 1. 建兩個候選目錄<br>2. patch sys.executable<br>3. 呼叫 |
| **預期結果** | 回 `tmp_path/bin/{name}`(binary 側贏過 dev_root) |
| **實作** | `tests/test_runtime_paths.py::test_external_dir_sys_executable_beats_dev_root` |

## TC-runtime-paths-05:/tmp/onefile_* 執行檔被拒

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-05 |
| **層級** | 單元 |
| **前置條件** | 實建 `/tmp/onefile_XXXX/{name}` 目錄(測後清除);monkeypatch `sys.executable` 指向其中 |
| **測試輸入** | `resolve_external_dir(name, dev_root=tmp_path/dev)`(dev 側也建目錄) |
| **測試步驟** | 1. mkdtemp(prefix="onefile_")<br>2. patch sys.executable<br>3. 呼叫 |
| **預期結果** | 回 `dev_root/{name}`(即使 onefile 解壓目錄裡有 bundled copy 也不用) |
| **實作** | `tests/test_runtime_paths.py::test_external_dir_rejects_tmp_onefile_executable` |

## TC-runtime-paths-06:非 compiled 回 dev_root

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-06 |
| **層級** | 單元 |
| **前置條件** | plain Python(無 frozen / `__compiled__` / Nuitka env) |
| **測試輸入** | `resolve_base_dir(dev_root=tmp_path)` |
| **測試步驟** | 1. 呼叫 |
| **預期結果** | 回 `tmp_path`(不誤用 python bin 目錄) |
| **實作** | `tests/test_runtime_paths.py::test_base_dir_dev_mode_returns_dev_root` |

## TC-runtime-paths-07:sys.frozen 時回執行檔目錄

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-07 |
| **層級** | 單元(Linux only) |
| **前置條件** | monkeypatch `sys.frozen = True`;無 Nuitka env |
| **測試輸入** | `resolve_base_dir(dev_root=tmp_path)` |
| **測試步驟** | 1. patch<br>2. 呼叫 |
| **預期結果** | 回 `Path("/proc/self/exe").resolve().parent`,且 != `tmp_path` |
| **實作** | `tests/test_runtime_paths.py::test_base_dir_frozen_uses_real_executable_dir` |

## TC-runtime-paths-08:NUITKA_ONEFILE_PARENT 指向存活 process

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-08 |
| **層級** | 單元(Linux only) |
| **前置條件** | `NUITKA_ONEFILE_PARENT="self"`(`/proc/self/exe` 必存在) |
| **測試輸入** | `resolve_base_dir(dev_root=tmp_path)` |
| **測試步驟** | 1. setenv<br>2. 呼叫 |
| **預期結果** | 回 `/proc/self/exe` 所在目錄(候選 ① 命中) |
| **實作** | `tests/test_runtime_paths.py::test_base_dir_nuitka_parent_pid_resolves_parent_exe` |

## TC-runtime-paths-09:無效 PID 仍視為 compiled 並 fallback

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-08 |
| **層級** | 單元(Linux only) |
| **前置條件** | `NUITKA_ONEFILE_PARENT="999999999"`(死 PID) |
| **測試輸入** | `resolve_base_dir(dev_root=tmp_path)` |
| **測試步驟** | 1. setenv<br>2. 呼叫 |
| **預期結果** | 候選 ① 落空後 fallback 候選 ②,回 `/proc/self/exe` 的目錄;不回 `tmp_path` |
| **實作** | `tests/test_runtime_paths.py::test_base_dir_invalid_nuitka_pid_falls_back_to_self_exe` |

## TC-runtime-paths-10:__main__.__compiled__ 標記觸發 compiled 路徑

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-runtime-paths-09 |
| **層級** | 單元(Linux only) |
| **前置條件** | monkeypatch `sys.modules["__main__"].__compiled__ = True`;無 Nuitka env |
| **測試輸入** | `resolve_base_dir(dev_root=tmp_path)` |
| **測試步驟** | 1. patch<br>2. 呼叫 |
| **預期結果** | 回 `/proc/self/exe` 所在目錄(Nuitka 標記被偵測) |
| **實作** | `tests/test_runtime_paths.py::test_base_dir_nuitka_compiled_marker_detected` |
