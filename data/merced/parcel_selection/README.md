# Merced Parcel Picker

A human-in-the-loop replacement for guessing parcel locations. Brent selects
the real fields each diversion serves, on satellite imagery, in QGIS. The
selection is authoritative (real DWR-surveyed field boundaries + Brent's
served-by judgment), so the demo's place-of-use stops landing on towns.

## Why this exists

The platform's geometry has no land-use layer, so coordinate-guessing kept
placing parcels on towns/bare ground. This pulls California's real surveyed
crop fields (DWR i15 Statewide Crop Mapping, 2023 final) and lets Brent pick.

## Workflow

1. **Build the picker** (already done; re-run only to refresh the crop data):
   ```sh
   ~/.local/share/gis-venv/bin/python fetch_crop_fields.py   # -> .gpkg
   sh build_picker_project.sh                                # -> .qgz
   ```
2. **Pick fields** — open `merced_parcel_picker.qgz` in QGIS:
   - The **Crop fields** layer is on top, colored by crop class, semi-transparent
     over satellite. Canals (cyan) and diversion headgates (gold stars) are
     labelled for reference.
   - Toggle editing on the Crop fields layer (pencil icon), click a field, and
     in the form set:
     - **served_by** — which diversion headgate feeds this field
     - **water_source** — surface (canal only) / groundwater (well only) /
       conjunctive (both)
   - Tag every field a diversion serves. Leave the rest blank.
   - **Save** (toggle editing off → Save).
3. **Tell Claude "done"** — Claude extracts the tagged fields to
   `../selected_parcels.geojson` (committed), then on Butler runs:
   ```sh
   python manage.py seed_merced_parcels_from_selection
   ```
   which rebuilds the parcels + POD/right/well links from the real geometry.

## Files

| File | Role | Git |
|------|------|-----|
| `fetch_crop_fields.py` | fetch DWR fields -> build GeoPackage | committed |
| `build_picker_project.py` / `.sh` | assemble the QGIS project | committed |
| `merced_*.geojson` | reference layers exported from the platform DB | committed |
| `merced_parcel_picker.gpkg` / `.qgz` | the picker (regenerable) | ignored |
| `../selected_parcels.geojson` | Brent's saved selection (the source of truth) | committed when made |
