---
phase: 22-engineering-math-validation
plan: 02
subsystem: accounting, reporting, datasync
tags: [gears, calwatrs, openet, acre-feet, unit-conversion, management-command, factory-boy]

requires:
  - phase: 22-01
    provides: PostGIS area auto-calc, area-weighted recharge, multi-parcel diversions, dashboard pro-rating, CSV sign validation
provides:
  - GEARS by-well fraction normalization (no more 3x double-counting)
  - CalWATRS/Email JSON null water_right crash guards
  - Granularity-aware OpenET validation thresholds (daily/monthly/annual)
  - sync_openet_to_ledger management command (OpenET cache → ParcelLedger)
  - et_mm_to_acre_feet helper with full derivation
  - Inline unit conversion citations across all accounting/reporting/datasync modules
affects: [phase-23, phase-20, phase-21]

tech-stack:
  added: []
  patterns: [per-well fraction normalization at query time, temporal-granularity-aware validation]

key-files:
  created:
    - accounting/management/commands/sync_openet_to_ledger.py
  modified:
    - reporting/generators.py
    - reporting/validators.py
    - datasync/adapters/openet.py
    - accounting/services.py
    - tests/factories.py
    - tests/test_accounting_services.py
    - tests/test_openet_cache.py

key-decisions:
  - "Normalize fractions at query time in generator, not in model default (preserves correct default for single-well parcels)"
  - "OpenET thresholds: daily=15mm, monthly=500mm, annual=2000mm (based on UC Davis CIMIS peak ET rates)"
  - "ET ledger entries use source_type='et_estimate' and negative amounts (consumption)"

patterns-established:
  - "Per-well fraction normalization pattern: group WIPs by well, divide each fraction by well total"
  - "Temporal-granularity-aware validation: pass resolution parameter, look up threshold from dict"

issues-created: []

duration: 14min
completed: 2026-05-27
---

# Phase 22 Plan 02: Report Bug Fixes, OpenET Pipeline, Unit Audit Summary

**Fixed GEARS double-counting (fraction normalization), CalWATRS/Email null crashes, granularity-aware OpenET threshold; built sync_openet_to_ledger management command; documented all unit conversions with authoritative citations.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-27T15:41:40Z
- **Completed:** 2026-05-27T15:55:22Z
- **Tasks:** 5
- **Files modified:** 8

## Accomplishments
- GEARS by-well generator normalizes WellIrrigatedParcel fractions per well — a well irrigating 3 parcels now reports 1x extraction instead of 3x
- CalWATRS CSV and Email JSON generators handle null water_right gracefully (empty right_id, descriptive holder name)
- OpenET validate() accepts temporal_resolution parameter with per-granularity thresholds (daily 15mm, monthly 500mm, annual 2000mm)
- New management command sync_openet_to_ledger converts OpenETCache mm data to ParcelLedger AF entries with deduplication
- All unit conversions across accounting/reporting/datasync documented with USGS and CA DWR citations

## Task Commits

Each task was committed atomically:

1. **Task 1: GEARS by-well fraction normalization** - `f390425` (fix)
2. **Task 2: CalWATRS and Email JSON null water_right guards** - `a207fc3` (fix)
3. **Task 3: OpenET validation threshold granularity-aware** - `a0396a8` (fix)
4. **Task 4: OpenET-to-ledger pipeline management command** - `abd89d3` (feat)
5. **Task 5: Unit conversion audit and inline formula citations** - `270ed08` (docs)

## Files Created/Modified
- `accounting/management/commands/sync_openet_to_ledger.py` - New command: cached OpenET mm → ParcelLedger AF entries
- `accounting/services.py` - et_mm_to_acre_feet helper + unit conversion constants block
- `reporting/generators.py` - GEARS fraction normalization + CalWATRS/Email null guards + conversion citations
- `reporting/validators.py` - Warnings for non-normalized fractions and missing water rights
- `datasync/adapters/openet.py` - Granularity-aware validation thresholds + CIMIS reference comments
- `tests/factories.py` - WellIrrigatedParcelFactory added
- `tests/test_accounting_services.py` - 11 new tests for GEARS fractions, null water rights, ET conversion, ledger sync
- `tests/test_openet_cache.py` - 4 new tests for granularity-aware validation

## Decisions Made
- Normalize fractions at query time in generator (not model default) — preserves correct default=1.0 for single-well parcels
- OpenET thresholds derived from UC Davis CIMIS peak ET rates for Central Valley crops
- ET ledger entries are negative (consumption) with source_type="et_estimate"

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 22 complete: all 9 known math/reporting issues resolved across plans 22-01 and 22-02
- Test suite at 186 tests (up from 171 pre-phase, originally 28)
- Ready for Phase 23: Navigation Restructure & Naming (UI Overhaul A)
- OpenET API key still not requested (needed for live adapter testing, not blocking)

---
*Phase: 22-engineering-math-validation*
*Completed: 2026-05-27*
