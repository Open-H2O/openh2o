# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Management command to backfill area_acres from PostGIS geometry.

A repair: the parcel download and every save already fill acreage. Fills each
use area that has an outline, no acreage and no hand-set acreage, in one
statement (parcels.areas.fill_area_acres), with the save receiver's formula.
"""

from django.core.management.base import BaseCommand

from parcels.areas import fill_area_acres


class Command(BaseCommand):
    help = "Recalculate area_acres from geometry for parcels missing acreage data."

    def handle(self, *args, **options):
        count = fill_area_acres()
        if not count:
            self.stdout.write(self.style.SUCCESS("No parcels need area recalculation."))
            return
        self.stdout.write(self.style.SUCCESS(f"Updated {count} parcel(s)."))
