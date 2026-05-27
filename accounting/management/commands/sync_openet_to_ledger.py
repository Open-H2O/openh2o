"""
Convert OpenET cache records to ParcelLedger entries.

For each parcel with cached OpenET data in the given date range:
1. Read OpenETCache.et_data (list of {date, et, unit} dicts)
2. Convert mm to acre-feet: -(ET_mm / 304.8) * area_acres
3. Create ParcelLedger entry with source_type="et_estimate"
4. Skip if a ledger entry already exists for that parcel+month+source_type

Formula reference:
  ET (acre-feet) = ET (mm) × area (acres) / 304.8
  304.8 = mm per foot × square feet per acre simplification
  More precisely: 1 acre-foot = 1 acre × 1 foot = 43,560 ft² × 0.3048 m/ft = 1,233.48 m³
  1 mm over 1 acre = 4.04686 m³, so 1 AF = 304.8 mm·acre
  Negative because ET is water CONSUMPTION (usage).

Usage:
  python manage.py sync_openet_to_ledger --start-date 2024-01-01 --end-date 2024-12-31
  python manage.py sync_openet_to_ledger --start-date 2024-01-01 --end-date 2024-12-31 --dry-run
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounting.services import et_mm_to_acre_feet
from datasync.models import OpenETCache
from parcels.models import Parcel, ParcelLedger

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Convert OpenET cache records to ParcelLedger entries (source_type=et_estimate)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            required=True,
            help="Start date (YYYY-MM-DD). Only process cache records overlapping this range.",
        )
        parser.add_argument(
            "--end-date",
            required=True,
            help="End date (YYYY-MM-DD). Only process cache records overlapping this range.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate and report what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        try:
            start_date = datetime.strptime(options["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(options["end_date"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}. Use YYYY-MM-DD.") from exc

        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date.")

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No database writes will occur."))

        # Find all OpenETCache records that overlap the requested date range
        cache_qs = OpenETCache.objects.filter(
            start_date__lte=end_date,
            end_date__gte=start_date,
            parcel__isnull=False,
        ).select_related("parcel").order_by("parcel_id", "start_date")

        counters = {
            "created": 0,
            "skipped_existing": 0,
            "skipped_no_area": 0,
            "skipped_no_data": 0,
            "errors": 0,
        }

        entries_to_create = []

        for cache in cache_qs:
            parcel = cache.parcel

            if not parcel.area_acres:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP parcel {parcel.parcel_number}: no area_acres set"
                    )
                )
                counters["skipped_no_area"] += 1
                continue

            if not cache.et_data:
                counters["skipped_no_data"] += 1
                continue

            # Aggregate et_data entries by month.
            # et_data items: {date: "YYYY-MM" or "YYYY-MM-DD", et: float, unit: "mm"}
            monthly_totals: dict[str, Decimal] = {}
            for item in cache.et_data:
                raw_date = item.get("date", "")
                et_value = item.get("et")
                if et_value is None:
                    continue
                # Normalize to YYYY-MM month key
                if len(raw_date) >= 7:
                    month_key = raw_date[:7]  # "YYYY-MM"
                else:
                    continue

                # Only include months within the requested range
                try:
                    item_month = datetime.strptime(month_key, "%Y-%m").date().replace(day=1)
                except ValueError:
                    continue
                if item_month < start_date.replace(day=1) or item_month > end_date:
                    continue

                monthly_totals[month_key] = monthly_totals.get(month_key, Decimal("0")) + Decimal(str(et_value))

            if not monthly_totals:
                counters["skipped_no_data"] += 1
                continue

            for month_key, total_et_mm in monthly_totals.items():
                try:
                    effective_date = datetime.strptime(month_key, "%Y-%m").date()
                except ValueError:
                    counters["errors"] += 1
                    continue

                # Check for existing ParcelLedger entry for this parcel+month+source_type
                already_exists = ParcelLedger.objects.filter(
                    parcel=parcel,
                    source_type="et_estimate",
                    effective_date__year=effective_date.year,
                    effective_date__month=effective_date.month,
                ).exists()

                if already_exists:
                    counters["skipped_existing"] += 1
                    continue

                # Convert mm to acre-feet (negative: ET is consumption)
                amount_af = et_mm_to_acre_feet(total_et_mm, parcel.area_acres)

                entries_to_create.append(
                    ParcelLedger(
                        parcel=parcel,
                        transaction_date=timezone.now().date(),
                        effective_date=effective_date,
                        amount_acre_feet=amount_af.quantize(Decimal("0.0001")),
                        source_type="et_estimate",
                        description=(
                            f"OpenET ET estimate: {total_et_mm:.2f}mm over "
                            f"{parcel.area_acres} acres = {abs(amount_af):.4f} AF "
                            f"({month_key})"
                        ),
                        reporting_period=None,
                        water_type=None,
                    )
                )
                counters["created"] += 1

        # Write to database in batches
        if not dry_run and entries_to_create:
            batch_size = 500
            with transaction.atomic():
                for i in range(0, len(entries_to_create), batch_size):
                    batch = entries_to_create[i: i + batch_size]
                    ParcelLedger.objects.bulk_create(batch)
        elif dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would create {counters['created']} ledger entries."
                )
            )

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("sync_openet_to_ledger complete"))
        self.stdout.write(f"  Created:           {counters['created']}")
        self.stdout.write(f"  Skipped (exists):  {counters['skipped_existing']}")
        self.stdout.write(f"  Skipped (no area): {counters['skipped_no_area']}")
        self.stdout.write(f"  Skipped (no data): {counters['skipped_no_data']}")
        self.stdout.write(f"  Errors:            {counters['errors']}")
