<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Importing Your Agency's Data

There are three ways to get data into OpenH2O. Most agencies use all three: demo data to learn the system, the Setup Wizard plus file imports for the data they already have, and auto-populate to fill in the rest from public sources.

Run every management-command importer with `--dry-run` first: it validates and reports what *would* happen without writing anything. The screen importers (an upload button in the browser) show the same preview-before-commit shape without a flag.

**A path on this page only resolves inside the `web` container.** The container carries no bind mount to your own computer's filesystem (there is no host folder mounted into it -- see `docker-compose.yml`), so a bare path like `wells.csv` on a management-command example is not a file on your machine, it is a file the container is being asked to find inside itself. Every command example on this page is written the way you actually run it: copy the file in with `docker compose cp` first, then reference the `/tmp/` path the copy created. **The screen importers do not have this problem** -- they take a file upload through your browser, so there is nothing to copy in first.

---

## 1. Demo data (to learn the system)

```bash
docker compose exec web python manage.py seed_merced   # the Merced Subbasin demonstration
```

This loads the Merced Subbasin demo (a real California basin, the same dataset running at openh2o.com), so you have a fully populated example to click through while you gather your agency's real data. One step fetches hydrography and monitoring stations live from public APIs (a few minutes, no key needed). Each sub-step is idempotent, so re-running is safe.

---

## 2. The Setup Wizard (start here for your own agency)

`/setup/` is where a real deployment begins. It offers three ways in, and you are never required to pick one over the others:

1. **Upload a boundary file** (GeoJSON, zipped shapefile, or KML) for your district or service area.
2. **Type an extent** by hand if you do not have a file.
3. **Start without one.** Every page works without a boundary; the map and station discovery need one, and you can come back and add it any time.

Once a boundary exists (or even if you skip it), the wizard's next step can run the same auto-populate steps described in section 4 below, one at a time, from the browser -- basins, parcels, flowlines, and monitoring stations near your watershed. The `auto_populate` management command runs the identical steps for scripting or a headless setup.

---

## 3. File imports (the data you already have)

> **Working with an AI agent?** You don't have to work out the column mapping yourself. Point the agent at your file (a county assessor export, a spreadsheet, an old system's dump) and ask it to import the data. The `--field` override flags below, and the mapping-step column pickers on the screen importers, let it map your column names onto what OpenH2O expects, and the `--dry-run` / preview-before-commit flow lets it check the result before anything is written. Crosswalking messy real-world data into an importer is exactly the kind of work an agent handles well.

### Parcels: `import_parcels`
The foundation: accounts, wells, and ledgers all hang off parcels. Accepts **GeoJSON or Shapefile**. Command only; no screen import.

```bash
docker compose cp parcels.geojson web:/tmp/
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson --dry-run
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson
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
docker compose cp wells.csv web:/tmp/
docker compose exec web python manage.py import_wells /tmp/wells.csv --dry-run
docker compose exec web python manage.py import_wells /tmp/wells.csv
```

`import_wells` reads exactly these columns: `WELL_NAME`, `LATITUDE`, `LONGITUDE`, `WELL_REG_ID`, `wcr_number`, `owner_name`, `depth_ft`, `casing_diameter_in`, `capacity_gpm`, `year_pumping_began`, `well_type`.

| Field | Column read | Override flag | Notes |
|---|---|---|---|
| Well name | `WELL_NAME` | `--name-field` | |
| Latitude | `LATITUDE` | `--lat-field` | |
| Longitude | `LONGITUDE` | `--lon-field` | |
| Well registration ID | `WELL_REG_ID` | `--reg-id-field` | **This agency's own local registry identifier** (the well page's own help text). Not the state's number -- see WCR Number below. |
| WCR Number | `wcr_number` | none | The state's own DWR Well Completion Report number. A different field from Well Registration ID above, even when a file happens to carry the same value in both. |
| Owner name | `owner_name` | none | |
| Depth (ft) | `depth_ft` | none | |
| Casing diameter (in) | `casing_diameter_in` | none | |
| Capacity (gpm) | `capacity_gpm` | none | |
| Year pumping began | `year_pumping_began` | none | |
| Well type | `well_type` | none | Matched case-insensitively against an existing Well Type name. An unmatched value is never used to create a new type (Well Type is seeded reference data); it is reported as a warning and the well imports with no type. |

