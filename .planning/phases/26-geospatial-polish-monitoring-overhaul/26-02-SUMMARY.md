---
phase: 26-geospatial-polish-monitoring-overhaul
plan: 02
subsystem: datasync
tags: [chart.js, cdec, telemetry, sparklines, monitoring, live-data]

requires:
  - phase: 26-geospatial-polish-monitoring-overhaul
    provides: Color tokens, OH2O.colors JS global, font sweep
  - phase: 18-telemetry-discovery-openet
    provides: CDEC adapter, station auto-discovery, DataRecordStaging model

provides:
  - Chart.js telemetry charts on station detail pages
  - Live CDEC data sync pipeline (Terminus Dam, 87 records)
  - Improved stat tile labels (Reporting/Not Reporting)
  - Consolidated freshness map partial
  - Station list scoped to Kaweah area (9 stations)

affects: [phase-27-data-entry-ux-clarity, monitoring-future-adapters]

tech-stack:
  added: [chart.js-v4-cdn]
  patterns: [cdec-live-sync, date-format-fallback, boundary-agnostic-station-list]

key-files:
  created:
    - templates/datasync/partials/_freshness_map.html
  modified:
    - templates/base.html
    - templates/datasync/station_detail.html
    - templates/datasync/station_list.html
    - templates/datasync/partials/_monitoring_content.html
    - templates/datasync/partials/_station_list_results.html
    - datasync/views.py
    - datasync/adapters/cdec.py
    - datasync/adapters/base.py
    - config/settings/base.py

key-decisions:
  - "Removed boundary filter from station list and stat counts - watershed stations in foothills must be visible"
  - "DATASYNC_MOCK_MODE default changed to False - live API calls are the norm, mock is opt-in"
  - "Deleted 21 non-Kaweah stations, keeping only 9 Kaweah-area stations for demo"
  - "Deactivated KWR and VIS (CDEC JSON API doesn't serve data for these stations)"
  - "Chart defaults to All data range instead of 30d to handle sparse historical data"

issues-created: [ISS-001, ISS-002, ISS-003, ISS-004, ISS-005]

duration: 57min
completed: 2026-05-28

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 26 Plan 02: Monitoring Overhaul Summary

**Chart.js telemetry on station detail, live CDEC sync for Terminus Dam (87 real records, 52K-176K AF), freshness map consolidation, stat label cleanup, and 8 bug fixes discovered during verification.**

## Performance

- **Duration:** 57 min
- **Started:** 2026-05-28T13:08:34Z
- **Completed:** 2026-05-28T14:05:36Z
- **Tasks:** 4 planned + 1 checkpoint + 8 bug fixes
- **Files modified:** 11

## Accomplishments
- Chart.js telemetry chart on station detail with parameter dropdown and 5 date range buttons
- Live CDEC sync: Terminus Dam has 87 real daily records (March-May 2026), reservoir storage 52K→176K AF
- Stat tiles renamed: "Reporting" / "Not Reporting" (was "Fresh" / "Stale")
- Freshness map extracted into shared partial (was duplicated inline MapLibre code)
- Sparklines enlarged to 120x40 with gradient fill
- Station list cleaned to 9 Kaweah-area stations (was 29 statewide)
- Mock mode disabled (DATASYNC_MOCK_MODE default=False)

## Task Commits

1. **Task 1: Chart.js telemetry chart** - `d5ee82a` (feat)
2. **Task 2: Stat tile labels + sparklines** - `39d6f30` (feat)
3. **Task 3: Freshness map partial** - `411aaf9` (refactor)
4. **Task 4: CDEC live sync** - `f24a37d` (feat)

Bug fixes discovered during checkpoint verification:
5. **Chart gradient color + sparkline viewBox** - `823324f` (fix)
6. **Chart days cap + All button** - `05a5511` (fix)
7. **Chart toggle + parameter display** - `95a6b5f` (fix)
8. **CDEC adapter sensor metadata** - `564e2dd` (fix)
9. **Mock mode + station cleanup** - `01ed380` (fix)
10. **CDEC date format parsing** - `ea6a1e3` (fix)
11. **CDEC parse field names** - `2a26e4a` (fix)
12. **Station list boundary filter** - `7f314c9` (fix)
13. **Stat tile boundary filter** - `d48e682` (fix)

## Files Created/Modified
- `templates/datasync/partials/_freshness_map.html` - Shared MapLibre freshness map partial
- `templates/base.html` - Added `{% block chart_scripts %}` for Chart.js CDN
- `templates/datasync/station_detail.html` - Chart.js canvas, controls, telemetry JS
- `templates/datasync/station_list.html` - Updated stat labels, includes freshness partial
- `templates/datasync/partials/_monitoring_content.html` - Updated labels, includes freshness partial
- `templates/datasync/partials/_station_list_results.html` - Sparkline 120x40 with gradient
- `datasync/views.py` - Chart data endpoint, parameter display names, removed boundary filter
- `datasync/adapters/cdec.py` - Fixed parse field names, sensor metadata in discover
- `datasync/adapters/base.py` - Date format fallback for CDEC non-ISO dates
- `config/settings/base.py` - DATASYNC_MOCK_MODE default=False

