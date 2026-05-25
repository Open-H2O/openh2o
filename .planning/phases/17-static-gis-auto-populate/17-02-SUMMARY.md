---
phase: 17-static-gis-auto-populate
plan: 02
subsystem: geography
tags: [arcgis, lightbox, parcels, pagination, bulk-create, mapserver]

requires:
  - phase: 17-static-gis-auto-populate
    provides: ArcGIS REST client, auto_populate command framework, step registry
provides:
  - LightBox parcel auto-population step (parcels step in auto_populate)
  - Page-by-page parcel creation from DWR MapServer
affects: [17-03 NLDI flowlines, 19 setup wizard, 21 Merced test]

tech-stack:
  added: []
  patterns: [MapServer query (same pagination as FeatureServer), bulk_create with ignore_conflicts for idempotent batch insert]

key-files:
  created: []
  modified:
    - geography/management/commands/auto_populate.py
    - tests/test_auto_populate.py

key-decisions:
  - "Direct Parcel creation (no staging) for auto_populate, unlike import_parcels which uses ParcelStaging"
  - "Page-by-page processing with query_feature_server generator instead of query_by_boundary (avoids holding all features in memory)"
  - "bulk_create with ignore_conflicts=True for efficiency and race-condition safety"
  - "Request outSR=4326 from MapServer (native EPSG:3857) to match model SRID"

patterns-established:
  - "MapServer query endpoints work identically to FeatureServer for pagination"
  - "APN dedup: per-page bulk check via parcel_number__in, not per-feature"

issues-created: []

duration: 3min
completed: 2026-05-25
---

# Phase 17 Plan 02: DWR LightBox Parcel Auto-Population Summary

**LightBox parcel step queries DWR statewide MapServer by boundary intersection, paginates at 1,500 records/page, and bulk-creates Parcel records with APN, geometry, and address**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-25T19:42:55Z
- **Completed:** 2026-05-25T19:46:12Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- _step_parcels replaces its stub with full LightBox API integration using the existing ArcGIS pagination generator
- Page-by-page processing: each page of 1,500 features is deduplicated, geometry-converted, and bulk_created before fetching the next
- Address assembled from SITE_ADDR, SITE_CITY, SITE_STATE, SITE_ZIP fields
- 5 new tests cover creation, idempotency, dry-run, empty APN handling, and multi-page pagination

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement _step_parcels** - `0143f49` (feat)
2. **Task 2: Add parcel step tests** - `dbce229` (test)

## Files Created/Modified
- `geography/management/commands/auto_populate.py` - LightBox parcel step implementation, LIGHTBOX_PARCELS_URL constant, Parcel import
- `tests/test_auto_populate.py` - TestStepParcels class with 5 tests, _lightbox_features fixture

## Decisions Made
- Direct Parcel creation (skipping ParcelStaging) because auto_populate targets well-structured API data, not user-uploaded files
- Page-by-page generator processing rather than loading all features into memory, for boundaries with thousands of parcels
- bulk_create with ignore_conflicts=True handles both efficiency and edge-case race conditions
- Requesting outSR=4326 from the MapServer (which stores data in EPSG:3857) to match the Parcel model's SRID

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Parcels step complete, ready for Plan 17-03 (USGS NLDI flowlines + static county boundary fixtures)
- All three auto_populate steps will be functional after 17-03 completes
- Flowlines stub still in place, awaiting implementation

---
*Phase: 17-static-gis-auto-populate*
*Completed: 2026-05-25*
