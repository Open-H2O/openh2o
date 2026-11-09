<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Importing Your Organization's Data

This guide explains how to load an organization's own records into OpenH2O. The
demonstration data gives you a complete sample site to explore. The Setup
Wizard sets the area your site covers and runs the populate step, which fills in
basins, parcels, streams and monitoring stations from public sources. The file
imports load the records you already have. Records are often kept as *CSV files*. A CSV
file holds a table as plain text. Each row is one line of text with commas between its
columns. Any spreadsheet program opens and saves this format.

Some imports are screens in the browser, and some are commands that you run on the
server. Several are both. On an import screen you upload the file and check a
preview, and OpenH2O saves nothing until you confirm. The Upload CSV page on the Use
Ledger is the one exception: it imports the file at once unless you tick Dry run.

Every import command takes `--dry-run`. With it, the command checks the file and
reports what it would do, and your records stay as they were. Run each command with
`--dry-run` first.

An import that skips rows already on the site does not skip a voided record: importing
it again adds it as a new, active record. A voided use area is the exception: it keeps
its number, so the import skips it.

Commands run inside the `web` container, which cannot see the files on your computer.
Copy the file into the container with `docker compose cp` first, then give the command
the `/tmp/` path that the copy created. Every command example in this guide that reads a
file copies it to `/tmp/` first. A *shapefile* is a map saved as several files that
share one name and differ only in their endings, such as `.shp` and `.dbf`. Copy all of
the files and give the command the path of the `.shp` file. Before you give a shapefile
to `import_boundary` or `import_infrastructure`, zip its files together. An import
screen uploads the file from your browser, so you do not need to copy it.

A zipped shapefile must hold only one shapefile. When a zip holds several, OpenH2O
rejects it and names the first ten and how many more there are; zip the one you want on
its own and try again. OpenH2O reads any projection a `.prj` file states, including the
State Plane and UTM projections that county and state files use. Without a `.prj` file,
it accepts only longitude and latitude.

An AI agent can do the column matching for you. Point the agent at your file and ask
it to import the records. The file might be a county assessor's export, a
spreadsheet or an export from an old system. The agent matches your column names to
the ones OpenH2O reads with the field-name flags on the commands or the column
choices on the import screens, and it checks the result with the dry run or the
preview before anything is saved.

---

## 1. The demonstration data

```bash
docker compose exec web python manage.py load_demonstration    # the demonstration data
docker compose exec web python manage.py remove_demonstration  # take it out again
```

`load_demonstration` loads published records from a real groundwater basin, together
with invented sample data: a complete site to explore while you gather your own
records. It loads only into a site that does not yet hold records of its own, and it
does not need a network connection, because every outside record it uses ships with
OpenH2O. `remove_demonstration` removes it and leaves a clean install, keeping the
site's users and reference lists. On removal, any setting changed while the
demonstration was loaded returns to its default, unless the site had its own settings
before the load. Load the demonstration before you run the Setup Wizard, because the
boundary the wizard saves is one of the site's own records, and remove it before you
import your own records. An administrator can load and remove it from Settings > Setup
Wizard > Demonstration data.

---

## 2. The Setup Wizard

A new site begins at the Setup Wizard (`/setup/`). On a site that does not hold records
of its own and runs the default modules, the wizard first asks how to start: load the
demonstration data, or start with your own records. Choosing to start with your own
records opens the wizard's first step, which offers four choices:

1. Select a boundary already on the site.
2. Upload a boundary file: a zipped shapefile, a KML file or a GeoJSON file. KML is the
   map format Google Earth saves.
3. Type an extent by hand.
4. Start without a boundary.

Everything except the map and the populate step works without a boundary, and you
can add one later. The wizard's second step shows the boundary on a map for you to
confirm. Its third step runs the populate steps described in section 4, one at a
time.

To load a boundary file with a command instead, use `import_boundary`. It reads the same
files as the wizard's upload:

```bash
docker compose cp boundary.geojson web:/tmp/
docker compose exec web python manage.py import_boundary --file /tmp/boundary.geojson --dry-run
docker compose exec web python manage.py import_boundary --file /tmp/boundary.geojson
```

