# Merced Demonstration Data

Real spatial canvas for the v1.9 Merced demonstration. One boundary — the
Merced Subbasin valley floor — drives the milestone, from an authoritative
public source so the demo is reproducible.

## The boundary

| Boundary | What it is | Area | Character |
|----------|-----------|------|-----------|
| **Merced Subbasin** | DWR Bulletin 118 basin **5-022.04** ("San Joaquin Valley – Merced") | 800.9 sq mi (512,606 ac) | Valley floor. Critically overdrafted, Merced Irrigation District canal network, three GSAs. |

> **Upper Merced River watershed: removed.** An earlier cut of this demo
> paired the valley with the Merced River drainage above Lake McClure as a
> "simple upper vs. complex lower" contrast. It was dropped: the only
> free-flowing reaches up there sit high in the Sierra (the foothill stretch
> is Lake McClure reservoir), so a district-scale diversion placed on them is
> geographically honest but operationally implausible. The simple-vs-complex
> contrast now lives entirely *within* the valley floor (single-source canal
> districts vs. conjunctive surface-plus-groundwater growers). Do not re-add it.

## Data sources and provenance

### `lower_merced_subbasin.geojson`

- **Source:** DWR Bulletin 118 California Groundwater Basins, B118
  FeatureServer (`gis.water.ca.gov/.../i08_B118_CA_GroundwaterBasins`,
  layer 0), filtered to `Basin_Subbasin_Number = '5-022.04'`, reprojected
  to EPSG:4326. This is the same FeatureServer the platform's own
  `auto_populate --steps basins` loader queries.
- **Geometry:** full-resolution MultiPolygon (8,446 vertices) — kept
  un-simplified because spatial realism against satellite imagery is the
  point of this phase.
- **Area note:** the authoritative B118 statutory area is **800.9 sq mi /
  512,606 acres**. The Merced Subbasin GSP cites a smaller ~767 sq mi /
  ~491,000-acre *managed* area; the difference is GSP plan area vs. the
  B118 basin outline, not an error.

## Rivers, canals, and stations

The boundary carries no hydrography of its own. Real flowlines and
monitoring stations are populated by driving the platform's own loaders
against it (3DHP rivers/canals + Phase-49 station discovery):

```bash
python manage.py seed_merced_base
python manage.py auto_populate --boundary "Merced Subbasin" --steps flowlines,stations
```

Merced Irrigation District's fine canal laterals are only partially present
in USGS 3DHP; the main canals and natural rivers are. Full MID GIS would
require a district data request (out of scope for the base layer).

### `flowlines.json` — the frozen flowlines, and why they are frozen

**Do not delete this as stale cached data.** It is deliberately frozen, and
the reason is the whole point of the file.

`auto_populate` is the only networked step in the entire `seed_merced`
sequence — every other step reads committed files in this directory. Leaving
it live meant CI could not seed the demonstration without calling USGS 3DHP
and DWR ArcGIS on every push. Flowlines are static geography: rivers and the
MID canal network change on a five-to-ten-year timescale, so fetching them
live on every build buys nothing and costs a permanent dependency on two
external map services. A gate that goes red because USGS had a bad afternoon
is a gate people learn to ignore, and this file exists so that never happens.

| | |
|---|---|
| **Frozen** | 2026-07-31, from the OpenH2O staging database |
| **Rows** | 5,658 flowlines, all in the Merced Subbasin |
| **Feature types** | Canal 2,365 · Channel Line 2,028 · Waterbody Connector 1,187 · Surface Connector 41 · Hydro Unenforced Connector 37 |
| **Size** | 7.2 MB on disk (~2.2 MB of repository weight after git compresses it) |
| **Used by** | `.github/workflows/clean-install.yml` job `demo-identity-guard`, and any offline rebuild |

The boundary is referenced by **natural key** (`["Merced Subbasin"]`), not by
primary key. That is load-bearing: the Merced Subbasin is pk 1 on staging and
pk 6 on production, so a pk-keyed fixture would attach all 5,658 rows to
whatever boundary happened to occupy that number, silently and differently on
every instance. `geography.BoundaryManager.get_by_natural_key` is what
resolves it back.

