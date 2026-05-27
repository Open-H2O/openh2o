"""
Management command to backfill area_acres from PostGIS geometry.

Finds all parcels with geometry set but area_acres null,
computes area from geometry using geography cast, and updates each row.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection

from parcels.models import Parcel

ACRES_PER_SQ_METER = Decimal("4046.8564224")


class Command(BaseCommand):
    help = "Recalculate area_acres from geometry for parcels missing acreage data."

    def handle(self, *args, **options):
        parcel_ids = list(
            Parcel.objects.filter(
                geometry__isnull=False,
                area_acres__isnull=True,
            ).values_list("pk", flat=True)
        )

        if not parcel_ids:
            self.stdout.write(self.style.SUCCESS("No parcels need area recalculation."))
            return

        count = 0
        for pk in parcel_ids:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ST_Area(geometry::geography) FROM parcels_parcel WHERE id = %s",
                    [pk],
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    area_sq_m = Decimal(str(row[0]))
                    area_acres = (area_sq_m / ACRES_PER_SQ_METER).quantize(Decimal("0.01"))
                    Parcel.objects.filter(pk=pk).update(area_acres=area_acres)
                    count += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {count} parcel(s)."))
