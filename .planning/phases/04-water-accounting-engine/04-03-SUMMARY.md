---
phase: 04-water-accounting-engine
plan: 03
subsystem: ui
tags: [django, htmx, dashboard, csv-upload, data-viz]

requires:
  - phase: 04-water-accounting-engine (plans 01-02)
    provides: balance engine (account_balance, zone_balance), AllocationPlan model, ParcelLedger CRUD
provides:
  - Water budget dashboard with period-filtered stat cards and tables
  - CSV upload page with dry-run validation and template download
  - parse_ledger_csv shared service function
affects: [phase-5-external-data, phase-6-reporting, phase-8-deploy]

tech-stack:
  added: []
  patterns: [HTMX period selector with partial swap, parse_ledger_csv reusable service extraction]

key-files:
  created:
    - templates/accounting/dashboard.html
    - templates/accounting/partials/_dashboard_content.html
    - templates/accounting/csv_upload.html
    - templates/accounting/partials/_csv_upload_results.html
  modified:
    - accounting/views.py
    - accounting/urls.py
    - accounting/services.py
    - accounting/forms.py
    - config/views.py
    - templates/partials/_sidebar.html
    - templates/accounting/ledger_list.html

key-decisions:
  - "Extracted parse_ledger_csv into services.py for reuse between management command and web upload"
  - "Index page redirects authenticated users to dashboard (unauthenticated see landing page)"
  - "Dashboard sidebar link replaces generic index link"

patterns-established:
  - "Service extraction pattern: management command logic → services.py function → web view calls service"

issues-created: []

duration: 14min
completed: 2026-05-24

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 4 Plan 3: Water Budget Dashboard & CSV Upload Summary

**Dashboard with HTMX period selector showing supply/usage/net stat cards, account and zone balance tables, plus browser-based CSV upload with dry-run validation**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-24T11:52:05Z
- **Completed:** 2026-05-24T12:06:59Z
- **Tasks:** 3 (2 auto + 1 human-verify)
- **Files modified:** 11

## Accomplishments
- Water budget dashboard with 3 stat cards (supply/usage/net) and account+zone balance tables
- HTMX-powered period selector that reloads dashboard content without full page refresh
- CSV upload page with dry-run mode, error reporting, and 5-entry preview
- CSV template download endpoint for user convenience
- Shared parse_ledger_csv service function extracted from management command
- Index page redirects logged-in users to dashboard

## Task Commits

1. **Task 1: Water budget dashboard** - `f131dd3` (feat)
2. **Task 2: CSV upload page** - `873630c` (feat)
3. **Task 3: Human verification** - approved

## Files Created/Modified
- `templates/accounting/dashboard.html` - Main dashboard page with period selector
- `templates/accounting/partials/_dashboard_content.html` - HTMX partial: stat cards + tables
- `templates/accounting/csv_upload.html` - Upload form with column reference
- `templates/accounting/partials/_csv_upload_results.html` - Upload results partial
- `accounting/views.py` - Added dashboard, csv_upload, csv_template views
- `accounting/urls.py` - Added dashboard/, ledger/upload/, ledger/template/ routes
- `accounting/services.py` - Added parse_ledger_csv shared function
- `accounting/forms.py` - Added CsvUploadForm
- `config/views.py` - Index redirects authenticated users to dashboard
- `templates/partials/_sidebar.html` - Dashboard link points to accounting:dashboard
- `templates/accounting/ledger_list.html` - Added "Upload CSV" button

## Decisions Made
- Extracted CSV parsing into services.py rather than importing from management command (cleaner dependency direction)
- Index view redirects logged-in users to dashboard (landing page still shown to anonymous visitors)
- Dashboard sidebar link replaces the old generic index link

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness
- Phase 4 (Water Accounting Engine) is 100% complete
- All accounting features operational: periods, accounts, allocations, ledger, CSV import, balance calculations, dashboard
- Ready for Phase 5 (External Data Aggregator) - requires OpenET API key research

---
*Phase: 04-water-accounting-engine*
*Completed: 2026-05-24*
