---
phase: 17-static-gis-auto-populate
plan: 01
subsystem: geography
tags: [arcgis, rest-api, pagination, bulletin-118, groundwater-basins, geojson, geos]

requires:
  - phase: 10-kaweah-subbasin-demo-data
    provides: Boundary and Zone model patterns, Kaweah boundary in DB for testing
provides:
  - ArcGIS REST API client with paginated spatial queries
  - auto_populate management command framework with step registry
  - Bulletin 118 groundwater basin population step
affects: [17-02 LightBox parcels, 17-03 NLDI flowlines, 19 setup wizard, 21 Merced test]

tech-stack:
  added: [requests>=2.31 (explicit dep)]
  patterns: [ArcGIS FeatureServer pagination via resultOffset, esri-to-geos geometry conversion, step-registry management command pattern]

key-files:
  created:
    - geography/services/__init__.py
    - geography/services/arcgis.py
    - geography/management/__init__.py
    - geography/management/commands/__init__.py
    - geography/management/commands/auto_populate.py
    - tests/test_auto_populate.py
  modified:
    - pyproject.toml

key-decisions:
  - "ArcGIS client lives in geography/services/ (not datasync/) because auto_populate is one-time setup, not recurring sync"
  - "Step registry uses OrderedDict for deterministic execution order"
  - "Idempotency via name+boundary uniqueness check, not upsert"

patterns-established:
  - "ArcGIS REST pagination: generator yields pages, caller flattens"
  - "Management command step registry: OrderedDict of {name: method}, filterable via --steps"
  - "Geometry conversion: esri rings <-> GEOSGeometry MultiPolygon with winding-order handling"

issues-created: []

duration: 6min
completed: 2026-05-25
---

# Phase 17 Plan 01: Auto-Populate Skeleton + ArcGIS Client + B118 Basins Summary

**Reusable ArcGIS REST client with paginated spatial queries, auto_populate management command with step registry, and Bulletin 118 groundwater basin population step**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-25T18:31:15Z
- **Completed:** 2026-05-25T18:37:50Z
- **Tasks:** 4
- **Files created:** 7

## Accomplishments
- ArcGIS REST client handles pagination, retries with exponential backoff, and geometry conversion between ESRI JSON and Django GEOSGeometry
- auto_populate command accepts --boundary (name or ID), --steps (basins,parcels,flowlines), and --dry-run
- B118 basin step queries DWR FeatureServer by boundary intersection, creates Zone records (zone_type=subbasin), and is fully idempotent
- 7 pytest tests cover geometry roundtrips, command argument parsing, mocked API calls, idempotency, and dry-run

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ArcGIS REST API client utility** - `89c874c` (feat)
2. **Task 2: Create auto_populate management command skeleton** - `75e1635` (feat)
3. **Task 3: Implement B118 groundwater basin population step** - `63bc080` (feat)
4. **Task 4: Add pytest for ArcGIS client and auto_populate** - `b7af057` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `geography/services/arcgis.py` - ArcGIS REST client: pagination, spatial queries, geometry conversion
- `geography/services/__init__.py` - Package init
- `geography/management/commands/auto_populate.py` - Management command with basins step + parcel/flowline stubs
- `geography/management/__init__.py` - Package init
- `geography/management/commands/__init__.py` - Package init
- `tests/test_auto_populate.py` - 7 tests across 4 classes (geometry, command, basins, idempotency)
- `pyproject.toml` - Added requests>=2.31 dependency

## Decisions Made
- ArcGIS client placed in geography/services/ rather than datasync/ because auto_populate is a one-time setup command, not a recurring data sync
- Step registry uses OrderedDict for deterministic execution order (basins first, then parcels, then flowlines)
- Idempotency checks zone existence by name+boundary rather than using get_or_create, to avoid partial updates

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added requests>=2.31 to pyproject.toml**
- **Found during:** Task 1 (ArcGIS client creation)
- **Issue:** requests was not listed as an explicit dependency in pyproject.toml (available transitively but not declared)
- **Fix:** Added `requests>=2.31` to project dependencies
- **Files modified:** pyproject.toml
- **Committed in:** 89c874c (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (blocking dependency), 0 deferred
**Impact on plan:** Necessary for correctness. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- ArcGIS client ready for reuse in Plan 17-02 (LightBox parcel pagination) and 17-03 (NLDI flowlines)
- auto_populate command framework ready for new steps to be wired in
- Parcels and flowlines stubs in place, ready for implementation

---
*Phase: 17-static-gis-auto-populate*
*Completed: 2026-05-25*
