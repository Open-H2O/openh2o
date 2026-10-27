<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Data Standards & Interoperability

This guide is for anyone who exchanges water data between OpenH2O and another
system. OpenH2O keeps one list of the kinds of measurement it handles, such as
stream discharge or depth to groundwater. Each kind on the list carries an EPA WQX
characteristic name and a UCUM unit, and seven of the eighteen also carry a USGS
parameter code. Each outside data source's own parameter codes are mapped onto the
same list, so a stream flow from USGS and a stream flow from CDEC are recorded as
the same kind of measurement.

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
| `gage_height` | Gage Height | 00065 | Gage height | `[ft_i]` |
| `water_temperature` | Water Temperature | 00010 | Temperature, water | `Cel` |
| `groundwater_level_depth` | Depth to Groundwater | 72019 | Depth to water level below land surface | `[ft_i]` |
| `groundwater_level_elevation` | Groundwater Level Elevation | 72020 | Water level elevation above NAVD 1988 | `[ft_i]` |
| `groundwater_level` | Groundwater Level | 62610 | Groundwater level | `[ft_i]` |
| `reservoir_storage` | Reservoir Storage | none | Reservoir storage | `[acr_us].[ft_i]` |
| `reservoir_elevation` | Reservoir Elevation | none | Reservoir water surface elevation | `[ft_i]` |
| `reservoir_inflow` | Reservoir Inflow | none | Flow, inflow | `[cft_i]/s` |
| `reservoir_outflow` | Reservoir Outflow | none | Flow, outflow | `[cft_i]/s` |
| `evapotranspiration` | Evapotranspiration | none | Evapotranspiration | `mm` |
| `reference_et` | Reference Evapotranspiration | none | Evapotranspiration, reference | `mm` |
| `precipitation` | Precipitation | 00045 | Precipitation | `mm` |
| `air_temperature` | Air Temperature | none | Temperature, air | `Cel` |
| `snowfall` | Snowfall | none | Snow depth | `mm` |
| `solar_radiation` | Solar Radiation | none | Solar radiation | `W/m2` |
| `wind_speed` | Wind Speed | none | Wind velocity | `m/s` |
| `extracted_volume` | Extracted Volume | none | Water withdrawal, volume | `[acr_us].[ft_i]` |

Eleven of the eighteen have no USGS parameter code on OpenH2O's list yet. The UCUM
units were looked up in the published UCUM tables and entered by hand.

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
| California Nevada River Forecast Center (CNRFC) | `streamflow`, `precip` | Forecasts of river flow and precipitation |

DWR is the California Department of Water Resources. OpenET's evapotranspiration
(ET) and GRIDMET's precipitation are not in this table. OpenH2O stores them for each
parcel as inputs to the monthly water balance and does not map them to the list.

The mapping of codes to keys is `CODE_TO_KEY`, a table written by hand in
`seed_observed_properties.py`. When `python manage.py seed_observed_properties`
runs, it reads each source adapter's list of codes and looks up each code in
`CODE_TO_KEY`. The test in `tests/test_standards_registry.py` fails when an adapter
emits a code that `CODE_TO_KEY` does not map. [crosswalk.csv](crosswalk.csv) has one
row for each mapping, with the source, the source's code, and the key's name, USGS
code, WQX characteristic name and UCUM unit.

---

## 3. Quality flags and vertical datum

- **Quality flag.** Each meter reading and sensor measurement carries a quality
  flag of `provisional`, `approved` or `estimated`. A new record is provisional. No
  screen sets the flag yet.
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

The command exits with an error when a kind of measurement has no UCUM unit or a
source code maps to no key, so a script can stop on either gap. It also lists the
kinds of measurement that have no USGS code, and it counts the stored measurements
that are linked to no kind of measurement. Neither of those reports makes the
command exit with an error. Nothing runs the command automatically. Run it by hand
after you change the list or an adapter.

`ObservedProperty.is_publishable()` returns true only for a kind of measurement that
has both a USGS code and a UCUM unit.

---

## 6. California's reporting format (under development)

A feature that writes figures in California's reporting format is under
development and switched off by default. It writes OpenH2O's figures in the file
layouts of GEARS and CalWATRS, two reporting systems run by state agencies. OpenH2O
does not submit reports to the state, and neither system can currently accept a
file that OpenH2O produces.

- **GEARS.** OpenH2O writes two GEARS layouts: monthly metered extraction by well,
  and monthly consumptive use from OpenET. Figures are in acre-feet.
- **CalWATRS.** OpenH2O writes the Direct Use and To Storage layouts for each point
  of diversion, in acre-feet and cubic feet per second. A parcel with both
  groundwater and surface water is marked as combined use. A diversion with no water
  right ID is left out of the file, and the check OpenH2O runs on each report lists
  it as a warning. The Measurement Method column shows the method recorded for the
  diversion. For a diversion measured by a device, the column adds the device's
  type after the method. A record with no method shows "Not stated".

The files are written by `reporting/generators.py`, and the models are in
`reporting/models.py`.

---

## 7. Estimated inputs to the water balance

Two inputs to the monthly water balance are estimates: effective precipitation,
which OpenH2O calculates, and precipitation, which OpenH2O reads from GRIDMET.

- **Effective precipitation.** The monthly water balance subtracts effective
  precipitation from crop ET. The method is set on the Methodology Settings page.
  The choices are all of the month's precipitation, a fixed fraction of it, or the
  USDA-SCS (TR-21) method. The USDA-SCS method never estimates more than the
  month's precipitation or the month's ET as the satellite reads it. The methods are in
  `accounting/precip_math.py`.
- **Precipitation.** OpenH2O reads each parcel's monthly precipitation in
  millimeters from GRIDMET's daily `pr` band, through Google Earth Engine. The
  adapter is `datasync/adapters/gee.py`. The OpenET ensemble dataset that OpenH2O
  reads is built on GRIDMET weather data, so precipitation from GRIDMET comes from
  the same weather data as the ET. The water balance uses GRIDMET precipitation even
  where a rain gauge is nearby.

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
