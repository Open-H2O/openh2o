# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed the three Groundwater Sustainability Agencies (GSAs) that govern the
Merced Subbasin, as ``management_area`` zones — the groundwater authority,
distinct from the surface-water district (the canal headgates).

WHY: SGMA splits the two jobs. The surface-water district moves canal water
to fields (modeled as water rights + points of diversion). The GSA manages
groundwater pumping (modeled as a management-area zone a well/parcel falls
within). (the same management-area-zone pattern any subbasin's GSAs use).

The three Merced GSAs (DWR Bulletin 118 subbasin 5-022.04) come from the
state's SGMA boundary service, committed as data/merced/merced_gsas.geojson
(EPSG:4326) so the demo is reproducible from authoritative public sources:

    Boundaries/i03_Groundwater_Sustainability_Agencies, filtered to
    Basin_Subbasin_Number = '5-022.04'.

Idempotent (update_or_create by name); additive (only Merced GSAs).
"""
import json
import os

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError

from geography.models import Boundary, Zone

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "data", "merced", "merced_gsas.geojson",
)
SUBBASIN = "Merced Subbasin"


class Command(BaseCommand):
    help = (
        "Seed the three Merced Subbasin GSAs (5-022.04) as management_area "
        "zones from committed SGMA-portal GeoJSON. Idempotent; additive."
    )

    def handle(self, *args, **options):
        boundary = Boundary.objects.filter(name=SUBBASIN).first()
        if boundary is None:
            raise CommandError(
                f"Boundary '{SUBBASIN}' not found. Run seed_merced_base first."
            )
        with open(FIXTURE) as f:
            features = json.load(f)["features"]

        created = updated = 0
        for ft in features:
            name = ft["properties"]["GSA_Name"]
            geom = GEOSGeometry(json.dumps(ft["geometry"]))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon(geom)
            if not geom.valid:
                geom = geom.buffer(0)
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom)
            _, was_created = Zone.objects.update_or_create(
                name=name,
                defaults={
                    "boundary": boundary,
                    "geometry": geom,
                    "zone_type": "management_area",
                    "basin_code": "5-022.04",
                    "description": (
                        "Groundwater Sustainability Agency governing part of "
                        "the Merced Subbasin under SGMA. Groundwater authority "
                        "(distinct from the surface-water district)."
                    ),
                },
            )
            created += was_created
            updated += not was_created
            self.stdout.write(f"  {'Created' if was_created else 'Updated'}: {name}")

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced GSAs seeded: {created} created, {updated} updated "
            f"({Zone.objects.filter(basin_code='5-022.04').count()} total)."
        ))
