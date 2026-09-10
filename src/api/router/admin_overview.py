
"""Control Center 資料面 API(唯讀彙總;掛進 admin 模組 router)。

- GET /api/admin/overview            — 總覽 KPI(folder/file/index/job)
- GET /api/admin/folders             — 全 folder + 索引彙總
- GET /api/admin/folders/{id}/files  — 單 folder 檔案級索引狀態
- GET /api/admin/jobs                — 近期 index job

auth 語義與設定 API 相同(免認證,產品決策 — 見 admin_settings.py)。
全部唯讀,不觸發任何索引/刪除動作。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from src.log import get_api_logger

logger = get_api_logger()

router = APIRouter(tags=["Admin: Overview"])

# 檢索評測(harness)背景執行狀態 — 單一 in-memory 執行槽(評測非高頻)。
_EVAL: dict = {"running": False, "folder": None, "done": 0, "total": 0,
               "result": None, "error": None, "started_at": None}


def _load_eval_mod():
    """載入 scripts/rag_eval.py(非套件,用 importlib 直載)。"""
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    path = os.path.join(root, "scripts", "rag_eval.py")
    spec = importlib.util.spec_from_file_location("rag_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_EVAL_TASK = None  # 保留 task 參考,避免被 GC(Task 物件不放進 _EVAL,否則 status 無法 JSON 序列化)


async def _run_eval_bg(folder_ref: str, n: int, k: int, regenerate: bool) -> None:
    """評測本體:**跑在主 event loop**(與快取的 PGVectorStore async engine 同 loop,
    避免 asyncpg『attached to a different loop』)。結果/錯誤寫回 _EVAL。"""
    try:
        mod = _load_eval_mod()
        _EVAL["result"] = await mod.run_eval_async(
            folder_ref, n=n, k=k, regenerate=regenerate,
            progress=lambda d, t: _EVAL.update(done=d, total=t))
    except Exception as e:  # noqa: BLE001 — 背景執行,錯誤存起來給 status 回報
        _EVAL["error"] = str(e)
        logger.warning(f"[EVAL] run failed: {e}")
    finally:
        _EVAL["running"] = False


@router.post("/api/admin/eval/run")
async def eval_run(body: dict = Body(default={}, example={"folder_id": 1, "n": 15})):
    """啟動一次檢索評測(主 loop 背景 task;生成合成問題 → 三路檢索 → nDCG/Recall/MRR)。

    reindex 後請帶 regenerate=true(node_id 變,舊標註集失效)。"""
    import asyncio
    import time
    global _EVAL_TASK
    if _EVAL["running"]:
        raise HTTPException(409, "An evaluation is already running")
    folder_ref = str(body.get("folder_id") or body.get("folder") or "").strip()
    if not folder_ref:
        raise HTTPException(422, "folder_id (or folder name) is required")
    n, k = int(body.get("n", 15)), int(body.get("k", 10))
    regen = bool(body.get("regenerate", False))
    _EVAL.update(running=True, folder=folder_ref, done=0, total=n,
                 result=None, error=None, started_at=time.time())
    # 主 loop 上跑(不開新執行緒/新 loop)—— 共用同一個 asyncpg 連線池不會跨 loop
    _EVAL_TASK = asyncio.create_task(_run_eval_bg(folder_ref, n, k, regen))
    return {"data": {"started": True}, "message": "evaluation started"}


@router.get("/api/admin/eval/status")
async def eval_status():
    """評測進度 / 結果(前端輪詢)。"""
    return {"data": dict(_EVAL), "message": "ok"}


@router.get("/api/admin/eval/report")
async def eval_report(folder_id: int = Query(...)):
    """讀該 folder 最近一次評測報告(reports/rag_eval_<name>.json);無則回 null。"""
    import json
    import os
    from db.cached_folderdb import CachedFolderDB
    folder = CachedFolderDB.get_by_id(folder_id)
    if not folder:
        raise HTTPException(404, f"Folder {folder_id} not found")
    slug = str(folder.name).replace("/", "_")
    path = os.path.join("reports", f"rag_eval_{slug}.json")
    if not os.path.exists(path):
        return {"data": None, "message": "no report yet"}
    with open(path, encoding="utf-8") as f:
        return {"data": json.load(f), "message": "ok"}


@router.get("/api/admin/overview")
async def get_overview():
    """總覽 KPI + 進行中 job + 目前模型配置摘要。"""
    from db import admin_stats
    from src.config import runtime_overrides as ro
    from src.config.config_manager import Config

    data = admin_stats.overview()
    try:
        data["trend"] = admin_stats.indexing_trend(7)
    except Exception:
        data["trend"] = []
    # 模型配置摘要(給總覽頁的服務卡;沿用設定白名單的遮罩語義)
    cfg = Config.get_config_model()
    eff = ro.get_effective(cfg) if cfg else {}
    try:
        from src.version import get_version
        data["version"] = get_version()
    except Exception:
        data["version"] = None
    data["models"] = {
        "embedding": {"model": eff.get("rag.embedding.model"),
                      "dimension": eff.get("rag.embedding.dimension"),
                      "base_url": eff.get("rag.embedding.base_url")},
        "llm": {"model": eff.get("rag.llm.model"), "base_url": eff.get("rag.llm.base_url")},
        "rerank": {"enabled": eff.get("rag.rerank.enabled"),
                   "model": eff.get("rag.rerank.model"),
                   "base_url": eff.get("rag.rerank.base_url")},
        "asr": {"enabled": eff.get("rag.asr.enabled"),
                "provider": eff.get("rag.asr.provider"),
                "available": _asr_available(cfg)},
    }
    return {"data": data, "message": "ok"}


def _asr_available(cfg) -> bool:
    """ASR provider 就緒與否(fireredasr = 權重在;docling-whisper = .pt 在;
    雲端 = 設定齊)。檔案存在性檢查,便宜、不載模型。"""
    try:
        from src.domain.rag.asr_provider import create_asr_provider
        asr_cfg = getattr(getattr(cfg, "rag", None), "asr", None)
        return bool(create_asr_provider(asr_cfg).available())
    except Exception:
        return False


@router.get("/api/admin/folders")
async def list_folders():
    """全部 folder + 各自索引彙總(檔案數/已索引/失敗/chunks/向量表)。"""
    from db import admin_stats
    return {"data": {"folders": admin_stats.folders_with_index_stats()}, "message": "ok"}


@router.get("/api/admin/folders/{folder_id}/files")
async def list_folder_files(folder_id: int):
    """單一 folder 的檔案級索引狀態(含失敗原因截斷)。"""
    from db import admin_stats
    files = admin_stats.files_with_index_status(folder_id)
    return {"data": {"folder_id": folder_id, "files": files}, "message": "ok"}


@router.get("/api/admin/active-stages")
async def active_stages():
    """目前正在索引的檔案在哪個階段({file_id: {stage,done,total,eta}})—
    檔案清單即時顯示「解析/生成上下文/向量化/寫入」用。"""
    from src.domain.rag.index_job_manager import IndexingJobManager
    return {"data": {"stages": IndexingJobManager.get_instance().active_file_stages()},
            "message": "ok"}


@router.get("/api/admin/folders/{folder_id}/files/{file_id}/chunks")
async def list_file_chunks(folder_id: int, file_id: str,
                           limit: int = Query(500, ge=1, le=2000)):
    """某檔切好的 leaf chunks(客戶檢視索引長相)。"""
    from db import admin_stats
    return {"data": admin_stats.chunks_for_file(folder_id, file_id, limit), "message": "ok"}


@router.get("/api/admin/audit")
async def settings_audit(limit: int = Query(100, ge=1, le=500)):
    """設定變更稽核記錄(誰在何時把什麼改成什麼)。"""
    from src.adapter import runtime_settings_service as svc
    return {"data": {"entries": svc.audit_log(limit)}, "message": "ok"}


@router.get("/api/admin/resources")
async def system_resources_endpoint():
    """系統資源:DB 大小 / 向量表大小 / 磁碟。"""
    from db import admin_stats
    return {"data": admin_stats.system_resources(), "message": "ok"}


@router.get("/api/admin/jobs")
async def list_jobs(limit: int = Query(20, ge=1, le=100)):
    """近期 index job(依最後更新排序)。"""
    from db import admin_stats
    return {"data": {"jobs": admin_stats.recent_jobs(limit)}, "message": "ok"}


@router.get("/api/admin/analytics")
async def query_analytics(
    folder_id: int | None = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """查詢分析:查詢量 / 平均延遲 / 零結果率 / 熱門查詢 / 每日趨勢。

    folder_id 省略 = 全部資料夾;days = 統計視窗。資料源為 QueryLog
    (每次 /query 檢索 best-effort 記一筆)。"""
    from db.query_log_db import QueryLogDB
    return {"data": QueryLogDB.analytics(folder_id=folder_id, days=days), "message": "ok"}


async def _probe_endpoint_health(base_url: str, api_key: str | None):
    """探測一個 OpenAI 相容端點(GET {base_url}/models),回 (status, detail, latency_ms)。

    SSRF 語義同 admin_settings.probe_endpoint:設計目的即探測內網模型服務,
    不做網段過濾;固定 GET /models、不跟隨 redirect、錯誤只回例外類名。
    """
    import time

    import httpx
    base = (base_url or "").rstrip("/")
    if not base:
        return "unset", "No endpoint configured", None
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers, follow_redirects=False) as c:
            resp = await c.get(f"{base}/models")
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code < 500:
            return "ok", f"HTTP {resp.status_code}", ms
        return "down", f"HTTP {resp.status_code}", ms
    except Exception as e:  # noqa: BLE001 — 只回類名,不回顯內部細節
        return "down", type(e).__name__, int((time.perf_counter() - t0) * 1000)


def _probe_db_health():
    """同步探測 DB(SELECT 1),回 (status, detail, latency_ms)。由 to_thread 呼叫。"""
    import time
    from sqlalchemy import text
    from db.db import get_engine
    t0 = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok", "Connection verified", int((time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        return "down", type(e).__name__, int((time.perf_counter() - t0) * 1000)


@router.get("/api/admin/health")
async def health_check():
    """外部依賴即時健康度:DB / Embedding / LLM / Reranker / Speech-to-Text。

    運維一眼看穿連線/端點問題(取代事後翻 log)。每項回 status(ok/down/
    disabled/unset)、detail、latency_ms、endpoint。"""
    import asyncio

    from src.config import runtime_overrides as ro
    from src.config.config_manager import Config

    cfg = Config.get_config_model()
    # 需要未遮罩 api_key 才能真的帶 Authorization 探測(遮罩值 ••• 非 latin-1
    # 會讓 httpx header 編碼炸 UnicodeEncodeError);金鑰只用於送出,不回傳。
    eff = ro.get_effective(cfg, mask_secrets=False) if cfg else {}
    checks = []

    # DB(同步 engine,丟 threadpool 不佔 loop)
    db_status, db_detail, db_ms = await asyncio.to_thread(_probe_db_health)
    checks.append({"name": "Database", "kind": "db", "status": db_status,
                   "detail": db_detail, "latency_ms": db_ms,
                   "endpoint": (getattr(getattr(cfg, "database", None), "url", "") or "").split("@")[-1]})

    # 端點類(embedding / llm / rerank)— 並行探測
    endpoint_specs = [
        ("Embedding", "layers", eff.get("rag.embedding.base_url"), eff.get("rag.embedding.api_key"), True),
        ("LLM", "spark", eff.get("rag.llm.base_url"), eff.get("rag.llm.api_key"), True),
        ("Reranker", "sort", eff.get("rag.rerank.base_url"), eff.get("rag.rerank.api_key"),
         bool(eff.get("rag.rerank.enabled"))),
    ]
    probe_tasks = [
        _probe_endpoint_health(url, key) if enabled else None
        for _, _, url, key, enabled in endpoint_specs
    ]
    results = await asyncio.gather(*[t for t in probe_tasks if t is not None])
    ri = 0
    for (name, icon, url, _key, enabled) in endpoint_specs:
        if not enabled:
            checks.append({"name": name, "kind": icon, "status": "disabled",
                           "detail": "Disabled in settings", "latency_ms": None, "endpoint": url or ""})
            continue
        status, detail, ms = results[ri]; ri += 1
        checks.append({"name": name, "kind": icon, "status": status,
                       "detail": detail, "latency_ms": ms, "endpoint": url or ""})

    # ASR(本地權重或雲端設定就緒與否;非 HTTP 探測)
    asr_enabled = bool(eff.get("rag.asr.enabled"))
    asr_provider = eff.get("rag.asr.provider") or "—"
    if not asr_enabled:
        checks.append({"name": "Speech-to-Text", "kind": "mic", "status": "disabled",
                       "detail": "Disabled in settings", "latency_ms": None, "endpoint": asr_provider})
    else:
        avail = _asr_available(cfg)
        checks.append({"name": "Speech-to-Text", "kind": "mic",
                       "status": "ok" if avail else "down",
                       "detail": "Ready" if avail else "Model/weights not found",
                       "latency_ms": None, "endpoint": asr_provider})

    active = [c for c in checks if c["status"] not in ("disabled", "unset")]
    overall = "ok" if active and all(c["status"] == "ok" for c in active) else (
        "down" if any(c["status"] == "down" for c in active) else "unset")
    return {"data": {"checks": checks, "overall": overall}, "message": "ok"}
