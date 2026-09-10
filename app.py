"""Agentic RAG MCP Server — FastAPI + FastMCP 應用組裝

設計取捨(跟前一版 flat RAG 的 app.py 對比):
- 不掛 file/folder REST API — 上傳/管理走前一版 flat RAG。本服務只提供 MCP RAG 查詢。
- 沿用 SelectiveAuthMiddleware + RequestIdMiddleware,行為與前一版 flat RAG 一致。
- 啟動時為每個 (folder, user_token) 對註冊 per-folder MCP 工具。
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastmcp import FastMCP
from pydantic import BaseModel

from db.folderdb import FolderDB
from src.api.startup_state import record_load_failure  # M15: 能力載入失敗反映到 health
from src.auth.init_auth import initialize_auth_system
from src.config.config_manager import Config
from src.domain.rag.index_job_manager import IndexingJobManager
from src.fastmcp_tools.agentic_tools import register_folder_tool
from src.fastmcp_tools.auth_filtered_mcp import AuthFilteredFastMCP
from src.log import get_api_logger
from src.middleware.auth_middleware import SelectiveAuthMiddleware
from src.middleware.request_id import RequestIdMiddleware
from src.utils.runtime_paths import resolve_external_dir
from src.version import get_version

api_logger = get_api_logger()


def _resolve_instructions_path() -> Path:
    config_dir = resolve_external_dir(
        "config",
        dev_root=Path(__file__).resolve().parent,
    )
    if config_dir is None:
        return Path(__file__).resolve().parent / "config" / "instructions.md"
    return config_dir / "instructions.md"


def _load_instructions() -> str:
    path = _resolve_instructions_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        api_logger.warning(f"Instructions file not found: {path}, using default")
        return "Agentic RAG — Hierarchical RAG with auto-merging retrieval"


def create_app(config: BaseModel, transport: str) -> FastAPI:
    if not isinstance(config, BaseModel):
        raise RuntimeError("create_app requires a Pydantic ConfigModel instance.")

    app_config = getattr(config, "app", None)
    app_name = getattr(app_config, "name", "Agentic RAG")
    app_version = get_version()  # 單一來源:pyproject.toml(見 src/version.py)
    app_title = getattr(app_config, "title", "Agentic RAG MCP Server")
    app_description = getattr(app_config, "description", "")
    instructions = _load_instructions()

    # ---------- MCP server ----------
    auth_config = getattr(config, "auth", None)
    dynamic_tools_config = getattr(auth_config, "dynamic_tools", None) if auth_config else None
    dynamic_tools_enabled = getattr(dynamic_tools_config, "enabled", False) if dynamic_tools_config else False

    if dynamic_tools_enabled:
        mcp = AuthFilteredFastMCP(name=app_name, version=app_version, instructions=instructions)
        api_logger.info("Using AuthFilteredFastMCP (per-token tool filtering)")
    else:
        mcp = FastMCP(name=app_name, version=app_version, instructions=instructions)
        api_logger.info("Using standard FastMCP")

    mcp_app = mcp.http_app(transport=transport)

    # ---------- Lifespan: compose MCP's lifespan + IndexingJobManager hooks ----------
    # Why a custom lifespan?
    #   1. A3 watchdog (heartbeat-stale → mark failed) needs an event loop to spawn its
    #      background task — startup is the right time.
    #   2. A4 restart cleanup (mark stale PENDING/RUNNING as failed with reason="server_restart")
    #      currently no-ops because state is in-memory only, but once C6 lands the DB will
    #      carry pre-restart jobs and this hook becomes meaningful. Wiring it now avoids a
    #      follow-up code change later.
    #
    # The MCP server's own lifespan must still run — wrap rather than replace.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_app.lifespan(app):
            manager = IndexingJobManager.get_instance()
            try:
                flipped = manager.mark_all_running_as_restart_failed()
                if flipped:
                    api_logger.info(f"Startup: marked {flipped} stale jobs as failed (server_restart)")
            except Exception as e:
                api_logger.warning(f"Startup restart-cleanup hook failed (continuing): {e}")
            try:
                manager.start_watchdog()
            except Exception as e:
                api_logger.warning(f"Startup watchdog start failed (continuing): {e}")
            # 終態 job rows 沒有其他回收機制(TTLCache 只管記憶體),
            # startup 清一次超過保留期的,擋 IndexJobs 無限成長
            try:
                from db.indexjobdb import IndexJobDB
                purged = IndexJobDB.purge_terminal_older_than(days=30)
                if purged:
                    api_logger.info(f"Startup: purged {purged} old terminal IndexJob rows")
            except Exception as e:
                api_logger.warning(f"Startup IndexJob purge failed (continuing): {e}")
            yield

    # ---------- FastAPI host ----------
    # openapi_tags 定義 Swagger UI 上 tag 群組的順序 + 群描述。
    # 順序由「user-facing 直觀」→「infra/維運」遞推:檔案管理 → RAG 操作 → 監控。
    openapi_tags = [
        {"name": "Folders",      "description": "資料夾 CRUD"},
        {"name": "Files",        "description": "檔案上傳 / 下載 / 列表 / 屬性修改 / 刪除"},
        {"name": "Media",        "description": "媒體類檔案專用端點(轉錄 / 截圖等)"},
        {"name": "RAG: Indexing","description": "啟動背景索引 job(folder / 單檔 / reindex)"},
        {"name": "RAG: Jobs",    "description": "查詢 / 列表 / 取消 / SSE realtime 進度"},
        {"name": "RAG: Status",  "description": "已索引列表 + 單檔索引狀態"},
        {"name": "RAG: Query",   "description": "Hybrid retrieval + rerank 查詢"},
        {"name": "RAG: Cleanup", "description": "刪除整個 folder 索引 / 刪除單檔索引"},
        {"name": "Health",       "description": "健康檢查 + cache / DB 統計"},
        {"name": "Index",        "description": "Landing page(內部)"},
    ]

    fastapi_app = FastAPI(
        title=app_title,
        description=app_description,
        version=app_version,
        lifespan=lifespan,
        openapi_tags=openapi_tags,
    )
    fastapi_app.state.config = config
    # Stash instructions on app.state so the landing page (/) can render them
    # without re-reading the file. Matches the template's index router contract.
    fastapi_app.state.instructions = instructions

    # Auth system (Token Server)
    initialize_auth_system(config)

    # M6: wiring folder 事件 hooks — folder 建/改/刪時同步 MCP tool 面。
    # adapter(folder.py)只呼叫 hooks、不認識 fastmcp;這裡(app 同時認識兩邊)
    # 把 MCP 層的 register/unregister 掛進去。必須早於任何 folder CRUD 請求 —
    # create_app 內、路由起服務前,任何位置皆滿足;沒 wiring 的話 notify_* 會記
    # ERROR(不阻斷 CRUD,但工具面不同步)。
    from src.adapter.folder_events import set_folder_tool_hooks
    from src.fastmcp_tools.agentic_tools import unregister_folder_tool
    set_folder_tool_hooks(register=register_folder_tool, unregister=unregister_folder_tool)

    # Mount MCP routes
    for route in mcp_app.routes:
        if route not in fastapi_app.routes:
            fastapi_app.routes.append(route)

    # ---------- Module loader ----------
    modules_conf = getattr(config, "modules", None)
    if modules_conf is None:
        raise RuntimeError("Modules configuration is missing in Pydantic ConfigModel.")
    enabled_modules = modules_conf.enabled or []

    for module_name in enabled_modules:
        module_config = Config.get_module_model(module_name)
        if not module_config:
            api_logger.warning(f"No configuration found for module '{module_name}'")
            continue
        try:
            # Load REST API router
            api_router_config = getattr(module_config, "api_router", None)
            if api_router_config:
                module_path = getattr(api_router_config, "module", None)
                router_name = getattr(api_router_config, "router_name", None)
                prefix = getattr(api_router_config, "prefix", None)
                if module_path and router_name:
                    try:
                        module = importlib.import_module(module_path)
                        router = getattr(module, router_name)
                        fastapi_app.include_router(router, prefix=prefix or "")
                        api_logger.info(f"API router loaded: {module_name} (prefix={prefix})")
                    except (ImportError, AttributeError) as e:
                        api_logger.error(f"Failed to load router {module_path}: {e}")
                        record_load_failure(f"router:{module_name}", e)

            # Load MCP tools
            mcp_tools_config = getattr(module_config, "mcp_tools", None)
            if mcp_tools_config:
                module_path = getattr(mcp_tools_config, "module", None)
                function_name = getattr(mcp_tools_config, "function_name", None)
                if module_path and function_name:
                    module = importlib.import_module(module_path)
                    tools_function = getattr(module, function_name)
                    tools_function(mcp)
                    api_logger.info(f"MCP tools loaded: {module_name}")
        except Exception as e:
            api_logger.error(f"Failed to load module '{module_name}': {e}")
            record_load_failure(f"module:{module_name}", e)

    # ---------- Per-folder tool registration ----------
    try:
        api_logger.info("Registering per-folder MCP tools for all known tokens...")
        all_folders = FolderDB.get()
        registered = 0
        for folder in all_folders:
            if folder.user_token:
                try:
                    register_folder_tool(folder.name, folder.description, folder.user_token)
                    registered += 1
                except Exception as e:
                    api_logger.warning(f"Failed to register tool for {folder.name}: {e}")
        api_logger.info(f"✅ Registered {registered} folder-specific MCP tools")
    except Exception as e:
        api_logger.warning(f"Per-folder tool registration encountered errors: {e}")

    # ---------- Health router(從前一版 flat RAG 沿用,功能齊全)----------
    try:
        from src.api.router.health import router as health_router
        fastapi_app.include_router(health_router)
        api_logger.info("Health check router loaded: /health")
    except Exception as e:
        api_logger.error(f"Failed to load health router: {e}")
        record_load_failure("router:health", e)

    # ---------- Index router (landing page at /) ----------
    # Replaces "only /docs has UI" — visiting / now renders title + version +
    # instructions and buttons into /docs and /health.
    try:
        from src.api.router.index import router as index_router
        fastapi_app.include_router(index_router)
        api_logger.info("Index router loaded: GET /")
    except Exception as e:
        api_logger.error(f"Failed to load index router: {e}")
        record_load_failure("router:index", e)

    # ---------- Error handlers ----------
    try:
        from src.middleware.error_handler import register_error_handlers
        register_error_handlers(fastapi_app)
    except Exception as e:
        api_logger.warning(f"Error handler registration skipped: {e}")

    # ---------- Wrap with middleware ----------
    # M15: ASGIErrorBoundary 必須在最外層 — auth / request_id 這兩個純 ASGI
    # wrapper 自身的未預期例外不會經過內層 FastAPI 的 exception handlers,
    # 沒有這層 client 會拿到裸 500 / 斷線而非統一 JSON。
    from src.middleware.asgi_error_boundary import ASGIErrorBoundary
    auth_wrapped = SelectiveAuthMiddleware(app=fastapi_app, config=config)
    final_app = ASGIErrorBoundary(RequestIdMiddleware(app=auth_wrapped))

    auth_enabled = getattr(getattr(config, "auth", None), "enabled", False)
    if auth_enabled:
        api_logger.info(
            f"MCP authentication enabled, protected paths: {SelectiveAuthMiddleware.PROTECTED_PATHS}"
        )

    return final_app
