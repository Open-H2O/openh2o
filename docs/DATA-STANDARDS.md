<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Data Standards & Interoperability

This guide is for anyone who exchanges water data between OpenH2O and another
system. OpenH2O keeps one list of the kinds of measurement it handles, such as
stream discharge or depth to groundwater. Each kind of measurement on the list has a
UCUM unit. Of the eighteen, eleven also have an EPA WQX characteristic name and nine
a USGS parameter code. Each outside data source's own parameter codes are mapped
onto the same list, so a stream flow from USGS and a stream flow from CDEC are
recorded as the same kind of measurement.

The mapping is also published in this folder as [crosswalk.csv](crosswalk.csv). To
write the same file from a running site, run
`python manage.py export_crosswalk --output docs/crosswalk.csv`. Run the commands in
this guide inside the `web` container, as
`docker compose exec web python manage.py ...`.

---

## 1. The kinds of measurement (ObservedProperty)

Each kind of measurement on the list is an *observed property*. Each one can carry
three identifiers from outside vocabularies:

- the **USGS parameter code**, the federal code for a kind of water measurement;
- the **EPA WQX characteristic name**, from EPA's Water Quality Exchange;
- the **UCUM unit**, from the Unified Code for Units of Measure
  (`unitsofmeasure.org`). A program can parse a UCUM unit such as `[cft_i]/s`, but
  it cannot parse a written abbreviation such as "cfs".

| Key | Name | USGS code | WQX characteristic | UCUM unit |
|---|---|---|---|---|
| `discharge` | Stream Discharge | 00060 | Stream flow | `[cft_i]/s` |
| `gage_height` | Gage Height | 00065 | Height, gage | `[ft_i]` |
| `water_temperature` | Water Temperature | 00010 | Temperature, water | `Cel` |
| `groundwater_level_depth` | Depth to Groundwater | 72019 | Depth to water level below land surface | `[ft_i]` |
| `groundwater_level_elevation` | Groundwater Level Elevation (NGVD 1929) | 72020 | none | `[ft_i]` |
| `groundwater_level` | Groundwater Level (NGVD 1929) | 62610 | Groundwater level | `[ft_i]` |
| `reservoir_storage` | Reservoir Storage | 00054 | Reservoir storage | `[acr_us].[ft_i]` |
| `reservoir_elevation` | Reservoir Elevation | none | Lake or reservoir elevation | `[ft_i]` |
| `reservoir_inflow` | Reservoir Inflow | none | none | `[cft_i]/s` |
| `reservoir_outflow` | Reservoir Outflow | none | none | `[cft_i]/s` |
| `evapotranspiration` | Evapotranspiration | none | none | `mm` |
| `reference_et` | Reference Evapotranspiration | none | none | `mm` |
| `precipitation` | Precipitation | 00045 | Precipitation | `[in_i]` |
| `air_temperature` | Air Temperature | 00020 | Temperature, air | `Cel` |
| `snowfall` | Snowfall | none | none | `mm` |
| `solar_radiation` | Solar Radiation | none | Solar radiation | `W/m2` |
| `wind_speed` | Wind Speed | none | Wind velocity | `m/s` |
| `extracted_volume` | Extracted Volume | none | none | `[acr_us].[ft_i]` |

Where the WQX column reads none, EPA's WQX list does not name that kind of
measurement. The UCUM units were looked up in the published UCUM tables and entered
by hand.

The list is defined in `standards/management/commands/seed_observed_properties.py`,
and the model is `ObservedProperty` in `standards/models.py`.

---

## 2. Each source's codes (SourceParameter)

Each outside source uses its own codes for what it measures. OpenH2O maps each
source's code to a key on the list and stores the source's own name and unit with
the mapping. USGS code `00060`, CDEC code `20` and CNRFC code `streamflow` all map
to `discharge`, so their figures can be compared and published together.

| Source | Codes mapped | Notes |
|---|---|---|
| USGS National Water Information System (NWIS) | `00060`, `00065`, `00010`, `72019`, `72020`, `62610` | Stream gages and groundwater wells |
| California Data Exchange Center (CDEC) | `15`, `6`, `76`, `23`, `1`, `20`, `2` | Reservoirs, streams and rain. Code `1` (River Stage) maps to `gage_height` and code `20` (Flow) to `discharge`. |
| DWR Water Data Library | `gw_level` | The Periodic Groundwater Level Measurements dataset |
| DWR SGMA Portal | `gw_level` | The same dataset, limited to wells in the SGMA monitoring program |
| California Irrigation Management Information System (CIMIS) | `day-asce-eto`, `day-precip`, `day-sol-rad-avg`, `day-wind-spd-avg`, `day-air-tmp-avg` | Daily reference ET and weather |
| NOAA Global Historical Climatology Network Daily (GHCND) | `PRCP`, `TMAX`, `TMIN`, `SNOW` | Daily climate. `TMAX` and `TMIN` both map to `air_temperature`. |
| Entered by hand | `00060`, `00065`, `00010`, `72019`, `72020`, `62610` | Readings a person types on a station's page, under the USGS codes |
| California Nevada River Forecast Center (CNRFC) | `streamflow`, `precip` | Forecasts of river flow and precipitation |

