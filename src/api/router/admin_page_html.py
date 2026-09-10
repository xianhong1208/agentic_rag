
"""Agentic RAG Control Center — 主控台 HTML 載入器。

HTML/CSS/JS 本體已抽出成獨立檔:`web/admin_console.html`(不再內嵌成 Python
字串,方便前端獨立編輯 / diff / 語法高亮)。此模組只在 import 時把它讀進
`ADMIN_PAGE_HTML`(維持原變數名,呼叫端 admin_settings 不需改)。

放 top-level `web/`(進 git、隨 app 出貨)而非 `assets/`(GB 模型,刻意不進
git/image、部署 volume 掛入)—— 主控台 HTML 是程式碼,必須隨 build 走。
打包:Nuitka 打包設定的 `data_dirs` 需含 `web`(比照 `config`),Nuitka
以 data file 帶上。路徑解析走 onefile-aware 的 `resolve_external_dir("web", …)`
(與 config 同一套),dev / Docker / Nuitka onefile 三種部署都能定位。
"""

from pathlib import Path

from src.log import get_api_logger

logger = get_api_logger()

_HTML_NAME = "admin_console.html"


def _load_admin_html() -> str:
    """讀取主控台 HTML(import 時執行一次)。找不到時回極簡 fallback 頁,不讓 import 崩。"""
    dev_root = Path(__file__).resolve().parents[3]  # repo root(src/api/router → 上三層)
    candidates = []
    try:
        from src.utils.runtime_paths import resolve_external_dir
        web = resolve_external_dir("web", dev_root)
        if web:
            candidates.append(web / _HTML_NAME)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[ADMIN_HTML] resolve_external_dir unavailable: {e}")
    candidates.append(dev_root / "web" / _HTML_NAME)  # dev / onefile bundled fallback
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ADMIN_HTML] read failed {p}: {e}")
    logger.error(f"[ADMIN_HTML] admin_console.html not found (looked: {[str(c) for c in candidates]})")
    return ("<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'>"
            "<h2>Agentic RAG Control Center</h2><p>admin_console.html not found — "
            "confirm <code>web/admin_console.html</code> ships with the build "
            "(the packaging config data_dirs must include <code>web</code>).</p>"
            "</body></html>")


ADMIN_PAGE_HTML = _load_admin_html()
