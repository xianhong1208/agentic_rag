# Defect Report Template

>
> Usage: copy to `docs/testing/defect-reports/DEF-<YYYY>-<seq>.md`. One file per defect.

---

# DEF-<YYYY>-<seq>: <defect title>

| Field | Content |
|-------|---------|
| **Defect ID** | DEF-<YYYY>-<seq> |
| **Status** | Open / In Progress / Fixed / Won't Fix / Deferred |
| **Severity** | Blocker / Critical / Major / Minor / Trivial |
| **Priority** | P0 / P1 / P2 / P3 |
| **Detection stage** | Static analysis / Unit / Integration / System / UAT / Code review |
| **Related requirement / test** | REQ-xxx / `tests/test_xxx.py::...` |
| **Reporter / date** | <name> / <YYYY-MM-DD> |
| **Assigned to** | <owner> |

## 1. Environment
<Version, branch, DB, GPU/device, relevant settings.>

## 2. Preconditions
<State / data / login identity required before reproducing.>

## 3. Steps to Reproduce
1. ...
2. ...
3. ...

## 4. Expected
<The behavior required by the specification.>

## 5. Actual
<The behavior actually observed.>

## 6. Evidence
<Test output, system logs, screenshots, stack traces. Attach relevant snippets from `logs/`.>

## 7. Root Cause (if known)
<Source of the problem: code error, requirement change not propagated, environment issue, etc.>

## 8. Resolution
<The fix, the related commit / MR, and regression tests.>
