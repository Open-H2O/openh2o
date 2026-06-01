# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the calculation engine for a period, writing idempotent `calculated` rows.

For each in-scope parcel that has gross-ET data for the period, evaluate the
active CalculationPlan and write exactly ONE ParcelLedger row with
source_type="calculated". The write is delete-then-insert per
(parcel, month, "calculated") inside one transaction, so re-running is
idempotent: running twice yields identical balances (no drift, no double-count).
"""

import datetime as dt
import re
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.calculation import evaluate_chain
from accounting.models import ReportingPeriod
from parcels.models import Parcel, ParcelLedger

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


class Command(BaseCommand):
    help = (
        "Evaluate the active CalculationPlan and write one idempotent "
        "`calculated` ledger row per parcel-month."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            required=True,
            help="Month to calculate, as YYYY-MM (e.g. 2024-06).",
        )
        parser.add_argument(
            "--parcel",
            help="Limit to a single parcel by parcel_number.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the per-parcel result without writing ledger rows.",
        )

    def handle(self, *args, **options):
        period = options["period"]
        if not PERIOD_RE.match(period):
            raise CommandError(f"--period must be YYYY-MM, got {period!r}")

        year, month = int(period[:4]), int(period[5:7])
        eff_date = dt.date(year, month, 1)
        dry_run = options["dry_run"]

        parcels = Parcel.objects.all().order_by("parcel_number")
        if options.get("parcel"):
            parcels = parcels.filter(parcel_number=options["parcel"])
            if not parcels.exists():
                raise CommandError(
                    f"no parcel with parcel_number={options['parcel']!r}"
                )

        reporting_period = ReportingPeriod.objects.filter(
            start_date__lte=eff_date, end_date__gte=eff_date
        ).first()

        written = 0
        skipped_no_et = 0
        for parcel in parcels:
            final_af, breakdown = evaluate_chain(parcel, period)

            et_step = next(
                (s for s in breakdown if s["step_type"] == "et_gross"), None
            )
            has_et = bool(et_step and et_step["detail"].get("rows", 0) > 0)
            if not has_et:
                skipped_no_et += 1
                continue

            gross_af = Decimal(et_step["output_af"]) if et_step else Decimal("0")

            if dry_run:
                self.stdout.write(
                    f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                    f"net {final_af} AF (would write {-final_af} AF)"
                )
                written += 1
                continue

            with transaction.atomic():
                ParcelLedger.objects.filter(
                    parcel=parcel,
                    effective_date=eff_date,
                    source_type="calculated",
                ).delete()
                ParcelLedger.objects.create(
                    parcel=parcel,
                    transaction_date=dt.date.today(),
                    effective_date=eff_date,
                    amount_acre_feet=(-final_af).quantize(Decimal("0.0001")),
                    source_type="calculated",
                    description="Derived extraction estimate (calculation engine)",
                    reporting_period=reporting_period,
                    water_type=None,
                )
            self.stdout.write(
                f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                f"net {final_af} AF (wrote {-final_af} AF)"
            )
            written += 1

        verb = "Would write" if dry_run else "Wrote"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {written} calculated row(s) for {period}; "
                f"{skipped_no_et} parcel(s) skipped (no ET data)."
            )
        )
