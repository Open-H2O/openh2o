# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed the three Groundwater Sustainability Agencies (GSAs) that govern the
Merced Subbasin, as ``management_area`` zones — the groundwater authority,
distinct from the surface-water district (the canal headgates).

WHY: SGMA splits the two jobs. The surface-water district moves canal water
to fields (modeled as water rights + points of diversion). The GSA manages
groundwater pumping (modeled as a management-area zone a well/parcel falls
within). (the same management-area-zone pattern any subbasin's GSAs use).

The three GSA zones (DWR Bulletin 118 subbasin 5-022.04) come from the
state's SGMA boundary service, committed as data/merced/merced_gsas.geojson
(EPSG:4326):

    Boundaries/i03_Groundwater_Sustainability_Agencies, filtered to
    Basin_Subbasin_Number = '5-022.04'.

**The geometry is that authoritative public boundary, unaltered. The names
are not.** Phase 97 replaced each feature's ``GSA_Name`` with a fictional
agency, and blanked the real DWR ``GSA_ID`` and agency ``GSA_URL``, because
these zones are the container the demo's entirely invented parcels and
pumping ledgers sit in — and naming a real public agency as the authority
over invented accounting is the defect that phase exists to delete. So do
not "restore" the names by re-fetching the layer: re-fetch would return the
real agencies and re-introduce the defect. Refresh the *geometry* from the
service if it changes; keep the fictional identity.

Idempotent (update_or_create by name); additive (only these three zones).
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
        "Seed the three GSAs of the Merced Subbasin (5-022.04) as "
        "management_area zones from committed SGMA-portal GeoJSON. "
        "Idempotent; additive."
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
