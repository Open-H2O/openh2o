---
phase: 02-core-domain-models
plan: 03
subsystem: database
tags: [django, geodjango, water-rights, accounting, recharge, calwatrs]

requires:
  - phase: 02-core-domain-models (plan 02)
    provides: Parcel, Well, Meter models for FK targets

provides:
  - WaterType and ReportingPeriod for accounting framework
  - WaterAccount and WaterAccountParcel for parcel-account linking
  - AllocationPlan ties zone + water type + reporting period
  - WaterRight and PointOfDiversion with spatial fields
  - DiversionRecord with CalWATRS A1/A2 alignment
  - CurtailmentOrder for drought response
  - RechargeSite with PointField + MultiPolygonField
  - RechargeEvent linked to WaterType

affects: [02-core-domain-models, 04-water-accounting, 05-external-data, 06-state-reporting]

tech-stack:
  added: []
  patterns: [CheckConstraint for date ordering, CalWATRS diversion_type alignment, recharge site dual geometry]

key-files:
  created: [accounting/models.py, accounting/apps.py, surface/models.py, surface/apps.py, recharge/models.py, recharge/apps.py]
  modified: [config/settings/base.py]

key-decisions:
  - "ReportingPeriod uses CheckConstraint to enforce start_date < end_date"
  - "DiversionRecord diversion_type aligns with CalWATRS A1 (direct_use) and A2 (to_storage)"
  - "RechargeSite has both PointField (location) and optional MultiPolygonField (boundary)"

patterns-established:
  - "CheckConstraint pattern for database-level validation"
  - "CalWATRS alignment: diversion_type choices match report template columns"

issues-created: []

duration: 4min
completed: 2026-05-23
---

# Phase 2 Plan 3: Accounting, Surface Water, and Recharge Summary

**13 models across 3 apps: water accounting framework with allocation plans, surface water rights with CalWATRS-aligned diversion records, and managed aquifer recharge tracking**

## Performance

- **Duration:** 4 min (batched with Plan 02-04)
- **Started:** 2026-05-24T00:35:09Z
- **Completed:** 2026-05-24T00:39:00Z
- **Tasks:** 3
- **Files modified:** 13

## Accomplishments
- Accounting app: WaterType, ReportingPeriod (with finalization workflow), WaterAccount, WaterAccountParcel, AllocationPlan
- Surface app: WaterRightType, WaterRight, PointOfDiversion (PointField), DiversionRecord (CalWATRS A1/A2 alignment), CurtailmentOrder
- Recharge app: RechargeSite (PointField + MultiPolygonField), RechargeEvent (linked to WaterType), RechargeMeasurement

## Task Commits

1. **Task 1: Create accounting app** - `79b193c` (feat)
2. **Task 2: Create surface app** - `be96f9e` (feat)
3. **Task 3: Create recharge app** - `170af46` (feat)

## Files Created/Modified
- `accounting/__init__.py`, `apps.py`, `admin.py`, `models.py` - 5 models
- `surface/__init__.py`, `apps.py`, `admin.py`, `models.py` - 5 models
- `recharge/__init__.py`, `apps.py`, `admin.py`, `models.py` - 3 models
- `config/settings/base.py` - Added accounting, surface, recharge to INSTALLED_APPS

## Decisions Made
- ReportingPeriod uses CheckConstraint for start_date < end_date enforcement at database level
- DiversionRecord.diversion_type uses direct_use/to_storage to align with CalWATRS A1/A2 report templates
- RechargeSite carries both a PointField (for map markers) and an optional MultiPolygonField (for site boundary polygons)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- All accounting/surface/recharge models ready
- Cross-app FK strings (accounting.WaterType, accounting.ReportingPeriod) now resolvable
- Ready for Plan 02-04 (datasync, reporting, health + migrations)

---
*Phase: 02-core-domain-models*
*Completed: 2026-05-23*
