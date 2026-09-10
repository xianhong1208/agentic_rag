# SPEC-runtime-paths:部署模式路徑解析


| 項目 | 內容 |
|------|------|
| 模組 | `src/utils/runtime_paths.py` |
| 對應測試 | `tests/test_runtime_paths.py` |
| 版本 | feat/rag-robustness |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

統一 dev / Nuitka onefile / Nuitka standalone / Docker 四種部署模式下的資源目錄定位,
避免 `Path(__file__)` 在 onefile 解壓目錄(`/tmp/onefile_*`)下讀到打包時的舊 snapshot:

- `resolve_external_dir(name, dev_root)`:查找**已存在**的 read-only 資源目錄
  (config / assets / nltk_data),候選順序 ① NUITKA_ONEFILE_PARENT 父 process 執行檔旁
  → ② `/proc/self/exe` 旁 → ③ `sys.executable` 旁 → ④ `/app/{name}` → ⑤ `dev_root/name`,
  全部不存在回 `None`。
- `resolve_base_dir(dev_root)`:回傳 writable base 目錄(storage / cache 的上層),
  **不要求子目錄已存在**;僅在 compiled(sys.frozen / `__main__.__compiled__` /
  NUITKA_ONEFILE_PARENT)時嘗試 binary 側 ①-③,否則直接回 `dev_root`,永不回 `None`。

不負責:目錄的建立、內容驗證。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-runtime-paths-01 | dev 模式命中 dev_root | 無 Nuitka 訊號且 `dev_root/name` 為既存目錄時回傳之 |
| REQ-runtime-paths-02 | 查無目錄回 None | 所有候選位置皆不存在時 `resolve_external_dir` 回 `None` |
| REQ-runtime-paths-03 | 只認目錄不認檔案 | 候選路徑存在但是一般檔案時不算命中(`is_dir()` 過濾) |
| REQ-runtime-paths-04 | binary 側優先於 dev_root | `sys.executable` 旁存在同名目錄時,優先於 `dev_root/name` 回傳 |
| REQ-runtime-paths-05 | 拒絕 onefile 解壓目錄 | `sys.executable` 位於 `/tmp/onefile_*` 時該候選作廢,fallback 至後續候選 |
| REQ-runtime-paths-06 | 非 compiled 回 dev_root | plain Python(無 frozen / `__compiled__` / env 訊號)時 `resolve_base_dir` 直接回 `dev_root` |
| REQ-runtime-paths-07 | compiled 回 binary 目錄 | `sys.frozen` 為真時回 `/proc/self/exe` 所在目錄,而非 `dev_root` |
| REQ-runtime-paths-08 | NUITKA_ONEFILE_PARENT 解析 | env 指向存活 process 時回其執行檔目錄;PID 無效時仍視為 compiled,fallback `/proc/self/exe` |
| REQ-runtime-paths-09 | Nuitka `__compiled__` 偵測 | `__main__.__compiled__` 存在即觸發 compiled 路徑 |

## 3. 非功能需求

- 任何解析失敗(`OSError` / `ValueError`)都必須被吞掉並嘗試下一個候選,不得讓啟動流程炸掉。
- 測試不得依賴真實 Nuitka 打包環境;以 monkeypatch 模擬 env / `sys` 狀態。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| 所有候選皆不存在 | `resolve_external_dir` → `None`;`resolve_base_dir` → `dev_root` |
| 候選為一般檔案 | 跳過(不視為命中) |
| `NUITKA_ONEFILE_PARENT` 指向死 PID | `/proc/{pid}/exe` 不存在 → 跳過,續用下一候選 |
| 執行檔位於 `/tmp/onefile_*` | 該候選拒用(即使目錄真的存在) |

## 5. 相依與假設 (Dependencies & Assumptions)

- 僅依賴標準庫(`os` / `sys` / `pathlib`)。
- `/proc/self/exe` 相關案例僅在 Linux 有意義,測試以 `skipif(not linux)` 保護。
- 測試目錄名一律帶 uuid,避免誤中真實 python bin 目錄或 `/app` 下的同名目錄
  (本機存在 `/app` 時 REQ-04 的優先序測試仍須成立)。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-runtime-paths-01 | TC-runtime-paths-01 | `tests/test_runtime_paths.py::test_external_dir_found_under_dev_root` |
| REQ-runtime-paths-02 | TC-runtime-paths-02 | `::test_external_dir_returns_none_when_nowhere` |
| REQ-runtime-paths-03 | TC-runtime-paths-03 | `::test_external_dir_ignores_plain_file` |
| REQ-runtime-paths-04 | TC-runtime-paths-04 | `::test_external_dir_sys_executable_beats_dev_root` |
| REQ-runtime-paths-05 | TC-runtime-paths-05 | `::test_external_dir_rejects_tmp_onefile_executable` |
| REQ-runtime-paths-06 | TC-runtime-paths-06 | `::test_base_dir_dev_mode_returns_dev_root` |
| REQ-runtime-paths-07 | TC-runtime-paths-07 | `::test_base_dir_frozen_uses_real_executable_dir` |
| REQ-runtime-paths-08 | TC-runtime-paths-08, TC-runtime-paths-09 | `::test_base_dir_nuitka_parent_pid_resolves_parent_exe`、`::test_base_dir_invalid_nuitka_pid_falls_back_to_self_exe` |
| REQ-runtime-paths-09 | TC-runtime-paths-10 | `::test_base_dir_nuitka_compiled_marker_detected` |

(測試腳本欄位省略共同前綴 `tests/test_runtime_paths.py`。)
