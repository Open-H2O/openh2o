<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Importing Your Organization's Data

This guide explains how to load an organization's own records into OpenH2O. The
demonstration data gives you a complete sample site to explore. The Setup
Wizard sets the area your site covers and runs the populate step, which fills in
basins, parcels, streams and monitoring stations from public sources. The file
imports load the records you already have.

Some imports are screens in the browser, and some are commands that you run on the
server. Several are both. On an import screen you upload the file and check a
preview, and OpenH2O saves nothing until you confirm. The Upload CSV page on the Use
Ledger is the one exception: it imports the file at once unless you tick Dry run.

Every import command takes `--dry-run`. With it, the command checks the file and
reports what it would do, and your records stay as they were. Run each command with
`--dry-run` first.

Commands run inside the `web` container, which cannot see the files on your
computer. Copy the file into the container with `docker compose cp` first, then give
the command the `/tmp/` path that the copy created. Every command example in this
guide that reads a file copies it to `/tmp/` first. A shapefile is several files
with the same name, so copy all of them and give the command the path of the `.shp`
file. An import screen uploads the file from your browser, so you do not need to
copy it.

An AI agent can do the column matching for you. Point the agent at your file and ask
it to import the records. The file might be a county assessor's export, a
spreadsheet or an export from an old system. The agent matches your column names to
the ones OpenH2O reads with the field-name flags on the commands or the column
choices on the import screens, and it checks the result with the dry run or the
preview before anything is saved.

---

## 1. The demonstration data

```bash
docker compose exec web python manage.py seed_data      # reference data
docker compose exec web python manage.py seed_merced    # the demonstration data
```

`seed_merced` loads the demonstration, a real groundwater basin with published
records and invented sample data. It gives you a complete site to explore
while you gather your own records. Run `seed_data` first, because the demonstration
needs the reference lists it loads. One step of `seed_merced` downloads streams and
monitoring stations from public government services. The download takes a few
minutes and needs no key.

---

## 2. The Setup Wizard

A new site begins at the Setup Wizard (`/setup/`). Its first step offers four
choices:

1. Select a boundary already on the site.
2. Upload a boundary file: a zipped shapefile, a KML file or a GeoJSON file.
3. Type an extent by hand.
4. Start without a boundary.

Everything except the map and the populate step works without a boundary, and you
can add one later. The wizard's second step shows the boundary on a map for you to
confirm. Its third step runs the populate steps described in section 4, one at a
time.

To load a boundary from a GeoJSON file with a command instead, use
`import_boundary`:

```bash
docker compose cp boundary.geojson web:/tmp/
docker compose exec web python manage.py import_boundary --file /tmp/boundary.geojson --dry-run
docker compose exec web python manage.py import_boundary --file /tmp/boundary.geojson
```

---

## 3. File imports

### Parcels: `import_parcels`

Wells, accounts and the ledger are all attached to parcels, so parcels come first.
`import_parcels` reads a GeoJSON file or a shapefile. It is a command, and there is
no import screen for parcels.

```bash
docker compose cp parcels.geojson web:/tmp/
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson --dry-run
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson
```

| Field | Default column name | Flag for a different name | Required |
|---|---|---|---|
| Parcel number (APN) | `APN` | `--parcel-number-field` | yes |
| Owner name | `OWNER` | `--owner-field` | no |
| Outline | the feature's geometry | none | no |

The command reads every feature into a holding table first, then adds the new
parcels to the site. A parcel whose APN is already on the site is skipped. When a
feature's outline cannot be read, the command reports it and imports the parcel
without an outline.

### Wells: `import_wells`

`import_wells` reads a CSV file or a shapefile. In a CSV file, the location comes
from the latitude and longitude columns.

```bash
docker compose cp wells.csv web:/tmp/
docker compose exec web python manage.py import_wells /tmp/wells.csv --dry-run
docker compose exec web python manage.py import_wells /tmp/wells.csv
```

`import_wells` reads exactly these columns: `WELL_NAME`, `LATITUDE`, `LONGITUDE`, `WELL_REG_ID`, `wcr_number`, `owner_name`, `depth_ft`, `casing_diameter_in`, `capacity_gpm`, `year_pumping_began`, `well_type`.