Regenerate it (needs network, and a database that has already run
`auto_populate`):

```bash
python manage.py seed_merced_base
python manage.py auto_populate --boundary "Merced Subbasin" --steps flowlines,stations
python manage.py dumpdata geography.Flowline --indent 2 --natural-foreign \
  > data/merced/flowlines.json
```

Load it (the boundary must exist first — `seed_merced_base` creates it):

```bash
python manage.py loaddata data/merced/flowlines.json
```

### `stations.json` — the frozen monitoring stations

The monitoring stations `auto_populate` fetches are frozen here for the same
reason the flowlines are, and by the same argument: a station catalogue is a
published registry that moves on a multi-year timescale, and a build that has
to reach CDEC, USGS, DWR, NOAA and CIMIS to produce a demonstration is a build
that fails whenever one of them has a bad afternoon.

| | |
|---|---|
| **Frozen** | 2026-08-01, read-only from the OpenH2O **production** database |
| **Rows** | 335 stations — **42 active**, 293 inactive |
| **Per source** | `dwr_wdl` 100 (2 active) · `dwr_sgma` 95 (17) · `cdec` 55 (15) · `usgs` 54 (5) · `noaa` 16 (3) · `cimis` 15 (0) |
| **Size** | 106 kB on disk — roughly 1/68th of `flowlines.json` |
| **Used by** | `scripts/rebuild-golden.sh`, and any offline rebuild |
| **Gate** | `data/demo/expected_shape.json` pins `datasync.MonitoredStation` to 335 at tolerance 0 |

**This file used to say the opposite, and the correction is worth reading.**
Until 2026-08-01 this section recorded that stations were "deliberately NOT
frozen" because nothing later in the `seed_merced` sequence reads
`MonitoredStation`. That test was build-internal — it asked what the *seed*
consumes, not what the *demonstration shows*. The stations are on the map, on
`/datasync/`, named on the about page under "Real published records — USGS and
CDEC", and counted in the landing-page hero. A repository build without them
rendered "0 of 0 stations reporting" where production reads **"37 of 42"**
(re-derived from production 2026-08-01 — an earlier "21 of 42" figure
was never re-derived and is wrong).

Records are keyed by the natural pair **(`source` code, `external_station_id`)**,
never by primary key. `DataSource` has no natural-key manager — only
`geography.Boundary` defines one — so a plain `loaddata` fixture would bake
`data_source_id` integers that differ between production and staging and
silently attach stations to the wrong source. `load_station_fixture` resolves
the codes, and refuses before writing anything if one is unknown. It never
creates a `DataSource`: `seed_data_sources` owns that table.

**The file carries no generated-at timestamp, hostname or git hash.** Re-running
the dump against an unchanged database produces a byte-identical file, so
`git diff` is an honest answer to "have the stations moved?"

### `last_data_at` is stored — and the first cut of this got it wrong

Each active station carries the time its source last published, as an ISO-8601
UTC string. All 42 do:

| Source | Active | Newest published reading |
|---|---|---|
| `cdec` | 15 | 2026-08-01 |
| `dwr_sgma` | 17 | **2026-03-23** |
| `usgs` | 5 | 2026-08-01 |
| `noaa` | 3 | 2026-07-27 |
| `dwr_wdl` | 2 | 2025-03-07 |

**The first version of this fixture threw those away**, arguing that a frozen
reading time would claim data arrived when it did not, and that the hourly sync
would refill it. Both halves were measured wrong on 2026-08-01:

- **They are not fabrications.** DWR SGMA genuinely published on 23 March. That
  is a real fact about a real published record — the same kind of fact as the
  station's name and coordinates, which this file freezes without hesitation.
  The honesty principle was aimed at invented data; this is not invented.
- **The sync could not refill them.** `sync_source` used a flat 7-day window
  while SGMA and WDL publish roughly quarterly, so both fetched **zero** rows
  for their 19 stations. Dropping the field would have taken production's
  landing page from "37 of 42" to "20 of 42" permanently, with the nightly 03:15
  restore re-applying it every night.

The 17 SGMA stations are the reason this matters. Four-month-old readings count
as **fresh** for them, because `freshness.py` records their expected cadence as
120 days. Without a stored `last_data_at` they read as dormant forever.