A USGS reading is also marked as a daily high, low or average. The mapping goes by
code alone, so the daily high, low and average of water temperature all map to
`water_temperature`.

DWR is the California Department of Water Resources. OpenET's evapotranspiration (ET)
and GRIDMET's precipitation are not in this table. OpenH2O stores ET and precipitation
as inputs to the monthly water balance and does not map them to the list. With the
default `OPENET_MODE`, OpenH2O stores ET and precipitation for each OpenET field and
records each use area's monthly crop ET from those fields.

The mapping of codes to keys is `CODE_TO_KEY`, a table written by hand in
`seed_observed_properties.py`. When `python manage.py seed_observed_properties`
runs, it reads each source adapter's list of codes and looks up each code in
`CODE_TO_KEY`. A reading typed at an Entered by hand station (source code `manual`)
uses the USGS codes and maps the same way as a USGS reading. The test in
`tests/test_standards_registry.py` fails when an adapter emits a code that
`CODE_TO_KEY` does not map. [crosswalk.csv](crosswalk.csv) has one row for each
mapping, with the source, the source's code, and the key's name, USGS code, WQX
characteristic name and UCUM unit.

---

## 3. Quality flags and vertical datum

- **Quality flag.** Each meter reading and sensor measurement carries a quality flag
  of `provisional`, `approved` or `estimated`. A new record is provisional. A person
  can mark a reading estimated in a well's meter reading form or through Correct
  this record. No screen sets a record to approved.
- **Vertical datum.** OpenH2O stores each groundwater well's vertical datum as
  `NAVD88` or `NGVD29`.

The quality flags are defined in `measurements/models.py` (`QUALITY_CHOICES`), and
the vertical datum in `wells/models.py`.

## 4. Drinking-water lab limits

When a drinking-water lab results file has `MCL` and `DLR` columns, OpenH2O stores
each row's limits in that row's units. It also stores the file's name and the date
of the import. The screens show the MCL from the lab's file beside each result, and
they do not compare the result with the MCL.

---

## 5. The conformance check

`check_conformance` checks the list and the mapping for gaps:

```bash
python manage.py check_conformance
```

The command exits with an error when a kind of measurement lacks a UCUM unit. It
also lists the kinds that lack a USGS code and counts the stored measurements not
linked to a kind, and neither of those makes it exit with an error. It does not
catch a source code that `CODE_TO_KEY` does not map: `seed_observed_properties`
prints a warning for each such code, and `tests/test_standards_registry.py` fails.
Nothing runs the command automatically. Run it by hand after you change the list or
an adapter.

`ObservedProperty.is_publishable()` returns true only for a kind of measurement that
has both a USGS code and a UCUM unit.

---

## 6. California's reporting format (under development)

A feature that writes figures in California's reporting format is under
development and switched off by default. It writes OpenH2O's figures in the file
layouts of GEARS (Groundwater Extraction Annual Reporting System) and CalWATRS
(California Water Accounting, Tracking, and Reporting System), two reporting
systems run by the State Water Board. OpenH2O does not submit reports to the
state, and neither system can currently accept a file that OpenH2O produces.

