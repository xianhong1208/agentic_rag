
"""Tool Handlers — re-export shim(M6)。

三模式 handler(handle_search / handle_list / handle_read)已搬進 domain:
src/domain/rag/agentic_handlers.py。它們不含任何 fastmcp 依賴,住在交付層
造成 adapter 反向 import(fastmcp → adapter → fastmcp 層次環)。

此檔保留原 import 路徑向下相容;新 code 請直接 import domain 模組。
"""

from src.domain.rag.agentic_handlers import (  # noqa: F401
    handle_list,
    handle_read,
    handle_search,
)
