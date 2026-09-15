# TC-db-bootstrap: DB URL Parsing Test Cases


| Item | Content |
|------|---------|
| Related spec | [SPEC-db-bootstrap](../specs/SPEC-db-bootstrap.md) |
| Test level | Unit (only `_parse_db_url`; connection functions belong to integration testing and are out of scope here) |
| Test script | `tests/test_db_bootstrap.py` |

---

## TC-db-bootstrap-01: full parse of a standard URL

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-01 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://alice:s3cret@db.example.com:5433/ragdb` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `{"user": "alice", "password": "s3cret", "host": "db.example.com", "port": 5433, "dbname": "ragdb"}` |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_standard_url` |

## TC-db-bootstrap-02: missing port defaults to 5432

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-02 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://alice:pw@localhost/ragdb` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `port` == 5432, `host` == `"localhost"` |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_url_without_port_defaults_5432` |

## TC-db-bootstrap-03: percent-encoded credentials preserved as-is (snapshot of current behavior)

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-03 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://u%40ser:p%40ss%3A1@db.host:6543/mydb` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `user` == `"u%40ser"`, `password` == `"p%40ss%3A1"` (**not** decoded to `u@ser` / `p@ss:1`); host/port correct |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_url_percent_encoded_credentials_not_decoded` |

> Potential gap: downstream psycopg2 requires decoded credentials, so a deployment with special characters in the password will fail to log in. See section 4 of SPEC-db-bootstrap for notes. If this is fixed to use `unquote`, this TC must be updated accordingly.

## TC-db-bootstrap-04: URL without credentials

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-04 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://localhost:5432/ragdb` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `user` / `password` are `None`; `dbname` == `"ragdb"`; no exception |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_url_without_credentials` |

## TC-db-bootstrap-05: dbname strips the leading slash

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://u:p@h:5432/agentic_rag` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `dbname` == `"agentic_rag"`, not starting with `/` |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_url_strips_leading_slash_from_dbname` |

## TC-db-bootstrap-06: dbname is an empty string when there is no path

| Field | Content |
|-------|---------|
| **Requirement** | REQ-db-bootstrap-05 |
| **Level** | Unit |
| **Preconditions** | None |
| **Test input** | `postgresql://u:p@h:5432` |
| **Test steps** | 1. Call `_parse_db_url` |
| **Expected result** | `dbname` == `""` |
| **Implementation** | `tests/test_db_bootstrap.py::test_parse_url_without_path_gives_empty_dbname` |
