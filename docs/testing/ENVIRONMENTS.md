# Agentic RAG — Test Environments


---

## Environment Separation

| Environment | Purpose | DB | Model services |
|------|------|----|---------| 
| **Development (unit tests)** | `uv run pytest` — pure-logic tests, **no external service required** | Not needed | Not needed (mock) |
| **Staging (integration/system)** | End-to-end verification of the indexing pipeline, queries, and SSE | Postgres + pgvector (dedicated test DB) | vLLM embedding (5043) / LLM (5020) / reranker (8787) |
| **Production** | Live service | Production DB | Production model endpoints |

## Principles

1. **Unit tests have zero external dependencies**: `tests/test_*.py` must pass directly on a CI runner with
   no DB, no GPU, and no network. Any test that needs an external service goes in the integration layer (ROADMAP) and is separated by a marker.
2. **Tests never touch the production DB**: integration tests always use a dedicated test database; running tests against the production DB is forbidden.
3. **Model services are replaceable**: embedding / LLM / reranker are all OpenAI-compatible endpoints,
   so staging may use small stand-in models to reduce resource needs (except for quality acceptance).
4. **Test data**: the representative document set (PDF / large xlsx / webm audio / images) is kept in the test environment and
   is not version-controlled (see `storage/` in `.gitignore`).

## Running Unit Tests (local / CI)

```bash
uv run --no-sync pytest                          # full suite
uv run --no-sync pytest --cov --cov-report=term-missing   # with coverage (non-zero exit below threshold)
uv run --no-sync pytest tests/test_hierarchy.py -v         # single file
```

## Integration Tests (tests/integration/ — needs a real PostgreSQL, opt-in)

```bash
RAG_RUN_DB_ITESTS=1 uv run --no-sync pytest tests/integration -v
```

- **opt-in**: without `RAG_RUN_DB_ITESTS=1` set, the whole group auto-skips (unit CI is unaffected,
  and it prevents creating a database unbidden on a machine that happens to have postgres).
- Connection info reuses the database url in `config/config.yaml`, but **never touches that DB**: each run
  creates a fresh `agentic_rag_itest` → runs the full alembic chain to build the schema (also re-verifying the migration
  chain) → DROPs it when done.
- Currently covers: IndexJobDB / FileIndexDB round trips against a real DB (job write-through, reindex
  idempotency, the mark_failed failure-tag path).

> ⚠️ **On a GPU machine, always pass `--no-sync`**: this project's torch depends on the GPU and goes through a PEP 735 dependency group
> (`uv sync --group cuda` (NVIDIA) / `--group rocm-r714` or `--group rocm-r713` (AMD)…,
> see the comparison table at the top of `pyproject.toml`).
> A `uv sync` without the group, or a bare `uv run` (which implicitly syncs), replaces the venv's three torch packages
> with the default resolved versions, breaking the installed GPU stack. To fix, rerun
> `uv sync --inexact --group <your GPU group>`.
>
> ⚠️ **Same for CI / pure-CPU environments**: the three torch packages are provided only by `[dependency-groups]`,
> not by `[project].dependencies`, and `cpu` is not a default group (pyproject sets no
> `default-groups`). So after `uv sync --group cpu`, a bare `uv run pytest` triggers an implicit
> sync that, under exact semantics, removes the just-installed torch as extraneous. CI test steps must always pass
> `--no-sync` (CI uses `uv run --no-sync pytest`).
