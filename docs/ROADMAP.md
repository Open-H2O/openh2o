<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Roadmap

OpenH2O is production-ready for the core accounting and reporting workflow. This roadmap tracks the next substantive work, in priority order. Items marked **(methodology)** close gaps identified by comparing OpenH2O against the more mature Qanat / Groundwater Accounting Platform codebase; the cited paths refer to that AGPL-licensed reference implementation, which is methodology to port, not code to copy (different stack).

## Near-term: standards publishing (open data out)

The data model is already standards-aligned; these are additive serializers, not remodeling. See [DATA-STANDARDS.md](DATA-STANDARDS.md).

- **OGC SensorThings API v1.1** — read-only REST endpoint over the existing `Datastream` model. FeatureOfInterest derives from well screen interval + vertical datum.
- **Frictionless Data Package export** — `datapackage.json` + typed CSV from the conformance registry.
- **WaDE 2.0 export** — shares the registry's field alignment; same export path as Frictionless.
- **Geoconnex PIDs** — persistent identifiers for water features. Needs external registration with the Internet of Water team; basin codes (DWR Bulletin 118) are already in place as the foundation.

## Methodology gaps to close

### 1. Data-driven measurement calculation engine **(methodology)** — highest value
Today OpenH2O *stores* measured values but has no engine to derive billable groundwater from raw inputs. The full chain that turns gross OpenET evapotranspiration into a consumptive-use number — subtract effective precipitation, subtract consumed surface water, handle facility-only parcels, clamp negatives, carry precipitation credits forward — is the SGMA accounting methodology OpenH2O is missing between "raw ET" and "billable groundwater."

Qanat encodes this as **data, not code**: each measurement type carries a calculation type + a JSON config and declares dependencies on other types, then a topological sort evaluates them in order. Worth porting the *structure*, not just one formula.
- Reference: `Qanat.EFModels/Entities/WaterMeasurementCalculations.cs` (the engine; the `ETMinusPrecipMinusTotalSurfaceWater` chain), `Qanat.Database/Scripts/LookupTables/dbo.WaterMeasurementCalculationType.sql` (the catalog of calculation types).
- OpenH2O touchpoint: `measurements/models.py`, plus the OpenET adapter in `datasync/adapters/gee.py`.

### 2. Multi-year allocation periods: carry-over and borrow-forward **(methodology)**
OpenH2O's `AllocationPlan` is a single flat budget per zone/water-type/period. Most real SGMA plans let unused allocation roll forward (with a depreciation rate) and let users spend next year's allocation early. Without this, OpenH2O can't represent the budgets most basins actually run.
- Reference: `Qanat.Database/dbo/Tables/dbo.AllocationPlanPeriod.sql`, `Qanat.EFModels/Entities/AllocationPlanPeriods.cs` (the `EnableCarryOver` / `CarryOverNumberOfYears` / `CarryOverDepreciationRate` / `EnableBorrowForward` levers).
- OpenH2O touchpoint: `accounting/models.py` (`AllocationPlan`).

### 3. Meter-reading interpolation and area apportionment **(methodology)**
Cumulative meter reads taken on irregular dates need to be spread into clean monthly volumes (day-weighted), then apportioned across multiple parcels by area when one well irrigates several. OpenH2O stores readings but does no temporal redistribution. Reach for this the moment a real meter dataset arrives.
- Reference: `Qanat.EFModels/Entities/MeterReadingMonthInterpolations.cs` (the `HandleReadings` interpolation and the per-well-area normalization).
- OpenH2O touchpoint: `measurements/models.py` (`MeterReading`).

## Opportunistic (nice to have)

- **Landowner self-reporting loop** — a first-class "tell us your monthly usage" form that feeds an override calculation. Qanat: `dbo.WaterMeasurementSelfReport*.sql`.
- **Configurable billing-statement generator** — per-account usage/allocation statements as composable blocks. Qanat: `dbo.Statement*.sql`.
- **Sustainability-projects intake** — a richer schema for land-fallowing / repurposing / recharge project proposals. Qanat has a fully-specified JSON vocabulary in `docs/sustainability-projects-json-spec.md`.
- **Raster coverage diagnostics** — if OpenH2O moves to local raster sampling, surface partial-coverage warnings instead of silently averaging. Qanat: `Qanat.API/Services/OpenET/RasterProcessingService.cs`.

## Notably *not* on the roadmap

OpenH2O is **ahead** of the Qanat snapshot on data standards and interoperability — that codebase has no SensorThings, WaDE, Frictionless, or Geoconnex work. The standards items above are OpenH2O's own contribution back to the lineage. There is also no telemetry/SCADA/LoRaWAN ingestion in either codebase; meter data arrives as manual readings or raster uploads.
