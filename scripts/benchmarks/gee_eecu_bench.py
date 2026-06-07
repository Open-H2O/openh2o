#!/usr/bin/env python
"""Measure real Earth Engine EECU consumption for OpenET parcel ET reduction.

Replicates the exact operation openh2o's GEE tier performs (polygon
reduceRegions(mean) over the OpenET Ensemble monthly collection), runs it as a
BATCH EXPORT task, and reads the authoritative `batch_eecu_usage_seconds` the
task reports on completion. That is the only trustworthy EECU number EE exposes.

This is the benchmark behind the cost numbers in
docs/earth-engine-tier-setup.md. Re-run it if Google changes EE pricing.

Measured (Merced County crop parcels, OpenET ensemble monthly ET, 30 m, 2023,
batch export):

    parcels   images  path        EECU-sec/yr
    76        12      filtered     9.05
    760       12      filtered    35.34
    3,800     12      filtered   158.22
    7,600     12      filtered   346.36
    76        384     unfiltered  20.65   (production path; filterBounds cuts 2.3x)

Per-parcel annual model (fixed per-field cost + area cost):

    EECU-seconds/year  ~=  parcels * (0.022 + 0.00035 * average_acres)
    EECU-hours/year    =   that / 3600
    cost/year ($)      =   EECU-hours/year * 0.40

A 50,000-parcel district at ~70-acre fields => ~0.63 EECU-hours/yr => ~$0.25/yr.

Usage: gee_eecu_bench.py <label> <n_replicas> <filterbounds:0|1> [year]
  GEOM_MODE=real|tiny|big controls field size (isolates the area component).
"""
import json, os, sys, time
import ee

PROJECT = os.environ.get("GEE_PROJECT", "gis-pipeline-495516")
EE_COLLECTION = "projects/openet/assets/ensemble/conus/gridmet/monthly/v2_1"
EE_BAND = "et_ensemble_mad"
EE_SCALE = 30
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEOJSONS = [
    os.path.join(_REPO, "data", "merced", "selected_parcels.geojson"),
    os.path.join(_REPO, "data", "merced", "selected_river_ag_parcels.geojson"),
]

def load_base_features():
    feats = []
    for path in GEOJSONS:
        d = json.load(open(path))
        for i, f in enumerate(d.get("features", [])):
            acres = float(f["properties"].get("ACRES") or 0)
            feats.append((f["geometry"], acres))
    return feats

def build_fc(base, n_replicas):
    """Replicate the real parcels n_replicas times (overlapping copies are fine:
    reduceRegions costs scale with feature COUNT regardless of overlap).

    GEOM_MODE env: 'real' (default, true polygons), 'tiny' (centroid buffered to
    ~1 pixel — isolates per-feature overhead), 'big' (polygon buffered +200m —
    amplifies the area/pixel component)."""
    import os
    mode = os.environ.get("GEOM_MODE", "real")
    out = []
    pid = 0
    for r in range(n_replicas):
        for geom, acres in base:
            g = ee.Geometry(geom)
            if mode == "tiny":
                g = g.centroid(maxError=1).buffer(20)
            elif mode == "big":
                g = g.buffer(200)
            out.append(ee.Feature(g, {"pid": pid}))
            pid += 1
    return ee.FeatureCollection(out), pid

def main():
    label = sys.argv[1]
    n_replicas = int(sys.argv[2])
    use_bounds = sys.argv[3] == "1"
    year = int(sys.argv[4]) if len(sys.argv) > 4 else 2023

    ee.Initialize(project=PROJECT)
    base = load_base_features()
    fc, n_parcels = build_fc(base, n_replicas)
    total_acres = sum(a for _, a in base) * n_replicas

    ic = (ee.ImageCollection(EE_COLLECTION)
          .filterDate(f"{year}-01-01", f"{year+1}-01-01")
          .select(EE_BAND))
    if use_bounds:
        ic = ic.filterBounds(fc.geometry())
    n_images = ic.size().getInfo()

    # Map the SAME reduceRegions(mean) the production adapter runs, over every
    # monthly image, then flatten to one table. Slim each output feature to just
    # the mean so the export table stays small.
    def reduce_one(img):
        red = img.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=EE_SCALE)
        return red.map(lambda ft: ee.Feature(None, {"mean": ft.get("mean")}))
    reduced = ic.map(reduce_one).flatten()

    task = ee.batch.Export.table.toDrive(
        collection=reduced, description=f"eecu_bench_{label}",
        folder="eecu_bench", fileFormat="CSV")
    task.start()
    tid = task.id
    print(f"[{label}] parcels={n_parcels} acres={total_acres:.0f} images={n_images} "
          f"filterBounds={use_bounds} task={tid}", flush=True)

    # poll
    t0 = time.time()
    while True:
        st = ee.data.getTaskStatus(tid)[0]
        state = st["state"]
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(15)
    wall = time.time() - t0

    eecu_s = st.get("batch_eecu_usage_seconds")
    print(json.dumps({
        "label": label, "state": state, "parcels": n_parcels,
        "acres": round(total_acres), "images": n_images, "filterBounds": use_bounds,
        "wall_s": round(wall), "batch_eecu_usage_seconds": eecu_s,
        "eecu_hours": (eecu_s/3600.0) if eecu_s else None,
        "error": st.get("error_message"),
    }), flush=True)

if __name__ == "__main__":
    main()
