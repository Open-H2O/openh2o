---
phase: 09-schema-fixes-test-infra
plan: 01
subsystem: database, testing
tags: [django, pytest, factory-boy, postgis, migrations]

requires:
  - phase: 04-water-accounting-engine
    provides: accounting services with explicit-param workarounds (ISSUE-001, ISSUE-002)
provides:
  - RechargeSite.zone FK (optional, SET_NULL)
  - WaterRightParcel junction table (unique_together)
  - FK fallback in create_diversion_ledger_entry and create_recharge_ledger_entries
  - pytest + factory_boy infrastructure with 18 model factories
  - 28 baseline tests (balance, ledger integration, CSV import, model constraints)
affects: [phase-10-kaweah, phase-11-merced, phase-14-cron-health]

tech-stack:
  added: [pytest, pytest-django, factory-boy]
  patterns: [factory-boy-model-factories, autouse-db-fixture]

key-files:
  created:
    - conftest.py
    - tests/__init__.py
    - tests/factories.py
    - tests/test_accounting_services.py
    - tests/test_models.py
    - recharge/migrations/0002_rechargesite_zone.py
    - surface/migrations/0002_waterrightparcel.py
  modified:
    - recharge/models.py
    - surface/models.py
    - accounting/services.py
    - core/management/commands/seed_demo_data.py
    - pyproject.toml
    - Dockerfile

key-decisions:
  - "WaterRightParcel as junction table (not direct FK) because one water right can apply to multiple parcels"
  - "Dockerfile installs dev deps via pip install .[dev] so pytest runs inside the container"
  - "Autouse db fixture in conftest.py since nearly every test hits the database"

patterns-established:
  - "factory-boy factories in tests/factories.py for all model creation in tests"
  - "BytesIO for CSV test fixtures (matches Django's binary file upload interface)"

issues-created: []

duration: 10min
completed: 2026-05-24
---

# Phase 9 Plan 1: Schema FK Fixes + Test Infrastructure Summary

**Resolved ISSUE-001/002 FK workarounds and stood up pytest with 28 baseline tests covering balance calculations, ledger integration, and CSV import**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-25T01:22:49Z
- **Completed:** 2026-05-25T01:32:50Z
- **Tasks:** 4
- **Files modified:** 14

## Accomplishments
- RechargeSite now has optional zone FK; services.py falls back to it when no explicit zone supplied
- WaterRightParcel junction table links water rights to parcels; services.py uses it for diversion entry lookup
- pytest + factory_boy installed with 18 model factories covering all accounting-related models
- 28 tests pass green: 8 balance, 7 diversion/recharge integration, 5 CSV import, 8 model constraints

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema FK fixes** - `35a945d` (feat)
2. **Task 2: pytest + factory_boy infrastructure** - `634f016` (chore)
3. **Task 3: Baseline accounting service tests** - `628469e` (test)
4. **Task 4: Model constraint tests + close ISSUES** - `297d15d` (test)

## Files Created/Modified
- `recharge/models.py` - Added zone FK to RechargeSite
- `surface/models.py` - Added WaterRightParcel junction table
- `accounting/services.py` - FK fallback logic for both diversion and recharge functions
- `core/management/commands/seed_demo_data.py` - Populates zone on recharge sites and WaterRightParcel links
- `recharge/migrations/0002_rechargesite_zone.py` - Zone FK migration
- `surface/migrations/0002_waterrightparcel.py` - Junction table migration
- `pyproject.toml` - Dev dependencies and pytest config
- `Dockerfile` - Install dev deps via .[dev]
- `conftest.py` - Autouse db fixture
- `tests/factories.py` - 18 model factories
- `tests/test_accounting_services.py` - 20 service tests
- `tests/test_models.py` - 8 constraint tests
- `.planning/ISSUES.md` - Closed ISSUE-001 and ISSUE-002

## Decisions Made
- WaterRightParcel as junction table (not direct FK) because one water right can apply to multiple parcels
- Autouse db fixture since the platform is database-heavy and nearly every test needs DB access
- Dockerfile installs dev deps so tests run inside the container environment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- CSV tests initially failed because `parse_ledger_csv` expects binary input (Django file upload format) but tests passed `StringIO`. Fixed by using `BytesIO` in test helper.

## Next Phase Readiness
- Both deferred FK issues resolved; services.py simplified
- Test infrastructure ready for incremental coverage in Phases 10-14
- Phase complete, ready for Phase 10 (Kaweah Subbasin Demo Data)

---
*Phase: 09-schema-fixes-test-infra*
*Completed: 2026-05-24*
