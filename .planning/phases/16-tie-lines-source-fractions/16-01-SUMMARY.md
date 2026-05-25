---
phase: 16-tie-lines-source-fractions
plan: 01
subsystem: maps, reporting
tags: [geojson, maplibre, tie-lines, fraction-weighting, gears, calwatrs]

requires:
  - phase: 03-parcel-well-crud-maps
    provides: MAP_CONFIG-driven map engine, GeoJSON endpoint pattern, WellIrrigatedParcel model
  - phase: 15-branding-about-page
    provides: VanderDev design tokens, deployed platform on Butler

provides:
  - Tie-lines GeoJSON endpoint (LineString from source to parcel centroid)
  - GW/SW dashed line layers with fraction labels on interactive map
  - Fraction-weighted GEARS CSV and CalWATRS CSV exports
affects: [17-static-gis-auto-populate, 19-streaming-dashboard]

tech-stack:
  added: []
  patterns: [manual GeoJSON construction for computed geometries, MapLibre expression-driven labels]

key-files:
  created: []
  modified:
    - geography/views.py
    - geography/urls.py
    - templates/geography/map.html
    - reporting/generators.py

key-decisions:
  - "Build GeoJSON manually (computed LineString geometries, not serializable model fields)"
  - "PODs not linked to any parcel get fraction=1.0 fallback to avoid silent data loss in CalWATRS export"

patterns-established:
  - "Manual GeoJSON construction pattern for computed geometries (non-model spatial data)"
  - "MapLibre expression-driven labels with symbol-placement: line-center"

issues-created: []

duration: 3min
completed: 2026-05-25
---

# Phase 16 Plan 01: Tie Lines & Source Fractions Summary

**GeoJSON tie-line endpoint, dashed map layers with fraction labels, and fraction-weighted GEARS/CalWATRS reporting exports**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-25T18:19:48Z
- **Completed:** 2026-05-25T18:23:14Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Tie-lines GeoJSON endpoint returns LineString features connecting wells/PODs to parcel centroids
- Map renders gold dashed GW lines and teal dashed SW lines with fraction % labels at zoom 13+
- GEARS CSV by_well method weights extraction volumes by WellIrrigatedParcel.fraction
- CalWATRS CSV adds Source Fraction and Combined Use columns, expands rows per parcel link

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tie-lines GeoJSON endpoint** - `c1416d8` (feat)
2. **Task 2: Add tie-line layers to interactive map** - `89ef5ce` (feat)
3. **Task 3: Apply fraction weighting in reporting exports** - `02cd16c` (feat)

## Files Created/Modified
- `geography/views.py` - Added tie_lines_geojson view (manual GeoJSON for GW/SW LineStrings)
- `geography/urls.py` - Registered tie-lines/geojson/ URL
- `templates/geography/map.html` - Added tie-lines source, 3 layers (gw-tie-lines, sw-tie-lines, tie-line-labels), 2 popups
- `reporting/generators.py` - Fraction-weighted by_well, expanded CalWATRS with Source Fraction + Combined Use columns

## Decisions Made
- Built GeoJSON manually (computed geometries from source point to parcel centroid, not model fields)
- PODs without parcel links get fraction=1.0 and "SW Only" to prevent silent data loss in CalWATRS
- Tie-line layers placed between parcels-outline and wells-points for correct visual z-order

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 16 complete, all 1 plan finished
- Ready for Phase 17: Static GIS & Auto-Populate Engine
- No blockers

---
*Phase: 16-tie-lines-source-fractions*
*Completed: 2026-05-25*
