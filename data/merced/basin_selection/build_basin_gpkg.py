# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Assemble the basin-picker GeoPackage from committed reference layers.

Mirrors data/merced/parcel_selection/fetch_crop_fields.py's role (build the
.gpkg the picker edits), but reads everything from committed GeoJSON instead of
fetching DWR — the candidate footprints are the 74 crop fields Brent already
hand-picked, and the hydrography is exported from the live DB by
_export_reference_layers.py.

Output: merced_basin_picker.gpkg with layers
  candidate_basins : the NON-agricultural county parcels (open land where a
                     basin can go), from fetch_parcels.py, + empty editable
                     columns (name, operator, capacity_acre_feet, feeds_via) —
                     Brent tags the parcels that become recharge basins
  agriculture      : the DWR crop fields, shown as a red "avoid" overlay (you
                     can't pond water on a working field)
  canals           : the named canal/lateral network (reference, labelled)
  rivers           : named NHD river flowlines (reference, labelled)
  diversions       : existing surface diversion headgates (reference, gold stars)
  existing_basins  : the v1.9 RechargeSite footprints (reference; wiped + repicked)
  subbasin         : the Merced Subbasin outline (reference)

Run with the gis-venv python (geopandas), AFTER fetch_parcels.py:
  ~/.local/share/gis-venv/bin/python build_basin_gpkg.py
"""
import geopandas as gpd

HERE = "/Users/slate/GitHub/openh2o/data/merced/basin_selection"
PARCEL_SEL = "/Users/slate/GitHub/openh2o/data/merced/parcel_selection"
CANDIDATE_PARCELS = f"{HERE}/merced_candidate_parcels.geojson"
CROP_FIELDS_GPKG = f"{PARCEL_SEL}/merced_parcel_picker.gpkg"
OUT = f"{HERE}/merced_basin_picker.gpkg"

# Context columns worth keeping so Brent can tell parcels apart and judge a
# plausible feed (assessor APN + acreage + how non-ag the parcel is).
KEEP_CONTEXT = ["APN", "GIS_ACRES", "ag_frac"]


def main():
    # --- candidate footprints: non-ag county parcels (open land) ---
    parcels = gpd.read_file(CANDIDATE_PARCELS).to_crs("EPSG:4326")
    cols = [c for c in KEEP_CONTEXT if c in parcels.columns] + ["geometry"]
    cand = parcels[cols].copy()
    # Empty columns Brent fills in for the parcels that become basins.
    #   name        -> basin name (e.g. "Cressey-Winton Recharge Basin")
    #   operator    -> operating district/GSA (optional)
    #   capacity_acre_feet -> design capacity hint (optional)
    #   feeds_via   -> NAME of the canal or river that fills this basin; the
    #                  62-02 seed resolves it to a real Flowline (REQUIRED)
    cand["name"] = ""
    cand["operator"] = ""
    cand["capacity_acre_feet"] = ""
    cand["feeds_via"] = ""
    cand = cand.reset_index(drop=True)
    cand.to_file(OUT, layer="candidate_basins", driver="GPKG")
    print(f"candidate_basins: {len(cand)} parcels")

    # --- agriculture overlay (the "avoid" layer): the DWR crop fields ---
    ag = gpd.read_file(CROP_FIELDS_GPKG, layer="crop_fields").to_crs("EPSG:4326")
    ag = ag[["geometry"]].copy()
    ag.to_file(OUT, layer="agriculture", driver="GPKG")
    print(f"agriculture (avoid): {len(ag)} fields")

    # --- reference layers (read-only context) ---
    refs = {
        "canals": f"{PARCEL_SEL}/merced_canals.geojson",
        "rivers": f"{HERE}/merced_river_flowlines.geojson",
        "diversions": f"{HERE}/merced_diversions.geojson",
        "existing_basins": f"{HERE}/merced_existing_basins.geojson",
        "subbasin": f"{PARCEL_SEL}/merced_subbasin.geojson",
    }
    for layer, path in refs.items():
        g = gpd.read_file(path).to_crs("EPSG:4326")
        g.to_file(OUT, layer=layer, driver="GPKG")
        print(f"{layer}: {len(g)} features")

    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
