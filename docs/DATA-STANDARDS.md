<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Data Standards & Interoperability

OpenH2O is **born-compliant** — meaning standards-*interoperable* by construction, not a claim of SGMA compliance: rather than bolting standards on at export time, every measurement it stores or ingests is mapped, at the source, to a single canonical vocabulary. That one decision is what lets the platform publish to open data standards (OGC SensorThings, the USGS/EPA water vocabularies, UCUM units) without per-agency remapping, and it's the part of OpenH2O most directly reusable by another district's system.

This document is the reference for that vocabulary, the crosswalk, the conformance rules, and the publishing roadmap. If you operate a different platform and want to align with OpenH2O (or with the standards it targets), start here.

> **Machine-readable crosswalk:** [crosswalk.csv](crosswalk.csv) in this folder. Regenerate it from any live deployment's registry with `python manage.py export_crosswalk`.

---

## 1. The canonical vocabulary (ObservedProperty)

Everything OpenH2O measures resolves to one of a small set of **observed properties**. Each one is tied to the three vocabularies that matter for interoperability:

- **USGS parameter code** — the federal water-data standard (the "pcode").
- **EPA WQX CharacteristicName** — the Water Quality Exchange vocabulary.
- **UCUM unit** — the Unified Code for Units of Measure (`unitsofmeasure.org`), so a unit is machine-parseable, not a free-text string like "cfs".

UCUM codes are a published lookup; they are hand-authored and verified in the registry, never guessed at runtime.

| Concept key | Name | USGS pcode | WQX characteristic | UCUM unit |
|---|---|---|---|---|
| `discharge` | Stream Discharge | 00060 | Stream flow | `[cft_i]/s` |
| `gage_height` | Gage Height | 00065 | Gage height | `[ft_i]` |
| `water_temperature` | Water Temperature | 00010 | Temperature, water | `Cel` |
| `groundwater_level_depth` | Depth to Groundwater | 72019 | Depth to water level below land surface | `[ft_i]` |
| `groundwater_level_elevation` | Groundwater Level Elevation | 72020 | Water level elevation above NAVD 1988 | `[ft_i]` |
| `groundwater_level` | Groundwater Level | 62610 | Groundwater level | `[ft_i]` |
| `reservoir_storage` | Reservoir Storage | — | Reservoir storage | `[acr_us].[ft_i]` |
| `reservoir_elevation` | Reservoir Elevation | — | Reservoir water surface elevation | `[ft_i]` |
| `reservoir_inflow` | Reservoir Inflow | — | Flow, inflow | `[cft_i]/s` |
| `reservoir_outflow` | Reservoir Outflow | — | Flow, outflow | `[cft_i]/s` |
| `evapotranspiration` | Evapotranspiration | — | Evapotranspiration | `mm` |
| `reference_et` | Reference Evapotranspiration | — | Evapotranspiration, reference | `mm` |
| `precipitation` | Precipitation | 00045 | Precipitation | `mm` |
| `air_temperature` | Air Temperature | — | Temperature, air | `Cel` |
| `snowfall` | Snowfall | — | Snow depth | `mm` |
| `solar_radiation` | Solar Radiation | — | Solar radiation | `W/m2` |
| `wind_speed` | Wind Speed | — | Wind velocity | `m/s` |

A blank USGS pcode is intentional: reservoir sensors, ET, and weather concepts genuinely have no USGS parameter code. They stay flagged as "publish-incomplete-as-pcode" until a real code is assigned — that's the conformance gate doing its job, not a defect.

**Source of truth:** `standards/management/commands/seed_observed_properties.py` and `standards/models.py` (`ObservedProperty`).

---

## 2. The source crosswalk (SourceParameter)

Every external source speaks its own dialect. The crosswalk maps each source's native parameter code onto a canonical concept, carrying the source's own name and unit alongside (we augment, never overwrite, the original). The result: USGS `00060`, CDEC `20`, and a CNRFC streamflow forecast all resolve to the same `discharge` concept and can be compared and published together.

| Source | Native codes mapped | Notes |
|---|---|---|
| **USGS** (NWIS) | `00060`, `00065`, `00010`, `72019`, `72020`, `62610` | Stream gauges + groundwater wells |
| **CDEC** | `15`, `6`, `76`, `23`, `1`, `20`, `2` | Reservoirs + streams; `1` (River Stage) → `gage_height`, `20` (Flow) → `discharge` |
| **DWR Water Data Library** | `gw_level` | Periodic (≈quarterly) groundwater levels |
| **DWR SGMA portal** | `gw_level` | Same CNRA dataset, filtered to SGMA monitoring |
| **CIMIS** | `day-eto`, `day-precip`, `day-sol-rad-avg`, `day-wind-spd-avg`, `day-air-tmp-avg` | Daily reference ET + weather |
| **NOAA** (GHCND) | `PRCP`, `TMAX`, `TMIN`, `SNOW` | Daily climate; TMAX/TMIN both → `air_temperature` |
| **CNRFC** | `streamflow`, `precip` | River-flow + precip forecasts |
| **OpenET** | (geometry-based, not a station parameter) | ET per parcel polygon → `evapotranspiration` |

