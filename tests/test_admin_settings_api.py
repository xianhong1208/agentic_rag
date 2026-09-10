
"""Admin 設定 API 契約(feat/runtime-settings)。

service 層邏輯在 test_runtime_settings.py;這裡釘 HTTP 面:
路由/狀態碼/回應形狀/錯誤轉譯(422)/probe 防呆/admin 頁可取。
免認證(產品決策 2026-09):端點不掛 auth,測試直接打。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router.admin_settings import router

_SVC = "src.adapter.runtime_settings_service"


@pytest.fixture()
def client():
    # 免認證(產品決策)— 不需任何 override,端點原樣可打
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestSettingsApi:
    def test_get_settings_shape(self, client):
        view = {"settings": [{"path": "rag.rerank.enabled", "value": True,
                              "level": "live", "overridden": False, "secret": False}]}
        with patch(f"{_SVC}.get_settings_view", return_value=view):
            r = client.get("/api/admin/settings")
        assert r.status_code == 200
        assert r.json()["data"] == view

    def test_put_applies_and_reports_warnings(self, client):
        with patch(f"{_SVC}.apply_settings",
                   return_value=({"rag.embedding.model": "m"}, ["警告文案"])) as ap:
            r = client.put("/api/admin/settings",
                           json={"settings": {"rag.embedding.model": "m"}})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["applied"] == {"rag.embedding.model": "m"}
        assert body["data"]["warnings"] == ["警告文案"]
        # 免認證:沒帶 Authorization → 稽核欄記 console
        assert ap.call_args.kwargs.get("updated_by") == "console"

    def test_put_with_bearer_records_masked_token(self, client):
        with patch(f"{_SVC}.apply_settings", return_value=({}, [])) as ap:
            client.put("/api/admin/settings",
                       json={"settings": {"rag.rerank.enabled": True}},
                       headers={"Authorization": "Bearer secret-token-xyz-12345"})
        ub = str(ap.call_args.kwargs.get("updated_by"))
        assert "secret-token-xyz-12345" not in ub  # 只進遮罩形

    def test_put_empty_body_422(self, client):
        assert client.put("/api/admin/settings", json={}).status_code == 422
        assert client.put("/api/admin/settings",
                          json={"settings": {}}).status_code == 422

    def test_put_validation_error_becomes_422(self, client):
        with patch(f"{_SVC}.apply_settings", side_effect=ValueError("不可熱改的設定路徑")):
            r = client.put("/api/admin/settings",
                           json={"settings": {"database.url": "x"}})
        assert r.status_code == 422
        assert "不可熱改" in r.json()["detail"]

    def test_delete_resets_override(self, client):
        with patch(f"{_SVC}.reset_setting", return_value=True):
            r = client.delete("/api/admin/settings/rag.rerank.score_threshold")
        assert r.status_code == 200
        assert r.json()["data"]["reset"] == "rag.rerank.score_threshold"

    def test_delete_no_override_404(self, client):
        with patch(f"{_SVC}.reset_setting", return_value=False):
            assert client.delete(
                "/api/admin/settings/rag.rerank.score_threshold").status_code == 404


class TestProbe:
    def test_rejects_non_http_url(self, client):
        r = client.post("/api/admin/probe", json={"base_url": "ftp://x"})
        assert r.status_code == 422

    def test_reachable_lists_models(self, client):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": [{"id": "m1"}, {"id": "m2"}]}
        ac = MagicMock()
        ac.__aenter__ = AsyncMock(return_value=ac)
        ac.__aexit__ = AsyncMock(return_value=False)
        ac.get = AsyncMock(return_value=resp)
        with patch("src.api.router.admin_settings.httpx.AsyncClient", return_value=ac):
            r = client.post("/api/admin/probe",
                            json={"base_url": "http://svc:8000/v1", "api_key": "k"})
        d = r.json()["data"]
        assert d["reachable"] is True and d["models"] == ["m1", "m2"]

    def test_unreachable_reports_error(self, client):
        ac = MagicMock()
        ac.__aenter__ = AsyncMock(return_value=ac)
        ac.__aexit__ = AsyncMock(return_value=False)
        ac.get = AsyncMock(side_effect=OSError("conn refused at 10.0.0.5:8080"))
        with patch("src.api.router.admin_settings.httpx.AsyncClient", return_value=ac):
            r = client.post("/api/admin/probe", json={"base_url": "http://down:1/v1"})
        d = r.json()["data"]
        # 只回例外類名 — 原始訊息(可能含內部位址)不得回顯
        assert d["reachable"] is False and d["error"] == "OSError"
        assert "10.0.0.5" not in str(d)

    def test_probe_does_not_follow_redirects(self, client):
        resp = MagicMock(status_code=302)
        resp.json.side_effect = ValueError
        ac = MagicMock()
        ac.__aenter__ = AsyncMock(return_value=ac)
        ac.__aexit__ = AsyncMock(return_value=False)
        ac.get = AsyncMock(return_value=resp)
        with patch("src.api.router.admin_settings.httpx.AsyncClient", return_value=ac) as C:
            client.post("/api/admin/probe", json={"base_url": "http://svc:8000/v1"})
        assert C.call_args.kwargs.get("follow_redirects") is False


class TestAdminPage:
    def test_root_serves_console(self, client):
        # 產品門面:根網址即設定頁
        r = client.get("/")
        assert r.status_code == 200 and "Control Center" in r.text

    def test_page_served(self, client):
        r = client.get("/admin")
        assert r.status_code == 200
        assert "Agentic RAG" in r.text and "Control Center" in r.text
        # 外部資源僅允許 Google Fonts(對齊 MCP_Center 設計語言;離線時
        # fallback stack 降級,版面不壞)— 其餘一律 inline
        import re
        externals = set(re.findall(r'https?://([^/"]+)', r.text))
        # www.w3.org 是 inline SVG 的 xmlns 宣告,非網路請求
        assert externals <= {"fonts.googleapis.com", "fonts.gstatic.com", "www.w3.org"}, externals


class TestAdminHtmlLoader:
    """主控台 HTML 抽成 web/admin_console.html 後的載入器行為。"""

    def test_reads_real_file(self):
        from src.api.router import admin_page_html as m
        html = m._load_admin_html()
        assert html.startswith("<!DOCTYPE html>") and "%%LOGO%%" in html

    def test_fallback_when_missing(self):
        from src.api.router import admin_page_html as m
        # 所有候選路徑都不存在 → 回明確 fallback 頁,不崩、不回空
        with patch("src.utils.runtime_paths.resolve_external_dir", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            html = m._load_admin_html()
        assert "admin_console.html not found" in html
