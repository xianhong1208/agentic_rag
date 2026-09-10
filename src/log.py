#!/usr/bin/env python3

"""
Log Configuration Module - 獨立的日誌配置模組

功能：
- 控制台日誌輸出（彩色）
- 分模組檔案日誌記錄（adapter、api、auth、db、mcptools、server）
- Request ID 自動注入（透過 contextvars，串聯整條請求鏈路）
- Structured Log Helpers（統一格式，方便 grep）
- HTTP 請求日誌記錄

查問題用法：
    # 串聯一個請求的完整鏈路
    grep "rid=abc12345" logs/*/info_*.log

    # 找某個 folder 的所有錯誤
    grep "fid=42" logs/adapter/error_*.log

    # 找某個 token 的操作
    grep "tok=abcd1234" logs/*/info_*.log
"""

import os
import sys
import json
import uuid
from contextvars import ContextVar
from typing import Dict, Any, Literal, Optional
from loguru import logger
from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request


# ============================================================================
# Request ID（每個 HTTP 請求自動產生，透過 contextvars 在所有層自動帶上）
# ============================================================================

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

def get_request_id() -> str:
    """取得當前請求的 request_id（在所有層都可呼叫）"""
    return _request_id_var.get()

def set_request_id(rid: str) -> None:
    """設定當前請求的 request_id（由 middleware 呼叫）"""
    _request_id_var.set(rid)

def generate_request_id() -> str:
    """產生短 request_id（取 UUID 前 8 碼，足夠在單日內唯一）"""
    return uuid.uuid4().hex[:8]


# ============================================================================
# 模組定義
# ============================================================================

LogModule = Literal["adapter", "api", "auth", "db", "mcptools", "server"]
LOG_MODULES: list[LogModule] = ["adapter", "api", "auth", "db", "mcptools", "server"]


# ============================================================================
# Logger Setup
# ============================================================================

def _format_file_log(record) -> str:
    """檔案 log 格式 ─ 自動附 request_id(contextvar 優先,fallback extra["rid"])。

    順序重要:get_logger 通常 module 頂層呼叫,那時 contextvar 是 "-",bind 進 extra 後
    就凍住了;所以 format 時必須先讀 contextvar 才能拿到當下 request 的真值。

    Args:
        record: loguru 的 record dict。

    Returns:
        format string (帶 placeholder,loguru 自己會代入)。
    """
    rid = _request_id_var.get()
    if rid == "-":
        rid = record["extra"].get("rid", "-")
    return (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
        f"rid={rid} | "
        "{function}:{line} | {message}\n"
    )

def _format_console_log(record) -> str:
    """控制台 log 格式:彩色 + request_id(參見 _format_file_log 的順序說明)。

    時間欄位用完整 YYYY-MM-DD HH:mm:ss.SSS。 隔夜長跑(indexing job /
    Whisper transcription / 跨日 SSE stream)時純看時分秒會把不同天
    混在一起,日期是必要 context — 跟檔案 log 對齊也更好 grep。
    """
    rid = _request_id_var.get()
    if rid == "-":
        rid = record["extra"].get("rid", "-")
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | "
        f"<dim>rid={rid}</dim> | "
        "<cyan>[{extra[module]}]</cyan> | {message}\n"
    )


def setup_logger(
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_base_dir: str = "logs",
    rotation: str = "5 MB",
    encoding: str = "utf-8"
) -> None:
    """設定 loguru 日誌系統

    為每個模組建立獨立的日誌資料夾，分 info/error 兩個檔案。
    所有 log 自動帶上 request_id，方便串聯請求鏈路。

    目錄結構：
        logs/adapter/info_2026-03-20.log   <- DEBUG/INFO/WARNING
        logs/adapter/error_2026-03-20.log  <- ERROR/CRITICAL
        logs/api/info_2026-03-20.log
        ...

    Args:
        console_level: 控制台日誌等級
        file_level: 檔案日誌等級
        log_base_dir: 日誌檔案基礎目錄
        rotation: 日誌輪替大小
        encoding: 檔案編碼
    """
    logger.remove()

    LOG_LEVELS = {
        "info": lambda record: record["level"].name in ["DEBUG", "INFO", "SUCCESS", "WARNING"],
        "error": lambda record: record["level"].name in ["ERROR", "CRITICAL"],
    }

    for module in LOG_MODULES:
        module_log_dir = os.path.join(log_base_dir, module)
        os.makedirs(module_log_dir, exist_ok=True)

        for level_name, level_filter in LOG_LEVELS.items():
            logger.add(
                f"{module_log_dir}/{level_name}_{{time:YYYY-MM-DD}}.log",
                rotation=rotation,
                level=file_level,
                encoding=encoding,
                format=_format_file_log,
                filter=lambda record, m=module, lf=level_filter: (
                    record["extra"].get("module") == m and lf(record)
                )
            )

    # 控制台日誌 (彩色輸出到 stderr，避免和 uvicorn stdout 混在一起)
    logger.add(
        sys.stderr,
        level=console_level,
        format=_format_console_log,
        filter=lambda record: record["extra"].get("module") in LOG_MODULES,
        colorize=True
    )


# ============================================================================
# Logger Getters
# ============================================================================

