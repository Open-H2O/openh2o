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

### Diversion records: the diversion import screen and `import_diversion_records`

A year of monthly diversion volumes against a point of diversion, through **Surface Diversions → Import diversion records** (`/surface/diversion/import/`) or the management command. **CSV only.** Two layouts are recognized by header, never by filename:

| Layout | Recognized by | Columns |
|---|---|---|
| The state's Water Use Reported export | `APPL_ID`, `YEAR`, `MONTH`, `DIVERSION_TYPE`, `AMOUNT` all present | `AMOUNT` is already acre-feet. `MONTH` is the calendar month number (1 = January, 10 = October). An optional `calendar_month` column (`YYYY-MM`) is trusted outright when present; otherwise the calendar month is computed from the deployment's own report-year rule (below). An optional `APPL_POD` column names the point directly. |
| An operator's book | a point-ish column (`point`, `local_name`, `headgate`, `name`) and either a volume-ish column (`volume`, `acre_feet`, `af`) or `flow_cfs` and `hours` together | `date` (first of its month) or `month` gives the reporting month. `acre_feet`/`af` are already acre-feet; a bare `volume` column needs a paired `unit` column (`af`, `gallons`, `ccf`, `mg`, `cfs_hours`). Absent a volume column, `flow_cfs` and `hours` together convert at 1.9835 acre-feet per cfs-day. Optional `type` (direct/storage/use) and `returned`. |

**Point resolution**, in order: the state's own `APPL_POD` column; then the right (`APPL_ID`) when it has exactly one point on file; then a point-ish column; then the whole-file point you choose in the mapping step. A row that resolves to none of these is unresolved and nothing is written for it, named in the preview so you can add a column or pick a whole-file point and re-run.

**Conversions**, named on every row that needed one: 325,851 gallons per acre-foot, 748.05 gallons per CCF, 1,000,000 gallons per MG, 1.9835 acre-feet per cfs-day.

**Two deployment settings** (Delivery Settings → Diversion records) decide two things every file needs: `diversion_report_year_rule` turns a `YEAR` and `MONTH` into a calendar month (water year, calendar year, or a season starting a chosen month), and `diversion_use_type_rule` decides what a `USE` row means here (the state publishes no product type for it): dropped, added to the matching `DIRECT` row as `returned_af` (USE minus DIRECT, floored at zero), or treated as its own direct-use row. A `COMBINED` row (pre-2015 files) is a row error naming the year; it is never guessed at.

**Rows landing on the same point, month and type within one file are summed into one record** (a ditch tender's book often carries two or more deliveries a month at one headgate), reported as "N rows combined into one month." A record whose (point, month, type) already exists in the database is skipped and counted, never overwritten -- re-importing the same file writes nothing the second time.

The mapping step lets you choose the whole-file point, the method and the data state applied to every record the file creates (default: method not stated, data state provisional; pick non-provisional when the file is the state's own already-published figure rather than a new measurement). The preview shows every conversion, every combined month, every unresolved row and every error before anything is written; the commit reports the same counts and attaches each record's reporting period by month.

```bash
docker compose exec web python manage.py import_diversion_records diversions.csv \
  --point 42 --dry-run
docker compose exec web python manage.py import_diversion_records diversions.csv --point 42
```

The `web` container has no bind mount to your host filesystem -- a bare path only resolves inside the container. Copy the file in first:

```bash
docker compose cp diversions.csv web:/tmp/
docker compose exec web python manage.py import_diversion_records /tmp/diversions.csv --point 42
```

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
