# Test Case Template

>
> Usage: copy this file to `docs/testing/test-cases/TC-<module>.md`. Each case maps to one requirement (REQ),
> documenting steps, inputs, and expected results in detail so a tester or an automated system can follow it.

---

# TC-<module>: <module name> Test Cases

| Item | Content |
|------|---------|
| Related spec | [SPEC-<module>](../specs/SPEC-<module>.md) |
| Test level | Unit / Integration / System |
| Test script | `tests/test_xxx.py` |

---

## TC-<module>-01: <case title>

| Field | Content |
|-------|---------|
| **Requirement** | REQ-<module>-01 |
| **Level** | Unit / Integration / System |
| **Preconditions** | <required environment / data / login state> |
| **Test input** | <concrete input values / request body / parameters> |
| **Test steps** | 1. ...<br>2. ...<br>3. ... |
| **Expected result** | <clearly determinable output / status code / side effect> |
| **Implementation** | `tests/test_xxx.py::test_yyy` |

---

## TC-<module>-02: <case title>

| Field | Content |
|-------|---------|
| **Requirement** | REQ-<module>-01 |
| **Level** | |
| **Preconditions** | |
| **Test input** | |
| **Test steps** | |
| **Expected result** | |
| **Implementation** | |

> Authoring principles: each case verifies exactly one thing; keep the happy path and the exception path separate; expected results must be **observable and determinable** (avoid vague phrasing such as "should work").