def get_logger(module: LogModule):
    """取得指定模組的 loguru logger(只 bind module,不 bind rid)。

    bind rid 會在 import 時凍住 "-",改由 format function 每次即時讀 contextvar。

    Args:
        module: "adapter" / "api" / "auth" / "db" / "mcptools" / "server" 其一。

    Returns:
        loguru.Logger 已綁定 module。
    """
    return logger.bind(module=module)


def get_adapter_logger():
    return get_logger("adapter")

def get_api_logger():
    return get_logger("api")

def get_auth_logger():
    return get_logger("auth")

def get_db_logger():
    return get_logger("db")

def get_mcptools_logger():
    return get_logger("mcptools")

def get_server_logger():
    return get_logger("server")


# ============================================================================
# Structured Log Helpers（統一格式，方便 grep）
# ============================================================================

def mask_token(token: Optional[str]) -> str:
    """遮罩 token，只顯示前 8 碼"""
    if not token:
        return "-"
    return f"{token[:8]}..." if len(token) > 8 else token


def _build_context(**kwargs) -> str:
    """把 key=value 組成 log context 字串，跳過 None"""
    parts = []
    for key, value in kwargs.items():
        if value is not None:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def log_op(log, op: str, *, folder_id=None, file_id=None, token=None, msg: str = "", **extra):
    """記錄 INFO 級別的操作事件(統一格式,方便 grep)。

    輸出:``[OP] fid=N file=UUID tok=abcdefgh... | msg``

    Args:
        log: loguru logger(從 get_xxx_logger 拿)。
        op: 操作識別字(e.g. "INDEX_START")。
        folder_id: 可選 folder id。
        file_id: 可選 file id。
        token: 可選 token(會自動 mask)。
        msg: 可選額外訊息接在 ``|`` 後面。
        **extra: 其他要塞進 context 的 key=value。
    """
    ctx = _build_context(
        fid=folder_id,
        file=str(file_id) if file_id else None,
        tok=mask_token(token),
        **extra,
    )
    log.info(f"[{op}] {ctx} | {msg}" if msg else f"[{op}] {ctx}")


def log_op_debug(log, op: str, *, folder_id=None, file_id=None, token=None, msg: str = "", **extra):
    """同 log_op 但走 DEBUG 級別 — 用於細節操作事件,日常不需要看,排查時開 DEBUG"""
    ctx = _build_context(
        fid=folder_id,
        file=str(file_id) if file_id else None,
        tok=mask_token(token),
        **extra,
    )
    log.debug(f"[{op}] {ctx} | {msg}" if msg else f"[{op}] {ctx}")


def log_err(log, op: str, error, *, folder_id=None, file_id=None, token=None, **extra):
    """記錄 ERROR 級別事件(同 log_op 但附 exception 類別 + 訊息)。

    輸出:``[OP] fid=N file=UUID tok=abcdefgh... | ExceptionName: message``

    Args:
        log: loguru logger。
        op: 操作識別字。
        error: 抓到的 exception 物件。
        folder_id: 可選 folder id。
        file_id: 可選 file id。
        token: 可選 token(自動 mask)。
        **extra: 其他 context k=v。
    """
    ctx = _build_context(
        fid=folder_id,
        file=str(file_id) if file_id else None,
        tok=mask_token(token),
        **extra,
    )
    log.error(f"[{op}] {ctx} | {error}")


def log_warn(log, op: str, *, folder_id=None, file_id=None, token=None, msg: str = "", **extra):
    """記錄警告（WARNING 級別）"""
    ctx = _build_context(
        fid=folder_id,
        file=str(file_id) if file_id else None,
        tok=mask_token(token),
        **extra,
    )
    log.warning(f"[{op}] {ctx} | {msg}" if msg else f"[{op}] {ctx}")


# ============================================================================
# HTTP Request Info Logger（支援 FastAPI 和 FastMCP）
# ============================================================================

async def log_request_info(
    tool_name: str = "",
    module: LogModule = "mcptools",
    request: Request = None
) -> Dict[str, Any]:
    """記錄並返回當前 HTTP 請求信息

    支援兩種呼叫方式：
    - FastAPI: 傳入 request 參數
    - FastMCP: 自動從 context 取得 request

    Args:
        tool_name: 調用此函數的工具名稱
        module: 要記錄到的模組名稱（預設為 "mcptools"）
        request: FastAPI Request（可選，FastMCP 會自動獲取）

    Returns:
        包含請求信息的字典
    """
    module_logger = get_logger(module)

    try:
        mcp_session_id = None

        if request:
            module_logger.info(f"[API_CALL] tool={tool_name}")
        else:
            request = get_http_request()
            mcp_session_id = request.headers.get("mcp-session-id", "N/A")
            module_logger.info(f"[MCP_CALL] tool={tool_name} session={mcp_session_id}")

        json_data = None
        content_type = request.headers.get("content-type", "")

        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                if "application/json" in content_type:
                    json_data = await request.json()
            except Exception as e:
                module_logger.warning(f"[REQ_PARSE] JSON parse failed: {e}")

        request_info = {"json": json_data}
        if mcp_session_id:
            request_info["mcp_session_id"] = mcp_session_id

        if json_data:
            module_logger.debug(f"[REQ_BODY] {json.dumps(json_data, ensure_ascii=False)}")

        return request_info

    except Exception as e:
        module_logger.warning(f"[REQ_INFO] unavailable: {e}")
        return {}
