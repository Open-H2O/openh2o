---
phase: 03-parcel-well-crud-maps
plan: 03
subsystem: ui, api
tags: [htmx, django, crud, inline-editing, maplibre, pagination, search, dark-mode]

requires:
  - phase: 03-parcel-well-crud-maps
    provides: Dashboard shell, GeoJSON endpoints, MapLibre CDN, URL routing
provides:
  - Parcel list view with HTMX search, status filter, pagination
  - Parcel detail view with inline editing, embedded map, related data sections
  - Well list view with HTMX search, status filter, pagination
  - Well detail view with inline editing, embedded map, related data sections
  - Reusable HTMX inline edit pattern (GET form / PATCH save)
affects: [03-04 (import commands populate these views), 04 (ledger entries shown on parcel detail)]

tech-stack:
  added: []
  patterns: [HTMX partial response (HX-Request header check), inline field editing via GET/PATCH, parse_qs for PATCH body, EDITABLE_FIELDS dict-driven field config]

key-files:
  created:
    - templates/parcels/detail.html
    - templates/parcels/partials/_list_results.html
    - templates/parcels/partials/_field_edit.html
    - templates/parcels/partials/_field_value.html
    - templates/parcels/partials/_status_badge.html
    - templates/wells/detail.html
    - templates/wells/partials/_list_results.html
    - templates/wells/partials/_field_edit.html
    - templates/wells/partials/_field_value.html
    - templates/wells/partials/_status_badge.html
  modified:
    - parcels/views.py
    - parcels/urls.py
    - wells/views.py
    - wells/urls.py
    - templates/parcels/list.html
    - templates/wells/list.html

key-decisions:
  - "EDITABLE_FIELDS dict drives inline edit form generation: field type, choices, validation all derived from config"
  - "PATCH body parsed via urllib parse_qs since Django doesn't populate request.POST for PATCH"
  - "Added _field_value.html partial for cancel/save round-trip: edit form submits to PATCH which returns value partial"
  - "ParcelZone (not ZoneMembership) is the actual model linking parcels to zones"

patterns-established:
  - "HTMX list pattern: full page on normal GET, partial on HX-Request, hx-include for cross-field filtering"
  - "Inline edit pattern: pencil icon triggers GET for form, Save triggers PATCH, Cancel triggers GET with ?cancel=1"
  - "Embedded detail map: serialize single object to GeoJSON, fitBounds with padding"
  - "Status badge partial: shared across list and detail, colored pills per status value"

issues-created: []

duration: 10min
completed: 2026-05-24

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 3 Plan 3: CRUD Views with HTMX Search and Inline Editing Summary

**Parcel and well list/detail views with HTMX search, status filtering, pagination, inline field editing, embedded MapLibre maps, and related data sections**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-24T02:14:04Z
- **Completed:** 2026-05-24T02:24:16Z
- **Tasks:** 2
- **Files modified:** 16

## Accomplishments
- Parcel list with HTMX search (parcel number + owner), status filter dropdown, 25-per-page pagination, zone badges per row
- Parcel detail with 5 inline-editable fields, zone memberships, related wells (via WellIrrigatedParcel), last 10 ledger entries, embedded MapLibre map
- Well list with HTMX search (name + registration ID), status filter, pagination, well type column
- Well detail with 6 inline-editable fields, current meters, irrigated parcels with fraction, monitoring data section, embedded MapLibre map
- Reusable HTMX inline edit pattern: EDITABLE_FIELDS dict, GET/PATCH cycle with form/value partials, cancel support
- Status badge partials with colored pills (active=green, inactive=gray, pending=gold, destroyed/proposed=fallback)

## Task Commits

Each task was committed atomically:

1. **Task 1: Parcel list and detail views with HTMX search and inline editing** - `c887f07` (feat)
2. **Task 2: Well list and detail views with HTMX search and inline editing** - `eedaa46` (feat)

## Files Created/Modified

