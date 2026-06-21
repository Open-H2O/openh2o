#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export the Merced demo as a flat JSON bundle for the OpenH2O *native* (Swift) app.

WHY this exists. The native macOS app is local-first and has the full data MODEL
already (parcels, wells, zones, ledger, calc plan) but no importer and only a tiny
five-parcel hand-seeded demo. This script produces the real Merced district at scale
— the 76 surveyed fields, their wells, the three GSAs, a methodology, and a 12-month
water-year ledger — so the native app can load it and be tested at scale.

DECOUPLED BY DESIGN (Strategy 2). It reads ONLY the committed GeoJSON fixtures in
``data/merced/`` — no Django, no Postgres, no Docker, no Earth Engine. Evapotranspiration
and precipitation are deliberately NOT exported: the native app fetches those itself
through its own OpenET sync after import (its "Refresh Data" button), which also
exercises that path at 76-parcel scale.

WHAT IT REPRODUCES vs. the web seed. Structure is faithful (real geometry, owners,
crops, water-source classification, shared-well groups, GSA membership). The recorded
ledger layer (surface deliveries + meter readings) is sized with the web seed's
FACE-VALUE seasonal model (area x rate x seasonal-weight x deterministic jitter) — the
exact fallback the web's seed_merced_ledgers uses when no ET cache is present. It is NOT
the web's demand-aware sizing (which needs ET-derived CalculationRuns). The native
engine then computes groundwater extraction, dispositions, banking, and basin-pool
recharge on top of this recorded layer once ET is fetched.

