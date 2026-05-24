---
phase: 03-parcel-well-crud-maps
plan: 01
subsystem: ui, api
tags: [maplibre, geojson, geodjango, htmx, tailwind, sidebar, navigation]

requires:
  - phase: 02-core-domain-models
    provides: All 48 models including Parcel, Well, PointOfDiversion, RechargeSite with spatial fields
provides:
  - Dashboard shell with sidebar navigation
  - MapLibre GL JS CDN integration (block-based, loaded only on map pages)
  - 4 GeoJSON API endpoints (parcels, wells, points of diversion, recharge sites)
  - URL routing for all Phase 3 apps
  - Placeholder list views for all nav targets
affects: [03-02 (map engine), 03-03 (CRUD views), 03-04 (import commands)]

tech-stack:
  added: [MapLibre GL JS v4.7.1 (CDN)]
  patterns: [dashboard shell layout, GeoJSON endpoint pattern, sidebar with active-state highlighting]

key-files:
  created:
    - templates/partials/_sidebar.html
    - templates/partials/_header.html
    - templates/geography/map.html
    - parcels/views.py
    - parcels/urls.py
    - wells/views.py
    - wells/urls.py
    - surface/views.py
    - surface/urls.py
    - recharge/views.py
    - recharge/urls.py
    - geography/views.py
    - geography/urls.py
    - templates/parcels/list.html
    - templates/wells/list.html
    - templates/surface/water_rights_list.html
    - templates/recharge/list.html
  modified:
    - templates/base.html
    - templates/index.html
    - config/urls.py
    - static/css/input.css

key-decisions:
  - "CARTO dark basemap for map page to match VanderDev dark-mode aesthetic"
  - "Sidebar collapse state persisted in localStorage"
  - "GeoJSON endpoints use HttpResponse with content_type rather than JsonResponse (GeoDjango serialize returns string)"

patterns-established:
  - "GeoJSON endpoint: serialize() → HttpResponse(data, content_type='application/json')"
  - "All views decorated with @login_required"
  - "Sidebar active state via request.path matching"
  - "Map scripts loaded via {% block map_scripts %} (not on every page)"

issues-created: []

duration: 7min
completed: 2026-05-24

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 3 Plan 1: Dashboard Shell and GeoJSON Endpoints Summary

**Dashboard shell with collapsible sidebar, MapLibre map page, and 4 GeoJSON API endpoints for parcels, wells, points of diversion, and recharge sites**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-24T01:51:59Z
- **Completed:** 2026-05-24T01:58:53Z
- **Tasks:** 2
- **Files modified:** 21

## Accomplishments
- Dashboard layout with collapsible sidebar (6 nav links with SVG icons), header with user menu, and content area
- MapLibre GL JS v4.7.1 loaded via CDN on map pages only (block-based inclusion)
- Map page with CARTO dark basemap centered on California
- 4 GeoJSON endpoints returning valid FeatureCollections (parcels, wells, PODs, recharge sites)
- URL routing wired for all 5 apps (parcels, wells, surface, recharge, geography)
- All views require authentication

## Task Commits

Each task was committed atomically:

1. **Task 1: Dashboard shell with sidebar navigation and MapLibre CDN** - `84a6fae` (feat)
2. **Task 2: URL routing and GeoJSON API endpoints** - `6f54bb9` (feat)

**Merge:** `f198dcc` (worktree merge)

## Files Created/Modified

**Created (17 files):**
- `templates/partials/_sidebar.html` - Collapsible sidebar with 6 nav links and active-state highlighting
- `templates/partials/_header.html` - Top bar with hamburger toggle and user menu
- `templates/geography/map.html` - MapLibre map page with CARTO dark basemap
- `parcels/views.py` - Parcel list view + GeoJSON endpoint
- `parcels/urls.py` - /parcels/ routes (list + geojson)
- `wells/views.py` - Well list view + GeoJSON endpoint
- `wells/urls.py` - /wells/ routes (list + geojson)
- `surface/views.py` - Water rights list + POD GeoJSON endpoint
- `surface/urls.py` - /surface/ routes (list + geojson)
- `recharge/views.py` - Recharge sites list + GeoJSON endpoint
- `recharge/urls.py` - /recharge/ routes (list + geojson)
- `geography/views.py` - Map view
- `geography/urls.py` - /map/ routes
- `templates/parcels/list.html` - Placeholder parcel list
- `templates/wells/list.html` - Placeholder well list
- `templates/surface/water_rights_list.html` - Placeholder water rights list
- `templates/recharge/list.html` - Placeholder recharge sites list

**Modified (4 files):**
- `templates/base.html` - Upgraded to dashboard shell with sidebar/header includes, map blocks
- `templates/index.html` - Dashboard landing with card grid
- `config/urls.py` - Added include() for all 5 app URL configs
- `static/css/input.css` - Dashboard layout CSS (sidebar, header, responsive, buttons)

## Decisions Made
- CARTO dark basemap chosen for map page (matches VanderDev dark-mode aesthetic vs bright OSM default)
- Sidebar collapse state persisted in localStorage for UX consistency across page loads
- GeoJSON endpoints use HttpResponse(data, content_type='application/json') since GeoDjango serialize() returns a string, not a dict

## Deviations from Plan

### Minor Adjustments

**1. Map page template created in Task 2 instead of Task 1**
- **Rationale:** Task 1 added the MapLibre CDN block infrastructure in base.html. The actual map page template (geography/map.html) required geography URL routing, which was Task 2's scope.
- **Impact:** None -- same total output, just slightly different task boundary.

**2. CARTO dark basemap instead of default**
- **Rationale:** Default OpenStreetMap bright style would clash with VanderDev dark-mode aesthetic.
- **Impact:** Better visual consistency.

---

**Total deviations:** 2 minor adjustments (no scope changes)
**Impact on plan:** Both adjustments improve the result. No scope creep.

## Issues Encountered
- `manage.py check` could not run locally (Django not installed on dev machine, Docker-only deployment on Butler). Python AST parsing confirmed all files syntactically correct and all URL name cross-references match.

## Next Phase Readiness
- Dashboard shell and GeoJSON endpoints ready for Phase 3 Plan 2 (map engine integration)
- All nav links resolve, no 404s expected
- GeoJSON endpoints return empty FeatureCollections until data is imported (Plan 4)

---
*Phase: 03-parcel-well-crud-maps*
*Completed: 2026-05-24*
