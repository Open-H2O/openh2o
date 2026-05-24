---
phase: 02-core-domain-models
plan: 02
subsystem: database
tags: [django, geodjango, postgis, parcels, wells, meters, sensors, double-entry]

requires:
  - phase: 02-core-domain-models (plan 01)
    provides: User model, SiteConfig, geography models, django-allauth

provides:
  - Parcel model with MultiPolygonField
  - ParcelLedger double-entry accounting (signed decimal)
  - ParcelStaging for bulk import
  - Well model with PointField
  - WellMeter and WellIrrigatedParcel junction tables
  - Meter and MeterReading for totalizer tracking
  - Sensor with anomaly exclusion flag (Zybach pattern)
  - WaterMeasurement generic measurement (Qanat pattern)

affects: [02-core-domain-models, 03-parcel-well-crud, 04-water-accounting, 05-external-data]

tech-stack:
  added: []
  patterns: [double-entry ledger via signed decimal, anomaly exclusion flag, junction tables for well-meter and well-parcel]

key-files:
  created: [parcels/models.py, parcels/apps.py, parcels/admin.py, wells/models.py, wells/apps.py, wells/admin.py, measurements/models.py, measurements/apps.py, measurements/admin.py]
  modified: [config/settings/base.py]

key-decisions:
  - "ParcelLedger uses signed DecimalField (positive=supply, negative=usage) for double-entry"
  - "WellIrrigatedParcel tracks allocation fraction (0-1) per well-parcel pair"
  - "Sensor.exclude_anomalies flag from Zybach pattern for data quality filtering"

patterns-established:
  - "Double-entry pattern: ParcelLedger amount_acre_feet positive for supply, negative for usage"
  - "Junction tables with metadata: WellMeter (installed/removed dates), WellIrrigatedParcel (fraction)"
  - "Staging table pattern: ParcelStaging holds raw import data before validation"

issues-created: []

duration: 3min
completed: 2026-05-23
---

# Phase 2 Plan 2: Parcels, Wells, and Measurements Summary

**15 models across 3 apps covering physical water infrastructure: parcels with double-entry ledger, wells with meter/parcel junction tables, and measurement instruments with anomaly detection**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-24T00:19:39Z
- **Completed:** 2026-05-24T00:23:13Z
- **Tasks:** 3
- **Files modified:** 13

## Accomplishments
- Parcels app: Parcel (MultiPolygonField), ParcelLedger (signed decimal double-entry), ParcelStaging (import workflow), UsageLocation (PointField), CropType
- Wells app: Well (PointField), WellType, WellMeter (well-meter junction), WellIrrigatedParcel (well-parcel allocation fractions), MonitoringWell (1:1 extension)
- Measurements app: Meter (serial/type/calibration), MeterReading (previous/current delta), Sensor (anomaly exclusion), SensorMeasurement, WaterMeasurement (generic)
- All cross-app ForeignKeys use string references for deferred migration resolution

## Task Commits

Each task was committed atomically:

1. **Task 1: Create parcels app** - `d185a57` (feat)
2. **Task 2: Create wells app** - `6192e37` (feat)
3. **Task 3: Create measurements app** - `7f84e23` (feat)

## Files Created/Modified
- `parcels/__init__.py` - App package
- `parcels/apps.py` - ParcelsConfig
- `parcels/admin.py` - Empty (registration deferred to 02-05)
- `parcels/models.py` - CropType, Parcel, ParcelLedger, ParcelStaging, UsageLocation
- `wells/__init__.py` - App package
- `wells/apps.py` - WellsConfig
- `wells/admin.py` - Empty (registration deferred to 02-05)
- `wells/models.py` - WellType, Well, WellMeter, WellIrrigatedParcel, MonitoringWell
- `measurements/__init__.py` - App package
- `measurements/apps.py` - MeasurementsConfig
- `measurements/admin.py` - Empty (registration deferred to 02-05)
- `measurements/models.py` - Meter, MeterReading, Sensor, SensorMeasurement, WaterMeasurement
- `config/settings/base.py` - Added parcels, wells, measurements to INSTALLED_APPS

## Decisions Made
- ParcelLedger uses signed DecimalField for double-entry (positive=supply, negative=usage) rather than separate debit/credit columns
- WellIrrigatedParcel.fraction tracks what portion of a well's output goes to each parcel (0-1 range)
- Sensor.exclude_anomalies boolean flag follows Zybach pattern for data quality filtering

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- All 15 physical infrastructure models defined
- Ready for Plan 02-03 (accounting and reporting models)
- Migrations still deferred to Plan 02-04
- Cross-app FK strings (accounting.WaterType, accounting.ReportingPeriod) will resolve when accounting app is created in 02-03

---
*Phase: 02-core-domain-models*
*Completed: 2026-05-23*
