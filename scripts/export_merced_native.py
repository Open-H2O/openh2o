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
import math
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

# --- Surface-water domain (Phase F) ----------------------------------------
# Synthesized from the SAME fixtures the ledger uses, so each POD's monthly
# DiversionRecords sum to exactly the surface_diversion ledger rows for its
# served parcels. Values mirror the web seed_merced_operations (the senior 1930
# MID right, the junior 1962 El Nido right that drought-curtails, the undated
# riparian take). The water-right HOLDER is the district/agency (as in CA), kept
# distinct from the farm parcel owners the bundle already carries.
#
# Right type codes: PRE14 / POST14 (appropriative) and RIP (riparian).
WATER_RIGHT_TYPES = [
    {"code": "PRE14", "name": "Pre-1914 Appropriative",
     "detail": "Pre-1914 appropriative water right"},
    {"code": "POST14", "name": "Post-1914 Appropriative",
     "detail": "Post-1914 appropriative water right"},
    {"code": "RIP", "name": "Riparian", "detail": "Riparian water right"},
]

# rightID -> typeCode, holder, priorityDate(str|None), faceValueAF, source, status, calwatrsPIN
WATER_RIGHTS = [
    ("MER-WR-004", "POST14", "Merced Irrigation District", "1930-04-10",
     "120000", "Merced River", "active", "A004720"),
    ("MER-WR-005", "POST14", "Le Grand-Athlone Water District", "1948-09-01",
     "18000", "Le Grand Canal", "active", "A015533"),
    ("MER-WR-006", "POST14", "Stevinson Water District", "1955-03-20",
     "22000", "Diversion Canal", "active", "A018002"),
    ("MER-WR-008", "RIP", "San Joaquin Bottomlands Ranch", None,
     "4000", "Merced River", "active", ""),
    # Junior right (newest priority) → first curtailed in the summer-2025 drought.
    ("MER-WR-009", "POST14", "Plainsburg Irrigation District", "1962-05-05",
     "9000", "El Nido Canal", "curtailed", "A021145"),
    # Merced Falls hydroelectric passthrough — serves no parcels, returns its full
    # diverted volume to the river (non-consumptive). Lights up the "Non-consumptive
    # (returned to stream)" classification with real-looking data on the read screen.
    ("MER-WR-010", "POST14", "Merced Falls Hydroelectric Co.", "1958-07-01",
     "60000", "Merced River", "active", "A019887"),
]

# POD code (matches a parcel's servedBy) -> rightID, name, streamName, maxRateCFS
POD_SURFACE = {
    "MER-POD-004": ("MER-WR-004", "MID Atwater Canal Headgate", "Atwater Canal", "900.0"),
    "MER-POD-005": ("MER-WR-005", "Le Grand Canal Headgate", "Le Grand Canal", "220.0"),
    "MER-POD-006": ("MER-WR-006", "Stevinson Diversion Canal Headgate", "Diversion Canal", "260.0"),
    "MER-POD-007": ("MER-WR-009", "Plainsburg El Nido Canal Headgate", "El Nido Canal", "130.0"),
    "MER-POD-008": ("MER-WR-004", "Crocker-Huffman River Diversion", "Merced River", "700.0"),
    "MER-POD-009": ("MER-WR-008", "Bottomlands Riparian Take", "Merced River", "45.0"),
}

# The hydro passthrough POD (no parcels; its records are synthesized, not ledger-derived).
HYDRO_POD = "MER-POD-010"
HYDRO_POD_SPEC = ("MER-WR-010", "Merced Falls Hydroelectric Diversion", "Merced River", "400.0")
# A plausible Merced River main-stem point (near Merced Falls), since it serves no parcels.
HYDRO_POD_LONLAT = (-120.30, 37.52)
HYDRO_MONTHLY_AF = Decimal("3200")   # flat monthly passthrough volume, fully returned

# The summer-2025 drought curtailment: basin-wide by priority date (how the State
# Water Board actually cut the Merced system in 2021-22). Its 1962 cutoff curtails
# only the junior El Nido right (MER-WR-009, priority 1962-05-05).
CURTAILMENT_ORDER = {
    "orderID": "MER-CURT-001",
    "title": "Merced River System Drought Curtailment — Summer 2025",
    "effectiveDate": "2025-07-01",
    "endDate": "2025-09-30",
    "watershed": "",                       # basin-wide (empty = matches every right)
    "priorityDateCutoff": "1962-01-01",
    "status": "active",
    "notes": "Curtails post-1962 junior appropriative rights during the 2025 drought.",
}