- **GEARS.** OpenH2O writes two GEARS files: a by-well file of meter readings, and a
  by-ET file of groundwater extraction estimated from crop ET. The two files have
  the same columns: Well Registration ID, Well Name, Latitude, Longitude, Month,
  Extraction Volume (AF) and Measurement Method. Figures are in acre-feet.

  OpenH2O keeps its figures by use area. A use area is an OpenH2O record that holds
  an Assessor Parcel Number (APN), an owner, an area in acres and an outline on the
  map. Once OpenET has sent a month's crop ET, OpenH2O calculates that month's
  figures for every use area that is not voided. A well's page lists each use area
  linked to the well, each with a share. A share is a number above 0 and up to 1,
  such as 0.2500, and the page's help describes it as "The share of this well's
  water that this use area receives."

  The by-well file has one line for each well and month, with Measurement Method
  "Metered". A well's own meters are the meters linked to it, and each link carries
  an Installed date and a Removed date. A reading counts under a well from the link's
  Installed date up to the day before its Removed date. A blank Installed date counts
  every earlier day, and a blank Removed date counts every later day. To record a
  meter moved from one well to another, set the Removed date on its link to the old
  well and the Installed date on a new link to the new well, both to the day of the
  move. Readings taken before that day count under the old well, and readings from
  that day on count under the new one. Unchecking Is current does not move any
  readings; only the two dates do. OpenH2O keeps readings per meter and adds
  them up per well, and a well's line holds what its own meters read. A meter linked
  to two wells over the same days, as when neither link has dates, has its full
  reading on each well's line. A reading can also be typed on a use area. A reading
  typed on a use area is written once, on the line of the use area's well with the
  largest share. In that month, a well linked to that use area does not write a line
  from its own meters. A reading typed on a use area that is not linked to a well
  goes on a line of its own, whose Well Name begins "[INCOMPLETE] [No well link]".

  Two kinds of reading cover a use area's month: a reading typed on the use area
  that month, and a meter reading that states a volume that month on a well linked
  to the use area. A well's meter reading does not cover the use area when any use
  area linked to that well has a typed reading that month.

  For a use area linked to a well, in a month that a reading does not cover, OpenH2O
  makes a groundwater extraction estimate: the month's ETAW met by groundwater
  divided by the use area's irrigation efficiency. A month calculated before OpenH2O
  began keeping the estimate has been calculated but does not have an estimate. The
  by-ET file counts that month at its ETAW met by groundwater, without dividing by
  irrigation efficiency. An account page's Groundwater budget card counts each month
  by the same rule (the estimate, or the ETAW met by groundwater for an older
  month). The card puts these figures inside one yearly Used figure per account that
  also holds the account's meter readings, so the card cannot be matched to the
  by-ET file line by line.

  OpenH2O keeps these estimates by use area. The by-ET file puts them on wells, as
  the State Water Board's GEARS User Guide (October 2026) requires: "Extraction
  volumes must be reported on a per well basis and can no longer be reported by
  parcel." The by-ET file has one line for each well and month, with Measurement
  Method "Unmetered/Estimated". A use area linked to one well puts its whole
  estimate on that well. A use area linked to more than one well has its estimate
  for the month divided among those wells. The division uses the share numbers from
  the wells' pages as weights among the use area's wells:

  - OpenH2O takes the wells in the order their links to the use area were made.
  - Each well's part is the estimate times that well's share, divided by the sum of
    the use area's shares on all its wells. Because each share is divided by that
    sum, the parts add up to the whole estimate even when the shares do not add up
    to 1.
  - Each well but the last has its part rounded to four decimal places of an
    acre-foot. The last well takes what is left after that rounding.

  A well's figure for a month adds up its parts of the estimates of the use areas
  linked to it. For example, take a use area with an estimate of 10 acre-feet that
  was linked to well A at a share of 0.5 and then to well B at a share of 0.3. Well
  A gets 10 times 0.5 divided by 0.8, which is 6.25 acre-feet. Well B gets the
  remaining 3.75 acre-feet.

  The by-ET file leaves out:

  - a use area that is not linked to any well;
  - a use area's month that a reading covers, because the by-well file reports that
    reading. The use area's water for the month is therefore in one file at most. A
    covered use area linked to one well with a meter reading that month and one well
    without does not put any part of that month on the second well's line;
  - a month not yet calculated: a month OpenET has not yet sent crop ET for, and a
    month whose crop ET OpenH2O has recorded but not yet calculated. A calculated
    month whose estimate is 0 has a figure, 0, and gets a line.

  OpenH2O makes a report for one water year and one file, GEARS or CalWATRS. Before
  it makes the report's file, OpenH2O runs checks, and the report's page lists them.
  Every report's checks include a warning when the water year is not finalized.
  Every GEARS report's checks include a warning when the GEARS Correspondence ID is
  missing. For the by-ET file, the checks also give:

  - the number of lines and the total acre-feet, or an error in their place when the
    by-ET file would not have any lines;
  - the number of use areas not linked to a well that have crop ET in acre-feet for
    a month neither file reports;
  - the months left out because OpenET has not sent them or OpenH2O has not
    calculated them, each with its number of use areas;
  - a warning naming each use area whose area in acres is not recorded and that has
    a calculated month or recorded crop ET in the water year.

  The methodology is the set of calculation steps and choices on Methodology
  Settings. Each month's calculation records the methodology's name and a
  12-character settings code. Neither GEARS file has a column or line that names the
  methodology. When OpenH2O makes a report's file, the report records the
  methodology behind the water year's calculated months. The record covers the
  calculations of every use area in the water year, including use areas the file
  leaves out. When the calculated months used one methodology, the report records
  its name and settings code, and the report's page shows them. When the calculated
  months used more than one methodology, the page says there were more than one.
  When the water year does not have a calculated month, the report records none and
  the page says so. A report made before OpenH2O began recording the methodology
  shows "Not recorded". OpenH2O does not submit reports to the state, so marking a
  report filed does not send anything. The methodology record stays as it was when
  the file was made.