---

## 3. File imports

Seven import screens take a file in two steps: the preview, then Import. OpenH2O keeps
the uploaded file on the server between the preview and Import, so a file can be up to
25 MB with any number of rows. Import runs in a background process, and the screen
shows the result when it finishes. OpenH2O keeps an upload for a day; after that,
upload the file again. OpenH2O deletes the stored file once Import finishes, whether or
not it succeeds.

### Use areas: the Import use areas screen, or `import_parcels`

Import use areas first: ledger entries are filed under a use area, a water account
holds use areas, and a well is linked to the use areas it serves. The Import use areas
button on the Use Areas page opens the screen (`/parcels/import/`). The screen reads a
zipped shapefile, a KML file or a GeoJSON file of up to 25 MB, such as a county parcel
file or a Google Earth file of field outlines. OpenH2O proposes a column for the parcel
number, you can choose one for the owner, and the screen shows the first five values
beside each. The preview counts the new use areas and their acres, and the ones Import
skips: parcel numbers already on file, which it never changes, and outlines outside the
site's boundary. It also counts the features it leaves out: those without a readable
outline or a parcel number, or with a parcel number over 50 characters. A parcel counts
as inside the boundary when a point within its outline lies inside it. Outlines that
share a parcel number become one use area. For a Google Earth file whose outlines carry
only names, choose the Name column: each name becomes the use area's number.

The `import_parcels` command reads the same zip, KML, GeoJSON and JSON files. It also
reads an unzipped shapefile. `import_parcels` differs from the Import use areas screen
in four ways: it imports parcels outside the boundary, it reads the parcel number from
the `APN` column unless you name another column, it stops at an outline it cannot read,
and it links each use area to its headgate from a headgate column:

```bash
docker compose cp parcels.geojson web:/tmp/
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson --dry-run
docker compose exec web python manage.py import_parcels /tmp/parcels.geojson
```

| Field | Default column name | Flag for a different name | Required |
|---|---|---|---|
| Parcel number (APN) | `APN` | `--parcel-number-field` | yes |
| Owner name | `OWNER` | `--owner-field` | no |
| Headgate | `HEADGATE` | `--headgate-field` | no |
| Outline | the feature's geometry | none | yes |

The command joins the outlines that share an APN into one parcel, checks every parcel,
then adds the new ones to the site. A dry run reports the same counts as a real run,
except that only a real run finds a parcel that cannot be saved. The command skips a
parcel whose APN is already on the site. When a feature has no APN, the command skips
that feature, counts it as an error and imports the rest of the file. When a feature's
outline cannot be read, the command names the feature and stops without importing any
of the file's parcels. If any parcel cannot be added, the command stops without adding
any and names the ones it refused.

With a headgate column, `import_parcels` links each use area to its point of diversion.
Each value in the column must be the local name of a point already on the site. A
point's name works too. Import the points of diversion before you run the command with
this column. The command links new use areas and use areas already on the site. It skips
a use area that is already linked to that point. It never changes a share you set.
OpenH2O divides a point's water among its use areas by acreage until you set a share for
each use area on the point's page. If a value is not the name of a point on the site,
the command lists the value. It then stops without importing any use area. The command
ignores a crop column. OpenH2O's figures for a use area are the same whatever crop the
use area grows.

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
| Well name | WELL_NAME | `--name-field` | |
| Latitude | `LATITUDE` | `--lat-field` | |
| Longitude | `LONGITUDE` | `--lon-field` | |
| Well registration ID | `WELL_REG_ID` | `--reg-id-field` | The organization's own number for the well. A row whose registration ID is already on the site is skipped. |
| WCR number | `wcr_number` | none | The number of the well's Well Completion Report from the California Department of Water Resources. It is a separate field from the registration ID, even when a file carries the same value in both. |
| Owner name | `owner_name` | none | |
| Depth (ft) | `depth_ft` | none | |
| Casing diameter (in) | `casing_diameter_in` | none | |
| Capacity (gpm) | `capacity_gpm` | none | |
| Year pumping began | `year_pumping_began` | none | |
| Well type | `well_type` | none | Matched to the name of a well type already on the site, with capital and small letters treated alike. When the file's well type is not one of the site's well types, the command imports the well without a type and reports a warning. |

