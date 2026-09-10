
"""版本單一來源:pyproject.toml 的 [project].version。

歷史問題:config.yaml 的 app.version(1.1.5)和 pyproject.toml(0.1.0)
各說各話,升版只改其中一邊。現在只維護 pyproject.toml,config.yaml 不再
攜帶版本欄位。

與 coreagent(core/version.py)同模式:專案以 package 安裝進 .venv
(pyproject.toml 的 [build-system]),importlib.metadata 讀 dist-info。
打包(Nuitka)時 metadata 隨 site-packages(libs/)
一起帶出,部署產物不需要攜帶 pyproject.toml。

解析順序:
  ① importlib.metadata — 已安裝(uv sync 後)與打包部署的主力路徑
  ② 專案根的 pyproject.toml — 尚未 uv sync 的 dev checkout fallback
  ③ "0.0.0" + warning — 兩者都失敗(打包時 libs/ 漏了 dist-info)時服務
     仍可啟動,但版本顯眼地錯

注意:editable 安裝的 metadata 是 uv sync 當下的快照 — 升版 pyproject 後
要重新 sync,dev 環境版本才會跟上(CI 每次 fresh sync 沒這問題)。
"""
from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

logger = logging.getLogger(__name__)

_DISTRIBUTION_NAME = "agentic-rag"
# src/version.py → parents[1] = 專案根(dev checkout 的 pyproject.toml 所在)
_PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


@lru_cache(maxsize=1)
def get_version() -> str:
    """回傳應用版本字串(來源見模組 docstring)。"""
    try:
        return _pkg_version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        pass  # 尚未以 package 安裝(未 uv sync 的 dev checkout)— 走 pyproject.toml

    try:
        with _PYPROJECT_PATH.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        logger.warning(
            f"無法從 metadata 或 {_PYPROJECT_PATH} 解析版本({e});回傳 0.0.0。"
            f"打包部署請確認 libs/ 內含 agentic_rag 的 dist-info。"
        )
        return "0.0.0"
