# Defect Reports Index


One file per defect, named `DEF-<YYYY>-<sequence>.md`; see the template at [../templates/DEFECT_REPORT_TEMPLATE.md](../templates/DEFECT_REPORT_TEMPLATE.md).

| ID | Title | Severity | Status |
|------|------|--------|------|
| [DEF-2026-001](DEF-2026-001.md) | `_parse_db_url` does not percent-decode credentials | Major | Open |
| [DEF-2026-002](DEF-2026-002.md) | Exception classes test `folder_id` by truthiness, so `0` is mistaken for "not provided" | Minor | Open |
| [DEF-2026-003](DEF-2026-003.md) | `${VAR:-default}` environment-variable expansion is not implemented, contrary to the README | Minor | Open |
| [DEF-2026-004](DEF-2026-004.md) | `_load_config` swallows FileNotFoundError, starting silently when the config path is wrong | Minor | Open |

**Exit criteria** (TEST_PLAN, Section 4): before merge / release, this index must contain no Open Blocker / Critical defects.
