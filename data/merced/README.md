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
| **Size** | 100 kB on disk — roughly 1/75th of `flowlines.json` |
| **Used by** | `scripts/rebuild-golden.sh`, and any offline rebuild |
| **Gate** | `data/demo/expected_shape.json` pins `datasync.MonitoredStation` to 335 at tolerance 0 |

**This file used to say the opposite, and the correction is worth reading.**
Until 2026-08-01 this section recorded that stations were "deliberately NOT
frozen" because nothing later in the `seed_merced` sequence reads
`MonitoredStation`. That test was build-internal — it asked what the *seed*
consumes, not what the *demonstration shows*. The stations are on the map, on
`/datasync/`, named on the about page under "Real published records — USGS and
CDEC", and counted in the landing-page hero. A repository build without them
rendered "0 of 0 stations reporting" where production read "21 of 42".

Records are keyed by the natural pair **(`source` code, `external_station_id`)**,
never by primary key. `DataSource` has no natural-key manager — only
`geography.Boundary` defines one — so a plain `loaddata` fixture would bake
`data_source_id` integers that differ between production and staging and
silently attach stations to the wrong source. `load_station_fixture` resolves
the codes, and refuses before writing anything if one is unknown. It never
creates a `DataSource`: `seed_data_sources` owns that table.

**`last_data_at` is deliberately absent, and the file carries no timestamp,
hostname or git hash.** Re-running the dump against an unchanged database
produces a byte-identical file, so `git diff` is an honest answer to "have the
stations moved?" A frozen reading time would also claim data arrived at a
moment it did not. The visible consequence is intended: straight after a
restore the hero reads "0 of 42 stations reporting" until the hourly
`sync_source` cron runs. **The fixture restores the stations; the ordinary sync
restores the readings** — `sync_source` cannot create a station but does fill
readings into existing ones, which is why `DataRecordStaging` stays unfrozen.

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

## The frozen OpenET cache (`openet_cache.json`)

| | |
|---|---|
| **What** | Every real satellite evapotranspiration draw behind the demonstration's water accounting |
| **Measured** | 380 rows = 76 parcels × 5 variables × 1 window (WY 2024-25, `2024-10-01` → `2025-09-30`) |
| **Variables** | `ET`, `et_mad_max`, `et_mad_min`, `model_count`, `precip` |
| **Size** | 481,352 bytes (470 kB) on disk |
| **Dumped from** | STAGING (`~/openh2o-staging`) on **2026-07-31**, and proven byte-identical to a dump of PRODUCTION taken the same day (sha256 `2b4b6a18…`) |
| **Used by** | `load_openet_fixture`, and therefore `scripts/rebuild-golden.sh` |

Without this file a rebuilt demonstration has two bad options: no ET at all —
and the accounting engine then computes nothing — or spend OpenET quota
re-fetching numbers that have not moved since WY 2024-25 closed. It is the
reason the golden snapshot can become a build output rather than a photocopy of
a live database.

Rows are keyed by **`parcel_number`**, never by primary key, for the same
reason `flowlines.json` uses a natural key: pks differ per deployment.

**`geometry` is deliberately absent.** It is `parcel.geometry` — the same
polygon, already committed in `selected_parcels.geojson` and already loaded by
the seed. Storing it again would add roughly a megabyte of duplicate
coordinates whose only possible future is to disagree with the parcel it claims
to describe. `load_openet_fixture` fills the column from the parcel.

**The file carries no timestamp, hostname or git hash, on purpose.**
Re-running the dump against an unchanged database produces a byte-identical
file, so `git diff` is an honest answer to "has the cache moved?" A
generated-at stamp would make every regeneration look like a change and the
diff would stop meaning anything. Reservation rows (`model_name` =
`__PENDING__`) and ad-hoc `parcel=NULL` geometry queries are excluded — neither
is data. Both deployments held **0** pending rows when this was taken.

Regenerate it (read-only; needs a database that already holds the cache):

```bash
python manage.py dump_openet_fixture          # -> data/merced/openet_cache.json
```

Load it (the parcels must exist first — `seed_merced` creates them; the loader
refuses before writing anything if any `parcel_number` is missing):

```bash
python manage.py load_openet_fixture
```

## Usage

```bash
python manage.py seed_merced_base   # idempotent; updates in place on re-run
```

Merced is **additive**: it coexists with the Demo Valley
dataset. Demo-Valley/Fresno teardown is deliberately Phase 53.
