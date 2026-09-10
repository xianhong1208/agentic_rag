# 整合現有 API 成 MCP 服務：兩種方案完整指南


本指南說明：當你**已經有一套開發好的 API / 業務系統**，要如何用本範本把它包成 MCP 服務，讓 AI agent 能呼叫。提供兩種方案：

| 方案 | 一句話 | 既有 API 的程式碼 | 既有 API 是否繼續獨立運作 |
|------|--------|------------------|--------------------------|
| **方案一：橋接 (Bridge)** | MCP 當前置代理，用 HTTP 去打你原本的 API | 留在原處，不搬 | ✅ 是，照常運作 |
| **方案二：搬遷 (Migrate)** | 把 API 的程式碼搬進本範本，MCP 直接呼叫 | 搬進 `src/` | ❌ 否，邏輯改由本服務承載 |

---

## 0. 共同基礎：MCP 工具是什麼

兩種方案最後都落在同一件事——**寫一個帶 docstring 的 `async` 函式，用 `@mcp.tool()` 註冊**：

```python
@mcp.tool()
async def get_order(order_id: str) -> dict:
    """查詢單一訂單明細。order_id 例如 "ORD-001"。"""
    ...
```

- **docstring 與型別註記 = 給 AI 看的介面契約**。AI 靠它決定何時呼叫、傳什麼參數。寫清楚「做什麼、參數意義、何時用」。
- 兩方案的差別只在「函式內部怎麼拿到資料」：橋接是 `await httpx...`，搬遷是 `await service...`。

**註冊與掛載流程（兩方案相同）：**

1. 在 `src/fastmcp_tools/你的模組.py` 寫一個 `register_xxx_tools(mcp)` 函式。
2. 在 `config/config.yaml` 的 `modules` 區段註冊它。
3. 重啟服務，App Factory（`app.py`）會用 `importlib` 動態載入。

```yaml
# config/config.yaml
modules:
  enabled:
    - order               # ← 啟用你的模組
  order:
    mcp_tools:
      module: "src.fastmcp_tools.order_tools"
      function_name: "register_order_tools"
    # 若也要對外開 REST API（可選）
    api_router:
      module: "src.api.router.order_api"
      router_name: "router"
      prefix: "/api"
```

---

## 1. 怎麼選？決策表

| 考量點 | 選「橋接」 | 選「搬遷」 |
|--------|-----------|-----------|
| 既有 API 要不要繼續被其他系統（網站、App）使用 | 要 → 橋接 | 只剩 AI 用 → 可搬遷 |
| 既有 API 的程式語言 | 任何語言（Java/.NET/Go…）皆可 | 最好是 Python（否則要重寫） |
| 你是否擁有/能改既有 API 的原始碼 | 不一定需要 | 需要（要搬程式碼） |
| 延遲要求 | 可接受多一次內網 HTTP 往返 | 要最低延遲（少一跳） |
| 部署單純度 | 兩個服務分開部署 | 一個服務搞定 |
| 上線速度 | 快（不動既有系統） | 慢（要搬程式碼、處理依賴） |

> **經驗法則**：既有 API 還要服務其他客戶端、或不是 Python → **橋接**。
> 既有 API 只為了被 AI 呼叫而存在、且是 Python → **搬遷**（少一個要維護的服務）。

也可以**混用**：核心走搬遷、少數外部系統走橋接。

---

## 2. 方案一：橋接 (Bridge)

### 2.1 架構

```
AI Client ──MCP──▶ 本 MCP 服務 ──HTTP──▶ 你既有的 API ──▶ DB / 其他系統
                   (本範本)              (留在原處，不動)
```

本服務只做三件事：(1) 認證 MCP 呼叫者、(2) 把參數轉成對既有 API 的 HTTP 請求、(3) 把回應整理回傳給 AI。

### 2.2 完整範例

```python
# src/fastmcp_tools/order_tools.py
"""訂單系統 MCP 工具 —— 橋接既有的訂單 REST API"""
import os
import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from src.log import get_api_logger
from src.domain.exceptions import ResourceNotFoundError, ValidationError

logger = get_api_logger()

# 後端 API 位址用環境變數，不要寫死（見 config 與 .env.example）
ORDER_API_BASE = os.environ.get("ORDER_API_BASE", "http://localhost:8080")

# 重用單一 AsyncClient（連線池），避免每次呼叫都重建連線
_client = httpx.AsyncClient(base_url=ORDER_API_BASE, timeout=10.0)


def register_order_tools(mcp: FastMCP):
    """註冊訂單相關 MCP 工具"""

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """查詢單一訂單的明細。

        Args:
            order_id: 訂單編號，例如 "ORD-20240101-001"

        Returns:
            訂單資料（狀態、金額、品項）。
        """
        if not order_id.strip():
            raise ValidationError(field="order_id", message="不可為空")

        resp = await _client.get(f"/orders/{order_id}")
        if resp.status_code == 404:
            raise ResourceNotFoundError(resource_type="order", identifier=order_id)
        resp.raise_for_status()
        return resp.json()

    @mcp.tool()
    async def search_orders(customer: str, status: str = "all") -> list:
        """依客戶名稱搜尋訂單。

        Args:
            customer: 客戶名稱
            status: 狀態篩選 "all" / "pending" / "shipped" / "done"
        """
        resp = await _client.get("/orders", params={"customer": customer, "status": status})
        resp.raise_for_status()
        return resp.json()
```

