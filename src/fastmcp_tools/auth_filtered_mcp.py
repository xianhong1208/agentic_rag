
"""自定義 FastMCP 類,實現基於 token 的工具權限過濾

FastMCP v3.x 的 list_tools 機制:
  - public method: `async def list_tools(*, run_middleware: bool = True)`
  - 當 run_middleware=True(預設,client 真實呼叫時):
        會把控制權交給 middleware chain,最後 call_next 又叫
        `self.list_tools(run_middleware=False)` 拿底層真正工具列表
  - 當 run_middleware=False:跳過 middleware,實際從 provider 拿 tools

我們要過濾在 run_middleware=False 階段做 — 那是最內層、middleware 看不到的地方,
也是 FastMCP 真正把 list 包進 response 前最後一道。

舊版實作走的 `_list_tools` 是 FastMCP v2 的 API,在 v3 不存在,所以
override 沒生效,每個 token 都看到全部工具 — 這正是你遇到的問題。
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import traceback

from cachetools import TTLCache
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from db.folderdb import FolderDB
from src.log import get_api_logger, mask_token
from src.auth.dependencies import get_remote_verifier_instance
from src.fastmcp_tools.dynamic_tool_manager import DynamicToolManager

if TYPE_CHECKING:
    from mcp.types import Tool

api_logger = get_api_logger()

# Cache filtered tool lists per token — every MCP list_tools call previously did
# token-verify + FolderDB.get round-trip. With many MCP clients polling list_tools
# this dominated request latency. TTL matches auth.cache_ttl (60s) — if it gets
# out of sync slightly that's OK, worst case is a stale tool list for <1min.
_FILTER_CACHE_TTL = 60
_FILTER_CACHE_MAX = 1024
_filter_cache: "TTLCache[str, list]" = TTLCache(maxsize=_FILTER_CACHE_MAX, ttl=_FILTER_CACHE_TTL)


class AuthFilteredFastMCP(FastMCP):
    """擴展 FastMCP 以支援基於 token 的工具過濾

    每個 token 只能看到自己有權限的 folder 對應的 MCP tools。
    """

    def _is_dynamic_folder_tool(self, tool_name: str) -> bool:
        """判斷工具是否為動態註冊的 per-folder 工具。

        正規:查 DynamicToolManager.registered_tools;備援:看名稱前綴(Agentic_)。

        Args:
            tool_name: 工具名稱。

        Returns:
            True = 動態工具(應走 ACL filter);False = 全域工具。
        """
        try:
            manager = DynamicToolManager.get_instance()
            if tool_name in manager.get_registered_tools():
                return True
            # 備援:某些 agentic_rag 部署環境 prefix 可能不一致
            return tool_name.startswith("Agentic_")
        except Exception:
            return tool_name.startswith("Agentic_")

    # ============================================================================
    # FastMCP v3.x 的正確 override 位置 — public method `list_tools`
    # ============================================================================
    async def list_tools(self, *, run_middleware: bool = True) -> "Sequence[Tool]":
        """list_tools override ─ 在 middleware 內層套 per-token ACL(避免雙層過濾)。

        FastMCP 兩層呼叫:run_middleware=True 是 client 入口,遞迴會再 call 一次 False;
        我們只在 False 那層套 ACL,確保 middleware 看到已過濾結果,且不重複跑 filter。

        Args:
            run_middleware: True = 入口層(走 middleware chain);False = 實際 fetch。

        Returns:
            過濾後的工具 list(該 token 看得到的)。
        """
        # 先讓 FastMCP 跑完它的 middleware / transforms / visibility 邏輯
        tools = await super().list_tools(run_middleware=run_middleware)

        # 只在最內層 fetch 階段套 ACL,避免兩次過濾
        if not run_middleware:
            tools = await self._apply_token_filter(list(tools))

        return tools

    async def _apply_token_filter(self, all_tools: list) -> list:
        """依當前 request 的 token 過濾工具列表(帶 TTL cache)。

        沒 token → 只回靜態工具。有效 token → 對每動態工具檢查 ACL + 注入 folder description。
        cache 走 _filter_cache (60s TTL,DynamicToolManager 註冊變更 bump version 自動 invalidate)。

        Args:
            all_tools: 全部已註冊工具的 list。

        Returns:
            過濾後 + description 已注入的工具 list。
        """
        _remote_verifier = get_remote_verifier_instance()

        try:
            request = get_http_request()
            auth_header = request.headers.get("Authorization", "")

            if not auth_header or not auth_header.startswith("Bearer "):
                api_logger.warning(
                    "list_tools without valid token, hiding all per-folder tools"
                )
                return [t for t in all_tools if not self._is_dynamic_folder_tool(t.name)]

            parts = auth_header.split(" ")
            token = parts[1] if len(parts) > 1 else ""

            # Cache key includes registry version so register/unregister auto-busts
            cache_key = f"{token}:{DynamicToolManager.get_registry_version()}"
            cached = _filter_cache.get(cache_key)
            if cached is not None:
                return cached

            if _remote_verifier is None:
                api_logger.warning(
                    "Remote verifier not initialized, hiding all per-folder tools"
                )
                return [t for t in all_tools if not self._is_dynamic_folder_tool(t.name)]

            result = await _remote_verifier.verify(token)
            if not result.valid:
                api_logger.warning(f"list_tools invalid token: {mask_token(token)}")
                return [t for t in all_tools if not self._is_dynamic_folder_tool(t.name)]

            # 找出該 token 可看到的 per-folder 工具
            try:
                manager = DynamicToolManager.get_instance()
                user_folders = FolderDB.get(user_token=token)
                allowed: set = set()
                if user_folders:
                    for folder in user_folders:
                        tool_name = manager._token_folder_to_tool.get(
                            f"{token}:{folder.name}"
                        )
                        if tool_name:
                            allowed.add(tool_name)
            except Exception as e:
                api_logger.error(f"Error getting allowed tools for token: {e}")
                allowed = set()

            # 過濾 + 注入 per-token folder description
            filtered: list = []
            for tool in all_tools:
                if not self._is_dynamic_folder_tool(tool.name):
                    filtered.append(tool)
                    continue
                if tool.name not in allowed:
                    continue

                # 動態注入該 token 的 folder description
                folder_name = manager.get_folder_name_from_tool(tool.name)
                if folder_name:
                    folder_desc = manager.get_folder_description_for_token(folder_name, token)
                    if folder_desc:
                        new_desc = f"{tool.description}\n\n資料夾說明:{folder_desc}"
                        tool = tool.model_copy(update={"description": new_desc})
                filtered.append(tool)

            api_logger.info(
                f"list_tools: token {mask_token(token)} sees {len(filtered)}/{len(all_tools)} tools "
                f"({len(allowed)} per-folder)"
            )
            _filter_cache[cache_key] = filtered
            return filtered

        except Exception as e:
            api_logger.error(f"Error in list_tools filtering: {e}")
            traceback.print_exc()
            # 安全保底:任何例外都隱藏所有動態工具
            return [t for t in all_tools if not self._is_dynamic_folder_tool(t.name)]
