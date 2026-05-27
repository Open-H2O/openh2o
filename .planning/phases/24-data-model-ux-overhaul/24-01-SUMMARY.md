---
phase: 24-data-model-ux-overhaul
plan: 01
subsystem: ui, accounting, surface, geography
tags: [django, htmx, maplibre, postgis, allocation, diversion, zone]

requires:
  - phase: 22-engineering-math-validation
    provides: correct allocation math, area-weighted recharge, multi-parcel diversions
  - phase: 23-navigation-restructure-naming
    provides: sidebar structure, page renames, Add/Import buttons, area_override pattern
provides:
  - allocation-optional dashboard (3-col vs 6-col conditional rendering)
  - POD-centric surface diversion views with inline record entry
  - zone management CRUD with map polygon drawing and parcel assignment
  - CalWATRS [INCOMPLETE] flag for diversions without water rights
affects: [25-content-polish, 20-ai-operator-guide]

tech-stack:
  added: []
  patterns: [allocation-optional conditional rendering, POD-centric diversion workflow, inline HTMX record creation, map polygon drawing for zone creation]

key-files:
  created:
    - surface/forms.py
    - geography/forms.py
    - templates/surface/pod_list.html
    - templates/surface/pod_detail.html
    - templates/surface/partials/_pod_list_results.html
    - templates/surface/partials/_diversion_form.html
    - templates/surface/partials/_diversion_records.html
    - templates/geography/zone_list.html
    - templates/geography/zone_detail.html
    - templates/geography/zone_create.html
    - templates/geography/partials/_zone_list_results.html
    - templates/geography/partials/_zone_parcels.html
    - templates/geography/partials/_zone_parcel_search_results.html
  modified:
    - accounting/views.py
    - surface/views.py
    - surface/urls.py
    - geography/views.py
    - geography/urls.py
    - infrastructure/views.py
    - reporting/generators.py
    - templates/accounting/partials/_dashboard_content.html
    - templates/partials/_sidebar.html

key-decisions:
  - "Dashboard renders 3-col (Supply/Usage/Net) when no allocations exist, 6-col with allocation/remaining when they do"
  - "Surface Diversions sidebar link changed from water_rights_list to pod_list; old water rights views preserved at /surface/rights/"
  - "Zone create uses duplicated _parse_polygon helper (shared extraction deferred)"
  - "CalWATRS CSV prefixes holder_name with [INCOMPLETE] for PODs without water rights"

patterns-established:
  - "Allocation-optional conditional rendering: has_allocations boolean controls template branches"
  - "POD-centric workflow: diversion points are primary, water rights are optional compliance context"
  - "Inline HTMX record creation: form + records table in same partial, hx-post swaps both"

issues-created: []

duration: 15min compute (235min wall-clock including checkpoint wait)
completed: 2026-05-27

quality-gates-run: [quality-sweep]
quality-gates-passed: true
quality-gates-violations-fixed: 1
---

# Phase 24 Plan 01: Data Model UX Overhaul Summary

**Allocation-optional dashboard, POD-centric surface diversions with inline diversion entry, and zone management with map polygon drawing**

## Performance

- **Duration:** ~15 min compute (235 min wall-clock including checkpoint wait)
- **Started:** 2026-05-27T19:57:49Z
- **Completed:** 2026-05-27T23:53:01Z
- **Tasks:** 4 (3 auto + 1 checkpoint)
- **Files modified:** 22

## Accomplishments
- Dashboard gracefully handles missing allocations: 3-column usage-only view with info banner linking to allocation creation
- Surface Diversions page leads with Points of Diversion, not water rights. Inline HTMX form for adding diversion records. Collapsible compliance details section.
- Zone management with full CRUD: list with parcel counts, create with MapLibre polygon drawing, detail with parcel assignment/removal
- CalWATRS CSV flags diversions without water rights as [INCOMPLETE]
- 186 tests passing (zero regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Allocation-optional dashboard** - `781c2b9` (feat)
2. **Task 2: POD-centric surface diversions redesign** - `6133195` (feat)
3. **Task 3: Zone management page with map drawing** - `0f07249` (feat)
4. **Quality sweep** - `00f8e08` (refactor)

## Files Created/Modified
- `accounting/views.py` - has_allocations check, conditional allocation computation skip
- `surface/forms.py` (new) - DiversionRecordForm, PointOfDiversionForm
- `surface/views.py` - pod_list, pod_detail, diversion_record_create views
- `surface/urls.py` - renamed root to pod_list, added pod_detail/record URLs
- `geography/forms.py` (new) - ZoneForm
- `geography/views.py` - zone_list, zone_detail, zone_create, parcel assign/remove/search, geojson endpoint
- `geography/urls.py` - 7 new zone URL patterns
- `infrastructure/views.py` - diversion detail_url updated to surface:pod_detail
- `reporting/generators.py` - CalWATRS [INCOMPLETE] prefix for missing water rights
- `templates/accounting/partials/_dashboard_content.html` - conditional 3/6-col tables, info banner
- `templates/surface/pod_list.html` (new) - POD list with HTMX search/filter toolbar
- `templates/surface/pod_detail.html` (new) - POD detail with map, records, compliance
- `templates/surface/partials/*` (3 new) - POD list results, diversion form, diversion records
- `templates/geography/zone_list.html` (new) - zone list with HTMX search/type filter
- `templates/geography/zone_detail.html` (new) - zone detail with parcels, budget, map
- `templates/geography/zone_create.html` (new) - zone form with MapLibre polygon drawing
- `templates/geography/partials/*` (3 new) - zone list results, parcels, parcel search
- `templates/partials/_sidebar.html` - Surface Diversions link to pod_list, Zones link added

## Decisions Made
- Dashboard renders 3-col (Supply/Usage/Net) when no allocations exist, 6-col with allocation/remaining when they do
- Surface Diversions sidebar link changed from water_rights_list to pod_list; old water rights views preserved at /surface/rights/
- Zone create uses duplicated _parse_polygon helper from infrastructure/views.py (shared extraction deferred)
- CalWATRS CSV prefixes holder_name with [INCOMPLETE] for PODs without water rights

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated infrastructure diversion detail_url**
- **Found during:** Task 2 (POD-centric surface diversions)
- **Issue:** Infrastructure list had `detail_url: None` for diversions, which would be a dead link
- **Fix:** Changed to link to `surface:pod_detail` so infrastructure list links work
- **Files modified:** infrastructure/views.py
- **Verification:** Infrastructure list diversion entries link correctly
- **Committed in:** 6133195 (Task 2 commit)

### Quality Sweep

**1. Unused import removed**
- `geography/views.py`: `Sum` imported from `django.db.models` but never used. Removed.
- **Committed in:** 00f8e08

---

**Total deviations:** 1 auto-fixed (1 bug), 0 deferred
**Impact on plan:** Bug fix was necessary for correct infrastructure list linking. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- Phase 24 complete: all three UX overhauls shipped and verified
- 186 tests passing (unchanged from pre-phase baseline)
- Ready for Phase 25: Content & Polish (About page rewrite, Getting Started redesign, help tooltip sweep)

---
*Phase: 24-data-model-ux-overhaul*
*Completed: 2026-05-27*
