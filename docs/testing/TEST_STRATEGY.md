# Agentic RAG — Test Strategy: Methodology, Levels, and Tools


> This strategy is built on the framework of the [FuSa Group "Complete Guide to Software Testing Methodologies"](https://fsg.tw/software-testing-methodologies-guide-a-high-level-overview/):
> development methodology → test levels → functional/non-functional classification → manual vs automated → AI assistance → exit criteria.

---

## 1. Development-Methodology Positioning

The guide lists four methodologies: Waterfall, Agile, Iterative, and DevOps continuous testing.

**This project adopts "Agile + DevOps continuous testing"**:

| Guide concept | This project's implementation |
|----------|-----------|
| Agile: testing is a continuous activity | Every feature/fix branch carries corresponding tests; nothing is left to a later "testing phase" |
| DevOps: automated tests integrated into CI/CD | `pytest --cov` + the `fail_under` threshold as the merge gate (CI pipeline on the ROADMAP) |
| **Shift-left testing** | New features first get requirements and acceptance criteria in `specs/`, then test cases, then implementation |
| Iterative feedback | Defect reports (`defect-reports/`) drive the next round of test reinforcement |

## 2. Test Levels — the Guide's Five Levels

The guide defines five test-type levels: **static analysis → unit → integration → system → acceptance**. This project maps them as follows:

### 2.1 Static Analysis
- **Definition** (guide): "detecting defects in code without running it".
- **This project**: Pydantic type models (config / adapter model) provide import-time validation;
  code review is mandatory on every merge; adoption of linter/type-checking tools is on the ROADMAP.

### 2.2 Unit Testing
- **Target**: the smallest units — pure-logic functions / classes (e.g. `hierarchy.build_hierarchy`, token estimation,
  filename normalization, config expansion).
- **Principle**: **no dependency on DB / vLLM / GPU / network**; external dependencies isolated with mocks.
- **Example**: `tests/test_hierarchy.py` and the other `tests/test_*.py`.

### 2.3 Integration Testing
- **Target**: multi-module collaboration — API routes + adapter + DB, the indexing pipeline (Docling → chunking →
  embedding → pgvector write), the `IndexingJobManager` lifecycle.
- **Infrastructure**: needs a Postgres (pgvector) test DB and model services; **currently relying mainly on `scripts/` manual scripts
  and deployment-environment verification**, with automated integration tests on the ROADMAP.

### 2.4 System Testing
- **Target**: end-to-end (black box): upload file → background indexing → SSE progress → query → citation sources.
- **Status**: manual walk-through in the deployment environment + MCP client (e.g. Claude) testing; automation on the ROADMAP.

### 2.5 Acceptance Testing
- **Target**: confirm business requirements from the user's perspective — RAG answer quality, citation correctness, cross-modal file support.
- **Status**: manual acceptance (retrieval quality inherently needs human judgment); a regression QA set with a representative document set is on the ROADMAP.

## 3. Functional vs Non-Functional Testing (the Guide's 5+5 Classification)

### 3.1 Functional Testing (the guide lists 5 kinds)

| Kind | This project's application |
|------|-----------|
| Unit testing | The pure-logic layer (see 2.2), currently the automation mainstay |
| Integration testing | The indexing/query pipeline and DB layer (see 2.3) |
| System testing | End-to-end API + MCP flow (see 2.4) |
| Acceptance testing | Manual RAG quality acceptance (see 2.5) |
| **Regression testing** | Run the full pytest suite on every change; the `fail_under` coverage threshold prevents the safety net from thinning |

### 3.2 Non-Functional Testing (the guide lists 5 kinds)

| Kind | This project's application | Status |
|------|-----------|------|
| Performance testing | Indexing throughput (per-file timing audit: `load_ms`/`index_ms`), query latency | 🔶 Measurement hooks exist, no automated baseline |
| Security testing | Token-scoped isolation (folders/files/vector tables invisible across tokens), upload filename/path safety | 🔶 Partly covered at the unit layer; penetration testing not scheduled |
| Usability testing | Readability of the landing page / Swagger / SSE progress | Manual |
| Compatibility testing | Multi-format files (PDF/Office/audio/images), GPU variants (cuda/rocm/cpu wheel groups) | Deployment-environment verification |
| Reliability testing | Watchdog, restart cleanup, cancel, PARTIAL_SUCCESS, embedding retry | ✅ A design core, progressively covered by unit tests |

## 4. Test Methods

| Method | Application |
|------|------|
| Black-box testing | API contract (status code / response structure); system flows |
| White-box testing | Branch coverage, error paths, boundary conditions (filling gaps per `--cov-report=term-missing`) |
| Gray-box testing | Knowing the internal structure but asserting on external behavior (e.g. job state-machine transitions) |
| Boundary-value analysis | Chunk token cap, empty document, single character, giant xlsx table, overly long filename |
| Equivalence partitioning | Legal / illegal input classes (file-format whitelist, audio-container variants) |

## 5. Manual vs Automated Testing

Guide: "Automation suits regression testing; manual testing suits usability and exploratory testing; the two should be combined."

| Type | This project's application |
|------|-----------|
| Automated | **The regression mainstay**: the pytest unit-test suite + coverage threshold; runs automatically on every commit once CI is adopted |
| Manual | RAG answer-quality acceptance, cross-modal file exploratory testing, SSE/frontend integration feel |

## 6. The Role of AI in Testing

Guide: "AI is a multiplier of human capability… but AI-produced results must always be reviewed, verified, and documented."

- This project's test cases and scripts are largely AI-assisted, **always merged after human review**.
- AI suggests affected tests based on the scope of a change (test selection).
- All AI-produced tests must be registered in `test-cases/` (traceability); "code without documentation" is not allowed.

## 7. Exit Criteria — as Defined by the Guide

| Guide criterion | This project's implementation |
|----------|-----------|
| All planned test cases executed | `uv run pytest` full suite passes (except registered exceptions) |
| Requirement traceability established | REQ → TC → `test_*.py` three-layer mapping (see the README matrix) |
| Code coverage meets target | The `[tool.coverage.report] fail_under` threshold (see TEST_PLAN Section 5) |
| Critical defects fixed | `defect-reports/` has no Open Blocker/Critical |
| Error rate down to the specified threshold | Zero product defects required to release; test defects must be registered |

## 8. Tools and Frameworks

| Purpose | Tool | Notes |
|------|------|------|
| Test framework | pytest + pytest-asyncio | `asyncio_mode = "auto"` |
| Mock | pytest-mock / unittest.mock | Isolate external dependencies (DB/LLM/embedding) |
| Coverage | pytest-cov (coverage.py) | `--cov=src --cov-report=term-missing`, guarded by `fail_under` |
| Typing/validation | Pydantic v2 | Import-time static guard for config and API models |
| Manual verification | Swagger UI / curl / MCP client | Integration and system layers (bridge before automation) |
