# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Backfill demo owner names onto Kaweah parcels (KAW-APN-*).

The Kaweah parcels are real Tulare County geometries whose only source
attribute is a land-use classification (USEDSCRP). An earlier seed stored
that land-use string in `owner_name`, so the map popup and detail pages
showed the crop under an "Owner" label. This command replaces those values
with realistic demo owner names — consistent with the rest of the synthetic
Kaweah dataset (wells, water rights, recharge sites already carry demo names).

Touches ONLY the `owner_name` display field. Geometry, ledger rows, primary
keys, and all accounting data are untouched. Deterministic and idempotent:
the same parcel always gets the same owner, so re-running changes nothing.
The granular land use remains available via each parcel's UsageLocation /
crop type — it is not lost from the platform.
"""
from django.core.management.base import BaseCommand

from parcels.models import Parcel

# Demo-grade Central Valley agricultural operations. Plainly synthetic names
# in the style of Tulare County farms, trusts, and grower partnerships.
KAWEAH_PARCEL_OWNERS = [
    "Sierra Vista Ranch",
    "Kaweah Delta Farms",
    "Oak Valley Orchards LLC",
    "Three Rivers Citrus Co.",
    "Cottonwood Creek Growers",
    "Lindsay Grove Partners",
    "Yokohl Valley Ranch",
    "Cutler Family Trust",
    "St. Johns River Farms",
    "Exeter Foothill Orchards",
    "Venice Hills Ag Holdings",
    "Dry Creek Land Co.",
    "Woodlake Grove Partners",
    "Frazier Valley Farms",
    "Persian Gardens Citrus",
    "Stokes Mountain Ranch",
    "Antelope Plains Farming",
    "Deep Creek Orchards LLC",
]


class Command(BaseCommand):
    help = (
        "Assign realistic demo owner names to Kaweah parcels (KAW-APN-*). "
        "Deterministic and idempotent; touches only owner_name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        parcels = Parcel.objects.filter(
            parcel_number__startswith="KAW-APN-"
        ).order_by("parcel_number")

        total = parcels.count()
        if not total:
            self.stdout.write("No KAW-APN- parcels found; nothing to backfill.")
            return

        updated = 0
        for i, parcel in enumerate(parcels):
            new_owner = KAWEAH_PARCEL_OWNERS[i % len(KAWEAH_PARCEL_OWNERS)]
            if parcel.owner_name != new_owner:
                if not dry_run:
                    parcel.owner_name = new_owner
                    parcel.save(update_fields=["owner_name", "updated_at"])
                updated += 1

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {updated} of {total} Kaweah parcel owner name(s)."
            )
        )
