# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed the real Merced boundary that forms the v1.9 demonstration's
spatial canvas:

  - **Merced Subbasin** — DWR Bulletin 118 basin 5-022.04 ("San Joaquin
    Valley - Merced"). The complex, critically-overdrafted valley floor.

The upper Merced River watershed was REMOVED from the demonstration: its
only free-flowing reaches sit high in the Sierra (the foothill stretch is
Lake McClure reservoir), so a district-scale diversion there is
geographically honest but operationally implausible. The simple-vs-complex
contrast now lives entirely within the valley floor. Do not re-add it.

The geometry is committed under ``data/merced/`` as EPSG:4326 GeoJSON
so the demo is reproducible from authoritative public sources (the same
doctrine as ``data/kaweah/``). Provenance lives in ``data/merced/README.md``.

This command loads ONLY the boundary. Rivers, canals, and stations are
populated separately by driving the platform's own loaders:

    python manage.py auto_populate --boundary "Merced Subbasin" --steps flowlines,stations

Idempotent: re-running updates the existing boundary's geometry and
attributes in place (matched by name), so a refreshed fixture re-seeds
cleanly without creating duplicates. Merced is additive — it does NOT
touch Kaweah or Demo Valley data.
"""
import json
import os
from decimal import Decimal

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand

from geography.models import Boundary

# Each entry: fixture filename + the Boundary fields to set/refresh. The
# geometry comes from the file; everything else is the curated identity.
BOUNDARY_CONFIGS = [
    {
        "filename": "lower_merced_subbasin.geojson",
        "name": "Merced Subbasin",
        "basin_code": "5-022.04",
        "huc": "",
        # Authoritative DWR Bulletin 118 statutory area. (The Merced
        # Subbasin GSP cites ~767 sq mi / ~491,000 acres for its managed
        # area; the larger figure here is the B118 basin outline itself.)
        "area_sq_miles": Decimal("800.948"),
        "description": (
            "DWR Bulletin 118 Merced Subbasin (5-022.04), part of the San "
            "Joaquin Valley Groundwater Basin. Valley floor south of the "
            "Merced River to the Chowchilla, San Joaquin River on the west, "
            "Sierra foothills on the east. Critically overdrafted under SGMA; "
            "served by Merced Irrigation District's canal network and three "
            "GSAs (MIUGSA, MSGSA, TIWD-1). The complex 'lower' half of the "
            "Merced demonstration."
        ),
    },
]


class Command(BaseCommand):
    help = (
        "Seed the real Merced Subbasin boundary (5-022.04) from "
        "committed public-source GeoJSON. "
        "Idempotent; additive (does not touch Kaweah or Demo Valley)."
    )

    def handle(self, *args, **options):
        data_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "merced",
        )

        created = updated = 0
        for cfg in BOUNDARY_CONFIGS:
            path = os.path.join(data_dir, cfg["filename"])
            with open(path) as f:
                fc = json.load(f)

            geom = GEOSGeometry(json.dumps(fc["features"][0]["geometry"]))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon(geom)

            if not geom.valid:
                # Repair self-intersections rather than store an invalid
                # geometry that would break spatial queries downstream.
                geom = geom.buffer(0)
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom)

            defaults = {
                "geometry": geom,
                "description": cfg["description"],
                "basin_code": cfg["basin_code"],
                "huc": cfg["huc"],
                "area_sq_miles": cfg["area_sq_miles"],
            }
            obj, was_created = Boundary.objects.update_or_create(
                name=cfg["name"], defaults=defaults,
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  Created: {cfg['name']} "
                    f"({cfg['basin_code'] or 'no basin code'}, "
                    f"{cfg['area_sq_miles']} sq mi)"
                ))
            else:
                updated += 1
                self.stdout.write(
                    f"  Updated existing: {cfg['name']}"
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced base geography seeded: {created} created, "
            f"{updated} updated."
        ))