# --- Managed-recharge domain (Phase F-recharge) -----------------------------
# The two REAL Merced Irrigation District spreading basins (from seed_merced_recharge:
# Cressey-Winton ~110 ac / 550 AF, El Nido ~85 ac / 425 AF), each placed on open
# cropland beside an MID canal that fills it. The basin↔POD link ties each basin to
# the surface diversion that feeds it — a data link surfaced on the detail page, not a
# flow line on the map. (El Nido is fed by MER-POD-007, the same canal whose junior
# right drought-curtails — the basin's supply and the surface book share one source.)
#
# code -> name, siteType, lon, lat, acres, capacityAF, fedByPOD
RECHARGE_SITES = {
    "MER-RB-001": ("Cressey-Winton Recharge Basin", "spreading_basin",
                   -120.666, 37.336, 110.0, "550.0", "MER-POD-004"),
    "MER-RB-002": ("El Nido Recharge Basin", "spreading_basin",
                   -120.498, 37.125, 85.0, "425.0", "MER-POD-007"),
}
RECHARGE_OPERATOR = "Merced Irrigation District"

# Wet-season recharge schedule for WY 2024-2025 (mirrors seed_merced_recharge_events):
# storm-driven, weighted to mid-winter; (event_date, fraction-of-capacity). Fractions
# sum to 1.0, so each basin recharges ~one full capacity over the season.
RECHARGE_WET_SEASON = [
    ("2024-12-15", Decimal("0.20")),
    ("2025-01-15", Decimal("0.30")),
    ("2025-02-15", Decimal("0.30")),
    ("2025-03-15", Decimal("0.20")),
]
# Decision (Brent, 2026-06-03): managed recharge credits Groundwater (GW); the physical
# source water (diverted storm/surface runoff) is preserved in the event source field.
RECHARGE_WATER_TYPE = "GW"
RECHARGE_SOURCE_DESC = "storm/surface runoff diverted to basin"

# On-site monitoring readings per basin across the recharge season (mirrors the
# seed_merced_recharge measurements: ponded depth, canal inflow, percolation rate,
# and source-water quality). Type vocabulary matches recharge/models.py
# RechargeMeasurement.MEASUREMENT_TYPE_CHOICES. Water level + inflow scale loosely
# with the basin; infiltration and TDS are intrinsic, so they read alike across both.
# code -> [(date, type, value, unit, note)]
RECHARGE_MEASUREMENTS = {
    "MER-RB-001": [   # Cressey-Winton — the larger (~110 ac) basin
        ("2024-12-16", "water_level", "3.4", "ft", "Ponded depth after the December storm flooding."),
        ("2024-12-16", "flow_rate", "82", "cfs", "Canal inflow while the basin was filling."),
        ("2025-01-16", "infiltration_rate", "0.9", "in/hr", "Percolation rate measured mid-season."),
        ("2025-02-16", "water_quality", "300", "mg/L", "Source-water total dissolved solids (storm runoff)."),
        ("2025-02-16", "water_level", "2.8", "ft", "Ponded depth during the February refill."),
    ],
    "MER-RB-002": [   # El Nido — the smaller (~85 ac) basin, fed by the curtailed canal
        ("2024-12-16", "water_level", "2.7", "ft", "Ponded depth after the December storm flooding."),
        ("2024-12-16", "flow_rate", "61", "cfs", "Canal inflow while the basin was filling."),
        ("2025-01-16", "infiltration_rate", "1.1", "in/hr", "Percolation rate measured mid-season."),
        ("2025-02-16", "water_quality", "330", "mg/L", "Source-water total dissolved solids (storm runoff)."),
        ("2025-02-16", "water_level", "2.2", "ft", "Ponded depth during the February refill."),
    ],
}


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


