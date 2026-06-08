# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Prove the Earth Engine tier end to end, headlessly.

This is the go/no-go gate for the GEE OpenET tier (Phase 37). It:

1. Authenticates to Google Earth Engine with a SERVICE ACCOUNT (no browser),
   the way a headless server must. Auth failure is fatal and printed verbatim,
   because "can it run headless?" is the question this command exists to answer.
2. Picks a few real parcels that ALSO have existing OpenET REST cache rows, so
   the GEE numbers can be compared against the REST numbers.
3. Pulls the SAME OpenET Ensemble monthly collection the REST tier serves
   (projects/openet/assets/ensemble/conus/gridmet/monthly/v2_1, band
   et_ensemble_mad, ET in mm) via polygon reduceRegions, synchronously.
4. Assembles per-parcel ET in the EXACT shape the REST path writes to
   OpenETCache.et_data, and prints a GEE-vs-REST comparison table.
5. With --write-cache, writes those GEE results to OpenETCache so that the
   existing `sync_openet_to_ledger --dry-run` can confirm the cache to ledger
   contract is satisfied unchanged.

Usage:
  python manage.py prove_gee_auth --limit 5
  python manage.py prove_gee_auth --limit 5 --start-date 2023-06-01 --end-date 2023-07-31
  python manage.py prove_gee_auth --limit 5 --write-cache
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datasync.adapters.gee import (
    _first_of_month,
    _first_of_next_month,
    build_et_data,
    init_earth_engine,
    reduce_et_by_parcel,
)
from datasync.models import OpenETCache
from parcels.models import Parcel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Prove headless Earth Engine auth + polygon reduceRegions ET against "
        "real parcels, and compare to the OpenET REST cache."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of parcels to test (default 5).",
        )
        parser.add_argument(
            "--start-date",
            default=None,
            help="Start date YYYY-MM-DD. Defaults to a 2-month window found in "
            "the REST cache for the selected parcels.",
        )
        parser.add_argument(
            "--end-date",
            default=None,
            help="End date YYYY-MM-DD. Defaults alongside --start-date.",
        )
        parser.add_argument(
            "--write-cache",
            action="store_true",
            default=False,
            help="Write GEE results to OpenETCache (default OFF: read-only proof).",
        )

    # -- parcel + window selection ------------------------------------------

    def _select_parcels(self, limit):
        """Pick real parcels to test.

        Prefer parcels that already have an OpenET REST cache row, so the proof
        can show GEE vs REST side by side. If none exist (e.g. a demo DB that
        never ran a live REST sync), fall back to any parcels with geometry +
        area: the GEE auth + reduceRegions proof still stands, just without a
        REST baseline to compare against. Returns (parcels, has_rest_baseline).
        """
        cached_parcel_ids = list(
            OpenETCache.objects.filter(parcel__isnull=False)
            .values_list("parcel_id", flat=True)
            .distinct()
        )
        if cached_parcel_ids:
            parcels = list(
                Parcel.objects.filter(
                    pk__in=cached_parcel_ids,
                    geometry__isnull=False,
                    area_acres__isnull=False,
                ).order_by("parcel_number")[:limit]
            )
            if parcels:
                return parcels, True

        parcels = list(
            Parcel.objects.filter(
                geometry__isnull=False, area_acres__isnull=False
            ).order_by("parcel_number")[:limit]
        )
        if not parcels:
            raise CommandError(
                "No parcels with geometry + area_acres found. Load parcel data "
                "first (e.g. seed_demo_data)."
            )
        self.stdout.write(
            self.style.WARNING(
                "No OpenET REST cache rows on this DB; running GEE-only proof "
                "(no REST baseline to compare against)."
            )
        )
        return parcels, False

    def _rest_lookup(self, parcels):
        """Build {parcel_id: {YYYY-MM: et_mm}} from REST OpenETCache rows.

        Mirrors how sync_openet_to_ledger reads et_data: month key = date[:7],
        values summed per month.
        """
        lookup = defaultdict(lambda: defaultdict(Decimal))
        rows = OpenETCache.objects.filter(parcel__in=parcels).order_by("queried_at")
        for row in rows:
            for item in row.et_data or []:
                raw_date = item.get("date", "")
                et_value = item.get("et")
                if et_value is None or len(raw_date) < 7:
                    continue
                month_key = raw_date[:7]
                lookup[row.parcel_id][month_key] += Decimal(str(et_value))
        return lookup

    def _resolve_window(self, parcels, start_opt, end_opt, rest_lookup):
        """Use provided dates, else the latest 2 months present in the REST cache."""
        if start_opt and end_opt:
            try:
                start = datetime.strptime(start_opt, "%Y-%m-%d").date()
                end = datetime.strptime(end_opt, "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError(f"Invalid date: {exc}. Use YYYY-MM-DD.") from exc
            if end < start:
                raise CommandError("--end-date must be >= --start-date.")
            return start, end

        months = sorted(
            {m for pmonths in rest_lookup.values() for m in pmonths.keys()}
        )
        if not months:
            # No REST baseline to derive a window from. Default to a peak-season
            # 2-month window in a year with settled OpenET coverage; summer ET
            # is a strong, easy-to-sanity-check signal for irrigated crops.
            self.stdout.write(
                "No REST window to borrow; defaulting to 2023-06-01..2023-07-31 "
                "(override with --start-date/--end-date)."
            )
            return date(2023, 6, 1), date(2023, 7, 31)
        chosen = months[-2:] if len(months) >= 2 else months
        start = datetime.strptime(chosen[0], "%Y-%m").date()
        end_month = datetime.strptime(chosen[-1], "%Y-%m").date()
        # end = last day of the latest chosen month (next month's first day - 1)
        end = _first_of_next_month(end_month) - timedelta(days=1)
        return start, end

    # -- the proof ----------------------------------------------------------

    def _print_table(self, parcels, months, gee, rest):
        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "GEE vs REST monthly ET (mm) — polygon mean vs REST cache"
            )
        )
        header = f"{'parcel':<16}{'month':<10}{'GEE mm':>10}{'REST mm':>10}{'delta':>10}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for parcel in parcels:
            for month in months:
                g = gee.get(parcel.pk, {}).get(month)
                r = rest.get(parcel.pk, {}).get(month)
                r_float = float(r) if r is not None else None
                g_str = f"{g:.2f}" if g is not None else "-"
                r_str = f"{r_float:.2f}" if r_float is not None else "-"
                if g is not None and r_float is not None:
                    d_str = f"{g - r_float:+.2f}"
                else:
                    d_str = "-"
                self.stdout.write(
                    f"{parcel.parcel_number:<16}{month:<10}{g_str:>10}{r_str:>10}{d_str:>10}"
                )

    def _write_cache(self, parcels, start, end, gee):
        written = 0
        for parcel in parcels:
            gee_for_parcel = gee.get(parcel.pk)
            if not gee_for_parcel:
                continue
            OpenETCache.objects.create(
                parcel=parcel,
                geometry=parcel.geometry,
                start_date=start,
                end_date=end,
                variable="ET",
                model_name="Ensemble",
                et_data=build_et_data(gee_for_parcel),
            )
            written += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {written} GEE-sourced OpenETCache rows. Now run: "
                f"python manage.py sync_openet_to_ledger --start-date "
                f"{start.isoformat()} --end-date {end.isoformat()} --dry-run"
            )
        )

    # -- entrypoint ---------------------------------------------------------

    def handle(self, *args, **options):
        # Re-raise library RuntimeErrors as CommandError so the go/no-go gate
        # still fails loud the way this proof command always has.
        try:
            ee = init_earth_engine()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Earth Engine initialized headlessly (project "
                f"{settings.GEE_PROJECT}, service account "
                f"{settings.GEE_SERVICE_ACCOUNT_EMAIL})."
            )
        )

        parcels, _has_rest = self._select_parcels(options["limit"])
        self.stdout.write(
            f"Selected {len(parcels)} parcel(s): "
            + ", ".join(p.parcel_number for p in parcels)
        )

        rest = self._rest_lookup(parcels)
        start, end = self._resolve_window(
            parcels, options["start_date"], options["end_date"], rest
        )
        self.stdout.write(
            f"Window: {start.isoformat()} .. {end.isoformat()}"
        )

        try:
            gee = reduce_et_by_parcel(ee, parcels, start, end)
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        months = sorted(
            {m for pm in gee.values() for m in pm}
            | {m for pm in rest.values() for m in pm}
        )
        # keep only months within the window
        months = [
            m
            for m in months
            if _first_of_month(start)
            <= datetime.strptime(m, "%Y-%m").date()
            <= end
        ]
        self._print_table(parcels, months, gee, rest)

        if options["write_cache"]:
            self._write_cache(parcels, start, end, gee)
        else:
            self.stdout.write("")
            self.stdout.write(
                "Read-only proof (no cache written). Re-run with --write-cache "
                "to populate OpenETCache for the sync_openet_to_ledger dry-run."
            )
