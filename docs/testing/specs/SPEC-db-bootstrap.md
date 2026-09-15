# SPEC-db-bootstrap: DB URL Parsing (bootstrap prerequisite)


| Item | Content |
|------|------|
| Module | `src/utils/db_bootstrap.py` (`_parse_db_url` only) |
| Test | `tests/test_db_bootstrap.py` |
| Version | feat/rag-robustness |
| Last updated | 2026-07-09 |

## 1. Purpose and Scope

At startup, `db_bootstrap` ensures the target DB exists, the pgvector extension is enabled, and HNSW indexes are in place. Chinese word segmentation is now handled by Python CKIP (ckip-transformers) rather than pg_jieba.
This spec covers **only the pure function `_parse_db_url(url) -> dict`**, which splits a SQLAlchemy-style
`postgresql://user:pwd@host:port/dbname` into a psycopg2 connection-parameter dict
(`user` / `password` / `host` / `port` / `dbname`).

Explicitly out of the unit-test scope (these require a real psycopg2 / SQLAlchemy connection and belong to integration testing):
`_database_exists`, `_create_database`, `_enable_extensions`,
`ensure_hnsw_for_table`, `_ensure_hnsw_indexes`, `ensure_database_ready`.

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|---------|---------|------------------------|
| REQ-db-bootstrap-01 | A standard URL parses completely | All five fields — user / password / host / port / dbname — are extracted correctly |
| REQ-db-bootstrap-02 | A missing port fills the default | When the URL carries no port, `port` = 5432 |
| REQ-db-bootstrap-03 | Percent-encoded credentials behave deterministically | urlparse **does not decode** userinfo; `u%40ser` is kept verbatim (a snapshot of current behavior, see the §4 note) |
| REQ-db-bootstrap-04 | Missing credentials are tolerated | When the URL has no userinfo, `user` / `password` are `None` and no error is raised |
| REQ-db-bootstrap-05 | dbname normalization | The leading `/` of the path is stripped; when the URL has no path, dbname is an empty string |

## 3. Non-Functional Requirements

- Pure function: must not initiate any connection or I/O.

## 4. Edge Cases & Errors

| Scenario | Expected Behavior |
|------|---------|
| URL missing port | fills 5432 |
| URL missing userinfo | user / password = `None` |
| URL missing path | dbname = `""` |
| Credentials contain percent-encoding (`%40`, etc.) | kept verbatim, not unquoted |

> **Note (likely gap)**: `urllib.parse.urlparse`'s `.username` / `.password` do not
> percent-decode, whereas the downstream `psycopg2.connect` needs the **decoded** credentials. If a deployment's
> DB password contains characters requiring percent-encoding such as `@` or `:`, the bootstrap connection will log in with the
> encoded string and fail. TC-db-bootstrap-03 locks this in as a "current-behavior snapshot"; if it is fixed in future (adding
> `urllib.parse.unquote`), that test must be updated accordingly.

## 5. Dependencies & Assumptions

- The module top-level imports `psycopg2` / `sqlalchemy` (import only, no connection is opened); the test environment need only have them installed.
- Validation of the other functions is classified as integration testing per docs/testing/TEST_STRATEGY.md and is covered by deployment-environment scripts.

## 6. Traceability

| Requirement | Test Case | Test Script |
|------|---------|---------|
| REQ-db-bootstrap-01 | TC-db-bootstrap-01 | `tests/test_db_bootstrap.py::test_parse_standard_url` |
| REQ-db-bootstrap-02 | TC-db-bootstrap-02 | `::test_parse_url_without_port_defaults_5432` |
| REQ-db-bootstrap-03 | TC-db-bootstrap-03 | `::test_parse_url_percent_encoded_credentials_not_decoded` |
| REQ-db-bootstrap-04 | TC-db-bootstrap-04 | `::test_parse_url_without_credentials` |
| REQ-db-bootstrap-05 | TC-db-bootstrap-05, TC-db-bootstrap-06 | `::test_parse_url_strips_leading_slash_from_dbname`, `::test_parse_url_without_path_gives_empty_dbname` |

(The test-script column omits the common prefix `tests/test_db_bootstrap.py`.)