A column in the file that is none of the above is read but not written anywhere; each one is reported once ("column X not read"), never an error -- the rest of the file still imports.

A row whose well name matches an existing well's is not a hard duplicate (only Well Registration ID is unique in the database): by default it still imports as a second row, and the command names it ("a well named X exists; imported as a second row; pass `--skip-duplicates` to skip"). Pass `--skip-duplicates` to skip it instead.

`--dry-run` prints the columns it will read and the columns it will ignore, before touching the database.

### Wells, points of diversion, storage ponds, and recharge sites: the infrastructure screen importer
Unlike `import_wells` above, this is a browser upload, not a management command: **Add Infrastructure → Import** (`/infrastructure/import/?type=well` or `diversion`, `storage`, `recharge_site`). Accepts **CSV, GeoJSON, zipped Shapefile, or KML** (up to 500 rows, 25 MB). A mapping step shows its best-guess column matches and lets you correct any of them before committing; nothing is written until you confirm.

Its own alias table is wider than `import_wells`'s and is tuned to the state's own exports (for example the DWR OSWCR well-completion-report CSV: `WCRNUMBER`, `DECIMALLATITUDE`, `DECIMALLONGITUDE`, `TOTALCOMPLETEDDEPTH`, `CASINGDIAMETER`, all recognized automatically). For wells it additionally reads tested yield, casing material, screen top/bottom, pump type, and measurement method; for a point of diversion it reads the stream name, the locally-known name, max rate, the water right it belongs to (`APPL_ID`), and the parcel it serves; for a recharge site it reads the site type, capacity in acre-feet, and operator. The mapping-step column list on the page names the exact fields for whichever type you picked.

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

A right without a season or a maximum rate on the state's own LIST export can be filled in afterward on the right's own edit page (`/surface/rights/<id>/edit/`).

### Diversion records: the diversion import screen and `import_diversion_records`

A year of monthly diversion volumes against a point of diversion, through **Surface Diversions → Import diversion records** (`/surface/diversion/import/`) or the management command. **CSV only.** Two layouts are recognized by header, never by filename:

| Layout | Recognized by | Columns |
|---|---|---|
| The state's Water Use Reported export | `APPL_ID`, `YEAR`, `MONTH`, `DIVERSION_TYPE`, `AMOUNT` all present | `AMOUNT` is already acre-feet. `MONTH` is the calendar month number (1 = January, 10 = October). An optional `calendar_month` column (`YYYY-MM`) is trusted outright when present; otherwise the calendar month is computed from the deployment's own report-year rule (below). An optional `APPL_POD` column names the point directly. |
| An operator's book | a point-ish column (`point`, `local_name`, `headgate`, `name`) and either a volume-ish column (`volume`, `acre_feet`, `af`) or `flow_cfs` and `hours` together | `date` (first of its month) or `month` gives the reporting month. `acre_feet`/`af` are already acre-feet; a bare `volume` column needs a paired `unit` column (`af`, `gallons`, `ccf`, `mg`, `cfs_hours`). Absent a volume column, `flow_cfs` and `hours` together convert at 1.9835 acre-feet per cfs-day. Optional `type` (direct/storage/use) and `returned`. |

**Point resolution**, in order: the state's own `APPL_POD` column; then the right (`APPL_ID`) when it has exactly one point on file; then a point-ish column; then the whole-file point you choose in the mapping step. A row that resolves to none of these is unresolved and nothing is written for it, named in the preview so you can add a column or pick a whole-file point and re-run.

**Conversions**, named on every row that needed one: 325,851 gallons per acre-foot, 748.05 gallons per CCF, 1,000,000 gallons per MG, 1.9835 acre-feet per cfs-day.

**One deployment setting** (Delivery Settings → Diversion records) decides what every file needs: `diversion_report_year_rule` turns a `YEAR` and `MONTH` into a calendar month (water year, calendar year, or a season starting a chosen month).

