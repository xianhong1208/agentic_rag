
"""Admin 設定 API + 設定主控台頁(執行期熱改;feat/runtime-settings)。

- GET  /admin                     — 設定主控台(HTML;頁內輸入 token 呼叫 API)
- GET  /api/admin/settings        — 白名單設定視圖(生效值/級別/覆寫狀態)
- PUT  /api/admin/settings        — 熱改({"settings": {路徑: 值}});全有全無驗證
- DELETE /api/admin/settings/{path} — 移除單條覆寫,還原 config.yaml 原值
- POST /api/admin/probe           — 測模型服務連線(GET {base_url}/models)

auth:**免認證**(2026-09 產品決策,與 media 端點同一語義)— 開根網址
即用。要上鎖時把 _AUTH 改回 [Depends(authenticate_request)]。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.log import get_api_logger, mask_token

logger = get_api_logger()

router = APIRouter(tags=["Admin: Runtime Settings"])

# Control Center 資料面(唯讀彙總)與管理面(CRUD/索引操作)掛進同一模組
from src.api.router.admin_overview import router as _overview_router  # noqa: E402
from src.api.router.admin_manage import router as _manage_router  # noqa: E402
router.include_router(_overview_router)
router.include_router(_manage_router)


# 產品決策(2026-09-03,用戶指示,與 media 端點同一決策):設定主控台
# **免認證** — 開根網址即用,不輸入 token。提權/匿名疑慮已向用戶揭示,
# 適用內網部署;要上鎖時把 _AUTH 改回 [Depends(authenticate_request)]。
_AUTH: list = []


@router.get("/api/admin/settings", dependencies=_AUTH)
async def get_settings():
    """目前生效的可熱改設定(白名單全表;secret 遮罩)。"""
    from src.adapter import runtime_settings_service as svc
    return {"data": svc.get_settings_view(), "message": "ok"}


@router.put("/api/admin/settings", dependencies=_AUTH)
async def put_settings(
    request: Request,
    body: Dict[str, Any] = Body(..., example={"settings": {"rag.rerank.score_threshold": 0.3}}),
):
    """套用一批設定(驗證全過才寫;寫入即生效並持久化,重啟不丟)。"""
    patch = body.get("settings") or {}
    if not isinstance(patch, dict) or not patch:
        raise HTTPException(422, "body 需為 {\"settings\": {\"<路徑>\": <值>, ...}}")
    # 免認證模式下 token 可選 — 有帶就進稽核欄,沒帶記 console
    auth = request.headers.get("Authorization", "")
    updated_by = mask_token(auth[7:]) if auth.startswith("Bearer ") else "console"
    from src.adapter import runtime_settings_service as svc
    try:
        applied, warnings = svc.apply_settings(patch, updated_by=updated_by)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {
        "data": {"applied": applied, "warnings": warnings},
        "message": f"已套用 {len(applied)} 項設定" + ("(含警告)" if warnings else ""),
    }


@router.delete("/api/admin/settings/{path:path}", dependencies=_AUTH)
async def delete_setting(path: str):
    """移除單條覆寫 → 還原 config.yaml 出廠值(即刻生效)。"""
    from src.adapter import runtime_settings_service as svc
    try:
        removed = svc.reset_setting(path)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not removed:
        raise HTTPException(404, f"{path} 沒有執行期覆寫")
    return {"data": {"reset": path}, "message": f"{path} 已還原出廠值"}


@router.post("/api/admin/probe", dependencies=_AUTH)
async def probe_endpoint(
    body: Dict[str, Any] = Body(..., example={"base_url": "http://localhost:7075/v1", "api_key": "..."}),
):
    """測模型服務連線:GET {base_url}/models(OpenAI 相容面;vLLM/rerank 服務通用)。

    只回可達性與模型清單 — 不代表推論一定成功,但能抓出網址打錯/服務沒起。

    SSRF 評註(安全審查 2026-09-03):此端點**設計目的**就是探測內網模型
    服務(localhost vLLM 等),封鎖 loopback/private 網段會毀掉功能,故不做
    IP 網段過濾。已做的收斂:①固定 GET /models、不回應原始 body(只抽
    model id)②不跟隨 redirect ③錯誤只回例外類名,不回顯原始訊息。
    殘餘風險 = 可對內網做 HTTP GET 可達性探測;免認證為用戶產品決策
    (2026-09,內網部署、與 media 端點同一風險模型),要上鎖改 _AUTH。
    """
    base_url = (body.get("base_url") or "").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "base_url 需為 http(s) 網址")
    headers = {}
    if body.get("api_key"):
        headers["Authorization"] = f"Bearer {body['api_key']}"
    try:
        async with httpx.AsyncClient(
            timeout=5.0, headers=headers, follow_redirects=False,
        ) as client:
            resp = await client.get(f"{base_url}/models")
        ok = resp.status_code < 500
        models = []
        try:
            models = [m.get("id") for m in resp.json().get("data", [])][:10]
        except Exception:
            pass
        return {"data": {"reachable": ok, "status_code": resp.status_code,
                         "models": models}, "message": "probe done"}
    except Exception as e:
        # 只回例外類名(ConnectError / ConnectTimeout…)— 足夠指出問題方向,
        # 不回顯原始訊息(可能含內部位址/路徑細節)
        return {"data": {"reachable": False, "error": type(e).__name__},
                "message": "probe failed"}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page():
    """設定主控台(單頁;token 由頁內輸入,僅存瀏覽器 localStorage)。

    產品門面:根網址(http://host:port/)即設定頁 — module router 先於
    index router 註冊,此 "/" 蓋過原 landing page(原 API 說明頁改由
    /docs Swagger 承擔)。/admin 為同頁別名。
    """
    from src.api.router.admin_page_html import ADMIN_PAGE_HTML
    from src.api.router.index import _logo_data_uri
    html = ADMIN_PAGE_HTML.replace("%%LOGO%%", _logo_data_uri() or "")
    return HTMLResponse(html)
