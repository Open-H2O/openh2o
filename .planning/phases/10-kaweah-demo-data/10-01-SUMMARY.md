---
phase: 10-kaweah-demo-data
plan: 01
subsystem: data, geography, maps
tags: [django, geojson, gdal, postgis, maplibre, kaweah, sgma, tulare]

requires:
  - phase: 09-schema-fixes-test-infra
    provides: RechargeSite.zone FK, WaterRightParcel junction, pytest infrastructure
provides:
  - seed_kaweah management command with real DWR/Tulare County GIS data
  - Boundary and zone GeoJSON endpoints for map rendering
  - Map auto-zoom to boundary extent
  - Parcel data pipeline pattern (Koordinates → clip → sample → seed)
affects: [phase-11-merced, phase-12-ui-sweep]

tech-stack:
  added: []
  patterns: [geojson-file-loading, spatial-containment-zone-assignment, grid-sampling-parcels]

key-files:
  created:
    - data/kaweah/README.md
    - data/kaweah/subbasin_boundary.geojson
    - data/kaweah/gsa_boundaries.geojson
    - data/kaweah/tulare_parcels_sample.geojson
    - core/management/commands/seed_kaweah.py
  modified:
    - Makefile
    - geography/views.py
    - geography/urls.py
    - templates/geography/map.html
    - static/js/map-engine.js

key-decisions:
  - "Use real DWR Basin 5-022.11 boundary and 3 GSA zones instead of synthetic polygons"
  - "Load real Tulare County assessor parcels from Koordinates, grid-sampled to 40 representative ag parcels"
  - "Store raw county parcel datasets at /Volumes/MAINDRIVE/GIS/vector/parcels/{county}/"
  - "Add boundary and zone GeoJSON endpoints to geography app for map rendering"

patterns-established:
  - "GeoJSON file loading: load real boundaries from data/ directory via GEOSGeometry"
  - "Spatial zone assignment: use zone.geometry.contains(point) with fallback"
  - "Parcel grid sampling: clip county data to boundary, filter by use/acreage, grid-sample for geographic spread"

issues-created: []

duration: 77min
completed: 2026-05-25

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 10 Plan 01: Kaweah Subbasin Seed Data Summary

**Real DWR subbasin boundary, 3 GSA management zones, 40 Tulare County assessor parcels, 25 wells, 10 water rights, 4 recharge sites, and full accounting ledger with 1,345 entries seeded from public California water data sources**

## Performance

- **Duration:** 77 min
- **Started:** 2026-05-25T01:52:27Z
- **Completed:** 2026-05-25T03:09:35Z
- **Tasks:** 4 auto + 1 checkpoint (with iterative feedback)
- **Files modified:** 10

## Accomplishments
- seed_kaweah management command (1,000+ lines) with idempotent seeding and --flush support
- Real DWR Basin 5-022.11 boundary (2,104 vertices) and 3 GSA zone boundaries from DWR ArcGIS REST API
- 40 real Tulare County assessor parcel geometries from Koordinates, grid-sampled across the subbasin
- 25 wells with meters and 12 months of seasonal readings (180 total)
- 10 water rights with 12 PODs and 144 monthly diversion records for real Kaweah River districts
- 4 recharge sites with wet-season events
- 10 water accounts with 1,345 ledger entries creating a realistic overdraft scenario
- 8 monitoring stations using real CDEC/USGS/CIMIS/DWR station IDs
- Map boundary and zone layers with auto-zoom to boundary extent
- Map scrollbar overlap fix and subtle frame
- Raw county parcel datasets (Tulare, Kings, Kern, Merced) archived to MAINDRIVE

## Task Commits

