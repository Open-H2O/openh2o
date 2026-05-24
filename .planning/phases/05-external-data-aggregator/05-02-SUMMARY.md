---
phase: 05-external-data-aggregator
plan: 02
subsystem: datasync
tags: [django, htmx, maplibre, geojson, station-management, dark-mode]

requires:
  - phase: 05-external-data-aggregator
    provides: MonitoredStation model, DataSource, DataRecordStaging, DataSyncLog, adapter registry
  - phase: 03-parcel-well-crud-maps
    provides: MapLibre MAP_CONFIG pattern, HTMX list pattern, GeoJSON endpoint pattern, sidebar
provides:
  - Station list/detail views with HTMX search and filter
  - Station active/inactive toggle via HTMX POST
  - Add custom station form
  - Stations GeoJSON endpoint
  - Monitoring stations layer on main map (coral red dots with popups)
  - Sidebar navigation link for stations
affects: [phase-6-reporting, phase-7-health, phase-8-ui]

tech-stack:
  added: []
  patterns: [htmx-outerhtml-toggle, manual-geojson-for-point-with-custom-properties]

key-files:
  created:
    - datasync/urls.py
    - datasync/views.py
    - templates/datasync/station_list.html
    - templates/datasync/station_detail.html
    - templates/datasync/station_add.html
    - templates/datasync/partials/_station_list_results.html
    - templates/datasync/partials/_station_toggle.html
  modified:
    - config/urls.py
    - templates/geography/map.html
    - templates/partials/_sidebar.html

key-decisions:
  - "GeoJSON endpoint builds features manually (not Django serialize) because PointField + custom properties need custom serialization"
  - "Toggle partial uses hx-target='this' with outerHTML swap for portability across list table and detail page contexts"
  - "discover_stations creates stations as inactive by default for user curation workflow"

patterns-established:
  - "HTMX toggle: button replaces itself via hx-target='this' hx-swap='outerHTML' (works in any container)"
  - "Station discovery + curation: discover creates inactive, user activates what they want"

issues-created: []

duration: 16min
completed: 2026-05-24
---

# Phase 5 Plan 2: Station Management UI Summary

**Station list/detail views with HTMX search/filter/toggle, add custom station form, GeoJSON endpoint, and coral red monitoring stations layer on the main map**

## Performance

- **Duration:** 16 min
- **Started:** 2026-05-24T13:47:03Z
- **Completed:** 2026-05-24T14:02:44Z
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint)
- **Files modified:** 10

## Accomplishments
- Station list page with HTMX search, data source filter, and active status filter
- Station detail page with embedded MapLibre map pin, recent data records table, and sync log history
- HTMX toggle for active/inactive that works on both list and detail pages without page reload
- Add custom station form with validation (data source, external ID, name, lat/lon)
- GeoJSON endpoint returning all active stations with properties
- Monitoring stations appear on main map as coral red dots (#FF6B6B) with glow, popups, and legend entry
- "Stations" link added to sidebar under DATA section

## Task Commits

Each task was committed atomically:

1. **Task 1: Station list/detail views with HTMX and GeoJSON endpoint** - `dc6fcc5` (feat)
2. **Task 2: Stations layer on main map page** - `f51a6b2` (feat)
3. **Task 3: Human verification** - verified via SSH rebuild + chrome-devtools screenshots on Butler
4. **Bug fix: HTMX toggle target** - `de0f622` (fix)

**Plan metadata:** (this commit)

## Files Created/Modified
- `datasync/urls.py` - URL configuration with 5 routes
- `datasync/views.py` - 5 views: station_list, station_detail, station_toggle, station_add, stations_geojson
- `templates/datasync/station_list.html` - List page with search and filter controls
- `templates/datasync/station_detail.html` - Detail page with map, data records, sync logs
- `templates/datasync/station_add.html` - Form for adding custom stations
- `templates/datasync/partials/_station_list_results.html` - HTMX partial for list table with pagination
- `templates/datasync/partials/_station_toggle.html` - HTMX toggle button (outerHTML swap)
- `config/urls.py` - Added datasync URL include
- `templates/geography/map.html` - Added stations GeoJSON source, circle layer, popup, legend
- `templates/partials/_sidebar.html` - Added Stations link under DATA section

## Decisions Made
- GeoJSON builds features manually rather than using Django serialize, because MonitoredStation.location is a PointField and we need custom properties (data_source_code, last_data_at)
- Toggle partial uses hx-target="this" with hx-swap="outerHTML" so the button replaces itself regardless of container (works in both list `<td>` and detail `<div>`)
- discover_stations creates stations as inactive by default, requiring user activation (curation workflow)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed HTMX toggle not updating on detail page**
- **Found during:** Task 3 (human verification via chrome-devtools)
- **Issue:** Toggle partial used `hx-target="closest td"` which works in the list table but fails on the detail page where the toggle is inside a `<div id="toggle-cell">`
- **Fix:** Changed to `hx-target="this"` with `hx-swap="outerHTML"` so the button replaces itself in any context
- **Files modified:** templates/datasync/partials/_station_toggle.html
- **Verification:** Confirmed toggle updates on both list and detail pages via chrome-devtools snapshot
- **Committed in:** de0f622

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix essential for correct toggle behavior. No scope creep.

## Issues Encountered
None beyond the toggle bug (fixed above).

## Next Phase Readiness
- Phase 5 complete: 8 adapters, 4 management commands, mock mode, station management UI, map integration
- All verification passed on Butler (docker rebuild, mock sync, health check, UI screenshots)
- Ready for Phase 6 (State Reporting) which depends on both Phase 4 (ledger data) and Phase 5 (external data)

---
*Phase: 05-external-data-aggregator*
*Completed: 2026-05-24*
