# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Extract Brent's tagged basins from the picker GeoPackage into the committed
fixture the 62-02 seed reads: data/merced/selected_basins.geojson (EPSG:4326).

A candidate parcel is a chosen recharge basin if it has a non-empty `feeds_via`
(the name of the canal/river that fills it — REQUIRED, the seed resolves it to a
real Flowline). Each kept feature carries:
    name                -> basin name (warned if blank)
    operator            -> operating district/GSA (optional)
    capacity_acre_feet  -> design capacity hint, acre-feet (optional)
    feeds_via           -> canal/river name (REQUIRED)

Run after a QGIS selection session (toggle editing off → Save first):

  ~/.local/share/gis-venv/bin/python extract_selection.py
"""
import geopandas as gpd

HERE = "/Users/slate/GitHub/openh2o/data/merced/basin_selection"
OUT = "/Users/slate/GitHub/openh2o/data/merced/selected_basins.geojson"
KEEP = ["name", "operator", "capacity_acre_feet", "feeds_via",
        "APN", "GIS_ACRES", "geometry"]


def main():
    g = gpd.read_file(f"{HERE}/merced_basin_picker.gpkg", layer="candidate_basins")
    for col in ("name", "operator", "capacity_acre_feet", "feeds_via"):
        if col not in g.columns:
            g[col] = ""
        g[col] = g[col].fillna("")

    tagged = g[g["feeds_via"].astype(str).str.strip() != ""].copy()
    if tagged.empty:
        raise SystemExit(
            "No basins tagged: set feeds_via on each parcel that becomes a "
            "recharge basin, Save in QGIS, then re-run."
        )

    tagged = tagged[[c for c in KEEP if c in tagged.columns]].to_crs("EPSG:4326")
    tagged.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(tagged)} tagged basins")

    blank_name = (tagged["name"].astype(str).str.strip() == "").sum()
    if blank_name:
        print(f"  WARNING: {blank_name} basin(s) have no name — add one in QGIS.")
    print("\nfeeds_via per basin (each must match a real Flowline name):")
    print(tagged[["name", "feeds_via"]].to_string(index=False))


if __name__ == "__main__":
    main()
