# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Extract Brent's tagged fields from the picker GeoPackage into the committed
fixture the ingest reads: data/merced/selected_parcels.geojson (EPSG:4326).

A field is "tagged" if it has a served_by (surface delivery) OR a water_source
(so groundwater-only fields, which have no canal, are included). Run after a
QGIS selection session:

  ~/.local/share/gis-venv/bin/python extract_selection.py
"""
import geopandas as gpd

HERE = "/Users/slate/GitHub/openh2o/data/merced/parcel_selection"
OUT = "/Users/slate/GitHub/openh2o/data/merced/selected_parcels.geojson"
KEEP = ["served_by", "water_source", "well_group", "MAIN_CROP", "crop_class",
        "COUNTY", "ACRES", "UniqueID", "geometry"]

g = gpd.read_file(f"{HERE}/merced_parcel_picker.gpkg", layer="crop_fields")
g["served_by"] = g["served_by"].fillna("")
g["water_source"] = g["water_source"].fillna("")
if "well_group" not in g.columns:
    g["well_group"] = ""
g["well_group"] = g["well_group"].fillna("")
tagged = g[(g["served_by"] != "") | (g["water_source"] != "")].copy()
tagged = tagged[[c for c in KEEP if c in tagged.columns]].to_crs("EPSG:4326")
tagged.to_file(OUT, driver="GeoJSON")
print(f"wrote {OUT}: {len(tagged)} tagged fields")
print(tagged.groupby(["served_by", "water_source"]).size().to_string())