def acre_box_footprint(lon, lat, acres):
    """An area-accurate square Polygon footprint for a facility whose seed geometry is only a
    centroid + an acreage (the recharge basins are placed this way). The box is sized so the
    native map reads a 110-acre basin as visibly larger than an 85-acre one, instead of an
    identical pin. The exact (lon, lat) is kept as the centroid so the basin marker sits true;
    bbox is the box itself. (Mirrors the river-MAR parcel pool's centroid→box synthesis.)
    """
    side_m = math.sqrt(float(acres) * 4046.8564224)          # 1 acre = 4046.8564224 m^2
    half = side_m / 2.0
    dlat = half / 111_320.0                                   # metres per degree latitude
    dlon = half / (111_320.0 * math.cos(math.radians(lat)))   # …shrinks with latitude
    ring = [
        [lon - dlon, lat - dlat], [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat], [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],                            # close the ring
    ]
    return {
        "geoJSON": json.dumps(
            {"type": "Polygon", "coordinates": [ring]}, separators=(",", ":")),
        "centroidLat": lat, "centroidLon": lon,
        "bbox": [lon - dlon, lat - dlat, lon + dlon, lat + dlat],
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

    # --- Surface-water domain (rights, PODs, diversion records, curtailment) ---
    surface = build_surface(parcels, parcel_by_number, ledger, schedule)

    # --- Managed-recharge domain (basins, basin↔POD links, recharge events) ---
    recharge = build_recharge()

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
            "waterRightCount": len(surface["waterRights"]),
            "podCount": len(surface["pointsOfDiversion"]),
            "diversionRecordCount": len(surface["diversionRecords"]),
            "rechargeSiteCount": len(recharge["sites"]),
            "rechargeEventCount": len(recharge["events"]),
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
        "surface": surface,
        "recharge": recharge,
    }
    return bundle


def build_surface(parcels, parcel_by_number, ledger, schedule):
    """The surface-water domain, synthesized from the same fixtures + ledger.

    Each POD's monthly DiversionRecords are the SUM of the surface_diversion ledger
    rows for the parcels it serves, so the surface book ties out to the ledger the
    accounting waterfall already consumes. Returns the bundle's ``surface`` dict.
    """
    # Which parcels each POD serves (a surface/conjunctive parcel names its POD in servedBy).
    pod_parcels = {}   # pod_code -> [parcelNumber, ...]
    for p in parcels:
        pod = (p.get("servedBy") or "").strip()
        if pod in POD_SURFACE and p["waterSource"] in SURFACE_SOURCES:
            pod_parcels.setdefault(pod, []).append(p["parcelNumber"])

    # --- Points of diversion (located at the centroid of the parcels they serve) ---
    points = []
    for code, (rid, name, stream, max_cfs) in POD_SURFACE.items():
        members = pod_parcels.get(code, [])
        if members:
            lats = [parcel_by_number[m]["footprint"]["centroidLat"] for m in members]
            lons = [parcel_by_number[m]["footprint"]["centroidLon"] for m in members]
            clat, clon = sum(lats) / len(lats), sum(lons) / len(lons)
            frac = q4(Decimal(1) / Decimal(len(members)))
        else:
            clat = clon = None
            frac = None
        points.append({
            "code": code, "name": name, "rightID": rid, "streamName": stream,
            "maxRateCFS": max_cfs, "status": "active",
            "footprint": ({
                "geoJSON": json.dumps(
                    {"type": "Point", "coordinates": [clon, clat]}, separators=(",", ":")),
                "centroidLat": clat, "centroidLon": clon, "bbox": None,
            } if clat is not None else None),
            "parcels": [{"parcelNumber": m, "fraction": frac} for m in members],
        })

    # The hydro passthrough POD: no parcels, fixed Merced River point, re-diverts nothing.
    hlon, hlat = HYDRO_POD_LONLAT
    hrid, hname, hstream, hmax = HYDRO_POD_SPEC
    points.append({
        "code": HYDRO_POD, "name": hname, "rightID": hrid, "streamName": hstream,
        "maxRateCFS": hmax, "status": "active",
        "footprint": {
            "geoJSON": json.dumps(
                {"type": "Point", "coordinates": [hlon, hlat]}, separators=(",", ":")),
            "centroidLat": hlat, "centroidLon": hlon, "bbox": None,
        },
        "parcels": [],
    })

    # --- Water-right ↔ parcel links (a right serves the union of its PODs' parcels) ---
    right_parcels = {}   # rightID -> set(parcelNumber)
    for code, members in pod_parcels.items():
        rid = POD_SURFACE[code][0]
        right_parcels.setdefault(rid, set()).update(members)
    water_right_parcels = [
        {"rightID": rid, "parcelNumber": n}
        for rid in sorted(right_parcels) for n in sorted(right_parcels[rid])
    ]

    # --- Diversion records: aggregate surface_diversion ledger by (POD, month) ---
    # parcel -> its POD; only surface-served parcels write surface_diversion rows.
    pod_of_parcel = {n: code for code, members in pod_parcels.items() for n in members}
    by_pod_month = {}   # (pod_code, day) -> summed magnitude (Decimal)
    for row in ledger:
        if row["sourceType"] != "surface_diversion":
            continue
        code = pod_of_parcel.get(row["parcelNumber"])
        if code is None:
            continue
        mag = abs(Decimal(row["amountAcreFeet"]))
        key = (code, row["transactionDate"])
        by_pod_month[key] = by_pod_month.get(key, Decimal("0")) + mag

    records = []
    for (code, day), vol in sorted(by_pod_month.items()):
        records.append({
            "podCode": code, "month": day, "periodName": "WY 2024-2025",
            "volumeAcreFeet": q4(vol), "returnedAF": "0",
            "diversionType": "direct_use",
            "detail": "Recorded monthly canal diversion",
        })

    # Hydro passthrough records: full volume returned each month (non-consumptive).
    for _yr, _mn, day in schedule:
        records.append({
            "podCode": HYDRO_POD, "month": day, "periodName": "WY 2024-2025",
            "volumeAcreFeet": q4(HYDRO_MONTHLY_AF), "returnedAF": q4(HYDRO_MONTHLY_AF),
            "diversionType": "direct_use",
            "detail": "Hydroelectric passthrough — returned to stream",
        })

    return {
        "waterRightTypes": WATER_RIGHT_TYPES,
        "waterRights": [
            {"rightID": rid, "typeCode": tc, "holderName": holder,
             "priorityDate": pdate, "faceValueAcreFeet": fv, "sourceName": src,
             "status": status, "calwatrsPIN": pin}
            for (rid, tc, holder, pdate, fv, src, status, pin) in WATER_RIGHTS
        ],
        "pointsOfDiversion": points,
        "waterRightParcels": water_right_parcels,
        "diversionRecords": records,
        "curtailmentOrders": [CURTAILMENT_ORDER],
    }