The full denormalized table is in [crosswalk.csv](crosswalk.csv). A regression test (`tests/test_standards_registry.py`) locks every adapter code to a concept so the crosswalk can't silently drift when an adapter changes.

**Source of truth:** the `CODE_TO_KEY` table in `seed_observed_properties.py`, built from each adapter's `PARAMETER_MAP` via `datasync/adapters/registry.py`.

---

## 3. Provenance: quality flags and vertical datum

Two fields make the data trustworthy enough to certify and to publish:

- **Quality flag** (`provisional` / `approved` / `estimated`) on every measurement, following OGC SensorThings and USGS conventions. Newly synced data is provisional; a reviewer marks it approved; derived or gap-filled values are estimated.
- **Vertical datum** (`NAVD88` / `NGVD29`) on groundwater wells. A depth-to-water reading is meaningless as an elevation without knowing the datum it was measured against — and you can't compare wells across a basin or build SensorThings geometry without it.

**Source of truth:** `measurements/models.py` (`QUALITY_CHOICES`), `wells/models.py` (vertical datum).

---

## 4. The conformance gate

Before any data reaches a publish path, `check_conformance` audits the registry:

```bash
python manage.py check_conformance
```

It exits non-zero only on a **real** publishing blocker — an observed property missing its UCUM unit. A missing USGS pcode is reported as pending but is non-blocking (some concepts legitimately have none). Orphaned crosswalk rows and measurements with no observed property are flagged. Run it in CI to prevent regressions.

The rule is encoded as `ObservedProperty.is_publishable()`: publishable only when it has a UCUM unit. Every publish path — API, CSV, Frictionless — needs a unit contract, so this is the one hard gate.

---

## 5. State reporting exports

OpenH2O prepares the two filings California agencies owe, as ready-to-submit CSV. It does **not** auto-submit: the state has no submission API, and the filings are certified under penalty of perjury, so a human reviews and files them.

- **GEARS** — two modes: *by-well* (monthly metered extraction) and *by-ET* (monthly consumptive use from OpenET). Unit: acre-feet.
- **CalWATRS** — *Direct Use* and *To Storage* templates, by point of diversion. Units: acre-feet and CFS. Flags parcels with both groundwater and surface-water sources as combined-use, and marks missing water rights as `[INCOMPLETE]`.

**Source of truth:** `reporting/generators.py`, `reporting/models.py`.

---

## 6. Derived values: effective precipitation & the precip feed

Two values OpenH2O computes (rather than ingests) are worth documenting plainly, because both are estimates, not measurements:

- **Effective precipitation.** Not all rain is usable by a crop, so the calculation engine subtracts only the *effective* share of precipitation from gross ET. The method is configurable per agency (`accounting/precip_math.py`): a raw pass-through, a flat fraction of total rain, or the USDA-SCS / TR-21 soil-storage model. The USDA-SCS option caps effective precipitation at the month's ET, so Pe never exceeds `min(P, ET)` and the net consumptive use stays ≥ 0.
- **Precipitation source.** Per-parcel precipitation is sampled from GRIDMET (`pr` band, mm), not a separate rain-gauge network. This is deliberate: the OpenET ensemble OpenH2O uses for ET is itself built on gridMET forcing, so drawing precip from the same source keeps ET and precip on consistent inputs (`datasync/adapters/gee.py`).

These are estimates used to fill gaps where direct measurements are absent; a district's own metered or recorded values always take precedence.

---

## 7. Publishing roadmap (open standards out)

The data model already maps onto these standards; the serializers are the remaining work.

| Standard | What it is | Status |
|---|---|---|
| **OGC SensorThings API v1.1** | An OGC standard REST API for sensor data — any compliant tool can consume it | Schema foundation built (`Datastream` model, FeatureOfInterest from well screen + datum); read-only API endpoint planned |
| **Frictionless Data Package** | A `datapackage.json` + typed CSV bundle for portable tabular data | Field alignment done in the registry; export path planned |
| **WaDE 2.0** | The Water Data Exchange schema used by the Western States Water Council and the CA Water Data Consortium | Shares the registry's field alignment; export path planned |
| **Geoconnex** | Persistent web identifiers (PIDs) for water features, for national federation | Deferred — needs external registration with the Internet of Water team. Basin codes (DWR Bulletin 118) are already carried on geography records as the foundation |

The design principle is that all four read from the **same** conformance registry, so adding one is additive serialization, not remodeling.

---

## How another district can reuse this

If you run a different water platform, the highest-leverage thing to copy is **the pattern, not the code**: a single canonical observed-property registry that every adapter and every export references, with the unit contract enforced by a gate. Grab [crosswalk.csv](crosswalk.csv) as a starting vocabulary, and `standards/` as a worked reference implementation under the AGPL.