| Field | Column read | Flag for a different name | Notes |
|---|---|---|---|
| Well name | `WELL_NAME` | `--name-field` | |
| Latitude | `LATITUDE` | `--lat-field` | |
| Longitude | `LONGITUDE` | `--lon-field` | |
| Well registration ID | `WELL_REG_ID` | `--reg-id-field` | The organization's own number for the well. A row whose registration ID is already on the site is skipped. |
| WCR number | `wcr_number` | none | The number of the well's Well Completion Report from the California Department of Water Resources. It is a separate field from the registration ID, even when a file carries the same value in both. |
| Owner name | `owner_name` | none | |
| Depth (ft) | `depth_ft` | none | |
| Casing diameter (in) | `casing_diameter_in` | none | |
| Capacity (gpm) | `capacity_gpm` | none | |
| Year pumping began | `year_pumping_began` | none | |
| Well type | `well_type` | none | Matched to the name of a well type already on the site, with capital and small letters treated alike. When the value matches no well type on the site, the well is imported without a type and the command reports a warning. |

The command ignores any column that is not in this table and names each one once in
its report. The rest of the file is imported. With `--dry-run`, the command lists
the columns it will read and the columns it will leave out. A row with no latitude
and longitude is skipped.

A well whose name matches a well already on the site is imported as a second well,
and the command names it. Pass `--skip-duplicates` to skip such rows instead.

### Wells, points of diversion, storage ponds and recharge sites: the Import screen

The Wells, Surface Diversions and Recharge sites pages each have an Import button,
and all three open the same import screen (`/infrastructure/import/?type=well`,
`diversion` or `recharge_site`). Storage ponds have no Import button, so open
`/infrastructure/import/?type=storage` directly. The screen reads a CSV file, a
GeoJSON file, a zipped shapefile or a KML file of up to 500 rows and 25 MB. A mapping
step shows the column OpenH2O matched to each field, and you can change any match
before you import.

The screen recognizes more column names than `import_wells` does. It reads the
column names of the Department of Water Resources' well completion report export,
such as `WCRNUMBER`, `DECIMALLATITUDE`, `DECIMALLONGITUDE` and `TOTALCOMPLETEDDEPTH`.
For a well, it also reads tested yield, casing material, the top and bottom of the
well screen, pump type and measurement method. For a point of diversion, it reads
the stream name, the local name, the maximum rate, the water right (`APPL_ID`) and
the parcel the point serves. For a recharge site, it reads the site type, the
capacity in acre-feet and the operator. The mapping step lists every field for the
type you chose.

Unlike `import_wells`, the screen refuses a row whose name is already on the site or
appears twice in the file. A point of diversion that names a water right needs that
right on the site first, so import the water rights before the points of diversion.

### Water rights: the Water Rights Import screen

The Import button on the Water Rights page opens the import screen
(`/surface/rights/import/`). It reads the CSV list of water rights exported from
eWRIMS, the State Water Resources Control Board's water rights system. A file can
hold up to 500 rows and 25 MB.

| Column | Required | Notes |
|---|---|---|
| `APPLICATION_NUMBER` | yes | Becomes the right's ID. A right already on the site is skipped and left as it is. |
| `WATER_RIGHT_TYPE` | yes | A type not yet on the site is added under the name the file uses. |
| `PRIMARY_OWNER_NAME` | yes | The holder of the right. |
| `FACE_VALUE_AMOUNT` / `FACE_VALUE_UNITS` | no | OpenH2O records a face value in acre-feet per year. A face value in other units is left out, and the preview names the right. |
| `MAX_DD_APPL` / `MAX_DD_UNITS` | no | OpenH2O records a maximum rate in cubic feet per second. A rate in other units is left out, and the preview names the right. |
| `PRIORITY_DATE` | no | Written as `YYYY-MM-DD` or `M/D/YYYY`. A blank date stays blank. |
| `LICENSE_ID`, `PERMIT_ID`, `USE_CODE`, `USE_NET_ACREAGE`, `WATERSHED`, `SOURCE_NAME`, `WATER_RIGHT_STATUS` | no | Copied to the right's license number, permit number, purpose of use, net acreage, watershed, source and status, as eWRIMS records them. |
| `DIRECT_SEASON_START_MONTH_1` / `DIRECT_DIV_SEASON_START_DAY_1` / `DIRECT_DIV_SEASON_END_MONTH_1` / `DIRECT_DIV_SEASON_END_DAY_1` | no | The direct diversion season. |
| `STORAGE_SEASON_START_MONTH_1` / `STORAGE_SEASON_START_DAY_1` / `STORAGE_SEASON_END_MONTH_1` / `STORAGE_SEASON_END_DAY_1` | no | The storage season. |