### 2.3 轉發呼叫者身分（企業最常漏）

MCP 中間件會先驗證呼叫者 token。若既有 API 也要做授權，**把同一個 token 帶下去**。
本範本內建 helper `extract_token()`（`src/api/dependencies/auth.py`），取出**純 token**（已去掉 `"Bearer "` 前綴）：

```python
from src.api.dependencies.auth import extract_token   # 範本內建 helper

@mcp.tool()
async def get_my_orders() -> list:
    """查詢目前登入使用者的所有訂單。"""
    token = await extract_token(get_http_request())    # 取出純 token，例如 "xxx"
    resp = await _client.get(
        "/orders/mine",
        headers={"Authorization": f"Bearer {token}"},  # 後端要完整 header → 補回 "Bearer "
    )
    resp.raise_for_status()
    return resp.json()
```

> 兩個取得方式擇一：
> - `extract_token(request)` → 純 token（適合記 log、當 cache key、或後端只要 token）。**注意是 `async`，要 `await`**。
> - `get_http_request().headers.get("Authorization")` → 整個 `"Bearer xxx"` header（若只是要**原樣轉發**，這個更直接，不必再拼回 `"Bearer "`）。

### 2.4 設定與環境變數

```yaml
# config/config.yaml — 把後端位址也納入設定（可選，亦可只用環境變數）
modules:
  enabled: [order]
  order:
    mcp_tools:
      module: "src.fastmcp_tools.order_tools"
      function_name: "register_order_tools"
```

```bash
# .env（參考 .env.example）
ORDER_API_BASE=http://internal-order-api:8080
```

### 2.5 優缺點

**優點**：不動既有系統、語言無關、上線快、既有 API 可繼續服務其他客戶端。
**缺點**：多一次內網 HTTP 往返（延遲）；要部署/監控兩個服務；既有 API 掛了 MCP 也跟著失效。

### 2.6 企業常問（橋接）

- **連線池**：用模組層級單一 `httpx.AsyncClient`（如上），不要每次呼叫 `with httpx.AsyncClient()`，否則無法重用連線、效能差。
- **逾時與重試**：`timeout` 必設；冪等的 GET 可加重試（可參考 `src/auth/remote_auth.py` 的重試寫法）。
- **大量回應**：只回傳 AI 需要的欄位，別把整包原始 JSON 丟回去——會吃光 token。
- **串流**：需要 SSE/串流時，本範本的 transport 已支援；工具回傳改用 generator/async iterator。

---

## 3. 方案二：搬遷 (Migrate)

### 3.1 架構

```
AI Client ──MCP──▶ 本 MCP 服務 ──直接函式呼叫──▶ 你的業務邏輯 ──▶ DB
                   (本範本，已內含原 API 的程式碼)
```

少一跳網路，邏輯與資料存取都在同一個 process。

### 3.2 搬遷步驟

1. **放置業務邏輯**：把既有 API 的「service / 業務層」程式碼搬到 `src/domain/`（純業務）或新建 `src/adapter/`（外部系統存取）。建議**只搬 service 層，不要把舊的 Flask/FastAPI 路由整包搬進來**——路由交給本範本的 `src/api/router/`。
2. **加依賴**：把既有 API 用到的套件加進 `pyproject.toml` 的 `dependencies`，執行 `uv sync`。
3. **搬設定**：原本散落各處的設定，集中到 `config/config.yaml`（新增區段時，在 `src/config/model.py` 加對應 Pydantic model）。機密改用 `${VAR:-default}` + `.env`。
4. **搬 DB**（若有）：ORM models 放 `db/`，用 `--migrate-only generate` 產生 Alembic migration。
5. **寫 MCP 工具**：薄薄一層，呼叫搬進來的 service。
6. **（可選）保留 REST API**：同一個 service 層也能被 `src/api/router/` 的 FastAPI 路由呼叫——**一份邏輯，REST 與 MCP 共用**。