Output: a single JSON object written to --out (default: the native repo's
App/Resources/merced_bundle.json). The native MercedImport reads it.
"""
from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, ROUND_HALF_EVEN

# --- Paths -----------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "data", "merced")
DEFAULT_OUT = os.path.expanduser(
    "~/GitHub/openh2o-native/App/Resources/merced_bundle.json"
)

PARCELS_GEOJSON = os.path.join(DATA, "selected_parcels.geojson")
RIVER_PARCELS_GEOJSON = os.path.join(DATA, "selected_river_ag_parcels.geojson")
GSAS_GEOJSON = os.path.join(DATA, "merced_gsas.geojson")
BOUNDARY_GEOJSON = os.path.join(DATA, "lower_merced_subbasin.geojson")

BASIN_CODE = "5-022.04"

# The junior El Nido right is curtailed mid-water-year: its POD stops delivering
# after June 2025 (mirrors seed_merced_ledgers CURTAILMENT_LAST_DELIVERY).
CURTAILED_POD = "MER-POD-007"

# Face-value sizing model (mirrors seed_merced_ledgers fallback constants).
SURFACE_RATE = Decimal("2.2")   # AF/acre/yr
GW_RATE = Decimal("1.8")        # AF/acre/yr
SEASONAL_WEIGHTS = {
    10: Decimal("0.05"), 11: Decimal("0.03"), 12: Decimal("0.02"),
    1: Decimal("0.02"), 2: Decimal("0.02"), 3: Decimal("0.04"),
    4: Decimal("0.08"), 5: Decimal("0.14"), 6: Decimal("0.16"),
    7: Decimal("0.16"), 8: Decimal("0.15"), 9: Decimal("0.13"),
}
SUBSTITUTION_MULTIPLIER = Decimal("1.6")   # curtailed conjunctive farms pump more Jul-Sep
POST_CURTAILMENT_MONTHS = {7, 8, 9}

GROUNDWATER_SOURCES = {"groundwater", "conjunctive"}
SURFACE_SOURCES = {"surface", "conjunctive"}

# Deterministic owner naming so accounts/summary group sensibly (web derives these
# from private constants; we synthesize stable, plausible names from the fixture keys).
OWNER_BY_WELLGROUP = {
    "TI-W-1": "Turner Island Farms LLC",
    "TI-W-2": "Sandy Mush Growers",
}
OWNER_BY_POD = {
    "MER-POD-004": "Atwater Ranch Partners",
    "MER-POD-005": "Le Grand Orchards",
    "MER-POD-006": "Diversion Canal Growers",
    "MER-POD-007": "El Nido Farming Co.",
    "MER-POD-008": "Crocker-Huffman Ranch",
    "MER-POD-009": "Bottomlands Cattle Co.",
}
GW_SOLO_OWNERS = [
    "Vela Farms", "Rio Verde LLC", "Ortega Ranch", "Hidden Spring Co.",
    "Cressey Land Partners", "Planada Ag Holdings", "Le Grand Family Farms",
    "Snelling Orchard Co.",
]


def q4(value) -> str:
    """Quantize to the ledger's 4 decimal places, return as a STRING.

    String form keeps Foundation's JSONDecoder reading it straight into Decimal
    without a Double round-trip (the native side decodes amounts as Decimal).
    """
    d = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    return f"{d}"


def jitter(seq: int) -> Decimal:
    """Deterministic +/-6% factor keyed on an index (no randomness, stable re-runs)."""
    return Decimal("1") + (Decimal(seq % 7) - Decimal("3")) * Decimal("0.02")


def month_schedule():
    """(year, month, 'YYYY-MM-DD' on day 15) for each month of WY 2024-2025."""
    out = []
    for offset in range(12):
        mn = ((10 + offset - 1) % 12) + 1
        yr = 2024 if mn >= 10 else 2025
        out.append((yr, mn, f"{yr:04d}-{mn:02d}-15"))
    return out


# --- Geometry helpers (pure, no GDAL) --------------------------------------

def _iter_positions(coords):
    """Yield every [lon, lat] position in an arbitrarily nested coordinate tree."""
    if (isinstance(coords, list) and len(coords) >= 2
            and all(isinstance(c, (int, float)) for c in coords[:2])):
        yield coords
        return
    if isinstance(coords, list):
        for c in coords:
            yield from _iter_positions(c)


def centroid_and_bbox(geometry):
    """Average-vertex centroid + [minLon, minLat, maxLon, maxLat] for a geometry dict."""
    xs, ys = [], []
    for lon, lat in ((p[0], p[1]) for p in _iter_positions(geometry.get("coordinates", []))):
        xs.append(lon); ys.append(lat)
    if not xs:
        return None, None, None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return cy, cx, [min(xs), min(ys), max(xs), max(ys)]


def footprint(geometry):
    """A native GeoFootprint dict: the raw geometry as a GeoJSON string + centroid + bbox.

    The native App/GeoJSON.swift parser is tolerant and walks canonical
    Polygon/MultiPolygon nesting, so we pass the geometry through verbatim.
    """
    lat, lon, bbox = centroid_and_bbox(geometry)
    return {
        "geoJSON": json.dumps(geometry, separators=(",", ":")),
        "centroidLat": lat,
        "centroidLon": lon,
        "bbox": bbox,
    }


def point_in_ring(lon, lat, ring):
    """Ray-casting point-in-polygon for a single ring of [lon, lat] positions."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def outer_rings(geometry):
    """The outer ring(s) of a Polygon/MultiPolygon as lists of [lon, lat]."""
    g = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if g == "Polygon":
        return [coords[0]] if coords else []
    if g == "MultiPolygon":
        return [poly[0] for poly in coords if poly]
    return []


def point_in_geometry(lon, lat, geometry):
    return any(point_in_ring(lon, lat, ring) for ring in outer_rings(geometry))


# --- Load fixtures ----------------------------------------------------------

def load(path):
    with open(path) as fh:
        return json.load(fh)