## Decisions Made
- Boundary filter removed from station list and stat counts. Watershed stations (TRM, USGS gauges) sit in the foothills outside the groundwater basin polygon but are essential for Kaweah monitoring.
- DATASYNC_MOCK_MODE flipped to False by default. Live API calls are the expected behavior; mock mode is now opt-in via environment variable.
- KWR and VIS deactivated because CDEC's JSON API returns empty arrays for these stations despite them existing in CDEC's station index.
- Chart defaults to "All" date range because CDEC data may not fall within a 30-day window.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Chart gradient color malformed**
- **Found during:** Checkpoint verification
- **Issue:** `rgba(22c55e33` instead of proper hex-to-rgba conversion
- **Fix:** Removed broken first gradient attempt; hexToRgba function already existed below
- **Committed in:** 823324f

**2. [Rule 1 - Bug] Sparkline viewBox wrong in _station_list_results.html**
- **Found during:** Checkpoint verification
- **Issue:** Still 0 0 80 24 instead of 0 0 120 40
- **Fix:** Updated viewBox, added gradient fill polygon, stroke-width 2
- **Committed in:** 823324f

**3. [Rule 1 - Bug] Chart days capped at 365**
- **Found during:** Checkpoint verification (chart showed 0 data points)
- **Issue:** CDEC data from 2024 fell outside the 365-day max window
- **Fix:** Removed cap, added days=0 for "All", added All button to UI
- **Committed in:** 05a5511

**4. [Rule 1 - Bug] DATASYNC_MOCK_MODE=True returning fixture data**
- **Found during:** User reported wrong values (millions of AF on river gauges)
- **Issue:** All stations got identical Shasta Dam fixture data
- **Fix:** Changed default to False, purged fixture data, synced live
- **Committed in:** 01ed380

**5. [Rule 1 - Bug] CDEC parse used wrong field names**
- **Found during:** Live sync returned empty parameter_code and unit
- **Issue:** API uses SENSOR_NUM/units, adapter expected sensorNumber/unit
- **Fix:** Updated parse to check both field name variants
- **Committed in:** 2a26e4a

**6. [Rule 1 - Bug] CDEC date format not ISO-compatible**
- **Found during:** Live sync staged 0 of 58 fetched records
- **Issue:** CDEC returns `2026-4-1 00:00` which fromisoformat rejects
- **Fix:** Added strptime fallback in base adapter staging
- **Committed in:** ea6a1e3

**7. [Rule 1 - Bug] Station list filtered by boundary, excluding TRM**
- **Found during:** User reported all stations red with no data
- **Issue:** TRM (foothills) outside groundwater basin polygon
- **Fix:** Removed boundary filter from station queryset and stat counts
- **Committed in:** 7f314c9, d48e682

**8. [Rule 3 - Blocking] 21 non-Kaweah stations in demo**
- **Found during:** User reported statewide stations
- **Issue:** discover_stations had imported stations across California
- **Fix:** Deleted all stations outside Kaweah watershed
- **Committed in:** 01ed380 (database cleanup on Butler)

### Deferred Enhancements

Logged to .planning/ISSUES.md:
- ISS-001: Wire USGS, DWR WDL, DWR SGMA adapters for live sync
- ISS-002: Get CIMIS API key and wire CIMIS adapter
- ISS-003: Fix chart parameter dropdown showing raw codes ("15") instead of names
- ISS-004: Add Y-axis unit labels and chart title context
- ISS-005: Add units and labels throughout monitoring pages

---

**Total deviations:** 8 auto-fixed (7 bugs, 1 blocking), 5 deferred
**Impact on plan:** All fixes necessary for live data pipeline. Remaining issues are UX polish and additional adapter wiring.

## Issues Encountered
- CDEC's JSON API field names differ from documentation (SENSOR_NUM vs sensorNumber)
- CDEC returns non-ISO date strings that Python's fromisoformat rejects
- KWR and VIS exist in CDEC station index but return empty data arrays
- Mock mode was silently enabled, masking all adapter integration issues since Phase 18

## Next Phase Readiness
- Phase 26 complete (both plans shipped)
- 5 monitoring issues logged for follow-up (adapter wiring, UX labels)
- Recommend a dedicated Phase 26.1 or incorporation into Phase 27 for full monitoring completion

---
*Phase: 26-geospatial-polish-monitoring-overhaul*
*Completed: 2026-05-28*