The command ignores any column that is not in this table and names each one once in
its report. The rest of the file is imported. With `--dry-run`, the command lists
the columns it will read and the columns it will leave out. A row with no latitude
and longitude is skipped.

A well whose name matches a well already on the site is imported as a second well,
and the command names it. Pass `--skip-duplicates` to skip such rows instead.

### Wells, points of diversion, storage ponds and recharge sites: the Import screen

The Import wells button on the Wells page and the Import buttons on the Surface
Diversions and Recharge Sites pages open the same import screen
(`/infrastructure/import/?type=well`, `diversion` or `recharge_site`). Each import
screen links to the others under "Importing something else?", and when the recharge
module is on, that list includes the storage pond import
(`/infrastructure/import/?type=storage`). The screen reads a CSV file, a GeoJSON file,
a zipped shapefile or a KML file of up to 25 MB. A mapping step shows the column
OpenH2O matched to each field, and you can change any match before you import.

The screen recognizes more column names than `import_wells` does. It reads the column
names of the Department of Water Resources' well completion report export, such as
`WCRNUMBER`, `DECIMALLATITUDE`, `DECIMALLONGITUDE` and `TOTALCOMPLETEDDEPTH`. For a
well, it also reads tested yield, casing material, the top and bottom of the well
screen, pump type and measurement method. For a point of diversion, it reads the stream
name, the local name, the maximum rate, the water right (`APPL_ID`) and the parcel the
point serves. For a recharge site, it reads the site type, the capacity in acre-feet
and the operator. Before you upload, the screen lists each column it reads for the type
you chose and marks the required ones: a name, and either latitude and longitude or a
geometry. The mapping step then lists every field for that type. When a file has no
site type column, OpenH2O saves each recharge site row as a spreading basin and each
storage pond row as a storage pond.

Unlike `import_wells`, the screen refuses a row whose name is already on the site or
appears twice in the file. A point of diversion that names a water right needs that
right on the site first, so import the water rights before the points of diversion.

The `import_infrastructure` command reads the same files as the Import screen. It checks
each row by the screen's rules. Give the kind of record after `--type`: `well`,
`diversion`, `storage` or `recharge_site`. To read a value from a column the screen
would not recognize, give `--column`, such as `--column local_name=HEADGATE`. A dry run
lists OpenH2O's name for each value and the column the command reads for it.

```bash
docker compose cp points.csv web:/tmp/
docker compose exec web python manage.py import_infrastructure /tmp/points.csv --type diversion --dry-run
docker compose exec web python manage.py import_infrastructure /tmp/points.csv --type diversion
```

### Water levels: the Import water levels screen

The Import water levels button on the Wells page and in each well's Measurement history
opens the import screen (`/wells/water-levels/import/`). The screen reads a CSV file of
up to 25 MB, such as the groundwater level data the Department of Water Resources (DWR)
publishes from its SGMA Portal, or the organization's own spreadsheet. Each row is one
visit to a well: a depth to water in feet below land surface, or the reason the depth
was not read.

| Column | DWR's column | Required | Notes |
|---|---|---|---|
| Well | WELL_NAME | yes | The well's name, state well number or WCR number, as the site records it, ignoring capital letters and spaces at either end. OpenH2O lists a row as an error unless exactly one well has that name or number. |
| Date | MSMT_DATE | yes | Written as `YYYY-MM-DD` or `M/D/YYYY`, with or without a time. OpenH2O records a date without a time at noon. |
| Depth | GSE_GWE | a depth or a reason | Feet below land surface. |
| Reason | WLM_QA_DESC | a depth or a reason | One of the twelve reasons on the well page, in DWR's wording. On a row that has a depth, OpenH2O copies DWR's quality remark from this column into the notes. |
| Method | WLM_DESC | no | One of the seven methods on the well page, in DWR's wording. OpenH2O copies any other method into the notes. |
| Notes | MSMT_CMT | no | Copied as written. |

