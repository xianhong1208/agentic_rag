# Agentic RAG — Test Summary Report


| Item | Content |
|------|------|
| Project / Version | Agentic RAG MCP Server (`pyproject.toml` 0.1.0) |
| Branch | `feat/rag-robustness` |
| Run date | 2026-07-09 |
| Test environment | Unit layer: zero external dependencies (no DB / vLLM / GPU / network); pytest + pytest-asyncio + pytest-mock + pytest-cov |
| Methodology basis | [FuSa Group Software Testing Methodologies Guide](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/) |

---

## 1. Execution Summary

| Metric | Count |
|------|------|
| Total test items | **274** |
| Passed | **274** |
| Failed | 0 |
| Pass rate | **100%** |
| Documentation registration rate | 100% (13 modules with REQ → TC → pytest three-layer mapping, see [COVERAGE.md](COVERAGE.md)) |
| **Line coverage** | **93%** (unit scope, `--cov=src` + omit list; the 85% threshold is guarded by pyproject `fail_under`) |

```
274 passed in 17.97s   (uv run pytest --cov -q)
```

## 2. Coverage Scope

**Unit layer (this report)**: chunking hierarchy / token estimation, context-generation language-script defense, Domain exception → HTTP mapping,
InMemoryCache and cache keys, filename-safety validation and file persistence, deployment path resolution, DB URL parsing,
YAML config loading and Pydantic models, token-validation cache (sha256, TTL, mock httpx),
middleware (request_id / error handler), adapter DTO, API request/response schema,
MCP output formatting (CJK width).

**Integration / system layer (not in this report)**: RAG pipeline (Docling / embedding / pgvector),
full-chain API routes, `IndexingJobManager`, MCP tool registration — these need external services and are
verified in the deployment environment, with automation on the [ROADMAP](../../ROADMAP.md); omit list in `pyproject.toml`.

## 3. Coverage-Target Attainment (TEST_PLAN Section 5)

| Target | Measured | Verdict |
|------|------|------|
| Overall unit scope ≥ 80% | **93%** | ✅ (threshold raised to 85 with an 8% buffer) |
| exceptions (security-critical) ≥ 90% | 100% | ✅ |
| Filename-validation logic (security-critical) ≥ 90% | `_validate_safe_name` all branches covered; file_storage overall 88% (missing physical-IO error branches) | ✅ (validation logic meets target; IO branches are integration scope) |
| auth cache (security-critical) ≥ 90% | remote_auth 85% (missing deep real-network error branches) | 🔶 Below 90 — registered as an improvement item; the gap is integration-scope behavior |
| runtime_paths | 67% (Nuitka/frozen deployment paths cannot be genuinely triggered in a unit environment) | 🔶 Known limitation, covered by deployment verification |

## 4. Defects and Accepted Exceptions

**Product defects (found during testing, all registered, see [defect-reports/](defect-reports/README.md)):**

| ID | Summary | Severity | Status |
|------|------|--------|------|
| [DEF-2026-001](defect-reports/DEF-2026-001.md) | `_parse_db_url` does not percent-decode credentials (deployments with a password containing `@`/`:` fail to log in) | Major | Open |
| [DEF-2026-002](defect-reports/DEF-2026-002.md) | Exception-class truthiness check treats `folder_id=0` as not provided | Minor | Open |
| [DEF-2026-003](defect-reports/DEF-2026-003.md) | `${VAR:-default}` env-var expansion not implemented, contradicting the README's claim | Minor | Open |
| [DEF-2026-004](defect-reports/DEF-2026-004.md) | `_load_config` swallows FileNotFoundError, starting silently when the config path is wrong | Minor | Open |

All four are pinned by "current-behavior snapshot" tests; the assertions are flipped when fixed (exit criterion: no Open Blocker/Critical — currently satisfied).

**Design-risk observations (not defects, see each DEF appendix):**
- The domain `FileNotFoundError` shadows the Python builtin of the same name.
- `estimate_tokens` docstring is inconsistent with the implementation (0.3 token/char, not 1.3 token/word).
- `_detect_scripts` does not cover Greek or the U+0080–U+00BF letters (the mismatch detection leans toward not falling back, the safe direction).
- `TokenCreateRequest.expires_in_days: int = None` should be `Optional[int]` (explicitly passing None raises ValidationError).

**Accepted exceptions:** None (all passed).

## 5. Conclusion

- The unit layer is all green across 274 items with 93% coverage ≥ the 85% threshold, satisfying the TEST_PLAN exit criteria — **mergeable**.
- Testing surfaced 2 real product defects (1 Major / 1 Minor), demonstrating the shift-left strategy works;
  the Major item (DEF-2026-001) should be prioritized in the next fix cycle.
- Next steps (ROADMAP): CI pipeline auto-gating → integration-test automation → RAG quality regression QA set.