The mapping step shows each column OpenH2O matched, and you can change a match. The
preview shows the first rows, and the import reports how many rights it created and
how many it skipped. When the list leaves out a right's season or maximum rate, you
can add it on the right's edit page (`/surface/rights/<id>/edit/`).

### Diversion records: the diversion import screen and `import_diversion_records`

You can import a file of monthly diversion volumes through Import diversion records
on the Surface Diversions page (`/surface/diversion/import/`) or with the
`import_diversion_records` command. The file is a CSV file of up to 2,000 rows and
25 MB. OpenH2O reads two layouts and tells them apart by their column headings:

| Layout | Recognized by | How OpenH2O reads it |
|---|---|---|
| California's Water Use Reported export | The columns `APPL_ID`, `YEAR`, `MONTH`, `DIVERSION_TYPE` and `AMOUNT` | `AMOUNT` is in acre-feet. `YEAR` is the report year, and `MONTH` is the month number (1 is January, 10 is October). When the file has a `calendar_month` column (`YYYY-MM`), OpenH2O uses it. Otherwise the report-year setting described below decides the calendar year of each month. An `APPL_POD` column names the point of diversion. |
| Your own book of deliveries | A point column (`point`, `local_name`, `headgate` or `name`) or a date column (`date` or `month`), and either a volume column (`volume`, `acre_feet` or `af`) or both `flow_cfs` and `hours` | `date` (the first of the month) or `month` gives the month. `acre_feet` and `af` are in acre-feet. A `volume` column needs a `unit` column that holds `af`, `gallons`, `ccf`, `mg` or `cfs_hours`. Without a volume column, OpenH2O converts `flow_cfs` and `hours` at 1.9835 acre-feet per cfs-day. The optional columns are `type` (direct, storage or use) and `returned`. |

OpenH2O looks for each row's point of diversion in this order:

1. The `APPL_POD` column.
2. The water right in `APPL_ID`, when that right has exactly one point on the site.
3. A point column.
4. A point you choose for the whole file in the mapping step. The list offers active
   points only.

OpenH2O saves nothing for a row whose point it cannot find, and the preview names the
row so you can add a point column or choose a whole-file point, then import again.

OpenH2O converts units at 325,851 gallons per acre-foot, 748.05 gallons per CCF,
1,000,000 gallons per MG and 1.9835 acre-feet per cfs-day, and the preview names
each row it converted.

The report-year setting is on the Delivery Settings page, under Diversion records.
When a Water Use Reported file has no `calendar_month` column, OpenH2O uses the
setting to find the calendar year of each month. The report year can be a water
year, a calendar year, or a season that starts in a month you choose.

When a file has rows of the type `USE`, the import screen asks how to handle them,
and the mapping step shows how many there are. The choices are:

- leave them out;
- record as water returned the amount by which each `USE` row exceeds the matching
  `DIRECT` row;
- import them as direct diversions.

OpenH2O keeps your answer and offers it again the next time a file has `USE` rows.
Files from before 2015 can hold `COMBINED` rows. OpenH2O refuses them, because
direct diversion and storage need separate rows.

Rows for the same point, month and type within one file are added together into one
record, because a book of deliveries often lists several deliveries a month at one
headgate. The preview shows how many rows were combined. A record whose point, month
and type are already on the site is skipped and counted. The one exception is a
record that OpenH2O estimated from the crop water use of the fields the point
serves. The file's volume replaces that estimate. OpenH2O refuses rows for months in
a water year that has been finalized.

In the mapping step you also choose the measurement method and the data state for
every record in the file. By default the method is left blank and the data state is
provisional. Choose a different data state when the file holds figures that have
already been published. The preview shows every conversion, every combined month,
every row without a point and every error before anything is saved. The import
reports the same counts and assigns each record to the water year that holds its
month.

The command takes `--point` for the whole-file point, `--method` and `--data-state`
for the method and data state, and `--use-rule` with `drop`, `returned` or
`as_direct` for `USE` rows. The point's number is the number at the end of its page
address, `/surface/diversion/<number>/`.

```bash
docker compose cp diversions.csv web:/tmp/
docker compose exec web python manage.py import_diversion_records /tmp/diversions.csv \
  --point 42 --dry-run
docker compose exec web python manage.py import_diversion_records /tmp/diversions.csv --point 42
```

### Ledger entries: `import_ledger_csv` or the Upload CSV page

