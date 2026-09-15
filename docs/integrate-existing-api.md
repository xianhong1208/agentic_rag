# Integrating an Existing API as an MCP Service: A Complete Guide to Two Approaches


This guide explains how, when you **already have a developed API / business system**, to use this template to wrap it as an MCP service that AI agents can call. It offers two approaches:

| Approach | In one line | Existing API's code | Does the existing API keep running independently |
|------|--------|------------------|--------------------------|
| **Approach 1: Bridge** | MCP acts as a front proxy, calling your original API over HTTP | Stays where it is, not moved | ✅ Yes, runs as before |
| **Approach 2: Migrate** | Move the API's code into this template; MCP calls it directly | Moved into `src/` | ❌ No, the logic is now carried by this service |

---

## 0. Common Foundation: What an MCP Tool Is

Both approaches ultimately come down to the same thing — **writing an `async` function with a docstring and registering it with `@mcp.tool()`**:

```python
@mcp.tool()
async def get_order(order_id: str) -> dict:
    """Query the details of a single order. order_id example: "ORD-001"."""
    ...
```

- **The docstring and type annotations = the interface contract the AI reads**. The AI uses them to decide when to call and what arguments to pass. State clearly "what it does, what the parameters mean, when to use it".
- The only difference between the two approaches is "how the function obtains its data internally": Bridge does `await httpx...`, Migrate does `await service...`.

**Registration and mounting flow (identical for both approaches):**

1. Write a `register_xxx_tools(mcp)` function in `src/fastmcp_tools/your_module.py`.
2. Register it in the `modules` section of `config/config.yaml`.
3. Restart the service; the App Factory (`app.py`) loads it dynamically via `importlib`.

```yaml
# config/config.yaml
modules:
  enabled:
    - order               # ← enable your module
  order:
    mcp_tools:
      module: "src.fastmcp_tools.order_tools"
      function_name: "register_order_tools"
    # if you also want to expose a REST API (optional)
    api_router:
      module: "src.api.router.order_api"
      router_name: "router"
      prefix: "/api"
```

---

## 1. How to Choose? Decision Table

| Consideration | Choose "Bridge" | Choose "Migrate" |
|--------|-----------|-----------|
| Does the existing API need to keep serving other systems (website, app) | Yes → Bridge | Only AI uses it → can Migrate |
| The existing API's programming language | Any language (Java/.NET/Go…) works | Preferably Python (otherwise a rewrite is needed) |
| Do you own / can you modify the existing API's source | Not necessarily | Required (you need to move the code) |
| Latency requirement | Can tolerate an extra internal HTTP round trip | Needs the lowest latency (one hop fewer) |
| Deployment simplicity | Two services deployed separately | One service does it all |
| Time to go live | Fast (existing system untouched) | Slower (move code, resolve dependencies) |

> **Rule of thumb**: If the existing API still serves other clients, or is not Python → **Bridge**.
> If the existing API exists only to be called by AI and is Python → **Migrate** (one fewer service to maintain).

You can also **mix**: core via Migrate, a few external systems via Bridge.

---

## 2. Approach 1: Bridge

### 2.1 Architecture

```
AI Client ──MCP──▶ This MCP service ──HTTP──▶ Your existing API ──▶ DB / other systems
                   (this template)            (stays in place, untouched)
```

This service does only three things: (1) authenticate the MCP caller, (2) translate parameters into an HTTP request to the existing API, and (3) tidy the response and return it to the AI.

### 2.2 Complete Example

