# Merced Basin Picker

A human-in-the-loop pick of the Merced demo's recharge basins, on the same
provenance footing as the 74 hand-selected crop fields. The old v1.9 basins are
**wiped and re-picked from a blank slate** — Brent chooses which parcels become
recharge basins, on satellite imagery, in QGIS, and names the canal or river
that fills each one.

## Why this exists

A recharge basin is a pond on **open, un-cultivated ground beside a canal** that
gets flooded to percolate into the aquifer — you can't pond water on a working
field, so basins go on NON-agricultural land. The DWR crop layer only maps
farmland, so it can't show basin sites. This pulls the county's real parcel
fabric, flags the parcels that aren't cropped, and lets Brent pick basins from
those — the same "a human chose this against the real map" provenance as the 74
crop fields. Phase 62-01 also adds the basin→POD schema link the 62-02 seed
hangs the pick on.

## Workflow

1. **Build the picker** (re-run only to refresh from source data):
   ```sh
   ~/.local/share/gis-venv/bin/python fetch_parcels.py      # county parcels -> non-ag candidates
   ~/.local/share/gis-venv/bin/python build_basin_gpkg.py   # -> .gpkg
   sh build_picker_project.sh                               # -> .qgz
   ```
   (`fetch_parcels.py` pulls Merced County assessor parcels and keeps the
   sizable ones NOT covered by crops. The reference hydrography is exported from
   the live DB by `_export_reference_layers.py`, run on Butler — its committed
   output is `merced_river_flowlines.geojson` / `merced_existing_basins.geojson`
   / `merced_diversions.geojson`; re-run only if the DB hydrography changes.)
2. **Pick basins** — open `merced_basin_picker.qgz` in QGIS:
   - The **Open non-ag parcels — CLICK TO TAG** layer (teal) is on top: the
     candidate basin land. **Agriculture** (faint red) is cropland — basins do
     NOT go there. Canals (cyan) and named rivers (blue) are labelled;
     **Diversion headgates** (gold stars) mark where surface water is pulled;
     the **Existing v1.9 basins** (magenta dashes) are reference only.
   - A basin plausibly sits on a teal parcel a labelled canal or river can
     flood — usually near one of the gold headgates or along a named canal.
   - Toggle editing on the Open non-ag parcels layer (pencil icon), click a
     parcel that should become a recharge basin, and in the form set:
     - **name** — the basin name
     - **operator** — operating district/GSA (optional)
     - **capacity_acre_feet** — design capacity hint (optional)
     - **feeds_via** — the NAME of the canal or river that fills it. Read it off
       the labelled canal/river layers; mix canal-fed and river-fed by what the
       map actually shows nearby. This is the field the seed resolves to a real
       `Flowline`, so it must match a real waterway name.
   - Leave the rest blank. A parcel counts as a basin only once `feeds_via` is set.
   - You're not limited to parcels touching a headgate — tag any teal parcel a
     labelled canal or river can plausibly flood.
   - **Save** (toggle editing off → Save).
3. **Tell Claude "picked"** — Claude extracts the tagged basins to
   `../selected_basins.geojson` (committed) and confirms every `feeds_via`
   resolves to a real `Flowline` name, then the 62-02 seed rebuilds the basins
   + basin↔POD links from the real geometry.

## Files

| File | Role | Git |
|------|------|-----|
| `fetch_parcels.py` | pull county parcels -> non-ag basin candidates | committed |
| `build_basin_gpkg.py` | assemble the picker GeoPackage | committed |
| `build_picker_project.py` / `.sh` | assemble the QGIS project | committed |
| `_export_reference_layers.py` | dump river flowlines + basins + headgates from the DB | committed |
| `merced_candidate_parcels.geojson` | non-ag county parcels (the pick canvas) | committed |
| `merced_river_flowlines.geojson` | named NHD rivers (feed options, reference) | committed |
| `merced_diversions.geojson` | existing diversion headgates (reference) | committed |
| `merced_existing_basins.geojson` | v1.9 basins (reference only) | committed |
| `esri_world_imagery.xml` | satellite basemap definition (GDAL TMS) | committed |
| `merced_basin_picker.gpkg` / `.qgz` | the picker (regenerable) | ignored |
| `../selected_basins.geojson` | Brent's saved selection (the source of truth) | committed when made |

Canals, the subbasin outline, and the crop "avoid" overlay are reused in place
from `../parcel_selection/` — not duplicated.
