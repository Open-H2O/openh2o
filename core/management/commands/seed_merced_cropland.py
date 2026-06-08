# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed crop land-use for the irrigated Merced parcels (Phase 52.5-01).

WHY this command exists. The calc engine's ``facility_only_zero`` step
(accounting/steps.py) forces a parcel's computed extraction to 0 unless the
parcel has at least one ``UsageLocation`` carrying a non-null ``crop_type`` —
those parcels are treated as facility-only and pump nothing billable. Phases
50–52 built the physical + accounting Merced demo but deliberately left
``CropType`` / ``UsageLocation`` out of scope (synthetic volumes were
``area × rate``, never crop-ET-derived). The side effect: EVERY Merced parcel
currently reads as facility-only, so a real ``run_calculations`` pass would zero
all of them. This command closes that gap — it gives every IRRIGATED Merced
parcel (one served by a well or a point of diversion) a ``UsageLocation`` with a
``crop_type``, so the engine passes it through. It is the land-use prerequisite
for routing Merced through the real engine (Plan 02).

This is a thin demonstration seed, not a crop model. The exact crop mix is not
load-bearing; what matters is only that each irrigated parcel carries SOME
``crop_type`` so it is not facility-only.

DETERMINISTIC + IDEMPOTENT + ADDITIVE. Crops are assigned by parcel index (no
``random``), so re-runs reproduce identical rows. The command keys its rows on
(parcel, name) via ``update_or_create`` and then prunes any stale Merced
UsageLocation a run did not (re)create — so a bare re-run creates nothing, leaves
counts unchanged, and a parcel that dropped out of the irrigated set is cleaned
up. It only ever touches MER- parcels' UsageLocations; Demo Valley land use is
untouched.

Prerequisite (the physical demo must already exist on this instance)::

    python manage.py seed_merced_parcels_from_selection   # the MER- parcels, OR
    python manage.py seed_merced                          # the full demo
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from parcels.models import CropType, Parcel, UsageLocation
from surface.models import PointOfDiversionParcel
from wells.models import WellIrrigatedParcel

MER_PARCEL_PREFIX = "MER-APN-"

# A small reference set of realistic San-Joaquin-Valley crops, as (name, code).
# Assigned round-robin by parcel index — the mix is illustrative, not modeled.
CROPS = [
    ("Almonds", "ALM"),
    ("Alfalfa", "ALF"),
    ("Corn", "CRN"),
    ("Grapes", "GRP"),
    ("Tomatoes", "TOM"),
]


class Command(BaseCommand):
    help = (
        "Give every irrigated Merced parcel a crop-type UsageLocation so the "
        "calc engine's facility_only_zero step passes it through. Idempotent; "
        "additive (MER-keyed; never touches Demo Valley land use)."
    )

    def add_arguments(self, parser):
        # Accepted for orchestrator symmetry. The command is idempotent with or
        # without it (update_or_create + stale-prune), so it is a no-op alias.
        parser.add_argument(
            "--flush", action="store_true",
            help="No-op alias: this seed is idempotent on its own.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            created, total = self._seed()
        self.stdout.write(self.style.SUCCESS(
            f"\nMerced crop land-use: {created} UsageLocation(s) created; "
            f"{total} irrigated parcel(s) now carry a crop_type."
        ))

    def _seed(self):
        parcels = list(Parcel.objects.filter(
            parcel_number__startswith=MER_PARCEL_PREFIX).order_by("parcel_number"))
        if not parcels:
            self.stdout.write(self.style.WARNING(
                "No MER- parcels found. Run seed_merced_parcels_from_selection "
                "(or `make merced`) first — nothing to give land use to."
            ))
            return 0, 0

        # The crop reference set (idempotent by name; code filled on first create).
        crop_objs = [
            CropType.objects.get_or_create(name=name, defaults={"code": code})[0]
            for name, code in CROPS
        ]

        # "Irrigated" = linked to a well OR to a point of diversion — i.e. every
        # parcel the accounting layer treats as surface, groundwater, or
        # conjunctive. Derived from PHYSICAL LINKS exactly like seed_merced_ledgers,
        # never a hardcoded parcel list.
        parcel_ids = [p.id for p in parcels]
        irrigated_ids = set(
            WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids)
            .values_list("parcel_id", flat=True)
        ) | set(
            PointOfDiversionParcel.objects.filter(parcel_id__in=parcel_ids)
            .values_list("parcel_id", flat=True)
        )

        kept_ids = []
        created = 0
        for i, p in enumerate(parcels):
            if p.id not in irrigated_ids:
                continue
            crop = crop_objs[i % len(crop_objs)]
            # UsageLocation.geometry is a PointField; the parcel geometry is a
            # polygon, so anchor the usage location at its centroid.
            point = p.geometry.centroid if p.geometry is not None else None
            usage, was_created = UsageLocation.objects.update_or_create(
                parcel=p, name=f"{crop.name} field",
                defaults={
                    "crop_type": crop,
                    "area_acres": p.area_acres,
                    "geometry": point,
                },
            )
            kept_ids.append(usage.id)
            created += int(was_created)

        # Prune any stale MER UsageLocation this run did not (re)create — a parcel
        # that dropped out of the irrigated set, or an old "<crop> field" left by a
        # crop reassignment. Keeps re-runs from accumulating orphans.
        UsageLocation.objects.filter(
            parcel__parcel_number__startswith=MER_PARCEL_PREFIX
        ).exclude(id__in=kept_ids).delete()

        return created, len(kept_ids)