The mapping step shows the column OpenH2O matched to each field, and you can change any
match. The preview counts the new levels, the rows already on file and the errors.
OpenH2O skips a row whose well, date and depth or reason are already on the site or
repeat an earlier row of the file. It lists a row dated in a finalized water year as an
error, in the preview and at import, even when the same level is already on the site.
OpenH2O does not convert units, so convert a file in meters, or one that gives
groundwater elevation or depth below the top of the casing, to depth in feet below land
surface before you import it.

### Water rights: the Water Rights Import screen

The Import button on the Water Rights page opens the import screen
(`/surface/rights/import/`). It reads the CSV list of water rights exported from
eWRIMS, the State Water Resources Control Board's water rights system. A file can
be up to 25 MB.

| Column | Required | Notes |
|---|---|---|
| `APPLICATION_NUMBER` | yes | Becomes the right's ID. A right already on the site is skipped and left as it is. |
| `WATER_RIGHT_TYPE` | yes | A type not yet on the site is added under the name the file uses. |
| `PRIMARY_OWNER_NAME` | yes | The holder of the right. |
| `FACE_VALUE_AMOUNT` / `FACE_VALUE_UNITS` | no | OpenH2O records a face value in acre-feet per year. A face value in other units is left out, and the import results list the right under "Imported with a note". |
| `MAX_DD_APPL` / `MAX_DD_UNITS` | no | OpenH2O records a maximum rate in cubic feet per second. A rate in other units is left out, and the import results list the right under "Imported with a note". |
| `PRIORITY_DATE` | no | Written as `YYYY-MM-DD` or `M/D/YYYY`. A blank date stays blank. |
| `LICENSE_ID`, `PERMIT_ID`, `USE_CODE`, `USE_NET_ACREAGE`, `WATERSHED`, `SOURCE_NAME`, `WATER_RIGHT_STATUS` | no | Copied to the right's license number, permit number, purpose of use, net acreage, watershed, source and status, as eWRIMS records them. |
| `DIRECT_SEASON_START_MONTH_1` / `DIRECT_DIV_SEASON_START_DAY_1` / `DIRECT_DIV_SEASON_END_MONTH_1` / `DIRECT_DIV_SEASON_END_DAY_1` | no | The direct diversion season. |
| `STORAGE_SEASON_START_MONTH_1` / `STORAGE_SEASON_START_DAY_1` / `STORAGE_SEASON_END_MONTH_1` / `STORAGE_SEASON_END_DAY_1` | no | The storage season. |

In the state's list, "NA" and "NaN" stand for a blank. OpenH2O imports "NA" and "NaN" as blanks.

The mapping step shows each column OpenH2O matched, and you can change a match. The
preview shows the first rows, and the import reports how many rights it created and
how many it skipped. When the list leaves out a right's season or maximum rate, you
can add it on the right's edit page (`/surface/rights/<id>/edit/`).

The `import_water_rights` command reads the same file as the Water Rights Import screen.
The command creates the same water rights as the screen. To read a value from a column
the screen would not recognize, give `--column`, such as `--column net_acreage=ACRES`.

```bash
docker compose cp rights.csv web:/tmp/
docker compose exec web python manage.py import_water_rights /tmp/rights.csv --dry-run
docker compose exec web python manage.py import_water_rights /tmp/rights.csv
```

### Diversion records: the diversion import screen and `import_diversion_records`

You can import a file of monthly diversion volumes through Import diversion records on
the Surface Diversions page (`/surface/diversion/import/`) or with the
`import_diversion_records` command. The file is a CSV file, and the screen takes up to
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
1,000,000 gallons per MG and 1.9835 acre-feet per cfs-day. The preview names the first
200 rows it converted and counts the rest.