- **CalWATRS.** OpenH2O writes the Direct Use and To Storage layouts for each point
  of diversion, in acre-feet and cubic feet per second. A parcel with both
  groundwater and surface water is marked as combined use. A diversion with no water
  right ID is left out of the file, and the check OpenH2O runs on each report lists
  it as a warning. The Measurement Method column shows the method recorded for the
  diversion. For a diversion measured by a device, the column adds the device's type
  after the method. A record with no method shows "Not stated". For a point of
  diversion that re-diverts another point's water, the file gives the volume in the
  last column, Re-diverted Volume (AF), and 0 in Volume (AF).

The files are written by `reporting/generators.py`, and the models are in
`reporting/models.py`.

---

## 7. Estimated inputs to the water balance

Two inputs to the monthly water balance are estimates: effective precipitation,
which OpenH2O calculates, and precipitation, which OpenH2O reads from GRIDMET.

- **Effective precipitation.** The monthly water balance subtracts effective
  precipitation from crop ET. The method is set on the Methodology Settings page.
  The choices are all of the month's precipitation, a fixed fraction of it, or the
  USDA-SCS (TR-21) method. The USDA-SCS method never estimates more than the month's
  precipitation or the month's satellite ET. The methods are in
  `accounting/precip_math.py`.
- **Precipitation.** OpenH2O reads GRIDMET's monthly precipitation in millimeters. With
  the default `OPENET_MODE`, OpenET sends each OpenET field's precipitation with its
  crop ET. For a use area with no OpenET field on record, `sync_precip_parcels` reads
  its precipitation from GRIDMET through Google Earth Engine. The OpenET ensemble
  dataset is built on GRIDMET weather data, so precipitation from GRIDMET comes from the
  same weather data as the ET. The water balance uses GRIDMET precipitation even where a
  rain gauge is nearby.

---

## 8. Publishing the data

Geoconnex addresses are built. The other three standards in the table are planned.

| Standard | What it is | Where OpenH2O stands |
|---|---|---|
| OGC SensorThings API v1.1 | The Open Geospatial Consortium's standard web interface for sensor data | Planned. A `Datastream` model exists, and OpenH2O stores each well's screen depths and vertical datum. There is no SensorThings interface yet. |
| Frictionless Data Package | A set of data files with a `datapackage.json` file that describes them | Planned |
| WaDE 2.0 | The Western States Water Council's Water Data Exchange format | Planned |
| Geoconnex | Permanent web addresses for water features, listed in a national index | Built, as the next paragraphs describe |

Each record on a site has a permanent address, `/id/<kind>/<number>/`. The kinds are
`boundary`, `zone`, `use-area`, `well`, `point-of-diversion`, `recharge-site`,
`station`, `water-system`, `facility`, `sampling-point` and `water-right`, and the
number is the record's number on the site. A browser that opens the address goes to
the record's page. A program that sends the header `Accept: application/ld+json`, or
adds `?format=jsonld` to the address, receives the record as schema.org JSON-LD in
the form Geoconnex specifies. A record with a location is published as a
`schema:Place`. It carries its outline or point as WKT under `gsp:hasGeometry` and
lists its identifiers from other systems. A water right is published as a
`schema:Thing` with no location. The addresses are built in `core/identifiers.py`.

To list your site's records in Geoconnex, register them with the Internet of Water.
You can file the registration on GitHub, as the steps describe, or through the web
form at register.geoconnex.us, which files the same pull request.

1. On Delivery Settings, set "Where your record addresses are published" to
   `geoconnex.us/<your-namespace>`. Every record's published address then begins
   with geoconnex.us. The site must be reachable from the public internet, because
   Geoconnex reads each record without signing in.
2. Fork the `internetofwater/geoconnex.us` repository on GitHub and add a folder for
   your namespace under `namespaces/`. In that folder, put a `README.md` that names
   your contacts and gives some example identifiers.
3. Add a CSV file of redirects. In each row, `id` is the geoconnex.us address,
   `target` is the site's own `/id/` address for the same record, and `creator` is
   your email address.
4. Open a pull request. The geoconnex.us administrators review it, and the
   addresses go live about 15 minutes after they merge it.

Geoconnex lists only records with a location. Leave water systems, water rights and
any other record with no location out of your redirect file. No site running
OpenH2O is registered yet.

---

## Reusing the design in another platform

If you run another water-data platform, you can copy the design: one list of the
kinds of measurement, a mapping from every source's codes onto that list, and a check
that every kind has a unit and every code has a key. You can start from
[crosswalk.csv](crosswalk.csv) as a vocabulary. The `standards/` folder is a working
example, and you can reuse its code under the AGPL.
