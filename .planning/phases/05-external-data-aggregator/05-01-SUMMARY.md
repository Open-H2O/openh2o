---
phase: 05-external-data-aggregator
plan: 01
subsystem: datasync
tags: [django, adapters, cdec, usgs, openet, cimis, cnrfc, dwr, noaa, management-commands, mock-mode]

requires:
  - phase: 03-parcel-well-crud-maps
    provides: MonitoredStation model, DataSource seed data, geography.Boundary model
  - phase: 04-water-accounting-engine
    provides: DataRecordStaging model, DataSyncLog model
provides:
  - BaseAdapter abstract class with fetch/parse/validate/stage/publish pipeline
  - 8 concrete adapters (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA)
  - Adapter registry with auto-registration pattern
  - 4 management commands (sync_source, sync_all, discover_stations, check_source_health)
  - Mock fixture data for all 8 sources
affects: [phase-6-reporting, phase-7-health, phase-8-ui]

tech-stack:
  added: []
  patterns: [adapter-registry-pattern, abstract-base-with-concrete-impls, mock-mode-via-settings, register-at-import]

key-files:
  created:
    - datasync/adapters/__init__.py
    - datasync/adapters/base.py
    - datasync/adapters/cdec.py
    - datasync/adapters/usgs.py
    - datasync/adapters/openet.py
    - datasync/adapters/cimis.py
    - datasync/adapters/cnrfc.py
    - datasync/adapters/dwr_wdl.py
    - datasync/adapters/dwr_sgma.py
    - datasync/adapters/noaa.py
    - datasync/fixtures/cdec.json
    - datasync/fixtures/usgs.json
    - datasync/fixtures/openet.json
    - datasync/fixtures/cimis.json
    - datasync/fixtures/cnrfc.json
    - datasync/fixtures/dwr_wdl.json
    - datasync/fixtures/dwr_sgma.json
    - datasync/fixtures/noaa.json
    - datasync/management/commands/sync_source.py
    - datasync/management/commands/sync_all.py
    - datasync/management/commands/discover_stations.py
    - datasync/management/commands/check_source_health.py
  modified:
    - config/settings/base.py

key-decisions:
  - "register_adapter() called at module level in each adapter file (auto-registration on import)"
  - "OpenET uses station.location point geometry, not parcel polygons, for initial sync"
  - "Mock mode controlled by DATASYNC_MOCK_MODE setting OR DataSource.is_active=False"
  - "Shared sync log across all stations in sync_source (one DataSyncLog per run, not per station)"

patterns-established:
  - "Adapter registry: ADAPTER_REGISTRY dict + register_adapter() + get_adapter()"
  - "BaseAdapter: abstract fetch/parse/validate/discover_stations, concrete sync/stage/publish"
  - "Mock fixtures at datasync/fixtures/{source_code}.json"
  - "Rate limiting via time.sleep() in _request(), retry with exponential backoff"

issues-created: []

duration: 9 min
completed: 2026-05-24
---

# Phase 5 Plan 01: External Data Adapter Framework Summary

**BaseAdapter abstract class with 8 concrete adapters (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA), adapter registry, 4 management commands, and mock fixtures for all sources**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-24T12:48:00Z
- **Completed:** 2026-05-24T12:57:03Z
- **Tasks:** 2
- **Files modified:** 23

## Accomplishments

- BaseAdapter with full fetch/parse/validate/stage/publish pipeline, rate limiting, retry with exponential backoff, and mock mode
- 8 concrete adapters covering California's key water data APIs (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA)
- Adapter registry with auto-registration pattern (import triggers registration)
- 4 management commands: sync_source, sync_all, discover_stations, check_source_health
- Mock fixtures with realistic California water data for all 8 sources
- DATASYNC_MOCK_MODE setting added to base.py (env-overridable)

## Task Commits

Each task was committed atomically:

1. **Task 1: BaseAdapter framework, registry, and management commands** - `5c95efe` (feat)
2. **Task 2: All 8 concrete adapters with mock fixtures** - `88fa4b1` (feat)

## Files Created/Modified

- `datasync/adapters/base.py` - Abstract base with fetch/parse/validate/stage/publish, mock, rate limiting, retry
- `datasync/adapters/__init__.py` - ADAPTER_REGISTRY, register_adapter(), get_adapter(), imports all 8
- `datasync/adapters/cdec.py` - CDEC JSON API (reservoir storage, river stage, flow, precipitation)
- `datasync/adapters/usgs.py` - USGS NWIS (discharge, gage height, water temp)
- `datasync/adapters/openet.py` - OpenET 3-stage submit/poll/retrieve (ET by point geometry)
- `datasync/adapters/cimis.py` - CIMIS (ETo, precipitation, solar radiation, wind, temperature)
- `datasync/adapters/cnrfc.py` - CNRFC file-based (streamflow/precip forecasts)
- `datasync/adapters/dwr_wdl.py` - DWR Water Data Library (groundwater levels)
- `datasync/adapters/dwr_sgma.py` - DWR SGMA Portal (GW levels, subsidence, ISW)
- `datasync/adapters/noaa.py` - NOAA NCEI (precipitation, temperature, snow)
- `datasync/fixtures/*.json` - 8 mock fixture files with realistic California water data
- `datasync/management/commands/sync_source.py` - Sync all active stations for one source
- `datasync/management/commands/sync_all.py` - Iterate all active sources and sync
- `datasync/management/commands/discover_stations.py` - Find stations near a Boundary geometry
- `datasync/management/commands/check_source_health.py` - Health report table
- `config/settings/base.py` - Added DATASYNC_MOCK_MODE = True

## Decisions Made

- register_adapter() called at module level in each adapter file for auto-registration on import
- OpenET adapter uses station.location point geometry for initial sync (parcel geometry support can be added later)
- Mock mode controlled by DATASYNC_MOCK_MODE setting OR DataSource.is_active=False
- Shared sync log across all stations in sync_source (one DataSyncLog per run, not per station)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Ready for 05-02-PLAN.md (station management UI or additional adapter features)
- Mock mode verified via AST syntax check; live verification against Butler pending
- OpenET API key still not requested (mock mode handles this cleanly)

---
*Phase: 05-external-data-aggregator*
*Completed: 2026-05-24*
