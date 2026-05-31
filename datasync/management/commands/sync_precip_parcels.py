# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sync per-parcel monthly precipitation into OpenETCache — the rainfall faucet the
calculation engine (Phase 38) needs to net effective precip out of gross ET.

Unlike ET, precip has NO REST tier: GRIDMET ``pr`` is sampled per-parcel only via
Earth Engine, so this command always goes through GEE directly (it does NOT route
on OPENET_MODE). It mirrors ``sync_openet_parcels`` flag-for-flag and writes
``OpenETCache`` rows with ``variable="precip"``, ``model_name="GRIDMET"``,
idempotently per (parcel, window) so re-runs never duplicate.

Usage:
  python manage.py sync_precip_parcels --start-date 2024-06-01 --end-date 2024-08-31
  python manage.py sync_precip_parcels --start-date 2024-06-01 --end-date 2024-08-31 \
      --parcel-prefix KAW- --limit 5 --dry-run
"""

import logging
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from datasync.adapters.gee import (
    build_precip_data,
    init_earth_engine,
    reduce_precip_by_parcel,
)
from parcels.models import Parcel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync per-parcel monthly precipitation (GRIDMET pr, mm) into OpenETCache "
        "with variable='precip', via Earth Engine. GEE-only (no REST tier)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True, help="YYYY-MM-DD.")
        parser.add_argument("--end-date", required=True, help="YYYY-MM-DD.")
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the number of parcels (cheap test runs).",
        )
        parser.add_argument(
            "--parcel-prefix",
            default=None,
            help="Only parcels whose number starts with this (e.g. KAW-).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report selected parcels + window (no Earth Engine calls, no writes).",
        )

    def handle(self, *args, **options):
        try:
            start_date = datetime.strptime(options["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(options["end_date"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}. Use YYYY-MM-DD.") from exc
        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date.")

        # Same selection as sync_openet_parcels: geometry is required (we sample
        # the polygon), area_acres is required because the engine later converts
        # mm -> acre-feet over the parcel's area.
        qs = Parcel.objects.filter(geometry__isnull=False, area_acres__isnull=False)
        prefix = options["parcel_prefix"]
        if prefix:
            qs = qs.filter(parcel_number__startswith=prefix)
        qs = qs.order_by("parcel_number")
        if options["limit"]:
            qs = qs[: options["limit"]]
        parcels = list(qs)

        if not parcels:
            raise CommandError(
                "No parcels match the filters (need geometry + area_acres"
                + (f", prefix {prefix!r}" if prefix else "")
                + "). Load parcel data first (e.g. seed_kaweah)."
            )

        self.stdout.write(
            f"GRIDMET precip -> {len(parcels)} parcel(s), {start_date} .. {end_date}"
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] No Earth Engine calls, no writes. Selected:")
            )
            for parcel in parcels:
                self.stdout.write(f"  {parcel.parcel_number}")
            return

        try:
            ee = init_earth_engine()
        except RuntimeError as exc:
            # GEE not configured is the expected gate here, not a crash.
            raise CommandError(
                f"Precip sync needs the Earth Engine tier configured: {exc}"
            ) from exc

        try:
            result = reduce_precip_by_parcel(ee, parcels, start_date, end_date)
        except Exception as exc:
            raise CommandError(f"GRIDMET precip sync failed: {exc}") from exc

        from datasync.models import OpenETCache

        written = 0
        parcel_months = 0
        for parcel in parcels:
            precip_by_month = result.get(parcel.pk, {})
            if not precip_by_month:
                continue
            OpenETCache.objects.update_or_create(
                parcel=parcel,
                start_date=start_date,
                end_date=end_date,
                variable="precip",
                defaults={
                    "geometry": parcel.geometry,
                    "model_name": "GRIDMET",
                    "et_data": build_precip_data(precip_by_month),
                },
            )
            written += 1
            parcel_months += len(precip_by_month)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("sync_precip_parcels complete"))
        self.stdout.write(f"  parcels written:  {written}")
        self.stdout.write(f"  parcel-months:    {parcel_months}")
