---
phase: 06-state-reporting
plan: 01
subsystem: reporting
tags: [csv, json, hmac, django-management-commands, htmx, state-reporting]

requires:
  - phase: 04-water-accounting-engine
    provides: ParcelLedger, ReportingPeriod, balance calculations
  - phase: 05-external-data-aggregator
    provides: DiversionRecord, PointOfDiversion, Well data

provides:
  - GEARS CSV generator (by-well and by-ET methods)
  - CalWATRS CSV generator (A1 and A2 templates)
  - Email JSON generator with HMAC-SHA256 signature
  - Report validation service
  - Management commands (generate_report, validate_report)
  - Full reporting UI with prepare-review-send workflow

affects: [09-deploy-polish-handoff]

tech-stack:
  added: []
  patterns: [prepare-review-send workflow, HMAC signing, StringIO CSV generation]

key-files:
  created:
    - reporting/generators.py
    - reporting/validators.py
    - reporting/views.py
    - reporting/urls.py
    - reporting/forms.py
    - reporting/management/commands/generate_report.py
    - reporting/management/commands/validate_report.py
    - templates/reporting/report_list.html
    - templates/reporting/report_generate.html
    - templates/reporting/report_detail.html
    - templates/reporting/partials/_list_results.html
    - templates/reporting/partials/_status_section.html
  modified:
    - config/urls.py
    - config/settings/base.py
    - templates/partials/_sidebar.html
    - .gitignore

key-decisions:
  - "MEDIA_ROOT for generated report files (media/reports/), gitignored"
  - "validate_report.py management command name (no conflict with validators.py function)"
  - "FileResponse for downloads (not streaming, files are small CSVs)"

issues-created: []

duration: 137min (includes ~115min pause for RCA and GSD reform work; actual code execution ~20min)
completed: 2026-05-24
---

# Phase 6 Plan 1: State Reporting Summary

**GEARS CSV, CalWATRS CSV, and Email JSON generators with validation, management commands, and full reporting UI featuring prepare-review-send status workflow**

## Performance

- **Duration:** 137 min total (actual code work ~20 min; remainder was project pause for incident RCA and GSD reform planning)
- **Started:** 2026-05-24T15:09:19Z
- **Completed:** 2026-05-24T17:26:34Z
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 17

## Accomplishments
- 3 report generators: GEARS by-well, GEARS by-ET, CalWATRS A1/A2, Email JSON with HMAC-SHA256
- Validation service checking finalization, data presence, duplicates, completeness
- 2 management commands: generate_report, validate_report
- Full reporting UI: list with HTMX search/filter, generate form with validation warnings, detail with download and status transitions
- Sidebar "Reporting" section with Reports link
- MEDIA_ROOT configured for generated file storage

## Task Commits

1. **Task 1: Report generator and validator service functions** - `2f861a4` (feat)
2. **Task 2: Management commands, reporting views, and UI** - `448e185` (feat)
3. **Task 3: Verification checkpoint** - human-verified on Butler (SSH, rebuild, management commands, browser verification)

## Files Created/Modified
- `reporting/generators.py` - generate_gears_csv, generate_calwatrs_csv, generate_email_json
- `reporting/validators.py` - validate_report with 6 check categories
- `reporting/views.py` - report_list, report_generate, report_detail, report_download, report_transition
- `reporting/urls.py` - 5 URL patterns under reporting namespace
- `reporting/forms.py` - ReportGenerateForm with dark-mode styling
- `reporting/management/commands/generate_report.py` - CLI report generation
- `reporting/management/commands/validate_report.py` - CLI data validation
- `templates/reporting/report_list.html` - List page with search and status filter
- `templates/reporting/report_generate.html` - Form with validation warning display
- `templates/reporting/report_detail.html` - Metadata, warnings, download, transitions
- `templates/reporting/partials/_list_results.html` - HTMX partial for list
- `templates/reporting/partials/_status_section.html` - HTMX partial for status transitions
- `config/urls.py` - Added reporting URL include and media URL pattern
- `config/settings/base.py` - Added MEDIA_ROOT and MEDIA_URL
- `templates/partials/_sidebar.html` - Added Reporting section with Reports link
- `.gitignore` - Added media/ directory

## Decisions Made
- MEDIA_ROOT = BASE_DIR / "media" for generated report files, gitignored
- Management command named validate_report.py (no namespace conflict with reporting.validators.validate_report function)
- FileResponse for downloads rather than streaming (report CSVs are small)
- Status transitions via HTMX POST to report_transition view

## Deviations from Plan

None - plan executed as written.

## Issues Encountered
- Checkpoint verification was initially delegated to user (7th occurrence of this pattern). Project paused for root cause analysis and GSD reform planning. Two reform documents drafted: checkpoint automation reform (5 gates) and phase sizing reform (7 changes). Verification ultimately completed correctly via SSH automation.

## Next Phase Readiness
- Phase 6 complete (1/1 plans finished)
- Reporting UI functional with prepare-review-send workflow
- Ready for Phase 7 (Health Check and Maintenance)

---
*Phase: 06-state-reporting*
*Completed: 2026-05-24*
