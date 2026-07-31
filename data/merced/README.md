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

**The monitoring stations `auto_populate` also fetches are deliberately NOT
frozen.** Nothing later in the `seed_merced` sequence references
`MonitoredStation`, so an offline run simply has no stations and every
downstream step is unaffected. Freezing a second fixture nothing reads would
be weight with no purpose.

## Usage

```bash
python manage.py seed_merced_base   # idempotent; updates in place on re-run
```

Merced is **additive**: it coexists with the Demo Valley
dataset. Demo-Valley/Fresno teardown is deliberately Phase 53.