To bring water use and supply history from an earlier system, import a CSV file of
ledger entries. The command and the Upload CSV page on the Use Ledger
(`/accounting/ledger/upload/`) read the same columns and check them the same way.
The page offers a template file to download, and it imports at once unless you tick
Dry run.

| Column | Required | Notes |
|---|---|---|
| `parcel_number` | yes | The APN of a parcel already on the site. |
| `effective_date` | yes | The date the entry applies to. |
| `amount_acre_feet` | yes | Its sign depends on `source_type`. |
| `source_type` | yes | One of the codes in the sign table. |
| `water_type_code` | no | The code of a water type on the site. |
| `transaction_date` | no | The date the entry was recorded. |
| `description` | no | Any text. |

Water taken against the allocation is a negative amount (meter readings, ET estimates, surface diversions, calculated rows); water added to it is positive (allocations, recharge credits); manual entries, CSV-import rows and adjustments carry the sign you give them.

When an amount's sign does not match its source type, OpenH2O reverses the sign and
lists every row it changed.

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

OpenH2O skips a row that repeats the parcel, date, source type and amount of an
entry already on the site or of an earlier row in the file. It refuses entries for a
water year that has been finalized.

A water year in OpenH2O is a record on the Water Years page, with a name and its
first and last dates. To assign the entries to one, create the water year first
(`/accounting/reporting-periods/create/`). On the Upload CSV page, choose it from
the list. With the command, pass its name to `--reporting-period` exactly as the
Water Years page shows it. Entries imported without a water year are assigned when
a water year that covers their dates is created. The command reads a comma-separated
file unless you pass another character with `--delimiter`.

```bash
docker compose cp ledger.csv web:/tmp/
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year" --dry-run
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year"
```

### Drinking water: lab sample results

To import a lab results file, use the Import lab results button on the Sample
Results page (`/drinking/import/`). There is no command for lab results. The file
can be a .csv, .tab or .txt file of up to 5,000 rows and 25 MB, and OpenH2O works
out a .txt file's separator by reading it. California's Division of Drinking Water
publishes lab results in its Safe Drinking Water Information System (SDWIS) files.
They are tab-separated files in zip archives, with one file for each span of years,
so unzip the archive before you upload. The SDWIS4 file holds every water system in
California, so upload only the rows for the water systems on your site.

OpenH2O recognizes the Division of Drinking Water's column headings, such as
`PS Code`, `Sample Date`, `Analyte Code` and `Result`, and several headings that
commercial labs use instead. OpenH2O imports a row when it has a PS Code, a sample
date, an analyte and a result. A row with a blank result is imported as a
non-detect when its "Less than reporting level" column is marked and it gives a
reporting level.

A PS Code is the code of a sampling point. OpenH2O builds each point's PS Code from
the PWSID, the facility ID and the point number. A PS Code that matches no sampling
point on the site is a row error. OpenH2O does not create a sampling point from a lab
file, because a mistyped code would then add a monitoring location that does not
exist. Add the sampling point first with Add sampling points on the Drinking Water
page, then import the file again.

An analyte the site does not have yet is added from the file's Analyte Code and
Analyte Name, and the preview says so. When the file carries MCL and DLR columns,
OpenH2O stores those limits as the file reports them and does not compare a result
with them.

### Drinking water: production by month

You can import a file of a water system's monthly production with the Import button
on the Production page (`/drinking/production/import/`) or with the
`import_production` command. The file is a CSV file of up to 2,000 rows and 25 MB.
OpenH2O reads two layouts and tells them apart by their column headings:

| Layout | Recognized by | How OpenH2O reads it |
|---|---|---|
| California's Electronic Annual Report (eAR) production export | The columns `PWSID`, `Year`, `Month`, `TypeCode` and `Quantity as in Units Reported` | Each row is one month of one type of water. `TypeCode` is one of `GW`, `SW`, `Purchased`, `Sold`, `Recycled`, `NonPotable` and `NonPotableSold`, and any other code is a row error. `Units of Measure As Reported` is `G`, `MG`, `AF`, `CCF` or blank. A blank unit is a row error until you choose a unit for blank rows in the mapping step. The export can repeat a row up to five times, and OpenH2O keeps one copy and reports how many it dropped. `PWSID` must match the water system on the site. |
| A monthly log kept on Section 5 of the eAR template | A `Date/Month` column and at least one of the six source columns | `Date/Month` holds the twelve month names. The rows `Maximum Day`, `Annual Total` and `Percent Treated` are skipped, and the preview names them. Each source has its own column: "Water Produced from Groundwater (Wells)", "...Surface Water", "Finished Water Purchased...", "Water Sold to Another PWS", "Non-potable..." and "Recycled". The "Total Amount of Potable Water" column is a total on the printed form, and OpenH2O does not read it. The log names no system, year or unit, so on the preview you enter the report year and choose one unit for the whole file. Gallons is the default. |