The report-year setting is on the Delivery Settings page, under Reporting year. When a
Water Use Reported file has no `calendar_month` column, OpenH2O uses the setting to
find the calendar year of each month. The report year can be a water year from October
to September, a calendar year, or a season that starts in a month you choose. The Water
year choice always means October to September, even when the site's own water year
starts in another month.

When a file has rows of the type `USE`, the import screen asks how to handle them,
and the mapping step shows how many there are. The choices are:

- leave them out;
- record as water returned the amount by which each `USE` row exceeds its `DIRECT` row
  for the same point and month, up to that `DIRECT` row's volume. OpenH2O rejects a
  `USE` row that has no such `DIRECT` row;
- import them as direct diversions.

OpenH2O keeps your answer and offers it again the next time a file has `USE` rows.
Files from before 2015 can hold `COMBINED` rows. OpenH2O refuses them, because
direct diversion and storage need separate rows.

Rows for the same point, month and type within one file are added together into one
record, because a book of deliveries often lists several deliveries a month at one
headgate. The preview shows how many rows were combined. A record whose point, month
and type are already on the site is skipped and counted. OpenH2O rejects rows for
months in a finalized water year. To change a record in a finalized year, an
administrator uses Correct this record on the record's page.

In the mapping step you also choose the measurement method and the data state for every
record in the file. By default the method is left blank and the data state is
provisional. Choose a different data state when the file holds figures that have
already been published. Before OpenH2O saves anything, the preview shows each error
message with its rows. It also lists the first 200 conversions and combined months and
the first 500 rows without a point, and counts the rest. The import reports the same
counts and assigns each record to the water year that holds its month.

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
| `water_type_code` | no | The code of a water type on the site. A negative entry without a water type counts against a groundwater allocation only when its source type is `meter_reading` or `calculated`, or `et_estimate` on a field with a well. |
| `transaction_date` | no | The date the entry was recorded. |
| `description` | no | Any text. |

A ledger file downloaded from the Use Ledger ends with one more column,
`calculation_method`. On a `calculated` row it gives the methodology and its settings
code, for example `Default Methodology, settings a582bd80c59b`, as the row's "How was
this calculated?" page shows them. On every other row it is blank. The import ignores
the column, so a downloaded file imports back unchanged.

A file downloaded with the As of box set to a past date carries a line naming that
date, and the import rejects it. The import compares a file's rows with today's ledger,
so a row corrected or voided since that date would come back as a new entry. Download
today's file to import.

On the ledger, water taken against the allocation is a negative amount and water added to it is a positive amount. The table below gives the sign for each source type. Manual entries, CSV imports and adjustments keep the sign you give them.

When an amount's sign does not match its source type, OpenH2O reverses the sign and
lists every row it changed. OpenH2O lists an `allocation` or `recharge` row with an
amount of 0 as an error and imports the file's other rows.

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

OpenH2O skips a row that repeats the parcel, date, source type and amount of an entry
already on the site or of an earlier row in the file. OpenH2O rejects entries in a
finalized water year. To change an entry in a finalized year, an administrator corrects
it on the ledger page.

You create each water year on the Water Years page or with `create_water_year`. A water year starts on the first day of a month and ends on the last day of a month. Give each water year a name. OpenH2O files each imported entry under the water year that contains its date. An entry dated outside every water year on the site stays unfiled until someone creates a water year that covers its date. With the command, `--reporting-period` limits the import to one water year: give its name exactly as the Water Years page shows it. OpenH2O lists each row dated outside that year as an error and does not import it. The command reads a comma-separated file unless you pass another character with `--delimiter`.

```bash
docker compose exec web python manage.py create_water_year --name "2024 Water Year" --start 2023-10-01 --end 2024-09-30
```

```bash
docker compose cp ledger.csv web:/tmp/
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year" --dry-run
docker compose exec web python manage.py import_ledger_csv /tmp/ledger.csv \
  --reporting-period "2024 Water Year"
```

### Drinking water: lab sample results

