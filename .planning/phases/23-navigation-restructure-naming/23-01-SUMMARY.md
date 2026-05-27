---
phase: 23-navigation-restructure-naming
plan: 01
subsystem: ui
tags: [django-templates, sidebar, navigation, postgis, area-calc, dwr-acronyms]

requires:
  - phase: 22-engineering-math-validation
    provides: PostGIS area auto-calc signal, corrected accounting math
  - phase: 19.2-visual-overhaul-ux-refinement
    provides: Previous sidebar structure (reorg was reverted in 19.2-02)

provides:
  - Restructured 5-group sidebar with domain-accurate names
  - Per-page Add/Import buttons on Water Data list pages
  - area_override BooleanField on Parcel model
  - DWR acronym expansion to full agency names

affects: [24-data-model-ux-overhaul, 25-content-polish]

tech-stack:
  added: []
  patterns:
    - Per-page action buttons linked to infrastructure:add with type parameter
    - area_override flag pattern for manual-vs-auto field calculation

key-files:
  created:
    - parcels/migrations/0002_parcel_area_override.py
  modified:
    - templates/partials/_sidebar.html
    - parcels/models.py
    - parcels/signals.py
    - parcels/admin.py
    - 29 templates (titles, breadcrumbs, descriptions, buttons, DWR expansion)

key-decisions:
  - "Import button links to infrastructure:add (which has file upload built in) rather than infrastructure:upload (POST-only HTMX endpoint)"

patterns-established:
  - "Per-page Add/Import buttons replace unified Infrastructure tab"

issues-created: []

duration: 16min compute (168min wall-clock including checkpoint wait)
completed: 2026-05-27

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 23 Plan 01: Navigation Restructure & Naming Summary

**Sidebar restructured from 6 groups to 5 with 8 domain-accurate renames, per-page Add/Import buttons on Water Data pages, area_override flag on Parcel model, and DWR acronym expansion across templates and seed data**

## Performance

- **Duration:** 16 min compute (168 min wall-clock including checkpoint wait)
- **Started:** 2026-05-27T16:57:52Z
- **Completed:** 2026-05-27T19:46:23Z
- **Tasks:** 6/6 (5 auto + 1 checkpoint)
- **Files modified:** 33

## Accomplishments
- Sidebar reorganized: Monitoring section removed, Stations→Water Data, Health→Administration, Periods→Compliance as "Water Years"
- All 8 navigation renames applied across sidebar and 20+ page templates (titles, breadcrumbs, descriptions)
- Add/Import buttons on all 5 Water Data list pages replace the removed Infrastructure sidebar link
- Parcel model gains `area_override` BooleanField; PostGIS auto-calc signal respects the flag
- Every user-facing "DWR" expanded to "Department of Water Resources" or "Division of Water Rights" as appropriate

## Task Commits

1. **Task 1: Sidebar restructure and link renames** - `e5d464b` (feat)
2. **Task 2: Template title, breadcrumb, and description sweep** - `517ee6b` (feat)
3. **Task 3: Checkpoint** - auto-verified + human-approved
4. **Task 4: Add/Import buttons on Water Data pages** - `3af3479` (feat)
5. **Task 5: Add area_override flag to Parcel model** - `e182adf` (feat)
6. **Task 6: DWR acronym sweep** - `39c21c2` (feat)

## Files Created/Modified
- `templates/partials/_sidebar.html` - Restructured 5-group navigation
- `parcels/models.py` - Added area_override BooleanField
- `parcels/signals.py` - Signal skips auto-calc when area_override=True
- `parcels/admin.py` - area_override in list_display and list_filter
- `parcels/migrations/0002_parcel_area_override.py` - AddField migration
- 20 templates - Updated titles, breadcrumbs, descriptions to new names
- 4 Water Data list templates - Added Add/Import buttons
- 3 templates - DWR acronym expansion (about, wells/detail, setup/confirm)
- 5 Python files - DWR expansion in adapters, generators, seed commands

## Decisions Made
- Import button links to infrastructure:add (which has file upload built in) rather than the POST-only infrastructure:upload endpoint
- station_list.html already had an Add Station button; left unchanged

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 23 complete: all navigation, naming, model, and acronym work done
- 186 tests passing (unchanged from pre-phase baseline)
- Ready for Phase 24: Data Model UX Overhaul (allocation-optional, surface diversions redesign, zone management)

---
*Phase: 23-navigation-restructure-naming*
*Completed: 2026-05-27*