1. **Task 1: Kaweah geography and command scaffolding** - `bd4f4f1` (feat)
2. **Task 2: Wells, parcels, and monitoring stations** - `54fdaa5` (feat)
3. **Task 3: Water rights, recharge, and accounting** - `e1ede88` (feat)
4. **Task 4: Makefile targets** - `6ae6066` (chore)
5. **Bug fix: reference data codes** - `babc985` (fix)
6. **Bug fix: naive datetime + bounds error** - `ee73cc1` (fix)
7. **Bug fix: station flush** - `e0c9ee4` (fix)
8. **Map CSS: scrollbar and frame** - `f4d30d6` (fix)
9. **Real DWR boundary GeoJSON files** - `6f0d431` (feat)
10. **Integrate real boundaries + improve parcels** - `1847ffd` (feat)
11. **Real Tulare County parcel geometries** - `02b3cfd` (feat)
12. **Boundary and zone map layers** - `9bbbe13` (feat)
13. **Map zoom to boundary** - `f9ebf2d`, `8c3eef0` (fix)

## Files Created/Modified
- `data/kaweah/README.md` - Data provenance documentation
- `data/kaweah/subbasin_boundary.geojson` - DWR Basin 5-022.11 boundary
- `data/kaweah/gsa_boundaries.geojson` - 3 Kaweah GSA boundaries from DWR
- `data/kaweah/tulare_parcels_sample.geojson` - 40 real assessor parcels
- `core/management/commands/seed_kaweah.py` - Kaweah seed command (1,000+ lines)
- `Makefile` - kaweah/flush-kaweah targets, fresh target updated
- `geography/views.py` - Boundary and zone GeoJSON endpoints
- `geography/urls.py` - GeoJSON URL routes
- `templates/geography/map.html` - Boundary/zone layers, fitBounds, frame CSS
- `static/js/map-engine.js` - fitBounds support

## Decisions Made
- Used real DWR boundaries instead of synthetic polygons (user feedback at checkpoint)
- 3 GSA zones (East, Mid, Greater Kaweah) instead of 2 arbitrary zones
- Real Tulare County assessor parcels from Koordinates instead of synthetic rectangles
- Grid sampling for geographic distribution of 40 parcels from 97K within boundary
- Raw county parcel data stored at MAINDRIVE/GIS/vector/parcels/ alongside existing GIS library

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WaterType/DataSource/WaterRightType code mismatches**
- **Found during:** Task 4 (first deployment to Butler)
- **Issue:** Codes in seed_kaweah.py didn't match existing DB records (STORMWATER→ST, CDEC→cdec, APPROP→POST14, RIPARIAN→RIP)
- **Fix:** Corrected all get_or_create lookups to use actual DB codes
- **Commit:** babc985

**2. [Rule 1 - Bug] Naive datetime and parcel-link bounds error**
- **Found during:** Task 4 (second deployment)
- **Issue:** MeterReading.reading_date got naive datetimes; randint(3, 0) crashed when parcel pool exhausted
- **Fix:** Added timezone.utc to datetimes; bounds-checked remaining_parcels
- **Commit:** ee73cc1

**3. [Rule 2 - Missing Critical] Boundary and zone layers not rendered on map**
- **Found during:** Checkpoint verification
- **Issue:** Map had no GeoJSON endpoints for boundaries/zones; boundary was in DB but invisible
- **Fix:** Added geography GeoJSON endpoints, map layers, and auto-zoom to boundary
- **Commits:** 9bbbe13, f9ebf2d, 8c3eef0

## Issues Encountered
- Koordinates Kart clone requires sudo for installer; worked around by downloading from website directly
- MapLibre `bounds` constructor parameter with `center: undefined` caused "failed to invert matrix"; fixed by using fitBounds() call after init

## Next Phase Readiness
- Phase 10 complete with real Kaweah data
- Parcel data pipeline pattern established (Koordinates → clip → sample → seed) ready for Merced replication
- Merced County parcel data already downloaded and archived at MAINDRIVE
- Map boundary/zone rendering infrastructure ready for Phase 11

---
*Phase: 10-kaweah-demo-data*
*Completed: 2026-05-25*