To import a lab results file, use the `import_lab_results` command or the import
screen at `/drinking/import/`. The Import lab results button on the Sample Results page
opens that screen. The file can be a .csv, .tab or .txt file. The screen takes a file of
up to 25 MB. OpenH2O detects the separator in a .txt file.
California's Division of Drinking Water publishes lab results in its Safe Drinking
Water Information System (SDWIS) files. They are tab-separated files in zip archives,
with one file for each span of years, so unzip the archive before you upload. The
SDWIS4 file holds every water system in California, so upload only the rows for the
water systems on your site.

```bash
docker compose cp lab-results.tab web:/tmp/
docker compose exec web python manage.py import_lab_results /tmp/lab-results.tab --dry-run
docker compose exec web python manage.py import_lab_results /tmp/lab-results.tab
```

OpenH2O recognizes the Division of Drinking Water's column headings, such as `PS Code`,
`Sample Date`, `Analyte Code` and `Result`, and several headings that commercial labs
use instead. OpenH2O imports a row when it has a PS Code, a sample date, an Analyte
Name and a result. OpenH2O lists a row with an Analyte Code and no Analyte Name as an
error. OpenH2O skips a row whose result is already on file and a row that repeats an
earlier row of the same file. The preview counts the first as already on file and the
second as repeated in this file. It lists any other row whose sample date falls
in a finalized water year as an error. A row with a blank result is imported as a
non-detect when its "Less than reporting level" column is marked and it gives a
reporting level.

A PS Code is the code of a sampling point. For a California water system, OpenH2O
builds each point's PS Code from the PWSID, the facility ID and the point number. For a
system in another state, enter each point's code exactly as it appears in the lab
results file. OpenH2O lists a row as an error when no sampling point on the site has
its PS Code. OpenH2O does not create a sampling point from a lab file, because a
mistyped code would then add a monitoring location that does not exist. Add the
sampling point first with `add_sampling_point` or with Add sampling points on the Water
Systems page (Drinking water > Water Systems). Then import the file again.

An analyte the site does not have yet is added from the file's Analyte Code and
Analyte Name, and the preview says so. When the file carries MCL and DLR columns,
OpenH2O stores those limits as the file reports them and does not compare a result
with them.

### Drinking water: production by month

You can import a file of a water system's monthly production with the
`import_production` command or the import screen at `/drinking/production/import/`. The
Production page links to that screen. The file is a CSV file, and the screen takes up to
25 MB. OpenH2O tells the first two kinds of file below apart by their column headings.
For any other headings, you choose on the preview what each column holds.

| Layout | Recognized by | How OpenH2O reads it |
|---|---|---|
| California's Electronic Annual Report (eAR) production export | The columns `PWSID`, `Year`, `Month`, `TypeCode` and `Quantity as in Units Reported` | Each row is one month of one type of water. `TypeCode` is one of `GW`, `SW`, `Purchased`, `Sold`, `Recycled`, `NonPotable` and `NonPotableSold`, and any other code is a row error. `Units of Measure As Reported` is `G`, `MG`, `AF`, `CCF` or blank. A blank unit is a row error until you choose a unit for blank rows in the mapping step. When the export repeats a month and type of water, OpenH2O keeps the first row and reports how many it skipped. `PWSID` must match the water system on the site. |
| A monthly log kept on Section 5 of the eAR template | A `Date/Month` column and at least one of the six source columns | `Date/Month` holds the twelve month names. OpenH2O skips any row whose `Date/Month` is not a full month name. The template's `Maximum Day`, `Annual Total` and `Percent Treated` rows are three such rows. Once you enter the report year, the preview names each skipped row. Each source has its own column: "Water Produced from Groundwater (Wells)", "...Surface Water", "Finished Water Purchased...", "Water Sold to Another PWS", "Non-potable..." and "Recycled". The "Total Amount of Potable Water" column is a total on the printed form, and OpenH2O does not read it. The log does not name the system, year or unit, so on the preview you enter the report year and choose one unit for the whole file. Gallons is the default. |
| A monthly log with its own column headings | Any other column headings | On the preview you choose the column that holds the month. For each other column you choose the type of water it holds. The month can be written `2024-01`, `1/2024` or `January 2024`. A column of month names with no year also works. In that case you enter the report year. You choose one unit for the whole file. This kind of log has no default unit. The import takes one column for each type of water. When the log has a column for each well, add the wells together into one column first. |

