# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcel signals.

Auto-computes area_acres from PostGIS geometry when a parcel is saved
with geometry set but no area_acres value.
"""

import logging
from decimal import Decimal

from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# 1 acre = 4046.8564224 square meters
ACRES_PER_SQ_METER = Decimal("4046.8564224")


def _compute_area_acres(parcel_pk):
    """Compute area in acres from PostGIS geometry using geography cast.

    Uses ST_Area(geometry::geography) for accurate geodetic area in square meters,
    then converts to acres. The geography cast is required because ST_Area on
    geometry with SRID 4326 returns square degrees, not square meters.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Area(geometry::geography) FROM parcels_parcel WHERE id = %s",
            [parcel_pk],
        )
        row = cursor.fetchone()
        if row and row[0] is not None:
            area_sq_m = Decimal(str(row[0]))
            return (area_sq_m / ACRES_PER_SQ_METER).quantize(Decimal("0.01"))
    return None


@receiver(post_save, sender="parcels.Parcel")
def auto_compute_area_acres(sender, instance, **kwargs):
    """Compute area_acres from geometry when geometry is set and area_acres is null.

    Respects area_override: if True, area_acres is never touched regardless of
    whether it is null or has a value (user has manually set it).

    Uses queryset.update() to avoid infinite recursion (does not re-trigger save).
    """
    if instance.area_override:
        return
    if instance.geometry is not None and instance.area_acres is None:
        area_acres = _compute_area_acres(instance.pk)
        if area_acres is not None:
            sender.objects.filter(pk=instance.pk).update(area_acres=area_acres)
            # Update in-memory instance so callers see the new value
            instance.area_acres = area_acres
            logger.info(
                "Auto-computed area_acres=%.2f for parcel %s",
                area_acres,
                instance.parcel_number,
            )
