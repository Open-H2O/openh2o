# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Fetch Merced County assessor parcels and flag the NON-agricultural ones — the
open/un-cultivated land where a recharge basin actually goes (you can't pond
water on a working field).

WHY this exists: a recharge basin is a pond built on open ground beside a canal,
NOT on cropland. The DWR i15 layer only maps farmland, so it can't show basin
sites. This pulls the county's real parcel fabric (all parcels, ag and not),
then derives a non-ag flag by how much of each parcel is covered by the irrigated
crop fields (data/merced/parcel_selection — the 74-field source set). A parcel
mostly NOT covered by crops is open land: a basin candidate.

Output: merced_candidate_parcels.geojson (EPSG:4326) — sizable (>= MIN_ACRES)
non-agricultural parcels in the Merced Subbasin, each with APN / acreage / the
ag-overlap fraction, ready for Brent to pick basins from.

Run with the gis-venv python (geopandas):
  ~/.local/share/gis-venv/bin/python fetch_parcels.py
"""
import json
import sys
import time
import urllib.parse
import urllib.request

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

HERE = "/Users/slate/GitHub/openh2o/data/merced/basin_selection"
PARCEL_SEL = "/Users/slate/GitHub/openh2o/data/merced/parcel_selection"
LAYER = ("https://gis.countyofmerced.com/server/rest/services/"
         "Assessment_Parcels/FeatureServer/42")
BBOX = "-120.97847,37.04449,-120.05146,37.52305"  # Merced Subbasin (EPSG:4326)
OUT_FIELDS = "OBJECTID,APN,NAME,GIS_ACRES"
PAGE = 2000
MIN_ACRES = 10.0       # a recharge basin needs real room; drop residential lots
AG_FRAC_MAX = 0.25     # <= this share covered by crop = "non-agricultural"


def fetch_page(offset):
    params = {
        "where": f"GIS_ACRES >= {MIN_ACRES}",
        "geometry": BBOX, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
        "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS, "returnGeometry": "true",
        "orderByFields": "OBJECTID",  # deterministic order for stable paging
        "resultOffset": str(offset), "resultRecordCount": str(PAGE), "f": "geojson",
    }
    url = LAYER + "/query?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            print(f"  page@{offset} attempt {attempt+1} failed: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"page@{offset} exhausted retries")


def main():
    feats, offset = [], 0
    while True:
        fc = fetch_page(offset)
        page = fc.get("features", [])
        feats.extend(page)
        print(f"  fetched {len(page)} (total {len(feats)})", file=sys.stderr)
        # Page until the service returns nothing; advance by what it actually
        # returned (servers may hand back fewer than PAGE yet still have more).
        if not page:
            break
        offset += len(page)
        if not fc.get("exceededTransferLimit") and len(page) < PAGE:
            break
    rows = [f["properties"] for f in feats if f.get("geometry")]
    geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
    parcels = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    print(f"parcels >= {MIN_ACRES} ac in bbox: {len(parcels)}")

    # Clip to the real subbasin polygon (bbox over-includes corners).
    sub = gpd.read_file(f"{PARCEL_SEL}/merced_subbasin.geojson").to_crs("EPSG:4326")
    parcels = parcels[parcels.geometry.representative_point().within(sub.union_all())]
    print(f"inside subbasin: {len(parcels)}")

    # Derive the ag-overlap fraction: equal-area metres, intersect each parcel
    # with the dissolved crop footprint. Low overlap = open / non-ag. County
    # parcel fabrics carry self-touching rings, so make_valid before any overlay
    # (else GEOS throws a side-location-conflict TopologyException).
    from shapely import make_valid, union_all
    crop = gpd.read_file(f"{PARCEL_SEL}/merced_parcel_picker.gpkg",
                         layer="crop_fields").to_crs(3310)
    crop_union = union_all(make_valid(crop.geometry.values))
    p3310 = parcels.to_crs(3310).reset_index(drop=True)
    p3310["geometry"] = gpd.GeoSeries(make_valid(p3310.geometry.values),
                                      crs=3310)
    areas = p3310.geometry.area
    inter = p3310.geometry.intersection(crop_union).area
    p3310["ag_frac"] = (inter / areas).fillna(0.0).round(3)

    nonag = p3310[p3310["ag_frac"] <= AG_FRAC_MAX].copy().to_crs("EPSG:4326")
    nonag = nonag[["APN", "NAME", "GIS_ACRES", "ag_frac", "geometry"]]
    out = f"{HERE}/merced_candidate_parcels.geojson"
    nonag.to_file(out, driver="GeoJSON")
    print(f"wrote {out}: {len(nonag)} non-agricultural candidate parcels "
          f"(ag_frac <= {AG_FRAC_MAX})")


if __name__ == "__main__":
    main()