**Created (10 files):**
- `templates/parcels/detail.html` - Parcel detail with info card, zones, related wells, ledger, embedded map
- `templates/parcels/partials/_list_results.html` - Parcel list table with count badge, pagination
- `templates/parcels/partials/_field_edit.html` - Inline edit form (text/number/select/textarea)
- `templates/parcels/partials/_field_value.html` - Read-only value display with pencil icon
- `templates/parcels/partials/_status_badge.html` - Colored status pill partial
- `templates/wells/detail.html` - Well detail with info, meters, irrigated parcels, monitoring, map
- `templates/wells/partials/_list_results.html` - Well list table with count badge, pagination
- `templates/wells/partials/_field_edit.html` - Inline edit form mirroring parcel pattern
- `templates/wells/partials/_field_value.html` - Read-only value display with pencil icon
- `templates/wells/partials/_status_badge.html` - Colored status pill with destroyed/proposed variants

**Modified (6 files):**
- `parcels/views.py` - Added parcels_list (search/filter/paginate), parcel_detail, parcel_edit_field
- `parcels/urls.py` - Added detail and edit-field URL patterns
- `wells/views.py` - Added wells_list (search/filter/paginate), well_detail, well_edit_field
- `wells/urls.py` - Added detail and edit-field URL patterns
- `templates/parcels/list.html` - Replaced placeholder with search bar, status filter, results area
- `templates/wells/list.html` - Replaced placeholder with search bar, status filter, results area

## Decisions Made
- EDITABLE_FIELDS dictionary pattern chosen to drive form generation: keeps field config (type, choices, max_length) in one place in the view, templates render generically
- PATCH request body parsed via urllib.parse.parse_qs because Django only populates request.POST for POST requests, not PATCH
- Added _field_value.html partial (not in original plan) to complete the HTMX edit/cancel round-trip cycle
- ParcelZone model used for zone memberships (plan referenced ZoneMembership which doesn't exist)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ParcelZone model instead of ZoneMembership**
- **Found during:** Task 1 (parcel detail view)
- **Issue:** Plan referenced ZoneMembership model, but the actual model in geography/models.py is ParcelZone with related_name="parcel_zones"
- **Fix:** Used ParcelZone and parcel.parcel_zones in views and templates
- **Files modified:** parcels/views.py, templates/parcels/detail.html, templates/parcels/partials/_list_results.html
- **Verification:** Correct related_name used; will resolve at runtime
- **Committed in:** c887f07

**2. [Rule 2 - Missing Critical] Added _field_value.html partial for edit round-trip**
- **Found during:** Task 1 (inline editing implementation)
- **Issue:** Plan only specified _field_edit.html, but the HTMX edit pattern requires a second partial to render the read-only state after save or cancel
- **Fix:** Created _field_value.html partial showing value + pencil icon, returned by PATCH (save) and GET with ?cancel=1
- **Files modified:** templates/parcels/partials/_field_value.html, templates/wells/partials/_field_value.html
- **Verification:** Complete edit cycle: pencil -> form -> save/cancel -> back to value
- **Committed in:** c887f07, eedaa46

**3. [Rule 2 - Missing Critical] Added _status_badge.html shared partial**
- **Found during:** Task 1 (status rendering in list and detail)
- **Issue:** Status badge rendering needed in both list results and detail value partials; duplicating the HTML would violate DRY
- **Fix:** Created _status_badge.html partial with colored pills per status, included from both list and detail templates
- **Files modified:** templates/parcels/partials/_status_badge.html, templates/wells/partials/_status_badge.html
- **Verification:** Badge renders correctly in both contexts
- **Committed in:** c887f07, eedaa46

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 missing critical), 0 deferred
**Impact on plan:** All fixes necessary for correct HTMX round-trip behavior. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- List and detail views ready for data (import commands in Plan 4 will populate them)
- Inline editing pattern established and reusable for future apps
- Embedded maps will show geometry once parcels/wells are imported with spatial data

---
*Phase: 03-parcel-well-crud-maps*
*Completed: 2026-05-24*
