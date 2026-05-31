# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drive the OpenET adapter over parcels — the live parcel-ET sync path.

Until this command existed, nothing actually called the OpenET adapter's
parcel-sync (the REST `sync_parcel_et` had no caller, and the demo's ET is
seed-random). This is the single live entry point for BOTH tiers: it resolves
the adapter via `get_openet_adapter()`, so `OPENET_MODE=gee` routes the batched
Earth Engine adapter and the default `api` routes the REST adapter, with no
change to how you invoke it.

Populates `OpenETCache`. To go all the way to the ledger in one shot, pass
`--to-ledger` and it chains `sync_openet_to_ledger` for the same window.

Usage:
  python manage.py sync_openet_parcels --start-date 2024-06-01 --end-date 2024-08-31
  python manage.py sync_openet_parcels --start-date 2024-06-01 --end-date 2024-08-31 \
      --parcel-prefix KAW- --limit 5 --dry-run
  python manage.py sync_openet_parcels --start-date 2024-06-01 --end-date 2024-08-31 \
      --to-ledger
"""

import logging
from datetime import date, datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from datasync.adapters import get_openet_adapter
from parcels.models import Parcel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync OpenET ET into OpenETCache for parcels, via the tier selected by "
        "OPENET_MODE (api=REST default, gee=batched Earth Engine)."
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
            help="Report what WOULD be fetched (no Earth Engine calls, no writes).",
        )
        parser.add_argument(
            "--to-ledger",
            action="store_true",
            default=False,
            help="After populating the cache, chain sync_openet_to_ledger for the window.",
        )

    def handle(self, *args, **options):
        try:
            start_date = datetime.strptime(options["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(options["end_date"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}. Use YYYY-MM-DD.") from exc
        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date.")

        # Select parcels. area_acres is required because the ledger step converts
        # mm -> acre-feet over the parcel's area.
        qs = Parcel.objects.filter(
            geometry__isnull=False, area_acres__isnull=False
        )
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

        mode = getattr(settings, "OPENET_MODE", "api")
        adapter = get_openet_adapter()
        self.stdout.write(
            f"OPENET_MODE={mode} -> {type(adapter).__name__} "
            f"({len(parcels)} parcel(s), {start_date} .. {end_date})"
        )

        if options["dry_run"]:
            self._dry_run(adapter, parcels, start_date, end_date)
            return

        try:
            summary = adapter.sync_parcel_et(parcels, start_date, end_date)
        except Exception as exc:
            # A batch EE failure (auth/coverage) is systemic — report cleanly
            # rather than dumping a traceback at the operator.
            raise CommandError(f"OpenET sync failed: {exc}") from exc

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("sync_openet_parcels complete"))
        for key, value in summary.items():
            self.stdout.write(f"  {key + ':':<16} {value}")

        if options["to_ledger"]:
            self.stdout.write("")
            self.stdout.write("Chaining sync_openet_to_ledger for the same window...")
            call_command(
                "sync_openet_to_ledger",
                start_date=options["start_date"],
                end_date=options["end_date"],
            )

    def _dry_run(self, adapter, parcels, start_date, end_date):
        """Report months-to-fetch per parcel without initializing Earth Engine."""
        months_needing = getattr(adapter, "_months_needing_fetch", None)
        if months_needing is None:
            # REST tier has no finalized-skip preview; just show the selection.
            self.stdout.write(
                self.style.WARNING(
                    "[DRY RUN] REST tier has no month-skip preview. Selected parcels:"
                )
            )
            for parcel in parcels:
                self.stdout.write(f"  {parcel.parcel_number}")
            return

        needs = months_needing(parcels, start_date, end_date, date.today())
        self.stdout.write(self.style.WARNING("[DRY RUN] No Earth Engine calls, no writes."))
        total = 0
        for parcel in parcels:
            to_fetch = needs.get(parcel.pk, [])
            total += len(to_fetch)
            months = ", ".join(to_fetch) if to_fetch else "(fully cached)"
            self.stdout.write(f"  {parcel.parcel_number:<16} {len(to_fetch)} month(s): {months}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"[DRY RUN] Would fetch {total} parcel-month(s) across "
                f"{len(parcels)} parcel(s)."
            )
        )
