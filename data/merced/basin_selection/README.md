# Merced Basin Picker

A human-in-the-loop pick of the Merced demo's recharge basins, on the same
provenance footing as the 74 hand-selected crop fields. The old v1.9 basins are
**wiped and re-picked from a blank slate** — Brent chooses which parcels become
recharge basins, on satellite imagery, in QGIS, and names the canal or river
that fills each one.

## Why this exists

A recharge basin's credibility rests on "a human chose this against the real
map," not an algorithm. There was also no data link between a basin and the
point of diversion (POD) that fills it — Phase 62-01 adds that schema link, and
this picker captures the human judgment the 62-02 seed hangs on it.

## Workflow

1. **Build the picker** (re-run only to refresh from the DB):
   ```sh
   ~/.local/share/gis-venv/bin/python build_basin_gpkg.py   # -> .gpkg
   sh build_picker_project.sh                               # -> .qgz
   ```
   (The reference hydrography is exported from the live DB by
   `_export_reference_layers.py`, run on Butler — see that file's header. The
   committed `merced_river_flowlines.geojson` / `merced_existing_basins.geojson`
   are its output; you only re-run it if the DB hydrography changes.)
2. **Pick basins** — open `merced_basin_picker.qgz` in QGIS:
   - The **Candidate basins** layer (the 74 crop-field footprints) is on top,
     semi-transparent over satellite. Canals (cyan) and named rivers (blue) are
     labelled; **Diversion headgates** (gold stars) mark where each surface
     right pulls water off its waterway; the **Existing v1.9 basins** show as
     magenta dashed outlines for reference only (they're being replaced).
   - A basin plausibly sits on a flat parcel a labelled canal or river can
     flood — usually near one of the gold headgates or along a named canal.
   - Toggle editing on the Candidate basins layer (pencil icon), click a parcel
     that should become a recharge basin, and in the form set:
     - **name** — the basin name
     - **operator** — operating district/GSA (optional)
     - **capacity_acre_feet** — design capacity hint (optional)
     - **feeds_via** — the NAME of the canal or river that fills it. Read it off
       the labelled canal/river layers; mix canal-fed and river-fed by what the
       map actually shows nearby. This is the field the seed resolves to a real
       `Flowline`, so it must match a real waterway name.
   - Leave the rest blank. A parcel counts as a basin only once `feeds_via` is set.
   - **Save** (toggle editing off → Save).
3. **Tell Claude "picked"** — Claude extracts the tagged basins to
   `../selected_basins.geojson` (committed) and confirms every `feeds_via`
   resolves to a real `Flowline` name, then the 62-02 seed rebuilds the basins
   + basin↔POD links from the real geometry.

## Files

| File | Role | Git |
|------|------|-----|
| `build_basin_gpkg.py` | assemble the picker GeoPackage from committed layers | committed |
| `build_picker_project.py` / `.sh` | assemble the QGIS project | committed |
| `_export_reference_layers.py` | dump river flowlines + existing basins from the DB | committed |
| `merced_river_flowlines.geojson` | named NHD rivers (feed options, reference) | committed |
| `merced_diversions.geojson` | existing diversion headgates (reference) | committed |
| `merced_existing_basins.geojson` | v1.9 basins (reference only) | committed |
| `esri_world_imagery.xml` | satellite basemap definition (GDAL TMS) | committed |
| `merced_basin_picker.gpkg` / `.qgz` | the picker (regenerable) | ignored |
| `../selected_basins.geojson` | Brent's saved selection (the source of truth) | committed when made |

Canals, the subbasin outline, and the candidate footprints are reused in place
from `../parcel_selection/` and `../selected_parcels.geojson` — not duplicated.