def build_recharge():
    """The managed-recharge domain: the MID spreading basins, the POD that fills each,
    and a wet-season of recharge events. Returns the bundle's ``recharge`` dict.

    Independent of the ledger (unlike surface): managed recharge is its own recorded book
    of deposits to the aquifer, sized as a fraction of each basin's capacity per event.
    """
    sites, links, events = [], [], []
    for code, (name, site_type, lon, lat, acres, cap_af, fed_by_pod) in RECHARGE_SITES.items():
        sites.append({
            "code": code, "name": name, "siteType": site_type,
            "capacityAcreFeet": q4(cap_af), "status": "active",
            "operator": RECHARGE_OPERATOR,
            "notes": (f"{acres:.0f}-acre spreading basin on open cropland beside an "
                      f"MID canal; flooded in storm events and pooled to percolate."),
            # An area-accurate box footprint (acres → square Polygon), so the native map draws the
            # basin's real extent instead of a pin. The seed places these by centroid + acreage.
            "footprint": acre_box_footprint(lon, lat, acres),
        })
        # Basin ← POD link (the diversion that fills it).
        links.append({"siteCode": code, "podCode": fed_by_pod})
        # Wet-season events: each a fraction of the basin's capacity.
        capacity = Decimal(cap_af)
        for ev_date, fraction in RECHARGE_WET_SEASON:
            vol = (capacity * fraction)
            events.append({
                "siteCode": code, "startDate": ev_date, "endDate": None,
                "volumeAcreFeet": q4(vol), "waterTypeCode": RECHARGE_WATER_TYPE,
                "periodName": "WY 2024-2025", "sourceDescription": RECHARGE_SOURCE_DESC,
                "notes": ("Managed aquifer recharge credited to groundwater (GW); "
                          "physical source is diverted surface/storm water."),
            })

    return {
        "sites": sites,
        "sitePODs": links,
        "events": events,
    }


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
    s = bundle["surface"]
    print(f"  surface: {len(s['waterRights'])} rights, {len(s['pointsOfDiversion'])} PODs, "
          f"{len(s['diversionRecords'])} diversion records, "
          f"{len(s['curtailmentOrders'])} curtailment order(s)")
    rc = bundle["recharge"]
    print(f"  recharge: {len(rc['sites'])} basins, {len(rc['sitePODs'])} basin↔POD links, "
          f"{len(rc['events'])} recharge events")


if __name__ == "__main__":
    main()
