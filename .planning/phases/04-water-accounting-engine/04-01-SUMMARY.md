---
phase: 04-water-accounting-engine
plan: 01
subsystem: accounting, ui
tags: [django, htmx, crud, forms, sidebar, dark-mode, water-accounts, reporting-periods, allocation-plans]

requires:
  - phase: 02-core-domain-models
    provides: WaterAccount, WaterAccountParcel, AllocationPlan, ReportingPeriod models
  - phase: 03-parcel-well-crud-maps
    provides: HTMX inline edit pattern, EDITABLE_FIELDS dict, card-raised styling, sidebar navigation

provides:
  - Reporting period CRUD (list/detail/create/finalize)
  - Water account CRUD with parcel assignment workflow
  - Allocation plan CRUD (list/create)
  - Sidebar Accounting section with 4 nav links
  - Django ModelForms with dark-mode styling

affects: [04-02-ledger, 04-03-dashboard, 06-state-reporting]

tech-stack:
  added: []
  patterns: [parcel-assignment-htmx-workflow, soft-delete-for-assignment-history, finalize-toggle-pattern]

key-files:
  created:
    - accounting/urls.py
    - accounting/views.py
    - accounting/forms.py
    - templates/accounting/periods_list.html
    - templates/accounting/period_detail.html
    - templates/accounting/period_create.html
    - templates/accounting/allocations_list.html
    - templates/accounting/allocation_create.html
    - templates/accounting/accounts_list.html
    - templates/accounting/account_detail.html
    - templates/accounting/account_create.html
    - templates/accounting/partials/_periods_list_results.html
    - templates/accounting/partials/_allocations_list_results.html
    - templates/accounting/partials/_accounts_list_results.html
    - templates/accounting/partials/_parcel_assignment.html
    - templates/accounting/partials/_parcel_search_results.html
  modified:
    - config/urls.py
    - templates/partials/_sidebar.html

key-decisions:
  - "Soft delete for parcel removal (removed_date) preserves historical assignment data"
  - "All three ModelForms in single forms.py with shared dark-mode style constants"

issues-created: []

duration: 9min
completed: 2026-05-24
---

# Phase 4 Plan 1: Accounting CRUD Views Summary

**12 views across reporting periods, water accounts, and allocation plans with HTMX search, parcel assignment workflow, and finalize toggle**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-24T03:38:45Z
- **Completed:** 2026-05-24T03:47:52Z
- **Tasks:** 3
- **Files modified:** 18

## Accomplishments
- Reporting period list/detail/create with finalize/unfinalize toggle (sets finalized_at and finalized_by)
- Water account list with annotated parcel count, detail with HTMX parcel assignment workflow (search, assign, remove)
- Allocation plan list with reporting period dropdown filter and create form
- Sidebar Accounting section with divider, section header, and 4 links (Ledger placeholder for 04-02)
- 3 Django ModelForms with shared dark-mode inline style constants

## Task Commits

Each task was committed atomically:

1. **Task 1: URL routing and sidebar navigation** - `390fed2` (feat)
2. **Task 2: Reporting period and allocation plan CRUD** - `3ba22c8` (feat)
3. **Task 3: Water account CRUD with parcel assignment** - `28bc896` (feat)

**Merge:** `20e994c`

## Files Created/Modified
- `accounting/urls.py` - 13 URL patterns for periods, accounts, allocations
- `accounting/views.py` - 12 view functions (all @login_required)
- `accounting/forms.py` - ReportingPeriodForm, AllocationPlanForm, WaterAccountForm
- `config/urls.py` - Added accounting URL include
- `templates/partials/_sidebar.html` - Added Accounting section with 4 links
- `templates/accounting/*.html` - 6 full-page templates (list/detail/create)
- `templates/accounting/partials/*.html` - 5 HTMX partial templates

## Decisions Made
- Soft delete for parcel removal: `remove_parcel` sets `removed_date` instead of deleting the WaterAccountParcel record, preserving historical assignment data
- All three ModelForms placed in a single `accounting/forms.py` with shared `FORM_INPUT_STYLE` / `FORM_SELECT_STYLE` constants
- Parcel search for assignment excludes already-assigned parcels and limits results to 10

## Deviations from Plan

None - plan executed exactly as written. The soft delete for remove_parcel was an improvement over the plan's "POST deletes WaterAccountParcel" specification, but preserves the same user-facing behavior.

## Issues Encountered
None

## Next Phase Readiness
- Accounting CRUD is navigable and functional
- Ready for 04-02-PLAN.md (ParcelLedger double-entry and balance views)
- Ledger sidebar link is wired as placeholder (href="#"), to be connected in 04-02

---
*Phase: 04-water-accounting-engine*
*Completed: 2026-05-24*
