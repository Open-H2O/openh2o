---
phase: 17-static-gis-auto-populate
plan: 03
subsystem: geography
tags: [3dhp, flowlines, polyline, tiger, counties, mapserver, census]

requires:
  - phase: 17-static-gis-auto-populate
    provides: ArcGIS REST client, auto_populate command framework, step registry
provides:
  - 3DHP flowline auto-population step (flowlines step in auto_populate)
  - Flowline model with MultiLineStringField
  - esri_polyline_to_geos geometry conversion
  - load_counties management command for CA county boundaries
affects: [18 telemetry station discovery, 19 setup wizard, 21 Merced test]

tech-stack:
  added: []
  patterns: [ArcGIS polyline path conversion to MultiLineString, Census TIGERweb county queries]

key-files:
  created:
    - geography/migrations/0002_flowline.py
    - geography/management/commands/load_counties.py
  modified:
    - geography/services/arcgis.py
    - geography/models.py
    - geography/management/commands/auto_populate.py
    - tests/test_auto_populate.py

key-decisions:
  - "USGS 3DHP MapServer (layer 50) instead of NLDI API for flowlines -- same ArcGIS pagination pattern as basins/parcels"
  - "Census TIGERweb as separate load_counties command, not an auto_populate step -- counties are reference data, not boundary-scoped"
  - "Flowline model with source_id+boundary for idempotency rather than geometry-based dedup"

patterns-established:
  - "esri_polyline_to_geos converts ArcGIS paths array to MultiLineString"
  - "auto_populate now has 3 working steps: basins, parcels, flowlines"

issues-created: []

duration: 5min
completed: 2026-05-25
---

# Phase 17 Plan 03: USGS 3DHP Flowlines + County Boundaries Summary

**3DHP flowline step queries USGS MapServer layer 50, polyline-to-MultiLineString conversion, Flowline model, and load_counties command for 58 CA county boundaries from Census TIGERweb**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-25T20:05:17Z
- **Completed:** 2026-05-25T20:09:51Z
- **Tasks:** 4
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments
- esri_polyline_to_geos handles single and multi-path ArcGIS geometries, returning MultiLineString with SRID 4326
- Flowline model stores name, boundary FK, feature_type, length_km, stream_order, source_id, and line geometry
- _step_flowlines pages through 3DHP MapServer at 2,500 records/page with bulk_create
- load_counties creates Boundary records for all CA counties from Census TIGERweb (idempotent)
- All three auto_populate stubs replaced with working implementations
- Test suite expanded from 12 to 20 functions across 8 classes

## Task Commits

1. **Task 1: Polyline conversion + Flowline model + migration** - `5f7eae1` (feat)
2. **Task 2: Implement _step_flowlines** - `f430573` (feat)
3. **Task 3: load_counties command** - `692cfb8` (feat)
4. **Task 4: Tests for flowlines, polyline conversion, county loading** - `0fa137e` (test)

## Files Created/Modified
- `geography/services/arcgis.py` - Added esri_polyline_to_geos, LineString/MultiLineString imports
- `geography/models.py` - Added Flowline model with MultiLineStringField
- `geography/migrations/0002_flowline.py` - Migration for Flowline table
- `geography/management/commands/auto_populate.py` - 3DHP flowlines step, all stubs replaced
- `geography/management/commands/load_counties.py` - TIGERweb county boundary loader
- `tests/test_auto_populate.py` - 8 new tests across 3 new classes

## Decisions Made
- Used USGS 3DHP MapServer instead of NLDI API: same ArcGIS pagination pattern already proven in basins/parcels, simpler integration
- County loading is a separate command (not an auto_populate step) because counties are global reference data, not scoped to a boundary
- Flowline idempotency uses source_id+boundary FK rather than geometry comparison

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 17 complete: auto_populate engine has all 3 steps (basins, parcels, flowlines)
- load_counties provides county reference boundaries
- Ready for Phase 18 (Telemetry Discovery & OpenET)

---
*Phase: 17-static-gis-auto-populate*
*Completed: 2026-05-25*
