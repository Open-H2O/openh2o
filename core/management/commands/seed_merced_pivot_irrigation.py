# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Set parcels.ParcelIrrigationMethod to the seeded "Center Pivot" row on every
use area whose outline is visibly a circle (146-05 checkpoint, Brent's
ruling 1, 2026-09-23).

WHY: MER-APN-001 through MER-APN-009 are round on the aerial map -- a center
pivot's own signature, and the reason a reader can tell just by looking.
Measured on staging (main session, 2026-09-23):

    ST_Area(g_3310) / ST_Area(ST_MinimumBoundingCircle(g_3310))

with each use area's geometry transformed to EPSG:3310 (California Albers, an
equal-area projection in meters, so the ratio is not a degrees-of-longitude
artifact) is 0.968-0.984 for exactly those 9 of the demonstration's 76 use
areas and at most 0.656 for every other one (a square sits near 0.637, its
own known value: 2/pi). 0.90 is comfortably below the 9 real pivots and
comfortably above every other shape.

This is DEMO data: the classification is derived from the real DWR-surveyed
field outline's SHAPE (`seed_merced_parcels_from_selection` reads real
crop-field polygons), never a claim about how the underlying farm is actually
irrigated. Phase 148 made the engine read it (`parcels.services.field_efficiency`).

Idempotent: a re-run changes nothing, because it is keyed by parcel and NEVER
overwrites a use area that already carries a method -- an operator's choice,
or an earlier run of this same command, stands. Skipped cleanly (no error, no
rows written) when `parcels` is off. Until 150.2-01 it was skipped when
`surface` was off, because `ParcelIrrigationMethod` lived there; it lives in
`parcels` now, so a groundwater-only demonstration gets its pivots too.

Not `MER-`-restricted: the test is purely geometric (this use area's own
shape against its own bounding circle), so it runs over every use area with
geometry, the way the shape itself would look to a reader regardless of what
seeded it. In this repository only the Merced demonstration ever seeds use
areas with geometry, so in practice this only ever touches the demo -- but it
makes no assumption about a parcel's number to reach that answer.

Standalone use: this command is *also* the one to run by hand against an
already-seeded deployment (e.g. staging) to apply ruling 1 to data seeded
before this command existed:

    python manage.py seed_merced_pivot_irrigation
"""
from django.core.management.base import BaseCommand
from django.db import connection

from core.modules import is_enabled
from parcels.models import IrrigationMethod, Parcel, ParcelIrrigationMethod

#: Comfortably below the 9 real pivots (0.968-0.984, measured on staging) and
#: comfortably above every other shape (squares near 0.637, everything else
#: at or under 0.656). 146-05-EVIDENCE.md has the full measurement.
CIRCULARITY_THRESHOLD = 0.90

#: The name a data migration (parcels/0013_irrigation_method) seeds
#: this row under, verbatim from East Turlock Subbasin GSA's table.
CENTER_PIVOT = "Center Pivot"


class Command(BaseCommand):
    help = (
        "Set parcels.ParcelIrrigationMethod to 'Center Pivot' on every use "
        "area whose outline fills at least 90% of its minimum bounding "
        "circle. Idempotent; never overwrites a method already set; no-op "
        "when the parcels module is off."
    )

    def handle(self, *args, **options):
        if not is_enabled("parcels"):
            self.stdout.write(
                self.style.WARNING(
                    "parcels module is off -- this deployment keeps no use "
                    "areas. Skipping pivot classification."
                )
            )
            return

        try:
            center_pivot = IrrigationMethod.objects.get(name=CENTER_PIVOT)
        except IrrigationMethod.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    f"No '{CENTER_PIVOT}' row in parcels.IrrigationMethod -- "
                    "has migration parcels 0013_irrigation_method run? Skipping."
                )
            )
            return

        table = Parcel._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id,
                       ST_Area(ST_Transform(geometry, 3310))
                         / NULLIF(
                             ST_Area(ST_MinimumBoundingCircle(
                                 ST_Transform(geometry, 3310)
                             )),
                             0
                           ) AS circularity
                FROM {table}
                WHERE geometry IS NOT NULL
                """
            )
            ratios = {pk: ratio for pk, ratio in cursor.fetchall() if ratio is not None}

        already_set = set(
            ParcelIrrigationMethod.objects.filter(parcel_id__in=ratios)
            .values_list("parcel_id", flat=True)
        )

        pivot_pks = sorted(
            pk
            for pk, ratio in ratios.items()
            if ratio >= CIRCULARITY_THRESHOLD and pk not in already_set
        )

        ParcelIrrigationMethod.objects.bulk_create(
            [
                ParcelIrrigationMethod(parcel_id=pk, method=center_pivot)
                for pk in pivot_pks
            ]
        )

        already_had_method_count = len(already_set)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(pivot_pks)} use area(s) newly set to Center Pivot by "
                f"outline shape (>= {CIRCULARITY_THRESHOLD:.0%} of minimum "
                f"bounding circle); {already_had_method_count} use area(s) "
                "already carried a method and were left unchanged."
            )
        )