```python
# src/fastmcp_tools/order_tools.py
"""Order-system MCP tools — bridges the existing order REST API"""
import os
import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from src.log import get_api_logger
from src.domain.exceptions import ResourceNotFoundError, ValidationError

logger = get_api_logger()

# Use an environment variable for the backend API address; do not hardcode it (see config and .env.example)
ORDER_API_BASE = os.environ.get("ORDER_API_BASE", "http://localhost:8080")

# Reuse a single AsyncClient (connection pool); avoid rebuilding the connection on every call
_client = httpx.AsyncClient(base_url=ORDER_API_BASE, timeout=10.0)


def register_order_tools(mcp: FastMCP):
    """Register order-related MCP tools"""

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """Query the details of a single order.

        Args:
            order_id: The order number, e.g. "ORD-20240101-001"

        Returns:
            Order data (status, amount, items).
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
        """Search orders by customer name.

        Args:
            customer: Customer name
            status: Status filter "all" / "pending" / "shipped" / "done"
        """
        resp = await _client.get("/orders", params={"customer": customer, "status": status})
        resp.raise_for_status()
        return resp.json()
```

### 2.3 Forwarding the Caller's Identity (the enterprise thing most often missed)

The MCP middleware validates the caller's token first. If the existing API also does authorization, **pass the same token downstream**.
This template ships a helper `extract_token()` (`src/api/dependencies/auth.py`) that returns the **bare token** (with the `"Bearer "` prefix already stripped):

```python
from src.api.dependencies.auth import extract_token   # built-in template helper

@mcp.tool()
async def get_my_orders() -> list:
    """Query all orders of the currently logged-in user."""
    token = await extract_token(get_http_request())    # get the bare token, e.g. "xxx"
    resp = await _client.get(
        "/orders/mine",
        headers={"Authorization": f"Bearer {token}"},  # the backend wants the full header → re-add "Bearer "
    )
    resp.raise_for_status()
    return resp.json()
```

> Pick one of two ways to obtain it:
> - `extract_token(request)` → the bare token (good for logging, as a cache key, or when the backend wants only the token). **Note it is `async`; you must `await` it.**
> - `get_http_request().headers.get("Authorization")` → the whole `"Bearer xxx"` header (if you just want to **forward it verbatim**, this is more direct — no need to re-assemble the `"Bearer "` prefix).

### 2.4 Configuration and Environment Variables

```yaml
# config/config.yaml — put the backend address into config too (optional; you may use an env var only)
modules:
  enabled: [order]
  order:
    mcp_tools:
      module: "src.fastmcp_tools.order_tools"
      function_name: "register_order_tools"
```

```bash
# .env (see .env.example)
ORDER_API_BASE=http://internal-order-api:8080
```

### 2.5 Pros and Cons

**Pros**: existing system untouched, language-agnostic, fast to go live, the existing API keeps serving other clients.
**Cons**: an extra internal HTTP round trip (latency); two services to deploy/monitor; if the existing API goes down, MCP fails with it.

### 2.6 Common Enterprise Questions (Bridge)

- **Connection pool**: use a single module-level `httpx.AsyncClient` (as above); do not call `with httpx.AsyncClient()` on every call, or connections cannot be reused and performance suffers.
- **Timeout and retry**: `timeout` is mandatory; idempotent GETs can add retries (see the retry pattern in `src/auth/remote_auth.py`).
- **Large responses**: return only the fields the AI needs; do not dump the entire raw JSON — it eats up tokens.
- **Streaming**: when you need SSE/streaming, this template's transport already supports it; have the tool return a generator/async iterator.

---

## 3. Approach 2: Migrate

### 3.1 Architecture

```
AI Client ──MCP──▶ This MCP service ──direct function call──▶ Your business logic ──▶ DB
                   (this template, now containing the original API's code)
```

One fewer network hop; logic and data access are in the same process.

### 3.2 Migration Steps

1. **Place the business logic**: move the existing API's "service / business layer" code into `src/domain/` (pure business) or a new `src/adapter/` (external-system access). Recommended: **move only the service layer; do not move the old Flask/FastAPI routes wholesale** — leave routing to this template's `src/api/router/`.
2. **Add dependencies**: add the packages the existing API uses to `pyproject.toml`'s `dependencies` and run `uv sync`.
3. **Move config**: consolidate settings scattered across the codebase into `config/config.yaml` (when adding a section, add the corresponding Pydantic model in `src/config/model.py`). Move secrets to `${VAR:-default}` + `.env`.
4. **Move the DB** (if any): put ORM models in `db/` and generate an Alembic migration with `--migrate-only generate`.
5. **Write MCP tools**: a thin layer that calls the migrated service.
6. **(Optional) Keep the REST API**: the same service layer can also be called by FastAPI routes in `src/api/router/` — **one set of logic, shared by REST and MCP**.

