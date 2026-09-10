
"""執行期設定覆寫 — 白名單、驗證、就地變更(admin 熱改的核心)。

分層:config.yaml = 出廠預設(唯讀)→ RuntimeSettings 表 = 現場覆寫
→ 疊加後的 ConfigModel = 全服務讀的唯一真相。

為什麼是「就地變更(in-place setattr)」而不是換一顆新 ConfigModel:
消費端(context_generator 持 llm_config、sub-service 持 ctx)拿的是
**物件參照** — 換新顆舊參照全部失聯,就地改才會全體生效。

白名單三級:
- live:改了即生效(HTTP 端點型服務、request-time 讀的參數)
- warn:改了生效但附影響警告(embedding 系 — 向量空間不相容,
  既有 folder 要重建索引)
- 名單外:一律拒絕(DB/port/auth 等基礎設施,重啟才能改)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 點路徑 → 級別。名單外的路徑一律拒絕。
# 注意:score_threshold 等雖凍在 Reranker instance,rebind(rag_context)
# 會重建該 instance — 這裡只管「值的驗證與寫入」,rebind 是另一層。
EDITABLE: Dict[str, str] = {
    # 模型服務 — embedding(warn:換模型 = 向量空間不相容,舊 folder 需重建)
    "rag.embedding.provider": "warn",
    "rag.embedding.model": "warn",
    "rag.embedding.dimension": "warn",
    "rag.embedding.base_url": "warn",
    "rag.embedding.api_key": "warn",
    "rag.embedding.query_prefix": "warn",
    "rag.embedding.passage_prefix": "warn",
    # 模型服務 — LLM(contextual retrieval)
    "rag.llm.provider": "live",
    "rag.llm.model": "live",
    "rag.llm.base_url": "live",
    "rag.llm.api_key": "live",
    # Contextual retrieval 行為
    "rag.contextual_retrieval.enabled": "live",
    "rag.contextual_retrieval.max_context_length": "live",
    "rag.contextual_retrieval.max_concurrent": "live",
    "rag.contextual_retrieval.max_doc_chars": "live",
    "rag.contextual_retrieval.max_tokens": "live",
    "rag.contextual_retrieval.reasoning_effort": "live",
    # 模型服務 — rerank
    "rag.rerank.enabled": "live",
    "rag.rerank.model": "live",
    "rag.rerank.base_url": "live",
    "rag.rerank.api_key": "live",
    "rag.rerank.top_n": "live",
    "rag.rerank.score_threshold": "live",
    "rag.rerank.query_template": "live",
    "rag.rerank.document_template": "live",
    # 模型服務 — ASR
    "rag.asr.enabled": "live",
    "rag.asr.provider": "live",
    "rag.asr.base_url": "live",
    "rag.asr.api_key": "live",
    "rag.asr.model": "live",
    # 檢索參數(REST/agentic 均 request-time 讀 config;ctx 標量由 rebind 同步)
    "rag.retrieval.default_top_k": "live",
    "rag.retrieval.default_similarity_cutoff": "live",
    "rag.retrieval.default_sparse_top_k": "live",
    "rag.retrieval.default_hybrid_alpha": "live",
    "rag.retrieval.hybrid_fusion": "live",
    "rag.retrieval.expand_context_default": "live",
    "rag.retrieval.expand_context_neighbors": "live",
    "rag.retrieval.auto_merging.enabled": "live",
    "rag.retrieval.auto_merging.merge_threshold": "live",
}

# 顯示時要遮罩的欄位(GET 回 "•••" 佔位;PUT 寫入不受影響)
SECRET_PATHS = {p for p in EDITABLE if p.endswith("api_key")}

# path 前綴 → rebind 群組(rag_context.apply_runtime_changes 的 dispatch key)
REBIND_GROUPS = ("rag.embedding", "rag.llm", "rag.contextual_retrieval",
                 "rag.rerank", "rag.asr", "rag.retrieval")


def _resolve(config_model, path: str, create: bool = True):
    """點路徑 → (父物件, 欄位名)。

    create=True:中途 None 的 optional 段以預設值補建(寫入路徑用);
    create=False:讀取路徑 — 不得有副作用,None 段回 (None, field)。
    """
    parts = path.split(".")
    obj = config_model
    for i, part in enumerate(parts[:-1]):
        nxt = getattr(obj, part)
        if nxt is None:
            if not create:
                return None, parts[-1]
            # optional 段(如 rag.asr 未設)→ 以該欄位型別的預設值補建
            field = type(obj).model_fields[part]
            ann = field.annotation
            # Optional[X] → X
            import typing
            args = typing.get_args(ann)
            target = next((a for a in args if a is not type(None)), ann) if args else ann
            nxt = target()
            setattr(obj, part, nxt)
        obj = nxt
    return obj, parts[-1]


def get_effective(config_model, mask_secrets: bool = True) -> Dict[str, Any]:
    """所有白名單路徑的目前生效值(secret 遮罩)。"""
    out: Dict[str, Any] = {}
    for path in EDITABLE:
        try:
            parent, field = _resolve(config_model, path, create=False)
            v = getattr(parent, field) if parent is not None else None
        except Exception:
            v = None
        if mask_secrets and path in SECRET_PATHS and v:
            v = "•••"
        out[path] = v
    return out


def validate_and_apply(config_model, patch: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """驗證 patch 後**就地**寫進 ConfigModel。

    全有全無:任何一項驗證失敗 → ValueError,一項都不寫。

    Returns:
        (applied, warnings) — 實際寫入的 {path: value} 與 warn 級路徑的警告。

    Raises:
        ValueError: 路徑不在白名單 / 型別驗證不過(訊息含明細)。
    """
    unknown = [p for p in patch if p not in EDITABLE]
    if unknown:
        raise ValueError(f"不可熱改的設定路徑:{unknown}(白名單見 GET /api/admin/settings)")

    # 先全部驗證(pydantic:套進 section copy 驗型別),全過才寫
    staged = []  # [(parent, field, validated_value, path)]
    errors = []
    for path, value in patch.items():
        try:
            parent, field = _resolve(config_model, path)
            section_cls = type(parent)
            data = parent.model_dump()
            data[field] = value
            validated = section_cls.model_validate(data)  # 型別/約束驗證
            staged.append((parent, field, getattr(validated, field), path))
        except ValueError as e:
            errors.append(f"{path}: {e}")
    if errors:
        raise ValueError("設定驗證失敗:" + "; ".join(errors))

    applied: Dict[str, Any] = {}
    warnings: List[str] = []
    for parent, field, value, path in staged:
        setattr(parent, field, value)  # 就地 — 持參照的消費端同步看到
        applied[path] = value
        if EDITABLE[path] == "warn":
            warnings.append(
                f"{path}:embedding 面變更 — 向量空間/維度不相容,"
                "既有 folder 需重建索引後才能正常檢索;新索引立即用新設定"
            )
    return applied, warnings


def rebind_groups_for(paths) -> List[str]:
    """一批已套用的路徑 → 需要觸發的 rebind 群組(去重、依固定順序)。"""
    hit = set()
    for p in paths:
        for g in REBIND_GROUPS:
            if p.startswith(g + "."):
                hit.add(g)
    return [g for g in REBIND_GROUPS if g in hit]