### 3.3 完整範例

```python
# src/domain/order_service.py  ← 搬進來的業務邏輯（與框架無關）
from src.domain.exceptions import ResourceNotFoundError

class OrderService:
    def __init__(self, repo):
        self._repo = repo

    async def get_order(self, order_id: str) -> dict:
        order = await self._repo.find(order_id)
        if order is None:
            raise ResourceNotFoundError(resource_type="order", identifier=order_id)
        return order.to_dict()
```

```python
# src/fastmcp_tools/order_tools.py  ← MCP 工具：薄薄一層
from fastmcp import FastMCP
from src.domain.order_service import OrderService
from src.adapter.order_repo import OrderRepo

def register_order_tools(mcp: FastMCP):
    service = OrderService(repo=OrderRepo())

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """查詢單一訂單的明細。order_id 例如 "ORD-001"。"""
        return await service.get_order(order_id)
```

```python
# src/api/router/order_api.py  ← （可選）同一個 service 也開成 REST API
from fastapi import APIRouter, Depends
from src.api.dependencies.auth import authenticate_request
from src.domain.order_service import OrderService
from src.adapter.order_repo import OrderRepo

router = APIRouter(tags=["Order"])
_service = OrderService(repo=OrderRepo())

@router.get("/orders/{order_id}")
async def get_order(order_id: str, auth=Depends(authenticate_request)):
    return await _service.get_order(order_id)
```

> 重點：**MCP 工具與 REST 路由都只是薄薄的轉接層，真正的邏輯只寫一次在 `OrderService`**。這就是搬遷最大的好處——單一事實來源。

### 3.4 優缺點

**優點**：延遲最低、單一服務好部署/監控、邏輯與 MCP 同版控、REST 與 MCP 共用邏輯。
**缺點**：要動原始碼、處理依賴衝突、既有 API 若還有其他客戶端就得保留或雙跑。

### 3.5 企業常問（搬遷）

- **依賴衝突**：搬進來的套件可能與本範本既有版本相衝；用 `uv` 的 lock 一次解決，衝突時優先就高版本。
- **舊框架殘留**：不要把舊的 Flask/Django app 物件搬進來，只搬「不依賴框架的業務函式」。框架層用本範本的。
- **DB 遷移**：既有資料庫沿用即可，只要 `DATABASE_URL` 指過去；schema 用 Alembic 接管（先 `stamp` 再 `generate`）。
- **設定遷移**：所有 `os.environ` 直接讀的地方，建議改走 `config.yaml` + Pydantic model，型別更安全。

---

## 4. 兩案共通

### 4.1 錯誤處理

工具/邏輯內 `raise` 本範本的 `DomainException` 子類，中間件會自動轉成正確的 HTTP 狀態與結構化錯誤：

| 例外 | HTTP | 用途 |
|------|------|------|
| `ValidationError` | 400 | 參數錯誤 |
| `InvalidTokenError` | 401 | token 無效 |
| `UnauthorizedAccessError` | 403 | 無權限 |
| `ResourceNotFoundError` | 404 | 找不到資源 |
| `ConflictError` | 409 | 衝突（如重複建立） |

（定義在 `src/domain/exceptions.py`；要新增就繼承 `DomainException` 並在 `get_http_status_for_exception()` 加 mapping。）

### 4.2 認證

- **MCP 路徑**（`/mcp`）：由 `SelectiveAuthMiddleware` 自動驗證，遵守 `config.yaml` 的 `auth.enabled`。
- **工具內取 token**：`from fastmcp.server.dependencies import get_http_request` → `request.headers.get("Authorization")`。
- **REST 路由**：`auth=Depends(authenticate_request)`，同樣遵守 `auth.enabled`（關閉時回匿名身分，方便本機測試）。

### 4.3 測試

兩案都建議寫測試（慣例見 `tests/`）：
- 橋接：用 `unittest.mock` patch 掉 `httpx`，不真的連線（參考 `tests/test_remote_auth.py`）。
- 搬遷：直接測 `OrderService`，repo 用 mock 注入（建構式注入 `repo`，測試最好寫）。

---

## 5. 快速對照總結

| | 橋接 Bridge | 搬遷 Migrate |
|---|---|---|
| 既有 API | 不動，HTTP 呼叫 | 程式碼搬進來 |
| 適合 | 多客戶端 / 非 Python / 快速上線 | 只給 AI / Python / 要低延遲 |
| 延遲 | +1 HTTP 跳 | 最低 |
| 部署 | 兩服務 | 單服務 |
| 工具內部 | `await httpx...` | `await service...` |
| 共通 | 註冊流程、認證、錯誤處理、設定、測試 完全一樣 | |

---