When a file has a January figure and no other month of that type of water, OpenH2O
marks the January figure as one figure for the whole year. This applies to the eAR
export and to a log on the eAR template.

OpenH2O converts units with the same figures as the other imports: 325,851 gallons
per acre-foot, 1,000,000 gallons per MG and 748.05 gallons per CCF.

When a month and type of water are already on the site as a figure for the whole system,
the import skips that figure. Importing the same file twice saves nothing the second
time. A month entered by hand for one facility does not stop the import from saving the
file's figure for that month and type of water. OpenH2O lists a month in a finalized
water year as an error. To enter one month by hand, use Enter water produced, purchased
or sold on the Production page.

The import screen saves the figures to the site's water system. A site keeps the records
of one water system. The command needs `--pwsid` only when someone has added a second
system some other way, such as through the administration site. For a file in the eAR
layout, `--unit-for-blank` sets the unit for rows with a blank unit. For a monthly log,
`--operator-year` sets the report year and `--operator-unit` sets the unit. For a log
with its own column headings, `--column` names what each column holds. `--operator-unit`
sets the unit for the whole file. In these commands, replace `XX1234567` with your
system's PWSID.

```bash
docker compose cp ear-2024-production.csv web:/tmp/
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv \
  --pwsid XX1234567 --dry-run
docker compose exec web python manage.py import_production /tmp/ear-2024-production.csv --pwsid XX1234567
```

```bash
docker compose cp production-log.csv web:/tmp/
docker compose exec web python manage.py import_production /tmp/production-log.csv \
  --column month=Month --column groundwater="All wells (gallons)" --operator-unit G --dry-run
```

### Drinking water: the sampling schedule

You can import the state's sampling schedule with the `import_schedule` command or the
import screen at `/drinking/schedule/import/`. The Schedule page links to that screen
with **Import the state's schedule**. The import reads the Last and Next Sample Report
from California's Division of Drinking Water. Save the report as a CSV file.

Each row names a sampling point by its PS Code. Add the sampling points before the
import. OpenH2O looks for each row's analyte by its code and then by its name. When no
analyte on the site has the row's code or name, OpenH2O shows the analyte's name under
**What is sampled** on the Schedule page.

`FREQ MONTHS` sets the frequency. OpenH2O saves 1, 3, 12, 36, 72, 108 and 120 months as
Monthly, Quarterly, Annual, Every 3 years, Every 6 years, Every 9 years and Every 10
years. OpenH2O saves any other number as Other. A new schedule row then gives the months
in its notes. The state gives the next due date as a month only. OpenH2O keeps it as a
month.

You can import a newer file over an older one. When a schedule row has the sampling
point and analyte of a row in the file, OpenH2O changes only that schedule row's
frequency, Last done and Next due. The preview lists each change before anything is
saved. A new schedule row gets the file's GROUP and NOTES in its notes. A changed
schedule row keeps its own notes. A schedule row the newer file leaves out stays on the
schedule. With `--dry-run` the command lists the same changes and saves nothing.

