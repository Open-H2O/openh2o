<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Importing Your Agency's Data

There are three ways to get data into OpenH2O. Most agencies use all three: demo data to learn the system, file imports for the data they already have, and auto-populate to fill in the rest from public sources.

Run every importer with `--dry-run` first: it validates and reports what *would* happen without writing anything.

---

## 1. Demo data (to learn the system)

```bash
docker compose exec web python manage.py seed_merced   # the Merced Subbasin demonstration
```

This loads the Merced Subbasin demo (a real California basin, the same dataset running at openh2o.com), so you have a fully populated example to click through while you gather your agency's real data. One step fetches hydrography and monitoring stations live from public APIs (a few minutes, no key needed). Each sub-step is idempotent, so re-running is safe.

---

## 2. File imports (the data you already have)

> **Working with an AI agent?** You don't have to work out the column mapping yourself. Point the agent at your file (a county assessor export, a spreadsheet, an old system's dump) and ask it to import the data. The `--field` override flags below let it map your column names onto what OpenH2O expects, and the `--dry-run` plus staging-table flow lets it check the result before anything is written. Crosswalking messy real-world data into the importer is exactly the kind of work an agent handles well.

### Parcels: `import_parcels`
The foundation: accounts, wells, and ledgers all hang off parcels. Accepts **GeoJSON or Shapefile**.

```bash
docker compose exec web python manage.py import_parcels parcels.geojson --dry-run
docker compose exec web python manage.py import_parcels parcels.geojson
```

Expected attributes (override the field names if yours differ):

| Field | Default name | Override flag | Required |
|---|---|---|---|
| Parcel number (APN) | `APN` | `--parcel-number-field` | yes |
| Owner name | `OWNER` | `--owner-field` | no |
| Geometry | (the feature geometry) | none | yes, polygons |

Records land in a staging table first, then promote to `Parcel`, so a bad file never half-corrupts your data.

### Wells: `import_wells`
Accepts **CSV or Shapefile**. For CSV, the geometry comes from latitude/longitude columns.

```bash
docker compose exec web python manage.py import_wells wells.csv --dry-run
```

| Field | Default column | Override flag |
|---|---|---|
| Well name | `WELL_NAME` | `--name-field` |
| Latitude | `LATITUDE` | `--lat-field` |
| Longitude | `LONGITUDE` | `--lon-field` |
| Well registration ID | `WELL_REG_ID` | `--reg-id-field` |

### Water rights: the rights LIST import screen

Unlike the other file imports on this page, water rights import through the web UI, not a management command: **Water Rights → Import** (`/surface/rights/import/`). Accepts **CSV only** (the state's own rights LIST export).

| Column | Required | Notes |
|---|---|---|
| `APPLICATION_NUMBER` | **yes** | becomes the right's ID; a repeat is skipped, never overwritten |
| `WATER_RIGHT_TYPE` | **yes** | must match a seeded `WaterRightType` name (or a known state spelling, such as bare "Appropriative") |
| `PRIMARY_OWNER_NAME` | **yes** | the holder |
| `FACE_VALUE_AMOUNT` / `FACE_VALUE_UNITS` | no | `FACE_VALUE_UNITS` must read "Acre-feet per Year" (any other unit is a row error, never converted) |
| `MAX_DD_APPL` / `MAX_DD_UNITS` | no | `MAX_DD_UNITS` must read "Cubic Feet per Second" (any other unit is a row error, never converted) |
| `PRIORITY_DATE` | no | ISO (`YYYY-MM-DD`) or `M/D/YYYY`; blank stays blank |
| `LICENSE_ID`, `PERMIT_ID`, `USE_CODE`, `USE_NET_ACREAGE`, `WATERSHED`, `SOURCE_NAME`, `WATER_RIGHT_STATUS` | no | copied through as the license number, permit number, purpose of use, net acreage, watershed, source and state status |
| `DIRECT_SEASON_START_MONTH_1` / `DIRECT_DIV_SEASON_START_DAY_1` / `DIRECT_DIV_SEASON_END_MONTH_1` / `DIRECT_DIV_SEASON_END_DAY_1` | no | the direct-diversion season |
| `STORAGE_SEASON_START_MONTH_1` / `STORAGE_SEASON_START_DAY_1` / `STORAGE_SEASON_END_MONTH_1` / `STORAGE_SEASON_END_DAY_1` | no | the storage season |

The mapping step shows every column it matched (and lets you correct one), a preview of the first rows, then created and skipped counts, the same shape the file imports above use.

### Ledger entries: `import_ledger_csv`
For migrating usage/supply history from a prior system. **CSV**, with these columns:

| Column | Required | Notes |
|---|---|---|
| `parcel_number` | **yes** | must match an imported parcel's APN |
| `effective_date` | **yes** | the date the entry applies to |
| `amount_acre_feet` | **yes** | see the sign each `source_type` carries, below |
| `source_type` | **yes** | one of the codes below |
| `water_type_code` | no | must match a seeded WaterType code |
| `transaction_date` | no | when it was recorded |
| `description` | no | free text |

Water taken against the allocation is a negative amount (meter readings, ET estimates, surface diversions, calculated rows); water added to it is positive (allocations, recharge credits); manual entries, CSV-import rows and adjustments carry the sign you give them.

The importer corrects a mismatched sign for you and reports every row it changed; it never rejects the row.

| `source_type` code | Sign |
|---|---|
| `meter_reading` | negative |
| `et_estimate` | negative |
| `manual_entry` | either |
| `csv_import` | either |
| `surface_diversion` | negative |
| `recharge` | positive |
| `allocation` | positive |
| `adjustment` | either |
| `calculated` | negative |

```bash
docker compose exec web python manage.py import_ledger_csv ledger.csv \
  --reporting-period "2024 Water Year" --dry-run
```

---

## 3. Auto-populate (fill in from public sources)

If you only have a basin boundary, `auto_populate` queries DWR and USGS to pull the rest:

```bash
docker compose exec web python manage.py auto_populate --boundary "Merced Subbasin" --dry-run
docker compose exec web python manage.py auto_populate --boundary "Merced Subbasin"
```

| Step | Source | Creates |
|---|---|---|
| `basins` | DWR Bulletin 118 groundwater basins | management zones |
| `parcels` | DWR LightBox statewide parcels | parcel boundaries |
| `flowlines` | USGS 3DHP | stream flowlines |
| `stations` | CDEC / USGS / CIMIS | monitoring stations |

Run a subset with `--steps basins parcels`. The boundary must already exist (create it in the UI or via `import_parcels` first).

---

## What still needs hand entry

No public source auto-populates these:

- **Water rights**: eWRIMS is not queried live; import the state's rights LIST CSV yourself, above, or add one right at a time under Water Rights
- **Water accounts**: the agency defines these, entered in the web UI under **Infrastructure**
- **Allocations**: the agency's budget decisions

---

## A sensible order

1. `seed_data` (reference tables) → `seed_merced` (to explore the demo)
2. `import_parcels` your real parcels, then confirm the boundary on the map
3. `import_wells` if you have a well list; `auto_populate --steps stations` for monitoring
4. Create water accounts and allocations in the UI
5. `import_ledger_csv` if migrating history; otherwise the ledger fills from sync + meter readings
6. Connect live data sources and the sync schedule (see [DEPLOY.md](../DEPLOY.md))
