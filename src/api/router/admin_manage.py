
"""Control Center 管理面 API — folder / file / index 的 CRUD 與操作。

設計:**act-as-owner** — folder 綁定 user_token(多租戶),console 對某
folder 的操作一律以「該 folder 的擁有者 token」呼叫既有 REST 端點函式
(folder_api / file_api / rag_indexing),讓 job-cancel、軟刪、向量清理、
儲存層等所有既有安全與清理邏輯零重複、單一真相。

- 建 folder 需帶 owner_token(綁定擁有者;使用者之後用該 token 存取)
- 無主 folder(user_token 空)→ 409,console 不代管(ACL fail-closed 語義)
- auth 語義同 admin 模組其他端點(免認證,產品決策)
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from src.log import get_api_logger

logger = get_api_logger()

router = APIRouter(tags=["Admin: Manage"])


def _owner(folder_id: int):
    """載入 folder 並回 (folder, owner_token);無主 folder 拒管。"""
    from db.cached_folderdb import CachedFolderDB
    folder = CachedFolderDB.get_by_id(folder_id)
    if not folder:
        raise HTTPException(404, f"Folder {folder_id} not found")
    if not folder.user_token:
        raise HTTPException(
            409, f"Folder {folder_id} has no owner token — console cannot manage it")
    return folder, folder.user_token


# ── Folder CRUD ─────────────────────────────────────────────────────────────

@router.post("/api/admin/manage/folders")
async def admin_create_folder(
    body: dict = Body(..., example={"name": "docs", "description": "", "owner_token": "…"}),
):
    """建 folder(owner_token 必填 — folder 綁定擁有者,使用者以該 token 存取)。"""
    name = (body.get("name") or "").strip()
    owner_token = (body.get("owner_token") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    if not owner_token:
        raise HTTPException(422, "owner_token is required — folders are token-scoped")
    from src.api.router.folder_api import create_folder
    from src.api.router.response import CreateFolderRequest
    return await create_folder(
        CreateFolderRequest(name=name, description=body.get("description")),
        user_token=owner_token,
    )


@router.patch("/api/admin/manage/folders/{folder_id}")
async def admin_update_folder(folder_id: int, body: dict = Body(...)):
    """改名/改描述(只 patch 有給的欄位)。"""
    _, token = _owner(folder_id)
    from src.api.router.folder_api import update_folder_api
    from src.api.router.response import UpdateFolderRequest
    return await update_folder_api(
        folder_id,
        UpdateFolderRequest(name=body.get("name"), description=body.get("description")),
        user_token=token,
    )


@router.delete("/api/admin/manage/folders/{folder_id}")
async def admin_delete_folder(folder_id: int):
    """刪 folder(沿用既有端點:先取消 in-flight job,再軟刪檔案與向量)。"""
    _, token = _owner(folder_id)
    from src.api.router.folder_api import delete_folder
    return await delete_folder(folder_id, user_token=token)


# ── File CRUD ───────────────────────────────────────────────────────────────

@router.post("/api/admin/manage/folders/{folder_id}/files")
async def admin_upload_file(
    folder_id: int,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    auto_index: bool = Form(True),
):
    """上傳檔案到 folder(auto_index=True 走既有背景索引流程)。"""
    _, token = _owner(folder_id)
    from src.api.router.file_api import upload_file
    return await upload_file(
        folder_id, file=file, description=description, tags=None,
        auto_index=auto_index, user_token=token,
    )


@router.get("/api/admin/manage/folders/{folder_id}/files/{file_id}/download")
async def admin_download_file(folder_id: int, file_id: UUID):
    _, token = _owner(folder_id)
    from src.api.router.file_api import download_file
    return await download_file(folder_id, file_id, user_token=token)


@router.delete("/api/admin/manage/folders/{folder_id}/files/{file_id}")
async def admin_delete_file(folder_id: int, file_id: UUID):
    """刪檔案(既有端點會一併清該檔的向量與索引記錄)。"""
    _, token = _owner(folder_id)
    from src.api.router.file_api import delete_file
    return await delete_file(folder_id, file_id, user_token=token)


# ── Index 操作 ──────────────────────────────────────────────────────────────

@router.post("/api/admin/manage/folders/{folder_id}/index")
async def admin_index_folder(
    folder_id: int,
    body: dict = Body(default={}, example={"skip_existing": True}),
):
    """啟動整個 folder 的背景索引 job。

    - skip_existing=True(增量):只補沒有索引記錄的檔案
    - skip_existing=False(全量重建):走 **reindex** 端點 — 先刪舊索引
      記錄再重跑。⚠️ 不能用 index(skip_existing=False)充當重建:per-file
      的 content_hash 短路會把內容沒變的檔案全部跳過(log 見
      INDEX_SKIP_IDEMPOTENT),改了 Contextual Retrieval / embedding /
      chunking 設定後的重建會完全無效。
    """
    folder, token = _owner(folder_id)
    from src.api.router.response import IndexRequest
    skip_existing = bool(body.get("skip_existing", True))
    if skip_existing:
        from src.api.router.rag_indexing import index_folder_endpoint
        return await index_folder_endpoint(
            folder_id, IndexRequest(), skip_existing=True, token=token, folder=folder)
    from src.api.router.rag_indexing import reindex_folder_endpoint
    return await reindex_folder_endpoint(
        folder_id, IndexRequest(), skip_existing=False, token=token, folder=folder)


@router.post("/api/admin/manage/folders/{folder_id}/files/{file_id}/retry")
async def admin_retry_file(folder_id: int, file_id: UUID):
    """重試單檔索引(force 旁路 content_hash 短路;失敗檔一鍵重跑)。"""
    _, token = _owner(folder_id)
    from db.filedb import FileDB
    from src.domain.rag.dto import FileRequest
    from src.adapter.rag import get_rag_adapter
    rows = FileDB.get(id=file_id)
    if not rows:
        raise HTTPException(404, f"File {file_id} not found")
    f = rows[0]
    req = FileRequest(
        id=f.id, file_name=f.file_name, file_path=f.file_path,
        folder_id=f.folder_id, mime_type=f.mime_type, file_size=f.file_size,
        content_hash=getattr(f, "content_hash", None))
    result = await get_rag_adapter().index_document(
        file_record=req, token=token, force=True)
    return {"data": result.model_dump(), "message": "Reindexed"}


@router.post("/api/admin/manage/folders/{folder_id}/query")
async def admin_query_folder(folder_id: int, body: dict = Body(..., example={"query": "…"})):
    """對 folder 跑一次檢索(查詢測試台;act-as-owner)。回命中 chunks + 分數。

    trace=true:走檢索軌跡(拆 vector / BM25 / hybrid / rerank 名次),
    並用軌跡的最終命中組成 results(不重跑一次一般查詢)。
    """
    folder, token = _owner(folder_id)
    q = (body.get("query") or "").strip()
    if len(q) < 2:
        raise HTTPException(422, "query too short (min 2 chars)")

    if body.get("trace"):
        from src.adapter.rag import get_rag_adapter
        from src.api.router.rag_query import _resolve_retrieval_defaults
        d = _resolve_retrieval_defaults()
        trace = await get_rag_adapter().query_trace(
            query=q, folder_id=folder_id, token=token,
            top_k=body.get("top_k") or d["top_k"],
            similarity_cutoff=body.get("similarity_cutoff") or d["similarity_cutoff"],
            sparse_top_k=d["sparse_top_k"], hybrid_alpha=d["hybrid_alpha"])
        results = [{"text": r["text"], "score": r["final_score"], "metadata": r["metadata"]}
                   for r in trace["results"]]
        resp = {"data": {"query": q, "results": results,
                         "total_results": len(results), "trace": trace}, "message": "ok"}
    else:
        from src.api.router.rag_query import query_rag
        from src.api.router.response import QueryRequest
        from fastapi import Request as _Req
        req = QueryRequest(
            query=q, folder_name=folder.name,
            top_k=body.get("top_k"), similarity_cutoff=body.get("similarity_cutoff"),
        )
        scope = {"type": "http", "headers": [], "method": "POST", "path": "/", "query_string": b""}
        resp = await query_rag(_Req(scope), req, token=token)
    # answer=true:檢索後接 CRAG 答案生成(相關性評分 → 只用相關段 → 附信心度)
    if body.get("answer"):
        try:
            gen = _generate_answer(q, resp["data"].get("results", []))
            resp["data"]["answer"] = gen.get("answer")
            resp["data"]["rag_gate"] = {k: gen[k] for k in
                                        ("confidence", "kept", "dropped", "note") if k in gen}
        except Exception as e:
            logger.warning(f"[ADMIN] answer generation failed: {e}")
            resp["data"]["answer"] = None
    return resp


def _generate_answer(query: str, results: list) -> dict:
    """CRAG(Corrective RAG)風格答案生成 — 先評每段檢索是否相關,只用相關段
    生成;全不相關 → 不硬答,回明確「找不到依據」。

    回 dict:{answer, confidence(high/medium/low/none), kept, dropped, note}。
    比「有結果就硬生成」更誠實 —— 檢索到不相關內容時避免幻覺(接你的零結果分析)。
    """
    if not results:
        return {"answer": None, "confidence": "none", "kept": 0, "dropped": 0,
                "note": "No chunks retrieved"}
    import json
    import re
    from src.config.config_manager import Config
    from src.domain.rag.context_generator import ContextGenerator
    llm_cfg = Config.get_config_model().rag.llm
    client = ContextGenerator._create_sync_client(llm_cfg)
    model = getattr(llm_cfg, "azure_deployment", None) or llm_cfg.model
    top = results[:6]

    # ── CRAG 第 1 步:相關性評分(單次 LLM 呼叫,回 boolean 陣列)──
    grades = [True] * len(top)
    try:
        gprompt = (
            "Grade whether each numbered context can help answer the question. "
            "Reply ONLY a JSON array of booleans (one per context, true = relevant).\n\n"
            + "\n\n".join(f"[{i+1}] {r['text'][:600]}" for i, r in enumerate(top))
            + f"\n\nQuestion: {query}\n\nJSON:")
        gr = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": gprompt}],
            max_tokens=1024, temperature=0)
        m = re.search(r"\[.*?\]", (gr.choices[0].message.content or ""), re.S)
        if m:
            arr = json.loads(m.group(0))
            grades = [bool(x) for x in arr][:len(top)] + [False] * (len(top) - len(arr))
    except Exception as e:
        logger.debug(f"[CRAG] grading skipped, using all context: {e}")

    kept = [r for r, g in zip(top, grades) if g]
    dropped = len(top) - len(kept)

    # ── CRAG gate:全部不相關 → 不硬答 ──
    if not kept:
        try:
            client.close()
        except Exception:
            pass
        return {"answer": "根據目前索引的內容,找不到足夠依據回答這個問題。"
                          "建議擴充相關文件,或換個問法。",
                "confidence": "low", "kept": 0, "dropped": dropped,
                "note": "CRAG gate: no retrieved chunk graded relevant"}

    # ── CRAG 第 2 步:只用相關段生成(引用以 [n] 標註)──
    ctx = "\n\n".join(f"[{i+1}] {r['text'][:1200]}" for i, r in enumerate(kept))
    prompt = (
        "You are a helpful assistant. Answer the question using ONLY the context "
        "below. Cite sources inline as [n]. If the context lacks the answer, say so.\n\n"
        f"Context:\n{ctx}\n\nQuestion: {query}\n\nAnswer:")
    # gpt-oss 等 reasoning 模型:reasoning token 會吃 max_tokens,額度太小 →
    # content 回 None(finish_reason=length)→ 答案靜默變空(實測『主科目6502』
    # 對 6 段 Excel context 在 800 就爆)。給足 2048。
    r = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=2048, temperature=0.2)
    ans = r.choices[0].message.content
    finish = getattr(r.choices[0], "finish_reason", None)
    if not (ans or "").strip():
        # 防呆:仍空(通常是 reasoning 又把額度用光)→ 不靜默回空,給明確訊息
        logger.warning(f"[CRAG] empty generation (finish={finish}) for query={query!r}")
        try:
            client.close()
        except Exception:
            pass
        return {"answer": "已找到相關內容,但答案生成未完成(模型輸出被截斷)。"
                          "請再試一次,或換更明確的問法。",
                "confidence": "low", "kept": len(kept), "dropped": dropped,
                "note": f"generation returned empty (finish={finish})"}
    # gpt-oss 慣用 OpenAI 風格引註【n†Lx-Ly】/【n†來源】;UI 不渲染 → 正規化成
    # 與結果卡一致的 [n](保留數字、丟掉來源/行號雜訊)
    ans = re.sub(r"【\s*(\d+)\s*†[^】]*】", r"[\1]", ans)
    try:
        client.close()
    except Exception:
        pass
    return {"answer": ans,
            "confidence": "high" if len(kept) >= 2 else "medium",
            "kept": len(kept), "dropped": dropped,
            "note": f"Answered from {len(kept)} relevant chunk(s)"}


@router.post("/api/admin/manage/folders/{folder_id}/jobs/{job_id}/cancel")
async def admin_cancel_job(folder_id: int, job_id: str):
    """取消執行中的索引 job。"""
    folder, token = _owner(folder_id)
    from src.api.router.rag_indexing import cancel_index_job
    return await cancel_index_job(folder_id, job_id, token=token, folder=folder)
