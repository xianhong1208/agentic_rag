# Spec Template

>
> Usage: copy this file to `docs/testing/specs/SPEC-<module>.md` and fill it in as the basis for test cases.
> Every requirement should be verifiable by at least one test case.

---

# SPEC-<module>: <module name>

| Item | Content |
|------|---------|
| Module | `<source path, e.g. src/domain/rag/hierarchy.py>` |
| Test | `<tests/test_xxx.py>` |
| Version | `<version that defines this requirement>` |
| Last updated | `<YYYY-MM-DD>` |

## 1. Purpose and Scope
<What this module is responsible for, and what it is not.>

## 2. Functional Requirements

| Requirement | Description | Acceptance Criteria (observable behavior) |
|-------------|-------------|-------------------------------------------|
| REQ-<module>-01 | <what this function / behavior must accomplish> | <given what input / state, what output / side effect results> |
| REQ-<module>-02 | | |

## 3. Non-Functional Requirements (if applicable)
<Security, performance, compatibility, etc. For example, "token isolation must not cross boundaries" or "secrets must not be written to logs".>

## 4. Edge Cases and Errors

| Scenario | Expected behavior |
|----------|-------------------|
| <null / None / empty string> | <reject / return default / raise> |
| <exceeds length limit> | |
| <malformed input> | |

## 5. Dependencies and Assumptions
<Which external modules / environment variables / tables it depends on; which need to be mocked during testing.>

## 6. Traceability

| Requirement | Test Case | Test Script |
|-------------|-----------|-------------|
| REQ-<module>-01 | TC-<module>-01 | `tests/test_xxx.py::test_yyy` |