OpenH2O converts units with the same figures as the other imports: 325,851 gallons
per acre-foot, 1,000,000 gallons per MG and 748.05 gallons per CCF.

A row whose month and type of water are already on the site is skipped and counted,
so importing the same file twice saves nothing the second time. To enter one month
by hand, use Add month on the Production page.

The import screen saves the figures to the site's water system. The command's
`--pwsid` names the system when the site keeps more than one. For a file in the eAR
layout, `--unit-for-blank` sets the unit for rows with a blank unit. For a monthly
log, `--operator-year` sets the report year and `--operator-unit` sets the unit. In
these commands, replace `XX1234567` with your system's PWSID.

```bash
docker compose cp ear-2024-production.csv web:/tmp/
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv \
  --pwsid XX1234567 --dry-run
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv --pwsid XX1234567
```

---

## 4. Filling in from public sources

### From a boundary

When a site has a boundary, `auto_populate` downloads the basins, parcels, streams
and monitoring stations for that area from public services. The Setup Wizard's third
step runs the same steps from the browser. In place of `My Basin`, give the boundary's
name as it appears in the Setup Wizard.

```bash
docker compose exec web python manage.py auto_populate --boundary "My Basin" --dry-run
docker compose exec web python manage.py auto_populate --boundary "My Basin"
```

| Step | Source | What it adds |
|---|---|---|
| `basins` | The California Department of Water Resources' Bulletin 118 groundwater basins | Management zones |
| `parcels` | The Department of Water Resources' statewide parcel layer | Parcel outlines |
| `flowlines` | USGS 3DHP | Streams and canals |
| `stations` | USGS; the California Data Exchange Center (CDEC); the Department of Water Resources' Water Data Library and SGMA Portal; and the California Irrigation Management Information System (CIMIS) and NOAA when their keys are set | Monitoring stations |

To run some of the steps, list them with commas: `--steps basins,parcels`. The
boundary must be on the site before the command runs. Create it in the Setup Wizard
or with `import_boundary`.

### From a PWSID, for a drinking-water system

Setting up a small water system usually starts from its PWSID, the identification
number of a public water system in EPA's records. The Add a water system page
(`/drinking/onboard/`) looks up the PWSID in EPA's Envirofacts records. It shows the
water system's record and its facilities, and it saves them when you confirm. A
facility that has no state facility ID is skipped, and the review lists it. When the
PWSID is already on the site, the review says so. If you confirm, OpenH2O updates the
system and its facilities from EPA's current record.

---

## What is entered by hand

These records have no file import and no public source. Each has its own page:

- Water rights, when you do not have the eWRIMS list: `/surface/rights/add/`
- Measuring devices on a point of diversion: from the point's page
- Water accounts: `/accounting/accounts/create/`
- Allocations: `/accounting/allocations/create/`
- Water system facilities that the PWSID lookup did not add: `/drinking/facilities/add/`
- Sampling points: Add sampling points on the Drinking Water page
- The sampling schedule: `/drinking/schedule/add/`

Water-level readings on a well and readings at a monitoring station have no page in
OpenH2O yet. Someone with a staff account can add them on the administration site at
`/admin/`.

---

## A sensible order

1. Load the reference lists with `seed_data`. Run `seed_merced` as well if you want
   to explore the demonstration first.
2. Open the Setup Wizard (`/setup/`) and choose, upload or type a boundary, or start
   without one. With a boundary, run the wizard's populate step to add monitoring
   stations, and basins, parcels and streams if you need them.
3. Import your parcels with `import_parcels`.
4. Import your wells with `import_wells` or the Wells page's Import screen.
5. Import your water rights, or add them by hand, before the points of diversion.
   Then import points of diversion, storage ponds and recharge sites on the Import
   screen.
6. For a drinking-water system, add the system from its PWSID, then add its sampling
   points, then import lab results and production.
7. Create water accounts and allocations on their pages.
8. Create the water years, then import ledger history with `import_ledger_csv` or
   the Upload CSV page, and diversion records with the diversion import.
9. Connect the live data sources and set up the update schedule, as
   [DEPLOY.md](../DEPLOY.md) describes.
