# Agentic RAG — Test Plan


| Item | Content |
|------|------|
| Project | Agentic RAG MCP Server |
| Version | Aligned with `pyproject.toml` |
| Document status | Living document (updated with each version) |
| Methodology basis | [FuSa Group Software Testing Methodologies Guide](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/) (see [TEST_STRATEGY.md](TEST_STRATEGY.md)) |

---

## 1. Purpose

Ensure that after every change, Agentic RAG's core logic — **hierarchical chunking, context generation, token isolation, file safety,
indexing-job reliability, and config loading** — remains correct and that new code does not break existing behavior (regression protection).

## 2. Scope

### In scope (unit layer, automated)
- **Chunking and hierarchy**: leaf/parent hierarchy, token estimation, metadata propagation
- **Context-generation defense**: language-script detection, script mismatch, safe fallback
- **Exception mapping**: the DomainException family → HTTP status
- **Cache**: InMemoryCache TTL / pattern eviction, cache-key generation (no plaintext token retained)
- **File safety**: filename/folder-name whitelist validation, path-traversal protection, file persistence
- **Config**: YAML loading, `${VAR:-default}` expansion, Pydantic validation, path safety
- **Auth unit logic**: validation-result cache (sha256 key, TTL), request/response models
- **Middleware**: request_id injection, error-handler status code and body structure
- **API schema**: request/response model validation and serialization

### Integration/system layer (deployment-environment verification; automation listed on the ROADMAP)
- Indexing pipeline (Docling → chunk → embed → pgvector), `IndexingJobManager` lifecycle
- Full chain of API routes + adapter + DB, SSE progress, MCP tools
- Requires Postgres / vLLM / GPU; for now verified via a manual deployment-environment flow + `scripts/`

### Out of scope (this phase)
- Automated RAG answer-quality evaluation (regression QA set is on the ROADMAP)
- Performance / stress testing (per-file timing hooks exist; benchmarking is on the ROADMAP)
- Internal behavior of third-party dependencies (docling / llama_index / torch)

## 3. Test Types (mapped to the guide's five levels)

| Type | Description | Status |
|------|------|------|
| Static analysis | Detect defects without running the program | 🔶 Pydantic import-time validation + code review; linter/typing on the ROADMAP |
| Unit testing | Pure-logic functions/classes, zero external dependencies | ✅ `tests/test_*.py`, the automation mainstay |
| Integration testing | Between modules + DB/model services | 🔶 Deployment environment + scripts/ (manual); automation on the ROADMAP |
| System testing | End-to-end black box (upload → index → query) | 🔶 Manual + MCP client testing |
| Acceptance testing | RAG quality, citation correctness | 🔶 Manual acceptance; regression QA set on the ROADMAP |

## 4. Entry / Exit Criteria

**Entry (before testing begins)**
- The requirement spec (`specs/`) is defined and reviewed.
- The code under test imports successfully (unit layer) or can start in staging (integration layer).

**Exit (mergeable / releasable) — mapping the guide's "exit criteria"**
- The full suite passes (except registered exceptions).
- New / changed code has corresponding REQ → TC → test (traceability).
- Coverage is no lower than the threshold (see Section 5), with no newly uncovered critical paths.
- `defect-reports/` has no Open Blocker / Critical.
- Security-related changes (token isolation, filename validation, upload paths) have corresponding tests.

## 5. Coverage Targets

**Scope definition**: coverage measures the **unit-test-scope** modules (pure logic, zero external dependencies).
Pipeline modules that need DB / vLLM / GPU fall under the integration-test scope and are listed in `pyproject.toml`
`[tool.coverage.run] omit` (each file listed with a rationale) — **neither padding the number nor dragging down the threshold**;
their quality is guarded by the integration/system layer (ROADMAP).

| Scope | Target |
|------|------|
| Overall unit-scope line coverage | ≥ 80% (`--cov=src`, omit list in pyproject) |
| Security-critical modules (file_storage filename validation, auth cache, exceptions) | ≥ 90% |
| New code | Must not lower the existing coverage of its module |

```bash
uv run pytest --cov --cov-report=term-missing   # exits non-zero below the threshold (pyproject fail_under)
```

> **Measured (2026-07-09): all 274 items passed, unit-scope line coverage 93%**, meeting the target and guarded by
> `[tool.coverage.report] fail_under = 85`. Details in [TEST_SUMMARY_REPORT.md](TEST_SUMMARY_REPORT.md).

## 6. Schedule and Milestones

| Stage | Content | Status |
|------|------|------|
| M1 (this phase) | Testing-process docs, templates, traceability; unit-test suite + coverage threshold | ✅ |
| M2 | CI pipeline (auto-run tests + coverage threshold blocks merge) + linter/typing | ⏳ |
| M3 | Automated integration tests (pgvector test DB + small stand-in models) | ⏳ |
| M4 | System-test automation + RAG quality regression QA set + performance baseline | ⏳ |

## 7. Roles and Responsibilities (the guide's "division of responsibility")

| Role | Responsibility |
|------|------|
| Developer | Shift-left: write REQ/TC/tests alongside the feature; commit only after passing the coverage threshold |
| Reviewer | Code review (static layer) + confirm traceability is complete |
| AI assistance | Draft test cases and scripts; **all output is reviewed by a human** (the guide's AI chapter) |
| Operations / deployment | Staging integration verification, production health monitoring |
