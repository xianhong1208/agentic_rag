
"""Agentic Tools — MCP 入口點

由 config.modules.rag.mcp_tools.function_name 指向此模組的 register_agentic_tools。
做兩件事:
1. 初始化 DynamicToolManager(綁定 FastMCP 實例)
2. 提供 _query 函數 — dynamic_tool_manager 註冊 tool 時注入此函數作為 backend

當 config.rag.retrieval.return_resource_files = True 且 mode='search' 時,
回傳 list 會在第一個 JSON text block 之後追加命中的原始檔案 binary File 物件,
讓 MCP client(例如 agent builder)可以接成 artifacts。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.utilities.types import File
from mcp.types import Annotations

from collections import Counter

from db.filedb import FileDB
from src.adapter.rag import get_rag_adapter
from src.config.config_manager import Config
from src.domain.exceptions import (
    InvalidTokenError,
    UnauthorizedAccessError,
)
from src.fastmcp_tools.acl import extract_token
from src.fastmcp_tools.dynamic_tool_manager import DynamicToolManager
from src.log import get_mcptools_logger, log_err, log_op, log_warn, mask_token
from src.storage.file_storage import FileStorage


# ============================================================================
# Pretty-print summary box for each tool call
# ============================================================================
# 每次 MCP tool 呼叫結束時 emit 一個多行方框,把所有關鍵資訊集中視覺化:
#   - mode / folder / token
#   - input 參數
#   - mode-specific 結果統計(search:命中分佈; list:狀態分佈; read:檔案資訊)
#   - 附檔資訊(若有)
#   - 結果 / 耗時
#
# 跟原本散亂的 [TOOL_CALL] / [SEARCH_START] / [SEARCH_DONE] / [TOOL_ATTACH]
# 多行 log 比起來,**單次查詢一個方框** 視覺集中,容易追蹤。
# 細節事件仍保留 DEBUG 級供深度排查。
# ============================================================================

# 視覺常數
_BOX_WIDTH = 90
_BOX_TOP = "═" * _BOX_WIDTH
_BOX_MID = "─" * _BOX_WIDTH
_MODE_ICONS = {"search": "🔍", "list": "📋", "read": "📖"}


def _truncate(s: str, max_len: int) -> str:
    """字串太長截斷加省略號"""
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _visual_width(s: str) -> int:
    """估算字串在終端機顯示的視覺寬度(CJK / 全形 / emoji = 2 columns,其餘 = 1)。

    用 unicodedata.east_asian_width + 額外處理 emoji 範圍。

    Args:
        s: 要量的字串。

    Returns:
        column 數總和。
    """
    import unicodedata
    width = 0
    for ch in s:
        # East Asian Width 屬性:W=Wide, F=Fullwidth → 2 columns
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        # Emoji 通常落在 0x1F000-0x1FFFF / 0x2600-0x27FF / 0x1F900+ 等
        elif 0x1F000 <= ord(ch) <= 0x1FFFF or 0x2600 <= ord(ch) <= 0x27FF:
            width += 2
        else:
            width += 1
    return width


def _center_line(text: str, width: int = _BOX_WIDTH) -> str:
    """把 text 置中在 width 內(考慮中文 / emoji 寬度)"""
    vw = _visual_width(text)
    if vw >= width:
        return text
    pad = (width - vw) // 2
    return " " * pad + text


def _format_summary_box(
    *,
    mode: str,
    folder_name: str,
    token: str,
    response: dict,
    attached_files: int,
    attached_bytes: int,
    elapsed_ms: float,
    error: Optional[str] = None,
) -> str:
    """根據 response 渲染整次 tool 呼叫的方框 summary"""
    icon = _MODE_ICONS.get(mode, "🔧")
    status_icon = "❌" if error else "✅"
    # Header 內容 → 置中對齊 _BOX_WIDTH(中英文 emoji 寬度都納入計算)
    header_inner = f"{icon}  {mode.upper()}   folder={folder_name}   token={mask_token(token)}"
    header = _center_line(header_inner)

    # 方框前後各塞空白行,跟前後 detail log 視覺隔開
    lines = ["", "", _BOX_TOP, header, _BOX_MID]

    # ---- mode-specific body ----
    if mode == "search":
        lines.extend(_format_search_body(response))
    elif mode == "list":
        lines.extend(_format_list_body(response))
    elif mode == "read":
        lines.extend(_format_read_body(response))

    # ---- attachment info ----
    if attached_files > 0:
        kb = attached_bytes / 1024
        lines.append(f"  Attach    : {attached_files} files (~{kb:.0f} KB)")

    # ---- error / done ----
    lines.append(_BOX_MID)
    if error:
        lines.append(f"  {status_icon} FAIL    : {_truncate(error, 70)}   elapsed={elapsed_ms:.0f}ms")
    else:
        blocks_count = 1 + attached_files  # 1 text + N files
        block_breakdown = f"{blocks_count} blocks (1 text + {attached_files} files)" if attached_files else "1 text block"
        lines.append(f"  {status_icon} DONE    : {block_breakdown}   elapsed={elapsed_ms:.0f}ms")
    lines.append(_BOX_TOP)
    lines.append("")  # 後置空行 → 跟下一條 log 隔開

    return "\n".join(lines)


def _format_search_body(response: dict) -> List[str]:
    """search mode 的內容:query / params / results 分佈 / files / scores / hint"""
    lines = []
    query = response.get("query", "")
    lines.append(f"  Query     : \"{_truncate(query, 70)}\"")

    # 從 response 推回 params(handle_search 沒明確 echo,但結果裡有)
    results = response.get("results", []) or []
    total = response.get("total_results", 0)

    lines.append(f"  Results   : {total}")
    if results:
        # roles 分佈
        roles = Counter(r.get("node_role", "?") for r in results)
        merged_total = sum(
            r.get("merged_from_leaves", 0) for r in results if r.get("node_role") == "parent"
        )
        role_parts = []
        if roles.get("leaf"):
            role_parts.append(f"leaf:{roles['leaf']}")
        if roles.get("parent"):
            role_parts.append(f"parent:{roles['parent']}(+{merged_total} merged)")
        if roles.get("expanded"):
            role_parts.append(f"expanded:{roles['expanded']}")
        lines.append(f"    Roles   : {'  '.join(role_parts)}")

        # files 分佈
        files = Counter(r.get("file_name", "?") for r in results)
        files_str = ", ".join(f"{name}:{cnt}" for name, cnt in files.most_common(3))
        if len(files) > 3:
            files_str += f", +{len(files) - 3} more"
        lines.append(f"    Files   : {_truncate(files_str, 70)}")

        # scores 分佈
        scores = [r.get("score", 0) for r in results]
        if scores:
            lines.append(
                f"    Scores  : min={min(scores):.3f}  max={max(scores):.3f}  avg={sum(scores)/len(scores):.3f}"
            )

    hint = response.get("_hint", "")
    if hint:
        # _hint 可能很長,截掉並換行 indent
        lines.append(f"  Hint      : {_truncate(hint, 70)}")

    return lines


def _format_list_body(response: dict) -> List[str]:
    """list mode 的內容:檔案數 / 索引狀態分佈"""
    lines = []
    files = response.get("files", []) or []
    total = response.get("total_files", 0)

    lines.append(f"  Files     : {total}")

    if files:
        status_counts = Counter(f.get("indexed_status", "?") for f in files)
        status_parts = [f"{k}:{v}" for k, v in status_counts.most_common()]
        lines.append(f"    Status  : {'  '.join(status_parts)}")

        total_chunks = sum(f.get("chunk_count", 0) for f in files)
        lines.append(f"    Chunks  : {total_chunks} (total across all files)")

    return lines


def _format_read_body(response: dict) -> List[str]:
    """read mode 的內容:檔名 / chunks / tokens / truncated"""
    lines = []
    file_name = response.get("file_name", "")
    file_id = response.get("file_id", "")
    chunk_count = response.get("chunk_count", 0)
    tokens = response.get("tokens_estimated", 0)
    truncated = response.get("truncated", False)

    lines.append(f"  File      : {_truncate(file_name, 60)}")
    lines.append(f"  File ID   : {file_id}")
    lines.append(f"  Loaded    : {chunk_count} chunks  ~{tokens} tokens"
                 + ("  ⚠️ TRUNCATED" if truncated else ""))
    return lines

logger = get_mcptools_logger()


# 副檔名 → 標準 MIME type 對照(對齊 coreagent 慣例)
# 為什麼自己維護一份:Python 的 mimetypes.guess_type 對 .docx / .xlsx 等 OOXML 不夠精確,
# 會回 'application/octet-stream',artifacts UI 認不出來。這份是 IANA 標準值。
_EXT_TO_MIME: Dict[str, str] = {
    "pdf":  "application/pdf",
    "doc":  "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls":  "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv":  "text/csv",
    "ppt":  "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt":  "text/plain",
    "md":   "text/markdown",
    "json": "application/json",
    "html": "text/html",
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif":  "image/tiff",
    "webp": "image/webp",
    "wav":  "audio/wav",
    "mp3":  "audio/mpeg",
}


class RagFile(File):
    """File 子類:URI 保持乾淨副檔名,但 mimeType 強制使用 IANA 標準值

    為什麼:FastMCP 的 File 會從 format 推導 URI 副檔名 與 MIME type,
    導致 format='docx' → mime='application/docx'(不是標準 OOXML mime)。
    這個子類保留 URI 走 format 推導,但 response 階段把 mimeType 換成標準值,
    確保 client 端 artifacts 能正確分辨檔案格式。
    """

    def __init__(
        self,
        data: bytes,
        format: str,
        name: str,
        mime_type: Optional[str] = None,
        annotations: Optional[Annotations] = None,
    ):
        super().__init__(data=data, format=format, name=name, annotations=annotations)
        self._standard_mime_type = mime_type

    def to_resource_content(self, mime_type=None, annotations=None):
        resource = super().to_resource_content(mime_type=mime_type, annotations=annotations)
        if self._standard_mime_type and not mime_type:
            resource.resource.mimeType = self._standard_mime_type
        return resource


def _build_resource_files(response: dict) -> List[File]:
    """從 search response 的 results 中提取 unique 檔案,讀取原始 bytes 包成 RagFile

    Args:
        response: handle_search 產出的 dict,需含 results[] 每筆有 file_id/file_name

    Returns:
        File 列表(去重後),依 hit_count 排序(高分檔案排前面)
    """
    results = response.get("results", []) if isinstance(response, dict) else []
    if not results:
        return []

    # 計算每個 file_id 的命中次數(用於排序),保留出現順序
    hits: Dict[str, int] = {}
    for r in results:
        fid = r.get("file_id")
        if fid:
            hits[fid] = hits.get(fid, 0) + 1

    if not hits:
        return []

    # 命中多的優先,讓 agent 看到的 artifacts 順序對應相關性
    sorted_fids = sorted(hits.keys(), key=lambda x: hits[x], reverse=True)

    file_records = FileDB.get_by_ids(sorted_fids)

    files: List[File] = []
    for fid in sorted_fids:
        record = file_records.get(fid)
        if not record:
            logger.warning(f"File record missing for id={fid}, skipping artifact")
            continue
        try:
            file_bytes = FileStorage.read_file(record.file_path)
            p = Path(record.file_name)
            ext = p.suffix.lstrip('.').lower()
            name_without_ext = p.stem
            standard_mime = _EXT_TO_MIME.get(ext)

            files.append(RagFile(
                data=file_bytes,
                format=ext or "bin",
                name=name_without_ext,
                mime_type=standard_mime,
            ))
            logger.debug(
                f"Attached artifact: {record.file_name} "
                f"({len(file_bytes)} bytes, ext={ext}, hits={hits[fid]})"
            )
        except Exception as e:
            logger.warning(f"Failed to read file {record.file_name} (id={fid}): {e}")

    return files


def register_agentic_tools(mcp: FastMCP) -> None:
    """模組進入點 — 由 app.create_app 動態載入後呼叫"""
    DynamicToolManager.initialize(mcp)
    logger.info("✅ Agentic tools module initialized")


async def _query(
    *,
    folder_name: str,
    mode: str,
    query: str,
    file_id: Optional[str],
    top_k: int,
    similarity_cutoff: float,
    expand_context: bool,
) -> list:
    """所有 per-folder MCP 工具共用的 backend query。

    每次呼叫結束 emit 一個多行方框 summary;細節 log 在 domain 的 agentic_handlers.py。

    Args:
        folder_name: 對應的 RAG folder。
        mode: ``search`` / ``list`` / ``read`` 其一。
        query: 查詢字串(mode=list 可為空)。
        file_id: mode=read 必填;其他 mode 忽略。
        top_k: 返回前 K 個結果。
        similarity_cutoff: 相似度閾值(reranker 啟用時無效)。
        expand_context: True → mode=search 沒 merge 的 leaves 展開鄰居。

    Returns:
        ``list[str | RagFile]`` ─ 首個 element 是 JSON 字串(metadata + hits),
        後續 element 是 RagFile 物件(僅 mode=search + config 啟用 return_resource_files)。
    """
    start = time.perf_counter()
    token: Optional[str] = None
    response: dict = {}
    attached_files = 0
    attached_bytes = 0
    error_msg: Optional[str] = None

    try:
        token = extract_token()
        adapter = get_rag_adapter()
        response = await adapter.query(
            folder_name=folder_name,
            mode=mode,
            query=query,
            file_id=file_id,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            expand_context=expand_context,
            token=token,
        )

        content_blocks: list = [json.dumps(response, ensure_ascii=False)]

        # 只有 search mode 才掛 artifacts(list/read 不需要)
        if mode == "search":
            rag_config = Config.get_config_model().rag
            if rag_config and getattr(rag_config.retrieval, "return_resource_files", False):
                resource_files = _build_resource_files(response)
                content_blocks.extend(resource_files)
                attached_files = len(resource_files)
                attached_bytes = sum(len(f.data) for f in resource_files if hasattr(f, "data"))

        elapsed_ms = (time.perf_counter() - start) * 1000

        # 🎁 方框 summary — 單次 tool 呼叫的視覺總結
        logger.info(_format_summary_box(
            mode=mode,
            folder_name=folder_name,
            token=token or "",
            response=response,
            attached_files=attached_files,
            attached_bytes=attached_bytes,
            elapsed_ms=elapsed_ms,
        ))

        return content_blocks

    except InvalidTokenError as exc:
        error_msg = f"AUTH_FAIL: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000
        # 沒 token 還是顯示方框,但標 error
        logger.warning(_format_summary_box(
            mode=mode, folder_name=folder_name, token=token or "(missing)",
            response={}, attached_files=0, attached_bytes=0,
            elapsed_ms=elapsed_ms, error=error_msg,
        ))
        return [json.dumps({"error": "unauthorized", "detail": str(exc)}, ensure_ascii=False)]

    except UnauthorizedAccessError as exc:
        error_msg = f"ACL_DENY: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning(_format_summary_box(
            mode=mode, folder_name=folder_name, token=token or "",
            response={}, attached_files=0, attached_bytes=0,
            elapsed_ms=elapsed_ms, error=error_msg,
        ))
        return [json.dumps({"error": "forbidden", "detail": str(exc)}, ensure_ascii=False)]

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(_format_summary_box(
            mode=mode, folder_name=folder_name, token=token or "",
            response={}, attached_files=0, attached_bytes=0,
            elapsed_ms=elapsed_ms, error=error_msg,
        ))
        # 額外印 traceback 給深度 debug
        logger.error(f"Tool exception traceback:", exc_info=True)
        return [json.dumps(
            {"error": "internal_error", "detail": f"Query failed: {exc}"},
            ensure_ascii=False,
        )]


def register_folder_tool(folder_name: str, folder_description: Optional[str], user_token: str) -> bool:
    """Public API — app.py 啟動時為每個 (token, folder) 註冊一次"""
    manager = DynamicToolManager.get_instance()
    return manager.register_folder_tool(
        folder_name=folder_name,
        query_function=_query,
        folder_description=folder_description,
        user_token=user_token,
    )


def unregister_folder_tool(folder_name: str, user_token: str) -> None:
    """Public API — folder 刪除時呼叫"""
    manager = DynamicToolManager.get_instance()
    manager.unregister_folder_tool(folder_name, user_token)