def build_bundle():
    parcels_fc = load(PARCELS_GEOJSON)
    river_fc = load(RIVER_PARCELS_GEOJSON)
    gsas_fc = load(GSAS_GEOJSON)
    boundary_fc = load(BOUNDARY_GEOJSON)

    # --- Zones (the three GSA management areas) + boundary ---
    boundary_geom = boundary_fc["features"][0]["geometry"]
    boundary = {
        "name": "Merced Subbasin",
        "detail": "Lower Merced Subbasin (DWR Bulletin 118 5-022.04).",
        "basinCode": BASIN_CODE,
        "footprint": footprint(boundary_geom),
    }
    zones = []
    for i, feat in enumerate(gsas_fc["features"]):
        props = feat["properties"]
        name = (props.get("GSA_Name") or props.get("Agency")
                or props.get("Name") or f"GSA {i + 1}")
        zones.append({
            "key": f"gsa-{i}",
            "name": name,
            "zoneType": "management_area",
            "basinCode": BASIN_CODE,
            "geometry": feat["geometry"],          # kept transiently for membership test
            "footprint": footprint(feat["geometry"]),
        })

    # --- Crop vocabulary (collect distinct from the fixtures) ---
    crops = {}  # code -> name

    # --- Parcels ---
    parcels = []
    well_members = {}   # well_group key -> [parcel_number, ...]
    gw_solo_i = 0

    def gsa_for(lon, lat):
        for z in zones:
            if lon is not None and point_in_geometry(lon, lat, z["geometry"]):
                return z["key"]
        return zones[0]["key"] if zones else None

    for seq, feat in enumerate(parcels_fc["features"], start=1):
        p = feat["properties"]
        geom = feat["geometry"]
        lat, lon, _ = centroid_and_bbox(geom)
        source = (p.get("water_source") or "").strip().lower()
        served = (p.get("served_by") or "").strip()
        wg = (p.get("well_group") or "").strip()
        crop_code = (p.get("MAIN_CROP") or "").strip() or "UNK"
        crop_name = (p.get("crop_class") or "").strip() or crop_code
        crops.setdefault(crop_code, crop_name)

        if wg in OWNER_BY_WELLGROUP:
            owner = OWNER_BY_WELLGROUP[wg]
        elif served in OWNER_BY_POD:
            owner = OWNER_BY_POD[served]
        else:
            owner = GW_SOLO_OWNERS[gw_solo_i % len(GW_SOLO_OWNERS)]
            gw_solo_i += 1

        number = f"MER-APN-{seq:03d}"
        parcels.append({
            "parcelNumber": number,
            "ownerName": owner,
            "areaAcres": q4(p.get("ACRES") or 0),
            "status": "active",
            "notes": f"DWR field {p.get('UniqueID', '?')} | {crop_name} | {p.get('COUNTY', '')}",
            "cropCode": crop_code,
            "waterSource": source,
            "servedBy": served,
            "wellGroup": wg,
            "zoneKey": gsa_for(lon, lat),
            "footprint": footprint(geom),
        })
        if source in GROUNDWATER_SOURCES:
            well_members.setdefault(wg or f"solo-{seq}", []).append(number)

    # --- River Flood-MAR parcels (no well; surface over-delivery -> basin pool) ---
    river_start = len(parcels)
    for j, feat in enumerate(river_fc["features"], start=1):
        p = feat["properties"]
        geom = feat["geometry"]
        lat, lon, _ = centroid_and_bbox(geom)
        number = f"MER-APN-R{j:02d}"
        crops.setdefault("ALF", "Alfalfa")
        parcels.append({
            "parcelNumber": number,
            "ownerName": "Merced River Flood-MAR Co-op",
            "areaAcres": q4(p.get("GIS_ACRES") or 0),
            "status": "active",
            "notes": f"Flood-MAR recharge field {p.get('APN', p.get('name', '?'))}",
            "cropCode": "ALF",
            "waterSource": "surface",                 # over-delivered surface, NO well
            "servedBy": (p.get("served_by") or "MER-POD-009").strip(),
            "wellGroup": "",
            "zoneKey": gsa_for(lon, lat),
            "footprint": footprint(geom),
            "floodMAR": True,
        })

    parcel_by_number = {p["parcelNumber"]: p for p in parcels}

    # --- Wells (one per shared group / per solo groundwater field) ---
    wells = []
    metered_parcels = set()   # parcels whose well is metered -> meter_reading rows
    well_seq = 0
    for key, members in sorted(well_members.items()):
        well_seq += 1
        metered = (well_seq % 2 == 0)   # alternate metered / unmetered
        # Centroid of member parcels for the well marker.
        lats = [parcel_by_number[m]["footprint"]["centroidLat"] for m in members]
        lons = [parcel_by_number[m]["footprint"]["centroidLon"] for m in members]
        clat = sum(lats) / len(lats)
        clon = sum(lons) / len(lons)
        shared = len(members) > 1
        frac = q4(Decimal(1) / Decimal(len(members)))
        wells.append({
            "registrationID": f"MER-W-{well_seq:03d}",
            "name": (f"Shared ag well ({key}) - {len(members)} parcels"
                     if shared else f"Ag well on {members[0]}"),
            "typeName": "Agricultural Production",
            "status": "active",
            "metered": metered,
            "footprint": {
                "geoJSON": json.dumps(
                    {"type": "Point", "coordinates": [clon, clat]}, separators=(",", ":")),
                "centroidLat": clat, "centroidLon": clon, "bbox": None,
            },
            "parcels": [{"parcelNumber": m, "fraction": frac} for m in members],
        })
        if metered:
            metered_parcels.update(members)

    # --- Ledger: 12 months of recorded surface deliveries + meter readings ---
    ledger = []
    schedule = month_schedule()
    seq_of = {p["parcelNumber"]: i for i, p in enumerate(parcels)}
    for p in parcels:
        number = p["parcelNumber"]
        area = Decimal(p["areaAcres"])
        seq = seq_of[number]
        curtailed = (p["servedBy"] == CURTAILED_POD)
        has_surface = p["waterSource"] in SURFACE_SOURCES and p["servedBy"]
        is_flood = p.get("floodMAR", False)

        for yr, mn, day in schedule:
            weight = SEASONAL_WEIGHTS[mn]
            # Surface delivery (negative; counts as supply). Flood-MAR parcels are
            # deliberately over-delivered to recharge the aquifer.
            if has_surface:
                if curtailed and (yr, mn) > (2025, 6):
                    pass  # El Nido cut after June 2025 -> no delivery
                else:
                    base = area * SURFACE_RATE * weight * jitter(seq)
                    if is_flood:
                        base *= Decimal("2.5")   # over-deliver for managed recharge
                    amt = q4(base)
                    if Decimal(amt) > 0:
                        ledger.append({
                            "parcelNumber": number,
                            "transactionDate": day, "effectiveDate": day,
                            "amountAcreFeet": f"-{amt}",
                            "sourceType": "surface_diversion",
                            "detail": ("Managed recharge flood delivery"
                                       if is_flood else "Canal delivery"),
                        })
            # Meter reading (negative; authoritative groundwater) for metered wells.
            if number in metered_parcels:
                bump = (SUBSTITUTION_MULTIPLIER
                        if curtailed and mn in POST_CURTAILMENT_MONTHS else Decimal("1"))
                amt = q4(area * GW_RATE * weight * jitter(seq) * bump)
                if Decimal(amt) > 0:
                    ledger.append({
                        "parcelNumber": number,
                        "transactionDate": day, "effectiveDate": day,
                        "amountAcreFeet": f"-{amt}",
                        "sourceType": "meter_reading",
                        "detail": "Monthly metered groundwater extraction",
                    })

    # --- GSA groundwater allocations (the budgets carryover rolls against) ---
    # One AllocationPlan per GSA zone per period, sized to a SGMA sustainable-yield
    # fraction of the zone's demo acreage (mirrors seed_merced_ledgers._build_budgets).
    # Native has only the management-area GSA zones (no surface-district zones — Phase F),
    # so only the GW budgets are emitted; that is exactly what groundwater carryover needs.
    GSA_SUSTAINABLE_RATE = Decimal("2.0")    # AF/acre
    GSA_BUDGET_FLOOR = Decimal("500.0")      # a GSA with no demo parcels still gets a budget
    acres_by_zone = {}
    for p in parcels:
        zk = p.get("zoneKey")
        if zk is not None:
            acres_by_zone[zk] = acres_by_zone.get(zk, Decimal("0")) + Decimal(p["areaAcres"])
    period_names = ["WY 2024-2025", "WY 2025-2026"]
    allocations = []
    for z in zones:
        acres = acres_by_zone.get(z["key"], Decimal("0"))
        budget = max(GSA_BUDGET_FLOOR, Decimal(q4(acres * GSA_SUSTAINABLE_RATE)))
        for rp_name in period_names:
            allocations.append({
                "zoneKey": z["key"], "waterTypeCode": "GW", "periodName": rp_name,
                "name": f"{z['name']} — Groundwater {rp_name}",
                "allocationAcreFeet": q4(budget),
                "notes": "SGMA sustainable-yield groundwater allocation (demo).",
            })

    # --- Water accounts (one per owner; the balance sheet groups parcels by who owns them) ---
    # The web derives accounts from private owner constants; we mirror that by grouping the
    # synthesized owner names every parcel already carries. Members are embedded as bare
    # parcelNumbers (same shape wells use), so the native importer maps them to the parcel
    # IDs it assigns. Account number is a stable, zero-padded ordinal over the sorted owners
    # so the "By water account" balance sheet lists deterministically.
    owners = sorted({p["ownerName"] for p in parcels})
    accounts = []
    for i, owner in enumerate(owners, start=1):
        accounts.append({
            "name": owner,
            "accountNumber": f"{i:03d}",
            "status": "active",
            "parcels": [p["parcelNumber"] for p in parcels if p["ownerName"] == owner],
        })

    # Strip the transient geometry from zones before emitting.
    for z in zones:
        z.pop("geometry", None)

    bundle = {
        "metadata": {
            "source": "openh2o fixtures (export_merced_native.py)",
            "basinCode": BASIN_CODE,
            "district": "Merced Subbasin GSA",
            "parcelCount": len(parcels),
            "wellCount": len(wells),
            "accountCount": len(accounts),
            "ledgerRows": len(ledger),
            "waterYear": "WY 2024-2025",
            "note": "ET/precip intentionally omitted; native fetches via OpenET after import.",
        },
        "waterTypes": [
            {"name": "Groundwater", "code": "GW", "detail": "Pumped groundwater"},
            {"name": "Surface Water", "code": "SW", "detail": "Canal / surface delivery"},
        ],
        "cropTypes": [{"name": name, "code": code} for code, name in sorted(crops.items())],
        "reportingPeriods": [
            # WY 2024-2025 imports OPEN: the native lifecycle is run the year →
            # finalize it (locking re-runs) → roll its balance forward. Pre-stamping
            # it finalized would lock the months before they were ever run.
            {"name": "WY 2024-2025", "startDate": "2024-10-01",
             "endDate": "2025-09-30", "isFinalized": False},
            {"name": "WY 2025-2026", "startDate": "2025-10-01",
             "endDate": "2026-09-30", "isFinalized": False},
        ],
        "allocations": allocations,
        "methodology": {
            "name": "Default Methodology v1",
            "waterTypeCode": "GW",
            "steps": [
                {"order": 1, "stepType": "et_gross", "label": "Gross ET",
                 "config": {"model": "Ensemble", "variable": "ET"}},
                {"order": 2, "stepType": "subtract_effective_precip",
                 "label": "Subtract Effective Precip",
                 "config": {"method": "usda_scs", "fraction": 0.70, "soil_storage_in": 3.0}},
                {"order": 3, "stepType": "subtract_surface_water",
                 "label": "Subtract Surface Water", "config": {}},
                {"order": 4, "stepType": "clamp_floor", "label": "Floor & Bank Surplus",
                 "config": {"floor": 0, "bank": True,
                            "depreciation_rate": 0.10, "expiry_months": 24}},
            ],
        },
        "boundary": boundary,
        "zones": zones,
        "parcels": parcels,
        "wells": wells,
        "accounts": accounts,
        "ledger": ledger,
    }
    return bundle


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT, help="output bundle path")
    args = ap.parse_args()

    bundle = build_bundle()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(bundle, fh, indent=1)

    m = bundle["metadata"]
    print(f"Wrote {args.out}")
    print(f"  parcels:   {m['parcelCount']}")
    print(f"  wells:     {m['wellCount']}")
    print(f"  zones:     {len(bundle['zones'])}")
    print(f"  crops:     {len(bundle['cropTypes'])}")
    print(f"  ledger:    {m['ledgerRows']} rows across {len(bundle['reportingPeriods'])} periods")
    print(f"  allocations: {len(bundle['allocations'])} GW budgets across {len(bundle['zones'])} zones")
    metered = sum(1 for w in bundle["wells"] if w["metered"])
    print(f"  wells metered/total: {metered}/{len(bundle['wells'])}")


if __name__ == "__main__":
    main()