Both halves were fixed together: `sync_source.default_window_days` now sizes the
pull window from each source's own cadence (SGMA and WDL go from 7 days to 240),
so the data can be re-fetched — and the frozen timestamp means the demonstration
is coherent the moment it is restored rather than a day later.

**Readings themselves are still not frozen**, and `DataRecordStaging` stays
pinned at 0 in the shape gate: `sync_source` cannot create a station but does
fill readings into existing ones. **The fixture restores the stations and their
last-known publication times; the ordinary sync brings the readings forward.**
Observed on first run into fixture-restored stations: CDEC published 13,173
readings, USGS 47, NOAA 9.

These are real public USGS/CDEC/DWR/NOAA/CIMIS stations, which is consistent
rather than a leak: the identity policy treats station names as **protected**,
not banned, exactly as it does the river network beside them.

Regenerate it (read-only; needs a database that already holds the stations):

```bash
python manage.py dump_station_fixture         # -> data/merced/stations.json
```

Load it (the data sources must exist first — `seed_data` creates them):

```bash
python manage.py load_station_fixture
```

## OpenET's field list (`openet_fields.json`)

| | |
|---|---|
| **What** | The OpenET fields that overlap the demonstration's 76 use areas: each field's number, acres and outline, each use area's acres inside each field, and each field's monthly crop ET and rain as OpenET's field list sent them |
| **Measured** | 78 fields, 84 overlaps, 1,872 field-months (78 fields × 24 months, October 2024 to September 2026) |
| **Figures** | Crop ET is OpenET's ensemble; rain is gridMET's, as OpenET's field list sends it. Both in millimetres, exactly as sent |
| **Source** | OpenET (https://etdata.org): the outlines, crop ET and rain are OpenET's data |
| **Received** | 2026-11-14 (Pacific), from OpenET's field list (https://etdata.org) |
| **Used by** | `load_openet_fields_fixture`, and therefore `scripts/rebuild-golden.sh` |

OpenH2O asked OpenET's field list for these figures on 2026-11-14 in nine requests.
Seven asked which OpenET fields lie in the seven rectangles that hold the use areas.
One asked for the 187 fields' outlines. One asked for the monthly crop ET and rain of
the 78 fields that overlap a use area.

**Each use area keeps its own outline.** Its crop use for a month is each overlapping
field's crop ET over that field's acres inside the use area, added up. Rain is
figured field by field the same way. Land inside a use area that lies in no OpenET
field counts no crop use and no rain. In this file, 69 use areas overlap one field,
6 overlap two and one overlaps three.

**Every field has crop ET and rain for all 24 months.** Nothing is filled in here.
OpenET may revise a month for about 120 days after it ends; the figures here are the
ones it had on the received day.

**Each field's outline is OpenET's, as its field list sent it** (GeoJSON, longitude
and latitude to six decimals). OpenET's terms ask that OpenET be named as the source
"in all instances" its data is shown or shared: anything that shows or passes on
these outlines names OpenET (https://etdata.org) as the source. The demonstration's
map draws them as a layer that is off until a person turns it on, with OpenET named
on the map while it shows. Each field's acres, and its acres inside each use area,
were measured from these outlines in California Albers (EPSG 3310) after any crossed
edge was repaired. The loader stores each outline as the field's geometry and keeps
the overlaps as this file states them; it does not work them out again.

Rows are keyed by `parcel_number` and OpenET's `field_id`, never by primary key,
because primary keys differ between sites.

**The file carries no time of its own: no generated-at stamp, host name or git hash.**
The received day belongs to the data. The loader refuses a field or month without a
received day, a month received before it ended, and a use area this database does
not have, and writes nothing.

Load it (the use areas must exist first; `seed_merced` creates them):

```bash
python manage.py load_openet_fields_fixture
```

Until 2026-11-14 the demonstration's crop ET and rain came from Earth Engine, in
`openet_cache.json`; git history keeps that file.

## Usage

```bash
python manage.py seed_merced_base   # idempotent; updates in place on re-run
```

This command loads the boundary only; it is the third step of
`load_demonstration`, which loads the whole demonstration. `remove_demonstration`
takes the demonstration off a site again.
