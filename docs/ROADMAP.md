<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Roadmap

OpenH2O is production-ready for the core accounting and reporting workflow. An
earlier comparison against the more mature Qanat / Groundwater Accounting
Platform codebase identified three headline methodology gaps; all three have
since been built (see **What's built**, below). This roadmap is forward-looking —
it tracks the substantive work that genuinely remains, in priority order.

The Qanat references cited below point at that AGPL-licensed reference
implementation: it is methodology to port, not code to copy (different stack).
Where OpenH2O has already ported a piece, the cite points at OpenH2O's own
module instead.

## What's built (the former "methodology gaps")

These were the three headline gaps against the Qanat snapshot. All three are now
in the codebase:

- **Data-driven calculation engine** — the chain that turns gross OpenET
  evapotranspiration into a net consumptive-use number (subtract effective
  precipitation, subtract consumed surface water, clamp negatives, carry
  precipitation credits forward) is built and tested. Shipped in Phase 38 and
  corrected to a consumptive-use spine in Phases 54–58. See
  [`accounting/steps.py`](../accounting/steps.py) (the step primitives and their
  registry), [`accounting/calculation.py`](../accounting/calculation.py), and
  [`accounting/services.py`](../accounting/services.py).
- **Multi-year allocation carry-over and borrow-forward** — unused allocation
  rolls forward (with an optional depreciation rate), and an overdraw is carried
  as a debt against the next year, capped at what that year actually holds.
  Shipped in Phase 39. See [`accounting/models.py`](../accounting/models.py)
  (`AllocationPlan`, `AllocationCarryover`) and the pure math in
  [`accounting/carryover_math.py`](../accounting/carryover_math.py) /
  [`accounting/banking_math.py`](../accounting/banking_math.py).
- **Apportionment of a shared supply across served parcels** — when one
  diversion or supply serves several parcels, the volume is split across them,
  demand-weighted by each parcel's measured ET (a refinement on the pure
  area-weighting the reference used). Shipped in Phases 55–56. See
  [`accounting/allocation_math.py`](../accounting/allocation_math.py)
  (`allocate_by_demand`, `apportion_shared_supply`).

## Near-term: standards publishing (open data out)

The data model is already standards-aligned — the canonical vocabulary,
crosswalk, and conformance gate landed in Phase 31, and the `Datastream` model
is in place. What remains is the additive serializer endpoints that publish it
out (not remodeling). These are deliberately deferred: the v1.3 Standards phases
are **postponed to on or after 2026-08-01**. They are the next real feature work,
not abandoned. See [DATA-STANDARDS.md](DATA-STANDARDS.md).

- **OGC SensorThings API v1.1** — read-only REST endpoint over the existing
  `Datastream` model. FeatureOfInterest derives from well screen interval +
  vertical datum.
- **Frictionless Data Package export** — `datapackage.json` + typed CSV from the
  conformance registry.
- **WaDE 2.0 export** — shares the registry's field alignment; same export path
  as Frictionless.
- **Geoconnex PIDs** — persistent identifiers for water features. Needs external
  registration with the Internet of Water team; basin codes (DWR Bulletin 118)
  are already in place as the foundation.

## Remaining methodology: meter-reading interpolation

The one methodology piece from the original comparison that is **not** yet built.
Cumulative meter reads taken on irregular dates need to be spread into clean
monthly volumes (day-weighted) before they enter the ledger. OpenH2O stores the
readings ([`measurements/models.py`](../measurements/models.py), `MeterReading`)
but does no temporal redistribution yet. Reach for this the moment a real meter
dataset arrives.

- Reference: `Qanat.EFModels/Entities/MeterReadingMonthInterpolations.cs` (the
  `HandleReadings` interpolation).
- OpenH2O touchpoint: `measurements/models.py` (`MeterReading`).

## Opportunistic (nice to have)

- **Landowner self-reporting loop** — a first-class "tell us your monthly usage"
  form that feeds an override calculation. Qanat: `dbo.WaterMeasurementSelfReport*.sql`.
- **Configurable billing-statement generator** — per-account usage/allocation
  statements as composable blocks. Qanat: `dbo.Statement*.sql`.
- **Sustainability-projects intake** — a richer schema for land-fallowing /
  repurposing / recharge project proposals. Qanat has a fully-specified JSON
  vocabulary in `docs/sustainability-projects-json-spec.md`.
- **Raster coverage diagnostics** — if OpenH2O moves to local raster sampling,
  surface partial-coverage warnings instead of silently averaging. Qanat:
  `Qanat.API/Services/OpenET/RasterProcessingService.cs`.

## Notably *not* on the roadmap

OpenH2O is **ahead** of the Qanat snapshot on data standards and
interoperability — that codebase has no SensorThings, WaDE, Frictionless, or
Geoconnex work. The standards items above are OpenH2O's own contribution back to
the lineage. There is also no telemetry/SCADA/LoRaWAN ingestion in either
codebase; meter data arrives as manual readings or raster uploads.
