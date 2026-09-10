
"""Dynamic Tool Manager — 為每個 token 可存取的 folder 註冊單一工具

跟前一版 flat RAG 的 dynamic_tool_manager 對齊(closure pattern),Python 3.13 + Nuitka 已驗證可跑。
唯一差異:此版本工具帶 mode 參數(search/list/read)+ expand_context,功能更豐富。
"""

from typing import Any, Callable, Dict, Literal, Optional

from fastmcp import FastMCP

from src.config.config_manager import Config
from src.log import get_mcptools_logger, mask_token
from db.folderdb import FolderDB

logger = get_mcptools_logger()


class DynamicToolManager:
    """Singleton 管理 per-folder MCP 工具註冊"""

    _instance: Optional["DynamicToolManager"] = None
    _mcp: Optional[FastMCP] = None
    _registered_tools: Dict[str, Callable] = {}                # tool_name -> func
    _token_folder_to_tool: Dict[str, str] = {}                 # "{token}:{folder}" -> tool_name
    _token_folder_descriptions: Dict[str, str] = {}            # "{token}:{folder}" -> description
    # Monotonic version — incremented on every register/unregister so external
    # caches (e.g., AuthFilteredFastMCP._filter_cache) can detect registry changes
    # without a separate invalidation channel.
    _registry_version: int = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, mcp: FastMCP):
        instance = cls()
        instance._mcp = mcp
        logger.info("DynamicToolManager initialized")
        return instance

    @classmethod
    def get_instance(cls) -> "DynamicToolManager":
        if cls._instance is None or cls._instance._mcp is None:
            raise RuntimeError("DynamicToolManager not initialized. Call initialize(mcp) first.")
        return cls._instance

    def get_registered_tools(self) -> Dict[str, Callable]:
        """Return the registry of dynamically registered per-folder tools.

        Used by AuthFilteredFastMCP to distinguish dynamic (folder-scoped) tools
        from static ones — name-prefix heuristics are unreliable when tool_prefix
        changes via config.
        """
        return self._registered_tools

    @classmethod
    def get_registry_version(cls) -> int:
        """Monotonic counter — bumped on every register/unregister.

        External caches keyed by token alone go stale when folders are added or
        removed for that token. Include this version in the cache key so cache
        entries auto-invalidate without an out-of-band purge call.
        """
        return cls._registry_version

    def register_folder_tool(
        self,
        folder_name: str,
        query_function: Callable,
        folder_description: Optional[str] = None,
        user_token: Optional[str] = None,
    ) -> bool:
        """註冊 per-token + per-folder 的工具

        Args:
            folder_name: 資料夾名稱
            query_function: async 函數,簽名 (folder_name, mode, query, file_id, top_k,
                                              expand_context, similarity_cutoff)
            folder_description: 描述,寫進 tool description 引導 agent
            user_token: token(必須)— 用於 ACL 過濾(only 此 token 看得到)

        Returns:
            True if registered (or already exists for this token)
        """
        if self._mcp is None:
            raise RuntimeError("FastMCP instance not set")
        if not user_token:
            logger.error("user_token is required")
            return False

        # ACL 預檢:確認 token 真的有權存取此 folder
        user_folders = FolderDB.get(user_token=user_token)
        if not any(f.name == folder_name for f in user_folders):
            logger.warning(
                f"Token {mask_token(user_token)} has no access to folder '{folder_name}', skip"
            )
            return False

        token_folder_key = f"{user_token}:{folder_name}"

        if folder_description:
            self._token_folder_descriptions[token_folder_key] = folder_description

        if token_folder_key in self._token_folder_to_tool:
            return True  # already registered

        # Tool name: 從 config 拿 prefix(預設 Agentic_)
        config = Config.get_config_model()
        prefix = getattr(getattr(config, "app", None), "tool_prefix", "Agentic")
        tool_name = f"{prefix}_{folder_name}"

        # 此 tool name 已被其他 token 註冊?共享同一個 tool function
        if tool_name in self._registered_tools:
            self._token_folder_to_tool[token_folder_key] = tool_name
            logger.info(
                f"Token {mask_token(user_token)} shares existing tool: {tool_name}"
            )
            return True

        # ---------- 構建工具描述(這是 agent 看到的核心介面文件)----------
        config = Config.get_config_model()
        retrieval = config.rag.retrieval
        default_top_k = retrieval.default_top_k
        default_cutoff = retrieval.default_similarity_cutoff
        default_expand = getattr(retrieval, "expand_context_default", True)

        desc_parts = [
            f"**{folder_name} 資料夾的智慧檢索工具**",
            "",
        ]
        if folder_description:
            desc_parts.append(f"資料夾用途:{folder_description}")
            desc_parts.append("")

        desc_parts.extend([
            "## 三種 mode(注意各自適用情境,不要混用)",
            "",
            "### 🔍 `mode=\"search\"` (預設,**90% 的情況都應該用這個**)",
            "自然語言檢索;命中後自動 auto-merge 同段落 chunks,並展開鄰居 chunks",
            "取得完整上下文。",
            "**使用情境**:",
            "- 使用者問「XXX 是什麼?」「規定怎麼說?」「有沒有提到 YYY?」",
            "- 任何想要從資料夾找答案、找線索、找片段的需求",
            "- 不確定答案在哪一份檔案中",
            "",
            "### 📋 `mode=\"list\"` (列目錄)",
            "列出此資料夾所有檔案及 file_id、estimated_tokens、indexed_status。",
            "**使用情境**:",
            "- 使用者問「這資料夾有哪些檔案?」「給我目錄」",
            "- 你需要 file_id 才能做後續 read(罕見)",
            "- ❌ 不要為了「先看看有什麼再決定查什麼」而呼叫 — 直接 search 就好",
            "",
            "### 📖 `mode=\"read\"` (整份載入,**嚴格使用**)",
            "把整份檔案的全部文字內容載入(最多 ~30000 tokens)。",
            "**僅在以下情況使用**:",
            "- ✅ 使用者**明確要求**「給我完整內容」「逐字稿」「整份報告/文件」",
            "- ✅ 使用者要求「逐字逐句翻譯 / 整理」整份檔案",
            "- ✅ 該檔案是**音訊轉錄稿**(Whisper 結果)且使用者要看完整對話",
            "",
            "**❌ 絕對不要在以下情境使用 read**:",
            "- 為了回答某個具體問題 → 用 search,不要 read",
            "- 「我想多了解這份檔案」這類模糊需求 → 用 search 抓 query 相關內容",
            "- search 結果不滿意 → 改 search query / 調 cutoff,不是直接 read",
            "- 探索性瀏覽 → 用 list 看目錄,不是 read 整份",
            "",
            "**為什麼嚴格**:read 一次塞 ~3000-30000 tokens 進你的 context,",
            "大部分內容跟使用者問題無關,浪費 token 預算又稀釋你的注意力。",
            "search 模式已經帶 auto-merge + context expansion,通常給的內容就夠回答。",
            "",
            "## 參數",
            "- `query` (str):mode=search 必填;mode=list/read 忽略",
            "- `mode` (str):search / list / read,預設 search",
            "- `file_id` (str):mode=read 必填(從 list 或 search 結果取得)",
            f"- `top_k` (int):mode=search 用,預設 {default_top_k}",
            f"- `similarity_cutoff` (float):mode=search 用,預設 {default_cutoff}",
            f"- `expand_context` (bool):mode=search 用,預設 {str(default_expand).lower()}",
            "",
            "回應結構:JSON 含 mode、results、_hint(下一步建議)",
        ])
        description = "\n".join(desc_parts)

        # ---------- 構建工具函數(對齊前一版 flat RAG 同 closure pattern)----------
        def create_tool_func(top_k, similarity_cutoff, expand_context):
            async def agentic_tool(
                query: str = "",
                mode: Literal["search", "list", "read"] = "search",
                file_id: Optional[str] = None,
                top_k: int = top_k,
                similarity_cutoff: float = similarity_cutoff,
                expand_context: bool = expand_context,
            ) -> list:
                return await query_function(
                    folder_name=folder_name,
                    mode=mode,
                    query=query,
                    file_id=file_id,
                    top_k=top_k,
                    similarity_cutoff=similarity_cutoff,
                    expand_context=expand_context,
                )
            return agentic_tool

        agentic_tool = create_tool_func(default_top_k, default_cutoff, default_expand)

        # 設置函數元數據(前一版 flat RAG 同樣作法)
        agentic_tool.__name__ = tool_name
        agentic_tool.__doc__ = f"Agentic RAG tool for folder '{folder_name}' (search / list / read modes)"
        tool_func = agentic_tool

        self._mcp.tool(
            name=tool_name,
            description=description,
            output_schema=None,
        )(tool_func)

        self._registered_tools[tool_name] = tool_func
        self._token_folder_to_tool[token_folder_key] = tool_name
        DynamicToolManager._registry_version += 1  # bust external caches

        logger.info(
            f"✅ Registered {tool_name} (token={mask_token(user_token)}, folder={folder_name})"
        )
        return True

    def unregister_folder_tool(self, folder_name: str, user_token: str):
        """移除 user_token 對某 folder 工具的訪問權。

        若該 token 是最後一個使用者,連 tool 本身一起 unregister。

        Args:
            folder_name: folder 名(對應已註冊工具)。
            user_token: 要移除的 token。
        """
        if self._mcp is None:
            raise RuntimeError("FastMCP instance not set")
        if not user_token:
            return

        token_folder_key = f"{user_token}:{folder_name}"
        tool_name = self._token_folder_to_tool.get(token_folder_key)
        if not tool_name:
            return

        self._token_folder_to_tool.pop(token_folder_key, None)
        self._token_folder_descriptions.pop(token_folder_key, None)
        DynamicToolManager._registry_version += 1  # bust external caches

        # 還有其他 token 在用嗎?
        still_in_use = any(
            t == tool_name for t in self._token_folder_to_tool.values()
        )
        if not still_in_use:
            try:
                # FastMCP v3:mcp.remove_tool() 已 deprecated,改走 local_provider
                if hasattr(self._mcp, "local_provider") and hasattr(
                    self._mcp.local_provider, "remove_tool"
                ):
                    self._mcp.local_provider.remove_tool(tool_name)
                else:
                    # 備援:舊版 FastMCP 還是用頂層 API
                    self._mcp.remove_tool(tool_name)
            except Exception as e:
                logger.warning(f"Failed to remove tool {tool_name} from MCP: {e}")
            self._registered_tools.pop(tool_name, None)
            logger.info(f"Tool '{tool_name}' fully removed (no remaining users)")
        else:
            logger.info(f"Token {mask_token(user_token)} removed from '{tool_name}' (others still use it)")

    def get_tools_by_token(self, user_token: str) -> list[str]:
        return [
            tool_name
            for key, tool_name in self._token_folder_to_tool.items()
            if key.startswith(f"{user_token}:")
        ]

    def get_folder_description_for_token(
        self, folder_name: str, user_token: str
    ) -> Optional[str]:
        return self._token_folder_descriptions.get(f"{user_token}:{folder_name}")

    def get_folder_name_from_tool(self, tool_name: str) -> Optional[str]:
        config = Config.get_config_model()
        prefix = getattr(getattr(config, "app", None), "tool_prefix", "Agentic")
        full_prefix = f"{prefix}_"
        if tool_name.startswith(full_prefix):
            return tool_name[len(full_prefix):]
        return None
