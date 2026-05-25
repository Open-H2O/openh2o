---
phase: 18-telemetry-discovery-openet
plan: 01
subsystem: datasync
tags: [openet, usgs, cdec, cimis, postgis, caching, geojson, groundwater]

requires:
  - phase: 05-external-data-aggregator
    provides: adapter registry, BaseAdapter, discover_stations pattern
  - phase: 17-static-gis-auto-populate
    provides: auto_populate step registry, ArcGIS client

provides:
  - stations step in auto_populate (CDEC/USGS/CIMIS discovery)
  - OpenETCache model with budget-aware caching
  - Polygon-based OpenET queries with centroid fallback
  - USGS groundwater well + spring discovery

affects: [19-streaming-dashboard, 20-ai-operator-guide, 21-merced-deployment-test]

tech-stack:
  added: []
  patterns: [cache-aware API adapter, per-source error isolation, multi-site-type discovery]

key-files:
  created:
    - datasync/migrations/0002_openetcache.py
    - tests/test_openet_cache.py
  modified:
    - geography/management/commands/auto_populate.py
    - datasync/models.py
    - datasync/adapters/openet.py
    - datasync/adapters/usgs.py
    - config/settings/base.py
    - tests/test_auto_populate.py

key-decisions:
  - "OpenETCache uses parcel FK for direct cache lookup, not geometry hashing"
  - "Budget enforcement returns None (skip), never raises exceptions"
  - "USGS discovers GW and SP as a combined query, not separate calls"

patterns-established:
  - "Cache-before-query pattern: check cache staleness, check budget, then API"
  - "Per-source error isolation in auto_populate: one failing source doesn't block others"

issues-created: []

duration: 6min
completed: 2026-05-25
---

# Phase 18 Plan 01: Telemetry Discovery & OpenET Summary

**Station auto-discovery for 3 sources, PostGIS-cached OpenET polygon adapter with monthly budget enforcement, and USGS groundwater well discovery.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-25T20:20:57Z
- **Completed:** 2026-05-25T20:27:16Z
- **Tasks:** 5
- **Files modified:** 8

## Accomplishments
- auto_populate now has 4 steps: basins, parcels, flowlines, stations
- OpenETCache model stores polygon ET results with configurable staleness (OPENET_CACHE_DAYS) and monthly budget cap (OPENET_MONTHLY_BUDGET)
- OpenET adapter gained fetch_polygon() with centroid fallback, sync_with_cache(), and sync_parcel_et() batch method
- USGS discover_stations now finds stream sites, groundwater wells, and springs (6 parameter codes total)
- 11 new tests: 4 station step + 7 OpenET cache

## Task Commits

Each task was committed atomically:

1. **Task 1: Add stations step to auto_populate** - `458f684` (feat)
2. **Task 2: Create OpenETCache model and migration** - `68a9882` (feat)
3. **Task 3: Upgrade OpenET adapter for polygon/caching** - `124c6eb` (feat)
4. **Task 4: Enhance USGS discover_stations** - `04db64e` (feat)
5. **Task 5: Tests for station discovery and OpenET cache** - `b8a0150` (test)

## Files Created/Modified
- `geography/management/commands/auto_populate.py` - Added stations step + mock fixture loader
- `datasync/models.py` - OpenETCache model with staleness/budget methods
- `datasync/migrations/0002_openetcache.py` - Migration for OpenETCache table
- `datasync/adapters/openet.py` - Polygon queries, cache-aware sync, batch method
- `datasync/adapters/usgs.py` - GW/SP site type queries, 3 new parameter codes
- `config/settings/base.py` - OPENET_CACHE_DAYS, OPENET_MONTHLY_BUDGET settings
- `tests/test_auto_populate.py` - 4 station step tests
- `tests/test_openet_cache.py` - 7 cache lifecycle and sync tests

## Decisions Made
- OpenETCache keyed by parcel FK + date range overlap (not exact date match) for flexible cache lookup
- Budget enforcement is soft (returns None, logs warning) rather than raising exceptions
- USGS combines GW+SP into one API call since both use groundwater parameters

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 18 complete (single plan), ready for Phase 19 (Streaming Dashboard & Setup Wizard)
- auto_populate has all 4 steps operational: basins, parcels, flowlines, stations
- OpenET caching ready for integration into dashboard views

---
*Phase: 18-telemetry-discovery-openet*
*Completed: 2026-05-25*
