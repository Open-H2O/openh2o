# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Fetch DWR 2023 Statewide Crop Mapping (final) for the Merced Subbasin and
build the parcel-picker GeoPackage.

WHY this exists: parcel placement kept landing on towns/bare ground because
the platform's geometry has no land-use layer. This pulls California's real
surveyed crop fields (DWR i15, 2023 final) — real boundaries, real crop
types — so Brent can SELECT the fields each diversion serves on satellite
imagery instead of Claude guessing coordinates.

Output: merced_parcel_picker.gpkg with layers
  - crop_fields : real DWR fields clipped to the subbasin, irrigated ag only,
                  plus empty `served_by` and `water_source` columns to fill in
  - diversions, canals, subbasin : reference layers (read-only context)

Run with the gis-venv python (geopandas):
  ~/.local/share/gis-venv/bin/python fetch_crop_fields.py
"""
import json
import sys
import time
import urllib.parse
import urllib.request

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

HERE = "/Users/slate/GitHub/openh2o/data/merced/parcel_selection"
LAYER = (
    "https://utility.arcgis.com/usrsvcs/servers/"
    "d94e891e00364e49a2ed9e9e2e27837d/rest/services/Planning/"
    "i15_Crop_Mapping_2023/MapServer/0"
)
# Merced Subbasin bbox (EPSG:4326), from the platform DB.
BBOX = "-120.97847,37.04449,-120.05146,37.52305"
# Attributes worth carrying into the picker (keep payload small).
OUT_FIELDS = "UniqueID,CLASS1,MAIN_CROP,CROPTYP1,IRR_TYP1PA,ACRES,COUNTY"
PAGE = 2000

# DWR CLASS1 codes that are NOT irrigated agriculture — drop these so the
# picker shows only plausible served fields. U=urban, NV/NW/NR/NS/NB=native,
# E=entryway/other, Z/X=unclassified, S=semi-ag, I handled via crop name.
NON_AG = {"U", "NV", "NW", "NR", "NS", "NB", "E", "Z", "X", "S", "NC", "W"}


def fetch_page(offset):
    params = {
        "where": "1=1",
        "geometry": BBOX,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE),
        "f": "geojson",
    }
    url = LAYER + "/query?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            print(f"  page@{offset} attempt {attempt+1} failed: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"page@{offset} exhausted retries")


def main():
    feats = []
    offset = 0
    while True:
        fc = fetch_page(offset)
        page = fc.get("features", [])
        feats.extend(page)
        print(f"  fetched {len(page)} (total {len(feats)})", file=sys.stderr)
        if len(page) < PAGE:
            break
        offset += PAGE
    print(f"raw fields fetched: {len(feats)}")

    rows = []
    geoms = []
    for f in feats:
        if not f.get("geometry"):
            continue
        rows.append(f["properties"])
        geoms.append(shape(f["geometry"]))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")

    # Clip to the real subbasin polygon (bbox over-includes the corners).
    sub = gpd.read_file(f"{HERE}/merced_subbasin.geojson").to_crs("EPSG:4326")
    gdf = gpd.clip(gdf, sub.union_all())
    print(f"after subbasin clip: {len(gdf)}")

    # Keep irrigated agriculture only.
    gdf = gdf[~gdf["CLASS1"].isin(NON_AG)].copy()
    # Drop slivers from the clip (tiny edge fragments).
    gdf = gdf[gdf.to_crs(3310).area > 4000].copy()  # > ~1 acre
    print(f"irrigated-ag fields for picker: {len(gdf)}")

    # Readable crop category from the DWR CLASS1 letter code, so the picker
    # labels read "Deciduous fruits & nuts" not "D". Satellite + this is
    # plenty to tell an orchard from a row crop.
    CLASS_NAMES = {
        "G": "Grain & hay", "R": "Rice", "F": "Field crops",
        "P": "Pasture", "T": "Truck/nursery/berry",
        "D": "Deciduous fruits & nuts", "C": "Citrus & subtropical",
        "V": "Vineyard", "I": "Idle", "X": "Fallow/unclassified",
    }
    gdf["crop_class"] = gdf["CLASS1"].map(CLASS_NAMES).fillna(gdf["CLASS1"])

    # Columns Brent fills in. served_by = which diversion feeds this field;
    # water_source = surface (canal only) / groundwater (well only) /
    # conjunctive (both) — this is the within-valley simple-vs-complex story.
    gdf["served_by"] = ""
    gdf["water_source"] = ""
    gdf = gdf.reset_index(drop=True)

    out = f"{HERE}/merced_parcel_picker.gpkg"
    gdf.to_file(out, layer="crop_fields", driver="GPKG")
    for name in ("diversions", "canals", "subbasin"):
        src = {"diversions": "merced_diversions", "canals": "merced_canals",
               "subbasin": "merced_subbasin"}[name]
        gpd.read_file(f"{HERE}/{src}.geojson").to_file(out, layer=name, driver="GPKG")
    print(f"wrote {out}")
    # Quick crop-mix summary so we can sanity-check realism.
    print("\ntop crops in picker:")
    print(gdf["MAIN_CROP"].value_counts().head(12).to_string())


if __name__ == "__main__":
    main()
