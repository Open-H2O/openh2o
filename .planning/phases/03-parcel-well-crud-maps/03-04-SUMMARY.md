---
phase: 03-parcel-well-crud-maps
plan: 04
subsystem: data-import, ui, api
tags: [gdal, geojson, shapefile, csv, management-commands, htmx, maplibre, surface-water, recharge]

requires:
  - phase: 03-parcel-well-crud-maps
    provides: Parcel/Well models, CRUD views with HTMX search/filter/inline-edit, MapLibre map
provides:
  - import_parcels management command (GeoJSON/Shapefile via GDAL)
  - import_wells management command (CSV/Shapefile)
  - Water rights list/detail views with POD map
  - Recharge sites list/detail views with event history
affects: [phase-4-accounting, phase-5-external-data, phase-8-deploy]

tech-stack:
  added: []
  patterns: [staged-import-with-promotion, gdal-datasource-for-gis-import]

key-files:
  created:
    - parcels/management/commands/import_parcels.py
    - wells/management/commands/import_wells.py
    - templates/surface/water_right_detail.html
    - templates/surface/partials/_list_results.html
    - templates/surface/partials/_status_badge.html
    - templates/recharge/site_detail.html
    - templates/recharge/partials/_list_results.html
    - templates/recharge/partials/_status_badge.html
  modified:
    - surface/views.py
    - surface/urls.py
    - recharge/views.py
    - recharge/urls.py
    - templates/surface/water_rights_list.html
    - templates/recharge/list.html

key-decisions:
  - "import_parcels uses ParcelStaging for staged import with duplicate detection before promotion"
  - "import_wells creates Well records directly (no staging table needed for simpler point data)"
  - "Surface water and recharge views are read-only (no inline editing) since data comes from external sources"

issues-created: []

duration: 40min
completed: 2026-05-24
---

# Phase 3 Plan 4: Import Commands, Surface/Recharge Views & Verification Summary

**GDAL-powered parcel/well import commands with staged promotion, plus full HTMX list/detail views for water rights and recharge sites with embedded MapLibre maps**

## Performance

- **Duration:** 40 min
- **Started:** 2026-05-24T02:29:12Z
- **Completed:** 2026-05-24T03:09:56Z
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 16

## Accomplishments
- import_parcels command: reads GeoJSON/Shapefile via GDAL DataSource, stages to ParcelStaging with duplicate detection, promotes pending records to Parcel table inside transaction.atomic(), supports --dry-run
- import_wells command: reads CSV (DictReader) or Shapefile (DataSource), creates Well records directly with coordinate validation, deduplicates by well_registration_id
- Water rights list view with HTMX search (right_id/holder_name) and status filter, detail view with POD map (gold dots), diversion records, and curtailment status
- Recharge sites list view with HTMX search and site_type filter, detail view with event history and measurement tables
- Full Phase 3 integration verified on Butler (192.168.0.114)

## Task Commits

1. **Task 1: Import management commands** - `f48b3bf` (feat)
2. **Task 2: Surface water and recharge views** - `9662820` (feat)
3. **Task 3: Human verification checkpoint** - approved

## Files Created/Modified
- `parcels/management/commands/import_parcels.py` - GeoJSON/Shapefile import with staged promotion
- `wells/management/commands/import_wells.py` - CSV/Shapefile import with direct creation
- `surface/views.py` - water_rights_list and water_right_detail views
- `surface/urls.py` - added detail route
- `recharge/views.py` - recharge_sites_list and recharge_site_detail views
- `recharge/urls.py` - added detail route
- `templates/surface/water_rights_list.html` - full list page replacing placeholder
- `templates/surface/water_right_detail.html` - detail with POD map and diversion records
- `templates/surface/partials/_list_results.html` - HTMX partial for search results
- `templates/surface/partials/_status_badge.html` - status badges (active/inactive/curtailed/revoked)
- `templates/recharge/list.html` - full list page replacing placeholder
- `templates/recharge/site_detail.html` - detail with event history and measurements
- `templates/recharge/partials/_list_results.html` - HTMX partial for search results
- `templates/recharge/partials/_status_badge.html` - status badges (active/inactive/proposed)

## Decisions Made
- import_parcels uses ParcelStaging for staged import (Polygon→MultiPolygon wrapping, SRID transform to 4326) before promotion to Parcel table
- import_wells creates Well records directly without staging (simpler point data, less risk of geometry issues)
- Surface water and recharge views are read-only (no inline editing) since this data typically comes from external sources, not manual entry

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Next Phase Readiness
- Phase 3 complete. All deliverables shipped: dashboard, map, parcel/well CRUD, import commands, surface water views, recharge views
- Ready for Phase 4 (Water Accounting Engine) or Phase 5 (External Data Aggregator), which can run in parallel
- OpenET API key not yet requested (needed by Phase 5)

---
*Phase: 03-parcel-well-crud-maps*
*Completed: 2026-05-24*
