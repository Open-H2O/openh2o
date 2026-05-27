---
phase: 22-engineering-math-validation
plan: 01
subsystem: accounting
tags: [postgis, decimal-accounting, area-weighting, rounding-residual, csv-validation, django-signals]

requires:
  - phase: 19.2-visual-overhaul-ux-refinement
    provides: stable UI and navigation for accounting views
  - phase: 4-water-accounting-engine
    provides: ParcelLedger, recharge/diversion services, _balance_dict
  - phase: 9-schema-fixes-test-infrastructure
    provides: pytest + factory_boy test infrastructure

provides:
  - PostGIS auto-calculation of parcel area_acres from geometry
  - Area-weighted recharge distribution with rounding residual
  - Multi-parcel diversion distribution using PointOfDiversionParcel fractions
  - Dashboard allocation pro-rating by zone coverage
  - CSV import sign validation for usage source types
  - Comprehensive _balance_dict edge case tests

affects: [23-navigation-restructure, 24-data-model-ux, reporting, accounting]

tech-stack:
  added: []
  patterns:
    - "Rounding residual: last entry gets total - sum(others) to prevent decimal drift"
    - "PostGIS geography cast: ST_Area(geometry::geography) for accurate m² on SRID 4326"
    - "Django signal + queryset.update() pattern to avoid save() recursion"

key-files:
  created:
    - parcels/signals.py
    - parcels/management/commands/recalc_parcel_areas.py
  modified:
    - accounting/services.py
    - accounting/views.py
    - parcels/apps.py
    - tests/factories.py
    - tests/test_accounting_services.py
    - tests/test_views.py

key-decisions:
  - "Raw SQL with ::geography cast instead of Django Area() — Area() returns square degrees for SRID 4326"
  - "Parcel count pro-rating for dashboard allocations (not area-weighted) — matches GSA practice"
  - "Reject wrong-sign CSV entries rather than auto-negate — surfaces data entry errors"

issues-created: []

duration: 17min
completed: 2026-05-27
---

# Phase 22 Plan 01: Engineering Math Validation Summary

**Fixed 6 core accounting bugs: PostGIS area auto-calc, area-weighted recharge distribution, multi-parcel diversion fractions, dashboard allocation pro-rating, CSV sign validation, and _balance_dict edge cases — 16 new tests, 171 total passing**

## Performance

- **Duration:** 17 min
- **Started:** 2026-05-27T15:21:42Z
- **Completed:** 2026-05-27T15:39:39Z
- **Tasks:** 6
- **Files modified:** 8

## Accomplishments

- Parcel acreage auto-computed from PostGIS geometry via post_save signal (with management command for backfill)
- Recharge distribution now area-weighted with rounding residual ensuring exact sums
- Diversion ledger distributes across all linked parcels by PointOfDiversionParcel fractions
- Dashboard pro-rates zone allocation by account's parcel count in each zone
- CSV import rejects positive amounts for usage source types (meter_reading, et_estimate, surface_diversion)
- _balance_dict edge cases fully tested and documented

## Task Commits

Each task was committed atomically:

1. **Task 1: PostGIS auto-calc of area_acres** - `50251ac` (feat)
2. **Task 2: Area-weighted recharge distribution** - `6cfaf4f` (fix)
3. **Task 3: Multi-parcel diversion distribution** - `59e539a` (fix)
4. **Task 4: Dashboard allocation pro-rating** - `980e68f` (fix)
5. **Task 5: CSV sign validation** - `f0cb90f` (fix)
6. **Task 6: _balance_dict edge case tests** - `0c24a2f` (test)

## Files Created/Modified

- `parcels/signals.py` - PostGIS area auto-calc signal (new)
- `parcels/management/commands/recalc_parcel_areas.py` - Backfill command (new)
- `parcels/apps.py` - Signal registration in ready()
- `accounting/services.py` - Area-weighted recharge, multi-parcel diversions, CSV sign validation, _balance_dict docs
- `accounting/views.py` - Dashboard allocation pro-rating
- `tests/factories.py` - PointOfDiversionParcelFactory, AllocationPlanFactory
- `tests/test_accounting_services.py` - 12 new tests across 4 test classes
- `tests/test_views.py` - Dashboard pro-rating test

## Decisions Made

- Used raw SQL `ST_Area(geometry::geography)` instead of Django's `Area()` ORM function — Django returns square degrees for SRID 4326, not square meters
- Dashboard uses parcel count pro-rating (not area-weighted) — matches how GSAs typically subdivide zones and avoids dependency on all parcels having populated area_acres
- CSV validation rejects wrong-sign entries rather than auto-negating — this surfaces data entry errors instead of hiding them

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Django Area() returns square degrees for SRID 4326**
- **Found during:** Task 1 (PostGIS auto-calc)
- **Issue:** Django's `Area("geometry")` with SRID 4326 returns area in square degrees, not square meters, producing wildly incorrect acreage
- **Fix:** Used raw SQL with `ST_Area(geometry::geography)` cast for accurate geodetic area in square meters
- **Files modified:** parcels/signals.py, parcels/management/commands/recalc_parcel_areas.py
- **Verification:** Test confirms auto-calculation within 1% of expected value
- **Committed in:** 50251ac

---

**Total deviations:** 1 auto-fixed (bug in Django ORM), 0 deferred
**Impact on plan:** Essential fix — without it, area auto-calc would produce garbage values. No scope creep.

## Issues Encountered

None

## Next Phase Readiness

- All 6 accounting bugs fixed with tests proving correctness
- Test suite: 171 passing (up from 155), 0 failures
- Ready for Plan 22-02 (remaining math validation items: GEARS double-count, CalWATRS null crash, OpenET pipeline, validation threshold)

---
*Phase: 22-engineering-math-validation*
*Completed: 2026-05-27*
