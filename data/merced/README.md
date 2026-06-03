# Merced Demonstration Data

Real spatial canvas for the v1.9 Merced demonstration. Two boundaries drive
the whole milestone's "simple upper vs. complex lower" contrast, and both
come from authoritative public sources so the demo is reproducible.

## The two boundaries

| Boundary | What it is | Area | Character |
|----------|-----------|------|-----------|
| **Merced Subbasin** | DWR Bulletin 118 basin **5-022.04** ("San Joaquin Valley – Merced") | 800.9 sq mi (512,606 ac) | Valley floor. Critically overdrafted, Merced Irrigation District canal network, three GSAs. The **complex** half. |
| **Upper Merced River Watershed** | Surface-water drainage of the Merced River **above Lake McClure** (New Exchequer Dam) | ~1,033 sq mi | Sierra/foothill, snowmelt-driven, single-source. The **simple** half. **Analytical construct — NOT a Bulletin 118 basin.** |

The two regions touch only at the foothill corner where the valley subbasin
meets the mountain watershed — they are deliberately different *kinds* of
region (a groundwater subbasin vs. a surface-water drainage), not a
hierarchy.

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

### `upper_merced_watershed.geojson`

- **Source:** USGS Network-Linked Data Index (NLDI) upstream-basin
  navigation (`api.water.usgs.gov/nldi/linked-data/comid/{comid}/basin`).
- **Delineation:** the NHD flowline at the New Exchequer Dam outlet
  (`POINT(-120.2675 37.5872)`) resolves to **comid 21608661** on the Merced
  River main stem; its upstream basin is the drainage above the dam — i.e.
  the Merced River watershed above Lake McClure.
- **Cross-check:** ~1,033 sq mi, matching the published Merced River
  drainage area above Exchequer (~1,037 sq mi). Roughly HUC8 18040008
  clipped above the reservoir.
- **Label:** this is an **analytical watershed construct**, recorded with a
  blank `basin_code` and a `description` stating it is not a B118 basin.

## Rivers, canals, and stations

The boundaries carry no hydrography of their own. Real flowlines and
monitoring stations are populated by driving the platform's own loaders
against these boundaries (3DHP rivers/canals + Phase-49 station discovery):

```bash
python manage.py seed_merced_base
python manage.py auto_populate --boundary "Merced Subbasin" --steps flowlines,stations
python manage.py auto_populate --boundary "Upper Merced River Watershed" --steps flowlines
```

Merced Irrigation District's fine canal laterals are only partially present
in USGS 3DHP; the main canals and natural rivers are. Full MID GIS would
require a district data request (out of scope for the base layer).

## Usage

```bash
python manage.py seed_merced_base   # idempotent; updates in place on re-run
```

Merced is **additive**: it coexists with the Kaweah and Demo Valley
datasets. Kaweah/Fresno teardown is deliberately Phase 53.