**The USE-row question is asked on the import screen, not on the deployment settings page**, and only when the uploaded file actually has rows typed `USE` (the state publishes no product type of its own for USE). The mapping step shows the count of USE rows in this file and three choices: ignore them, count the difference against the matching `DIRECT` row as `returned_af` (USE minus DIRECT, floored at zero), or treat them as their own direct-use rows. The rule chosen there is applied to that file; when it differs from the deployment's remembered answer, committing the import saves it back onto `SiteConfig.diversion_use_type_rule` so the same file, imported again next year, defaults to the same answer. A `COMBINED` row (pre-2015 files) is a row error naming the year; it is never guessed at.

**Rows landing on the same point, month and type within one file are summed into one record** (a ditch tender's book often carries two or more deliveries a month at one headgate), reported as "N rows combined into one month." A record whose (point, month, type) already exists in the database is skipped and counted, never overwritten -- re-importing the same file writes nothing the second time.

The mapping step lets you choose the whole-file point, the method and the data state applied to every record the file creates (default: method not stated, data state provisional; pick non-provisional when the file is the state's own already-published figure rather than a new measurement). The preview shows every conversion, every combined month, every unresolved row and every error before anything is written; the commit reports the same counts and attaches each record's reporting period by month.

```bash
docker compose cp diversions.csv web:/tmp/
docker compose exec web python manage.py import_diversion_records /tmp/diversions.csv \
  --point 42 --dry-run
docker compose exec web python manage.py import_diversion_records /tmp/diversions.csv --point 42
```

### Ledger entries: `import_ledger_csv` or the ledger's own Upload CSV screen
For migrating usage/supply history from a prior system. Same file, same columns, same validation, two doors: the management command below, or **Use Ledger → Upload CSV** (`/accounting/ledger/upload/`) in the browser, which needs no `docker compose cp` step because it is a file upload. **CSV**, with these columns:

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
docker compose cp ledger.csv web:/tmp/
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year" --dry-run
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year"
```

### Drinking water: lab sample results (screen only)

A lab's or the state's own EDT export of sample results, through **Drinking Water → Results → Import** (`/drinking/import/`). Screen only, no management command. Accepts **CSV, or the state's own tab-delimited `SDWIS1-4.tab` files inside a `.zip`** (the EDT Library's current export shape; the older `.CSV` layout the *Data Dictionary for SDWIS.CSV Files* describes still works too).

The mapping step recognizes the state's own header spellings automatically (`PS Code`, `Sample Date`, `Analyte Code`, `Result`, and so on) and a handful of the spellings commercial labs ship instead. Four columns are required for a row to become a result at all: PS Code, sample date, analyte name, and the result value.

**A `PS Code` that does not match an existing sampling point is a row error, never a new sampling point** -- inventing one from a lab file would let a typo silently manufacture system structure that then looks like a real monitoring location. Add the sampling point first (under Drinking Water → Sampling Points), then re-import.

**An analyte the platform has not seen before is created from the file's own Analyte Code and Analyte Name** (the regulator's vocabulary, not this platform's), and the preview says so.

**MCL and DLR columns, when the file carries them, are stored exactly as reported and never compared against the result** (a limit stored beside the value must never read as a compliance verdict, which this platform does not make).

### Water system production: the production import screen and `import_production`

A year of a drinking-water system's own production or delivery, by month and by source, through **Drinking Water → Production → Import** (`/drinking/production/import/`) or the management command. **CSV only.** Two layouts are recognized by header, never by filename:

| Layout | Recognized by | Columns |
|---|---|---|
| The state's eAR production export | `PWSID`, `Year`, `Month`, `TypeCode`, `Quantity as in Units Reported` all present | One row per (PWSID, Year, Month, TypeCode). `TypeCode` is one of the state's seven: `GW`, `SW`, `Purchased`, `Sold`, `Recycled`, `NonPotable` and `NonPotableSold` (non-potable water sold to another system, kept as its own type). Any other code is a row error naming it. `Units of Measure As Reported` is `G`, `MG`, `AF`, `CCF`, or blank; a blank cell is a row error until you choose the mapping step's "unit for blank rows." Repeated keys within the file are exact duplicates (the state's own export can carry a key up to five times) and are collapsed, counted, never doubled. `PWSID` must match this deployment's own water system -- a row for another system is a row error naming it. |
| The operator's own monthly log | a `Date/Month` column, plus at least one of the six source columns | The Small Water System eAR template's own Section 5 layout: `Date/Month` (the twelve month names; `Maximum Day`, `Annual Total` and `Percent Treated` are not months and are skipped, named in the preview, never misread as a thirteenth month) and one column per source ("Water Produced from Groundwater (Wells)", "...Surface Water", "Finished Water Purchased...", "Water Sold to Another PWS", "Non-potable...", "Recycled"). "Total Amount of Potable Water" is a computed total on the printed form and is never read as a source. The file carries no PWSID and no unit -- both are the mapping step's own questions (the report year is required; the unit defaults to gallons). |

**Conversions**, matching every other importer's own figures: 325,851 gallons per acre-foot, 1,000,000 gallons per MG, 748.05 gallons per CCF.

**A month and source already on file is skipped and counted, never overwritten** -- re-importing the same file writes nothing the second time. A single month can also be typed in by hand at **Drinking Water → Production → + Add month**.

```bash
docker compose cp ear-2024-production.csv web:/tmp/
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv \
  --pwsid CA2410011 --dry-run
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv --pwsid CA2410011
```

---

## 4. Auto-populate (fill in from public sources)

### By boundary
If you only have a basin boundary, `auto_populate` queries DWR and USGS to pull the rest. The wizard's own second step (section 2, above) runs the identical steps interactively from the browser.

```bash
docker compose exec web python manage.py auto_populate --boundary "Merced Subbasin" --dry-run
docker compose exec web python manage.py auto_populate --boundary "Merced Subbasin"
```

| Step | Source | Creates |
|---|---|---|
| `basins` | DWR Bulletin 118 groundwater basins | management zones |
| `parcels` | DWR LightBox statewide parcels | parcel boundaries |
| `flowlines` | USGS 3DHP | stream flowlines |
| `stations` | USGS, CDEC, DWR WDL, DWR SGMA, CIMIS, NOAA, CNRFC | monitoring stations |

Run a subset with `--steps basins parcels`. The boundary must already exist (create it in the wizard or via `import_parcels` first).

### By PWSID (drinking-water systems)
A small water system usually does not have a boundary to draw; it has a PWSID. **Drinking Water → Onboard** (`/drinking/onboard/`) looks up a PWSID against EPA's Envirofacts (SDWIS), shows the water system's own record and every facility EPA has for it, and writes them on confirmation -- nothing is written until you review and commit. Re-running it on an already-onboarded PWSID is safe; it shows what would change rather than duplicating.

---

## What still needs hand entry

No public source and no bulk importer fills these; each has its own full-page create screen instead of a file or auto-populate path:

- **Water rights** (unless you have the state's rights LIST CSV, above): `/surface/rights/add/`
- **Curtailment orders**: `/surface/curtailments/add/`
- **Measuring devices** (on a point of diversion): from the point's own page
- **Water accounts**: `/accounting/accounts/create/`
- **Allocations** (the agency's budget decisions): `/accounting/allocations/create/`
- **Water system facilities** (beyond what PWSID onboarding brings in): `/drinking/facilities/add/`
- **The sampling schedule**: `/drinking/schedule/add/`

One gap has no screen at all: a water-level or staff reading on a well, or a reading on a monitoring station, is not yet enterable anywhere. It is planned for a later release.

---

## A sensible order

1. **Start the Setup Wizard** (`/setup/`): upload a boundary file, type an extent, or start without one. Every page works without a boundary, so this step can be skipped and returned to later.
2. `seed_data` (reference tables); `seed_merced` if you want to explore the demo first.
3. Bring in your own features: `import_parcels` first (everything else hangs off parcels), then `import_wells` or the infrastructure screen importer for wells, points of diversion, storage ponds and recharge sites; import your rights list or add rights by hand. A drinking-water system onboards by PWSID instead of any of these.
4. Run the wizard's own populate step (or the `auto_populate` command) for monitoring stations, and for basins/parcels/flowlines if you skipped step 1's boundary.
5. Create water accounts and allocations in the UI (no bulk path for either).
6. `import_ledger_csv` if migrating usage/supply history; otherwise the ledger fills from sync and meter readings.
7. Connect live data sources and the sync schedule (see [DEPLOY.md](../DEPLOY.md)).