### 3.3 Complete Example

```python
# src/domain/order_service.py  ← migrated business logic (framework-agnostic)
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
# src/fastmcp_tools/order_tools.py  ← MCP tool: a thin layer
from fastmcp import FastMCP
from src.domain.order_service import OrderService
from src.adapter.order_repo import OrderRepo

def register_order_tools(mcp: FastMCP):
    service = OrderService(repo=OrderRepo())

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """Query the details of a single order. order_id example: "ORD-001"."""
        return await service.get_order(order_id)
```

```python
# src/api/router/order_api.py  ← (optional) expose the same service as a REST API too
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

> Key point: **both the MCP tool and the REST route are thin adapters; the real logic is written once in `OrderService`**. This is the biggest benefit of migrating — a single source of truth.

### 3.4 Pros and Cons

**Pros**: lowest latency, a single service that is easy to deploy/monitor, logic version-controlled with MCP, logic shared by REST and MCP.
**Cons**: you must touch the source, resolve dependency conflicts, and if the existing API still has other clients you must keep it or run both.

### 3.5 Common Enterprise Questions (Migrate)

- **Dependency conflicts**: the migrated packages may conflict with this template's existing versions; resolve them once with `uv`'s lock, preferring the higher version on conflict.
- **Legacy framework leftovers**: do not move the old Flask/Django app object; move only the "framework-independent business functions". Use this template's framework layer.
- **DB migration**: keep using the existing database — just point `DATABASE_URL` at it; have Alembic take over the schema (`stamp` first, then `generate`).
- **Config migration**: for every place that reads `os.environ` directly, prefer moving to `config.yaml` + a Pydantic model for stronger typing.

---

## 4. Common to Both Approaches

### 4.1 Error Handling

Inside a tool/logic, `raise` one of this template's `DomainException` subclasses, and the middleware automatically converts it into the correct HTTP status and structured error:

| Exception | HTTP | Purpose |
|------|------|------|
| `ValidationError` | 400 | Bad parameter |
| `InvalidTokenError` | 401 | Invalid token |
| `UnauthorizedAccessError` | 403 | No permission |
| `ResourceNotFoundError` | 404 | Resource not found |
| `ConflictError` | 409 | Conflict (e.g. duplicate creation) |

(Defined in `src/domain/exceptions.py`; to add one, subclass `DomainException` and add a mapping in `get_http_status_for_exception()`.)

### 4.2 Authentication

- **MCP path** (`/mcp`): validated automatically by `SelectiveAuthMiddleware`, honoring `auth.enabled` in `config.yaml`.
- **Getting the token inside a tool**: `from fastmcp.server.dependencies import get_http_request` → `request.headers.get("Authorization")`.
- **REST routes**: `auth=Depends(authenticate_request)`, likewise honoring `auth.enabled` (when disabled it returns an anonymous identity, convenient for local testing).

### 4.3 Testing

Both approaches should have tests (conventions in `tests/`):
- Bridge: patch out `httpx` with `unittest.mock` and do not connect for real (see `tests/test_remote_auth.py`).
- Migrate: test `OrderService` directly, injecting a mock repo (constructor injection of `repo` makes it easiest to test).

---

## 5. Quick Comparison Summary

| | Bridge | Migrate |
|---|---|---|
| Existing API | Untouched, called over HTTP | Code moved in |
| Best for | Multiple clients / non-Python / fast go-live | AI-only / Python / low latency needed |
| Latency | +1 HTTP hop | Lowest |
| Deployment | Two services | One service |
| Inside the tool | `await httpx...` | `await service...` |
| Common | Registration flow, authentication, error handling, config, testing are all identical | |

---
