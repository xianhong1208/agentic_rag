
"""Runtime path resolution for dev / Nuitka / Docker deployments.

為什麼這個檔案存在
----------------
`Path(__file__).parent / "xxx"` 是 Python 專案查找「專案根目錄下的資源」最常見
的慣例，在 dev 模式下完全正確，但在 **Nuitka onefile 模式下會壞掉**：
- Nuitka onefile 啟動時會把整個壓縮包解到 `/tmp/onefile_<pid>_<rnd>/` 臨時目錄
- 解壓目錄裡的 `__file__` 指向 `/tmp/onefile_xxxx/src/domain/rag/foo.py`
- 於是 `Path(__file__).parent / "config"` 變成 `/tmp/onefile_xxxx/config/`
- 但使用者部署時把真正的 `config/` 放在 binary 旁邊（或 Docker volume mount 到
  `/app/config`），根本不在解壓目錄裡
- 結果 code 讀到的是 Nuitka 打包當下的舊 config snapshot，不是使用者改過的

這個檔案提供 `resolve_external_dir(name, dev_root)`，統一處理：
1. Nuitka onefile：用 `NUITKA_ONEFILE_PARENT` env var + `/proc/<pid>/exe` 找到
   真正的 binary 位置
2. Nuitka standalone：用 `sys.executable` 或 `/proc/self/exe`
3. Docker container：硬寫的 `/app/{name}` 慣例
4. Dev 模式：呼叫端傳進來的 `dev_root`
5. Fallback 到 onefile 解壓目錄的 bundled copy（最後手段）

優先順序的關鍵決定：**`/app/{name}` 要排在 dev_root 前面**，因為 Docker volume
mount 必須贏過 onefile bundled copy。否則使用者 `docker run -v ./config:/app/config`
掛上去的 config 會被 bundled 的舊 snapshot 蓋掉。

相關 bug 歷史
----------------
- 2026-04-09: 在 production Docker + Nuitka onefile 環境發現 app.py 讀到
  `/tmp/onefile_1_1775725057_21650/config/instructions.md` 而不是 mounted
  `/app/config/instructions.md`，就是這個檔案存在的原因。
- 2026-04-09: 把 `db/migrate.py:get_external_base_dir()` 的重複偵測邏輯
  （原本自己寫一份 `_get_real_executable_path()` + `__compiled__` 偵測 +
  config marker check）統一到本模組。migrate.py 現在透過
  `resolve_external_dir("config", ...).parent` 取得 base directory，
  因為 config 和 versions 在每種部署模式下都是兄弟目錄，找到 config
  就知道 base 在哪。原本「避免反向 import」的顧慮已過時：migrate.py
  早就在 import `src.log` 和 `src.config.config_manager`。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional


def resolve_external_dir(name: str, dev_root: Path) -> Optional[Path]:
    """Locate an external resource directory across deployment modes.

    Args:
        name: 目錄名稱（例如 "config"、"assets"、"nltk_data"）
        dev_root: dev 模式下專案根目錄的 Path（呼叫端根據自己的位置計算，
            例如 app.py 用 `Path(__file__).resolve().parent`，
            src/domain/rag/docling_loader.py 用 `Path(__file__).resolve().parents[3]`）

    Returns:
        第一個存在的候選目錄，全部都找不到回傳 None。

    候選順序（由高到低）：
        ① `NUITKA_ONEFILE_PARENT` 父 process 的執行檔旁邊 / name
           — onefile 模式唯一可靠的定位方式
        ② `/proc/self/exe` 旁邊 / name
           — Linux 通用，拒絕 /tmp/onefile_* 假路徑
        ③ `sys.executable` 旁邊 / name
           — Nuitka standalone 非 onefile
        ④ `/app/{name}`
           — Docker container 慣例。刻意排在 ⑤ 之前，確保 volume mount
             的真實路徑永遠贏過 onefile bundled copy
        ⑤ `dev_root / name`
           — dev 模式主力路徑，也是 onefile bundled copy 的最後 fallback
    """
    candidates: List[Path] = []

    # ① Nuitka onefile: NUITKA_ONEFILE_PARENT 是啟動 onefile binary 的父 process PID
    nuitka_parent = os.environ.get("NUITKA_ONEFILE_PARENT")
    if nuitka_parent:
        try:
            parent_exe = Path(f"/proc/{nuitka_parent}/exe").resolve()
            if parent_exe.exists():
                candidates.append(parent_exe.parent / name)
        except (OSError, ValueError):
            pass

    # ② Linux 通用：/proc/self/exe 永遠指向當前 process 真正在執行的 binary。
    # 拒絕 /tmp/onefile_* 假路徑（onefile 解壓目錄裡的那顆 binary）
    if sys.platform.startswith("linux"):
        try:
            proc_exe = Path("/proc/self/exe").resolve()
            if not str(proc_exe).startswith("/tmp/onefile_"):
                candidates.append(proc_exe.parent / name)
        except (OSError, ValueError):
            pass

    # ③ Nuitka standalone（非 onefile）：sys.executable 就是真正的 binary
    try:
        exe_path = Path(sys.executable).resolve()
        if not str(exe_path).startswith("/tmp/onefile_"):
            candidates.append(exe_path.parent / name)
    except (OSError, ValueError):
        pass

    # ④ Docker container 寫死路徑。刻意排在 dev_root 之前，
    # 讓 volume mount 的真實內容贏過 onefile bundled copy
    candidates.append(Path(f"/app/{name}"))

    # ⑤ Dev 模式 / onefile bundled fallback
    candidates.append(dev_root / name)

    for p in candidates:
        if p.is_dir():
            return p
    return None


def resolve_base_dir(dev_root: Path) -> Path:
    """Locate the writable base directory across deployment modes.

    跟 resolve_external_dir 同一套 priority,差別:
      - resolve_external_dir 要求**子目錄存在**,適合查找已 bundled 的 read-only
        資源(config, assets, nltk_data)
      - resolve_base_dir 回傳「base 在哪」,**不要求任何子目錄存在** — 適合
        writable output dir(storage, cache),第一次部署該目錄還不存在

    Args:
        dev_root: dev 模式下專案根目錄的 Path(對應 caller 自己算)

    Returns:
        最高優先級且能通過 ephemeral 過濾的 base dir。永遠回傳一個 Path(最終
        fallback 是 dev_root),不會回傳 None。

    候選順序:
        ①-③ 只在 compiled binary 模式試(避免 dev 模式把 /usr/local/bin 當 base):
          ① NUITKA_ONEFILE_PARENT 父 process 的 binary dir
          ② /proc/self/exe 的 binary dir(拒 /tmp/onefile_*)
          ③ sys.executable 的 binary dir(拒 /tmp/onefile_*)
        ④ dev_root  ── 最終 fallback(plain Python 在 Docker WORKDIR /app 跑
                       時,dev_root = parents[2] 算出來剛好 = /app,自動對)

    為什麼要先偵測 is_compiled:
        Plain Python 跑時 /proc/self/exe 是 `/usr/local/bin/python`,parent 是
        系統 bin 目錄,絕對不是該寫 storage 的地方。`resolve_external_dir` 沒
        這問題是因為它有 .is_dir() 兜底,我們不能用同套兜底所以要先過濾。

    為什麼不直接走 /app fallback:
        某些 dev 環境(例如本機就是有 /app symlink)會誤判。compiled mode 都
        有 ① ② ③ 兜住,plain Python 算 dev_root 也對得上 — /app 那條不必要。
    """
    main_mod = sys.modules.get("__main__")
    is_compiled = (
        getattr(sys, "frozen", False)  # PyInstaller
        or (main_mod is not None and hasattr(main_mod, "__compiled__"))  # Nuitka
        or "NUITKA_ONEFILE_PARENT" in os.environ  # Nuitka onefile redundant signal
    )

    if is_compiled:
        # ① Nuitka onefile parent process
        nuitka_parent = os.environ.get("NUITKA_ONEFILE_PARENT")
        if nuitka_parent:
            try:
                parent_exe = Path(f"/proc/{nuitka_parent}/exe").resolve()
                if parent_exe.exists():
                    return parent_exe.parent
            except (OSError, ValueError):
                pass

        # ② Linux /proc/self/exe
        if sys.platform.startswith("linux"):
            try:
                proc_exe = Path("/proc/self/exe").resolve()
                if not str(proc_exe).startswith("/tmp/onefile_"):
                    return proc_exe.parent
            except (OSError, ValueError):
                pass

        # ③ sys.executable
        try:
            exe_path = Path(sys.executable).resolve()
            if not str(exe_path).startswith("/tmp/onefile_"):
                return exe_path.parent
        except (OSError, ValueError):
            pass

    # ④ Dev fallback
    return dev_root
