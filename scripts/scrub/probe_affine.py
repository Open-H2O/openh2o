#!/usr/bin/env python3
"""Read-only feasibility probe for relocating the Merced demonstration geometry.

Phase 97 asks whether the demonstration's geography can be moved off Merced by a
rigid affine transform (translation, optionally plus rotation) without breaking
the demo's internal consistency or its test suite. This script answers that with
measurements instead of reasoning.

It NEVER writes to ``data/``. Every transform is applied to an in-memory copy.

Usage::

    python3 scripts/scrub/probe_affine.py            # offline, uses cached geocodes
    python3 scripts/scrub/probe_affine.py --online   # refresh landing lookups

Method notes
------------
* Areas are measured with ``pyproj.Geod`` — true geodesic area on the WGS84
  ellipsoid. There is deliberately NO reproject-to-metric-CRS-and-back round
  trip: the point of this probe is to measure drift, not to add it.
* Containment and topology are exact predicates on the translated coordinates,
  so a uniform translation is expected to preserve them by construction. The
  probe measures them anyway, because the real failure mode is geometry that
  does NOT move with the rest — hardcoded coordinates in seed commands and test
  fixtures. Those are reported separately under "Suite exposure".
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "merced"
CACHE = Path(__file__).resolve().parent / "geocode-cache.json"
GEOD = Geod(ellps="WGS84")
SQM_PER_ACRE = 4046.8564224

# ---------------------------------------------------------------------------
# Candidate destinations
# ---------------------------------------------------------------------------
# Each is a pure lat/long translation of the whole geography as one piece,
# expressed as the offset applied to every coordinate. The Merced Subbasin
# centroid sits at roughly (-120.52, 37.28).
CANDIDATES = [
    {
        "id": "central-valley-south",
        "label": "Central Valley, ~1.5 deg south / 1.0 deg east (Tulare-Kern)",
        "dlon": 1.00,
        "dlat": -1.50,
        "why": "The most plausible destination: same valley, same hydrology, "
               "same crops, same climate. Keeps the demo believable.",
    },
    {
        "id": "pacific-offshore",
        "label": "Pacific Ocean, ~2.4 deg west of Merced",
        "dlon": -2.40,
        "dlat": 0.00,
        "why": "The only destination on Earth that overlays no real "
               "jurisdiction. Included to price what that costs.",
    },
    {
        "id": "east-of-sierra",
        "label": "East of the Sierra crest, ~2.1 deg east (Inyo / Owens Valley)",
        "dlon": 2.10,
        "dlat": 0.00,
        "why": "Sparsely populated rangeland and high desert, still California, "
               "so the CA regulatory framing survives.",
    },
    {
        "id": "nevada-basin-range",
        "label": "Nevada Basin and Range, ~4.0 deg east / 1.0 deg north",
        "dlon": 4.00,
        "dlat": 1.00,
        "why": "Out of state entirely. Included because leaving California is "
               "the only way to leave the SGMA/DDW framework the demo models.",
    },
]

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
# Every geometry-bearing artifact under data/. `committed` is filled in at run
# time from `git ls-files`, because whether a file is in the public repo is what
# determines whether it has to move.
GEOJSON_GLOB = "**/*.geojson"
POINT_JSON = DATA / "drinking" / "sampling_points.json"

# Coordinates hardcoded in Python, NOT in data/. Each was hand-picked against
# the aerial basemap to sit on open cropland clear of any town, per the comments
# at their definitions. They do not move when data/ moves.
#   core/management/commands/seed_merced_operations.py::PARCEL_CLUSTER_CONFIGS
#   core/management/commands/seed_merced_recharge.py::BASIN_CONFIGS
SEED_ANCHORS = [
    (-120.665, 37.345),   # MID Atwater Canal cluster
    (-120.270, 37.270),   # Le Grand Canal cluster
    (-120.520, 37.100),   # Stevinson Diversion Canal cluster
    (-120.475, 37.205),   # Plainsburg El Nido Canal cluster
    (-120.490, 37.420),   # Crocker-Huffman river diversion cluster
    (-120.825, 37.375),   # Bottomlands riparian cluster
    (-120.666, 37.336),   # Cressey-Winton Recharge Basin
    (-120.498, 37.125),   # El Nido Recharge Basin
]


def sh(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPO, capture_output=True, text=True, check=False
    ).stdout


def committed_paths() -> set[str]:
    return {
        line.strip()
        for line in sh("git", "ls-files", "data/").splitlines()
        if line.strip()
    }


def load_geojson(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def geoms_of(fc: dict) -> list:
    out = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry")
        if geom:
            out.append(shape(geom))
    return out


def translate(geom, dlon: float, dlat: float):
    return shapely_transform(lambda x, y, z=None: (x + dlon, y + dlat), geom)


def geodesic_acres(geom) -> float:
    """True ellipsoidal footprint in acres. No CRS round trip."""
    area, _perim = GEOD.geometry_area_perimeter(geom)
    return abs(area) / SQM_PER_ACRE


def geodesic_metres(lon1, lat1, lon2, lat2) -> float:
    _az1, _az2, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return dist


# ---------------------------------------------------------------------------
# Landing analysis
# ---------------------------------------------------------------------------
def load_cache() -> dict:
    if CACHE.exists():
        with CACHE.open() as fh:
            return json.load(fh)
    return {}


def save_cache(cache: dict) -> None:
    with CACHE.open("w") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)
        fh.write("\n")


def reverse_geocode(lon: float, lat: float, cache: dict, online: bool) -> str:
    key = f"{lon:.4f},{lat:.4f}"
    if key in cache:
        return cache[key]
    if not online:
        return "?? (not cached; re-run with --online)"
    import requests  # imported lazily so the offline path needs no network dep

    headers = {"User-Agent": "openh2o-demo-scrub-probe/1.0 (phase 97 research)"}
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 8},
            headers=headers,
            timeout=20,
        )
        payload = resp.json()
        name = payload.get("display_name") or "OPEN WATER / no jurisdiction"
    except Exception as exc:  # network problems must not fail the probe
        name = f"LOOKUP FAILED ({type(exc).__name__})"
    else:
        cache[key] = name
        save_cache(cache)
    time.sleep(1.2)  # Nominatim asks for <= 1 request/second
    return name


def sample_points(geom, n_per_axis: int = 3) -> list[tuple[float, float]]:
    """Centroid plus an interior grid, so the overlay report covers the footprint
    rather than one lucky point."""
    minx, miny, maxx, maxy = geom.bounds
    pts = [(geom.centroid.x, geom.centroid.y)]
    for i in range(1, n_per_axis + 1):
        for j in range(1, n_per_axis + 1):
            x = minx + (maxx - minx) * i / (n_per_axis + 1)
            y = miny + (maxy - miny) * j / (n_per_axis + 1)
            pts.append((x, y))
    return pts


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------
def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def section_inventory() -> dict:
    rule("1. INVENTORY - every geometry-bearing artifact under data/")
    tracked = committed_paths()
    rows = []
    for path in sorted(DATA.glob(GEOJSON_GLOB)):
        rel = path.relative_to(REPO).as_posix()
        fc = load_geojson(path)
        geoms = geoms_of(fc)
        verts = sum(
            len(list(g.exterior.coords)) if g.geom_type == "Polygon" else 0
            for g in geoms
        )
        gtype = geoms[0].geom_type if geoms else "-"
        rows.append((rel, len(geoms), gtype, rel in tracked))
    # the drinking sampling points carry lat/long outside any geojson
    pts = json.loads(POINT_JSON.read_text())
    with_coords = [p for p in pts if p.get("latitude") is not None]
    rows.append(
        (
            POINT_JSON.relative_to(REPO).as_posix(),
            len(with_coords),
            "Point (lat/long fields)",
            POINT_JSON.relative_to(REPO).as_posix() in tracked,
        )
    )

    print(f"{'IN REPO':<8} {'FEATURES':>9}  {'TYPE':<24} FILE")
    print("-" * 78)
    for rel, n, gtype, is_committed in rows:
        flag = "yes" if is_committed else "NO"
        print(f"{flag:<8} {n:>9}  {gtype:<24} {rel}")

    n_committed = sum(1 for r in rows if r[3])
    n_ignored = len(rows) - n_committed
    print()
    print(f"  {len(rows)} geometry-bearing artifacts total: "
          f"{n_committed} committed to the PUBLIC repo, {n_ignored} gitignored.")
    print("  Only the committed ones are visible to a reader of the repo, and")
    print("  only they would have to move under a relocation.")
    return {"rows": rows}


def section_baseline() -> dict:
    rule("2. BASELINE - what the geometry asserts today")
    boundary = geoms_of(load_geojson(DATA / "lower_merced_subbasin.geojson"))[0]
    gsas = load_geojson(DATA / "merced_gsas.geojson")
    parcels = load_geojson(DATA / "selected_parcels.geojson")
    basins = load_geojson(DATA / "selected_basins.geojson")
    wells = [
        p
        for p in json.loads(POINT_JSON.read_text())
        if p.get("latitude") is not None
    ]

    stated = load_geojson(DATA / "lower_merced_subbasin.geojson")["features"][0][
        "properties"
    ]["Area_Acres"]
    measured = geodesic_acres(boundary)
    print(f"  Subbasin stated Area_Acres  : {stated:,.0f}")
    print(f"  Subbasin geodesic measured  : {measured:,.0f} acres")
    print(f"  Stated-vs-measured delta    : {abs(measured - stated) / stated * 100:.3f}%")
    print(f"  Boundary bbox               : {boundary.bounds}")
    print(f"  Boundary centroid           : "
          f"({boundary.centroid.x:.5f}, {boundary.centroid.y:.5f})")
    print(f"  Municipal wells with coords : {len(wells)}")
    print(f"  Selected parcels            : {len(parcels['features'])}")
    print(f"  Recharge basins             : {len(basins['features'])}")
    print(f"  GSA zones                   : {len(gsas['features'])}")
    return {
        "boundary": boundary,
        "gsas": gsas,
        "parcels": parcels,
        "basins": basins,
        "wells": wells,
        "stated_acres": stated,
    }


def run_assertions(base: dict, dlon: float, dlat: float) -> list[tuple[str, bool, str]]:
    """Apply the transform in memory and re-test every claim the seed makes."""
    results = []

    boundary = translate(base["boundary"], dlon, dlat)

    # -- 1. Containment: wells inside the subbasin -------------------------
    inside = 0
    for w in base["wells"]:
        from shapely.geometry import Point

        pt = Point(w["longitude"] + dlon, w["latitude"] + dlat)
        if boundary.contains(pt) or boundary.touches(pt):
            inside += 1
    total = len(base["wells"])
    results.append(
        (
            "Containment: municipal wells inside subbasin",
            inside == total,
            f"{inside}/{total} inside",
        )
    )

    # -- 1b. Containment: parcels inside a GSA zone ------------------------
    zones = [
        translate(shape(f["geometry"]), dlon, dlat)
        for f in base["gsas"]["features"]
    ]
    placed = 0
    for f in base["parcels"]["features"]:
        p = translate(shape(f["geometry"]), dlon, dlat)
        if any(z.intersects(p) for z in zones):
            placed += 1
    n_parcels = len(base["parcels"]["features"])
    results.append(
        (
            "Containment: parcels inside a GSA zone",
            placed == n_parcels,
            f"{placed}/{n_parcels} placed",
        )
    )

    # -- 1c. Containment: recharge basins inside the subbasin --------------
    in_basin = 0
    for f in base["basins"]["features"]:
        b = translate(shape(f["geometry"]), dlon, dlat)
        if boundary.intersects(b):
            in_basin += 1
    n_basins = len(base["basins"]["features"])
    results.append(
        (
            "Containment: recharge basins inside subbasin",
            in_basin == n_basins,
            f"{in_basin}/{n_basins} inside",
        )
    )

    # -- 2. Area drift on the ellipsoid ------------------------------------
    before = geodesic_acres(base["boundary"])
    after = geodesic_acres(boundary)
    drift_pct = (after - before) / before * 100
    drift_acres = after - before
    # The suite / data assert 512,606 acres. Does the drift cross a rounded
    # whole acre? Anything above 0.5 acre changes the stated integer.
    results.append(
        (
            "Area: subbasin geodesic acreage preserved",
            abs(drift_acres) < 0.5,
            f"{before:,.0f} -> {after:,.0f} ac "
            f"({drift_acres:+,.0f} ac, {drift_pct:+.3f}%)",
        )
    )

    # per-parcel ACRES property vs measured, before and after
    worst_before = worst_after = 0.0
    for f in base["parcels"]["features"]:
        stated = f["properties"].get("ACRES")
        if not stated:
            continue
        g = shape(f["geometry"])
        b_err = abs(geodesic_acres(g) - stated) / stated
        a_err = abs(geodesic_acres(translate(g, dlon, dlat)) - stated) / stated
        worst_before = max(worst_before, b_err)
        worst_after = max(worst_after, a_err)
    results.append(
        (
            "Area: per-parcel ACRES still matches geometry",
            worst_after <= worst_before + 1e-6,
            f"worst error {worst_before * 100:.3f}% -> {worst_after * 100:.3f}%",
        )
    )

    # -- 3. Distance / topology --------------------------------------------
    canals = geoms_of(load_geojson(DATA / "parcel_selection" / "merced_canals.geojson"))
    parcel_geoms = [shape(f["geometry"]) for f in base["parcels"]["features"]]
    max_delta = 0.0
    for p in parcel_geoms[:20]:  # 20 parcels x 87 canals is plenty of signal
        d_before = min(p.distance(c) for c in canals)
        d_after = min(
            translate(p, dlon, dlat).distance(translate(c, dlon, dlat))
            for c in canals
        )
        max_delta = max(max_delta, abs(d_after - d_before))
    results.append(
        (
            "Topology: canal-to-parcel adjacency preserved",
            max_delta < 1e-9,
            f"max degree-space delta {max_delta:.3e}",
        )
    )

    # true-metre distance is NOT preserved by a lat/long translation that
    # changes latitude - measure it, because the placement helper works in metres
    from shapely.geometry import Point

    w0, w1 = base["wells"][0], base["wells"][1]
    m_before = geodesic_metres(
        w0["longitude"], w0["latitude"], w1["longitude"], w1["latitude"]
    )
    m_after = geodesic_metres(
        w0["longitude"] + dlon,
        w0["latitude"] + dlat,
        w1["longitude"] + dlon,
        w1["latitude"] + dlat,
    )
    results.append(
        (
            "Topology: true-metre well spacing preserved",
            abs(m_after - m_before) < 1.0,
            f"{m_before:,.1f} m -> {m_after:,.1f} m "
            f"({m_after - m_before:+,.1f} m)",
        )
    )

    # -- 3b. The anchors that do NOT move ----------------------------------
    # Six parcel-cluster anchors and two recharge-basin sites are hardcoded in
    # the seed commands, hand-picked against aerial imagery. `data/` moving does
    # not move them. Measure how many fall outside the relocated boundary, i.e.
    # how many seed commands break outright if they are left alone.
    stranded = sum(
        1
        for lon, lat in SEED_ANCHORS
        if not boundary.contains(Point(lon, lat))
    )
    results.append(
        (
            "Seed anchors still inside the boundary",
            stranded == 0,
            f"{stranded}/{len(SEED_ANCHORS)} hardcoded anchors stranded outside",
        )
    )
    return results


def section_transforms(base: dict, cache: dict, online: bool) -> None:
    for cand in CANDIDATES:
        rule(f"3. TRANSFORM '{cand['id']}' - {cand['label']}")
        print(f"  Offset  : dlon {cand['dlon']:+.2f}, dlat {cand['dlat']:+.2f}")
        print(f"  Rationale: {cand['why']}")
        print()
        print(f"  {'RESULT':<6} {'ASSERTION':<46} MEASUREMENT")
        print("  " + "-" * 74)
        for name, ok, detail in run_assertions(base, cand["dlon"], cand["dlat"]):
            print(f"  {'PASS' if ok else 'FAIL':<6} {name:<46} {detail}")

        # -- landing analysis ------------------------------------------------
        moved = translate(base["boundary"], cand["dlon"], cand["dlat"])
        print()
        print("  LANDING - what real jurisdiction the relocated boundary overlays:")
        seen: dict[str, int] = {}
        for lon, lat in sample_points(moved):
            if not moved.contains(__import__("shapely.geometry", fromlist=["Point"]).Point(lon, lat)):
                continue
            name = reverse_geocode(lon, lat, cache, online)
            seen[name] = seen.get(name, 0) + 1
        if not seen:
            print("    (no interior sample point landed inside the polygon)")
        for name, count in sorted(seen.items(), key=lambda kv: -kv[1]):
            print(f"    {count:>2} sample point(s): {name}")


def section_suite_exposure() -> None:
    rule("4. SUITE EXPOSURE - what moves with the geometry")
    print("  Files carrying HARDCODED Merced-area coordinates. These do NOT move")
    print("  when data/ moves; each is an independent edit under a relocation.")
    print()
    # NB: the pattern is passed after `-e` because it begins with a hyphen and
    # grep would otherwise read it as a flag. `\b` is a GNU extension BSD grep
    # does not honour, so the latitude branch brackets the boundary explicitly.
    pattern = r"-12[01]\.[0-9]{2}|(^|[^0-9.])37\.[0-9]{3}"
    out = sh(
        "grep", "-rnE", "-e", pattern,
        "--include=*.py", "--include=*.html", "--include=*.js",
        "core", "geography", "parcels", "wells", "surface", "recharge",
        "drinking", "accounting", "datasync", "reporting", "scripts",
        "tests", "templates",
    )
    by_file: dict[str, int] = {}
    for line in out.splitlines():
        f = line.split(":", 1)[0]
        if f.startswith("scripts/scrub/"):
            continue  # the probe's own candidate offsets, not demo geometry
        by_file[f] = by_file.get(f, 0) + 1
    for f, n in sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {n:>3} hardcoded coordinate line(s)  {f}")
    print()
    print(f"  {len(by_file)} files, {sum(by_file.values())} lines.")


def section_readonly_proof() -> None:
    rule("5. READ-ONLY PROOF")
    out = sh("git", "status", "--porcelain", "data/")
    if out.strip():
        print("  FAIL - the probe modified data/:")
        print(out)
        sys.exit(1)
    print("  PASS - `git status --porcelain data/` is empty. Nothing under data/")
    print("         was written. Every transform was applied in memory only.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--online",
        action="store_true",
        help="refresh the landing lookups from Nominatim (default: use cache)",
    )
    args = ap.parse_args()

    print("Phase 97 - rigid-transform feasibility probe (READ ONLY)")
    print(f"Repo: {REPO}")

    cache = load_cache()
    section_inventory()
    base = section_baseline()
    section_transforms(base, cache, args.online)
    section_suite_exposure()
    section_readonly_proof()

    print()
    print("Probe complete.")


if __name__ == "__main__":
    main()
