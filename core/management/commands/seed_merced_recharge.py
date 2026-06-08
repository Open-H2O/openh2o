# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the two real Merced Irrigation District recharge basins.

This command kills the synthetic-square anti-pattern named by the v1.9
demonstration: a naive seed builds spreading basins with
``make_box(size=0.008)``, a fixed-degree box that is ~150-190 acres at Central
Valley latitude — about ten times too large for a real spreading basin. A
basin that swallows half a city is the single most visible tell that makes a
domain expert stop trusting the rest of the map.

A recharge basin is an open area — cropland or rangeland — that is FLOODED
during storm events when water is diverted from a surface-water channel and
pooled to percolate into the aquifer. So each basin sits on open cropland
ADJACENT TO A CANAL (the diversion source) and must contain no structures —
you cannot flood a farmhouse. Central Valley spreading basins span a wide
range, up to ~120 acres; these two are placed at the larger, realistic end:

  - **Cressey-Winton Recharge Basin** — Cressey-Winton area, eastern Merced
    County (~110 acres) on open cropland beside an MID canal.
  - **El Nido Recharge Basin** — El Nido area, southern subbasin (~85 acres)
    on open cropland beside an MID canal.

Footprints are sized to TRUE acreage via ``recharge.geometry.area_accurate_box``
(which corrects for the cos(latitude) longitude compression), NOT a fixed
degree box. (MID's large "incidental" recharge happens via its ~700-mile canal
network, NOT a giant basin polygon — that belongs to the conceptual/ledger
layer later, never one enormous footprint.)

Idempotent: matched by name via ``update_or_create``, so a re-run refreshes the
location / footprint / attributes in place without duplicating. Additive — it
does NOT touch Kaweah, Demo Valley, or the Merced boundaries seeded by
``seed_merced_base``. ``zone`` is left null until Merced zones exist.
"""
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from recharge.geometry import SQ_M_PER_ACRE, area_accurate_box
from recharge.models import RechargeSite

# name, lon, lat, acres, capacity (AF, ~5 ft ponded depth × acres), operator.
# Coordinates sit on open cropland beside an MID canal (the diversion source),
# clear of farmsteads — confirmed against aerial imagery.
BASIN_CONFIGS = [
    {
        "name": "Cressey-Winton Recharge Basin",
        "lon": -120.666,
        "lat": 37.336,
        "acres": 110.0,
        "capacity_acre_feet": Decimal("550.0"),
        "operator": "Merced Irrigation District",
        "notes": (
            "Spreading basin on open cropland in the Cressey-Winton area of "
            "eastern Merced County, beside a Merced Irrigation District canal. "
            "~110 surface acres; flooded during storm events when water is "
            "diverted from the canal and pooled to percolate. Footprint sized "
            "to true acreage (area_accurate_box), not a fixed-degree box."
        ),
    },
    {
        "name": "El Nido Recharge Basin",
        "lon": -120.498,
        "lat": 37.125,
        "acres": 85.0,
        "capacity_acre_feet": Decimal("425.0"),
        "operator": "Merced Irrigation District",
        "notes": (
            "Spreading basin on open cropland in the El Nido area of the "
            "southern Merced Subbasin, beside a Merced Irrigation District "
            "canal. ~85 surface acres; flooded during storm events when water "
            "is diverted from the canal and pooled to percolate. Footprint "
            "sized to true acreage (area_accurate_box), not a fixed-degree box."
        ),
    },
]


class Command(BaseCommand):
    help = (
        "Seed the two real Merced Irrigation District recharge basins "
        "(Cressey-Winton ~20 ac, El Nido ~18 ac) at real coordinates with "
        "true-area footprints. Idempotent; additive (does not touch Kaweah)."
    )

    def handle(self, *args, **options):
        created = updated = 0
        for cfg in BASIN_CONFIGS:
            geom = area_accurate_box(cfg["lon"], cfg["lat"], cfg["acres"])
            defaults = {
                "site_type": "spreading_basin",
                "location": Point(cfg["lon"], cfg["lat"], srid=4326),
                "geometry": geom,
                "capacity_acre_feet": cfg["capacity_acre_feet"],
                "status": "active",
                "operator": cfg["operator"],
                "notes": cfg["notes"],
            }
            obj, was_created = RechargeSite.objects.update_or_create(
                name=cfg["name"], defaults=defaults,
            )
            # Report the true (equal-area) acreage so the operator can see the
            # footprint is right-sized, not just trust the input number.
            true_acres = obj.geometry.transform(3310, clone=True).area / SQ_M_PER_ACRE
            verb = "Created" if was_created else "Updated"
            self.stdout.write(self.style.SUCCESS(
                f"  {verb}: {cfg['name']} "
                f"(target {cfg['acres']:.0f} ac, true {true_acres:.1f} ac)"
            ))
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced recharge basins seeded: {created} created, "
            f"{updated} updated."
        ))