```bash
docker compose cp sample-schedule.csv web:/tmp/
docker compose exec web python manage.py import_schedule /tmp/sample-schedule.csv --dry-run
docker compose exec web python manage.py import_schedule /tmp/sample-schedule.csv
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

Setting up a small water system usually starts from its PWSID, the identification number
of a public water system in EPA's records. The `add_water_system` command and the Add a
water system page (`/drinking/onboard/`) look up the PWSID in EPA's Envirofacts records.
The page shows the water system's record and its facilities. When you confirm, the page
saves both. The command saves both as soon as it runs. With `--dry-run`,
`add_water_system` prints the review and leaves the site's water system and facilities
as they were. A site keeps the records of one water system. Once a system is on the
site, OpenH2O refuses any other PWSID and does not save anything. OpenH2O skips a
facility that has no state facility ID. The review and the command list each facility it
skips. When the PWSID is already on the site, the review and the dry run say so. If you
confirm, OpenH2O updates the system and its facilities from EPA's record. OpenH2O keeps
a copy of each record it reads from EPA for 30 days. A lookup within those 30 days reads
the copy and not EPA's service.

Then add the sampling points. The `add_sampling_point` command adds one sampling point
to a facility. You can also add points one at a time on the Sampling points page. The
Add sampling points link on the Water Systems page opens it. For a California water
system, give the facility ID and the point number. OpenH2O builds the PS Code from the
PWSID, the facility ID and the point number. For a system outside California, give the
point's code with `--ps-code` exactly as it appears in the lab results file. In these
commands, replace `XX1234567` with your system's PWSID and `010` with one of its
facility IDs.

```bash
docker compose exec web python manage.py add_water_system XX1234567 --dry-run
docker compose exec web python manage.py add_water_system XX1234567
docker compose exec web python manage.py add_sampling_point --facility 010 --point-number 010 --type source
```

---

## What is entered by hand

These records have no file import and no public source. Each has its own page:

- Water rights, when you do not have the eWRIMS list: `/surface/rights/add/`
- Measuring devices on a point of diversion: from the point's page
- Water accounts: `/accounting/accounts/create/`
- Allocations: `/accounting/allocations/create/`
- Water system facilities that the PWSID lookup did not add: `/drinking/facilities/add/`
- Sampling points: Add sampling points on the Water Systems page (Drinking water > Water Systems) or `add_sampling_point`
- The sampling schedule, when you do not have the state's file: `/drinking/schedule/add/`

Enter a water level, or a visit without a measurement and its reason, on the well's
page under Add a water level. Enter a reading at a station the organization measures
itself, such as a staff gauge, on the station's page under Add a reading. Add the
station first on Add monitoring station (`/datasync/stations/add/`) with the data
source Entered by hand. Readings at a station of a public source, such as CDEC, USGS,
NOAA or DWR, come only from that source, so the station's page has no Add a reading
form.

---

## A sensible order

1. Load the reference lists with `seed_data`. To explore the demonstration first, run
   `load_demonstration`, and run `remove_demonstration` before the next step. Set the
   organization's name with `set_organization` or at `/admin/` under Core > Site
   configs.
2. Open the Setup Wizard (`/setup/`), choose Start with your own records, and choose,
   upload or type a boundary, or start without one. With a boundary, run the wizard's
   populate step to add monitoring stations, and basins, parcels and streams if you need
   them. Without a browser, load the boundary with `import_boundary` and run
   `auto_populate`.
3. Import your use areas on the Import use areas screen, or with `import_parcels`.
   If the file of use areas has a headgate column, run `import_parcels` on that file
   after you import the points of diversion in step 5.
4. Import your wells with `import_wells` or the Wells page's Import screen.
   Then import the wells' water levels on the Import water levels screen.
5. Import your water rights with `import_water_rights` or the Water Rights Import
   screen. You can also add a right by hand on the Water Rights page. Next, import
   points of diversion, storage ponds and recharge sites with `import_infrastructure` or
   the Import screen. A point that names a water right needs that right on the site
   first. Then run `import_parcels` again with the headgate column to link each use area
   to its point.
6. For a drinking-water system, add the system from its PWSID with `add_water_system` or
   on the Add a water system page. Then add its sampling points with
   `add_sampling_point` or with Add sampling points on the Water Systems page. Then
   import lab results with `import_lab_results` or the import screen. Import production
   with the `import_production` command or the import screen at
   `/drinking/production/import/`.
7. Create water accounts and allocations on their pages.
8. Create the water years with `create_water_year` or on the Water Years page. Then
   import ledger history with `import_ledger_csv` or the Upload CSV page. Import
   diversion records with `import_diversion_records` or the diversion import screen.
9. Connect the live data sources and set up the update schedule, as
   [DEPLOY.md](../DEPLOY.md) describes.
