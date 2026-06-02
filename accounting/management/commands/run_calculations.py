# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the calculation engine for a period, writing idempotent `calculated` rows.

For each in-scope parcel that has gross-ET data for the period, evaluate the
active CalculationPlan and write exactly ONE ParcelLedger row with
source_type="calculated". The write is delete-then-insert per
(parcel, month, "calculated") inside one transaction, so re-running is
idempotent: running twice yields identical balances (no drift, no double-count).

38-04 folds WaterCredit banking into this same per-parcel transaction. In a wet
month the chain nets below the floor; clamp_floor surfaces that surplus and we
DEPOSIT it as a WaterCredit. In a later deficit month we DRAW down available,
non-expired credits (oldest first, each depreciated) to reduce the billable
number — the drawn amount comes out of `final_af` BEFORE the single calculated
row is written, and the draws themselves are recorded as WaterCreditDraw rows for
lifecycle + audit. The credit offset folds into the one calculated row; it is NOT
a separate ledger row (the spine stays the single source of truth).

Idempotency is preserved by clearing this period's banking state (this-period
draws + this-period precip_surplus deposits) at the top of the transaction before
re-depositing/re-drawing. Periods are processed FORWARD in time: a credit can
only be drawn by a later period; re-running an older period after newer periods
already drew the same credit is out of scope here (run by --period, one month at
a time, in order).
"""

import datetime as dt
import re
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from accounting.banking_math import depreciated_value, is_expired, periods_between
from accounting.calculation import evaluate_chain, plan_config_hash
from accounting.models import (
    CalculationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterCredit,
    WaterCreditDraw,
)
from parcels.models import Parcel, ParcelLedger

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def _add_months(period, months):
    """Return the 'YYYY-MM' string `months` after `period` (months may be 0)."""
    year, month = int(period[:4]), int(period[5:7])
    idx = year * 12 + (month - 1) + int(months)
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _apply_banking(parcel, period, final_af, breakdown, *, commit):
    """Deposit a wet-month surplus and draw credits down in a deficit month.

    Reads the clamp_floor record from `breakdown` for the surplus + credit levers,
    then (when commit) clears this period's banking state, deposits any surplus as
    a WaterCredit, and draws available non-expired credits oldest-first to cover a
    positive `final_af`, writing WaterCreditDraw rows. Returns
    `(net_final_af, {"deposited", "drawn"})`.

    When commit is False (dry-run) it computes the SAME numbers but writes nothing
    and clears nothing — the available-credit math excludes this-period draws, so
    the preview matches what a real run (which clears them) would produce.

    MUST be called inside the per-parcel transaction.atomic() block when committing.
    """
    clamp = next(
        (s for s in breakdown if s["step_type"] == "clamp_floor"), None
    )
    if clamp is None:
        return final_af, {"deposited": Decimal("0"), "drawn": Decimal("0")}

    detail = clamp["detail"]
    bank = bool(detail.get("bank", False))
    surplus_af = Decimal(str(detail.get("surplus_af", "0")))
    rate = Decimal(str(detail.get("depreciation_rate", 0) or 0))
    expiry_months = detail.get("expiry_months", None)

    # (a) Clear this period's banking state so re-runs don't double-bank/draw.
    if commit:
        WaterCreditDraw.objects.filter(
            credit__parcel=parcel, draw_period=period
        ).delete()
        WaterCredit.objects.filter(
            parcel=parcel, origin_period=period, origin="precip_surplus"
        ).delete()

    # (c) Deposit a surplus as one immutable WaterCredit.
    deposited = Decimal("0")
    if bank and surplus_af > 0:
        deposited = surplus_af.quantize(Decimal("0.0001"))
        expires_period = (
            _add_months(period, expiry_months) if expiry_months is not None else None
        )
        if commit:
            WaterCredit.objects.create(
                parcel=parcel,
                origin_period=period,
                amount_af=deposited,
                origin="precip_surplus",
                depreciation_rate=rate,
                expires_period=expires_period,
            )

    # (d) Draw down available non-expired credits, oldest origin_period first.
    drawn_total = Decimal("0")
    if final_af > 0:
        remaining = final_af
        credits = WaterCredit.objects.filter(
            parcel=parcel, origin_period__lte=period
        ).order_by("origin_period", "id")
        for credit in credits:
            if remaining <= 0:
                break
            if is_expired(credit.expires_period, period):
                continue
            elapsed = periods_between(credit.origin_period, period)
            gross = depreciated_value(
                credit.amount_af, credit.depreciation_rate, elapsed
            )
            # available = depreciated value minus draws in STRICTLY EARLIER periods
            # (this-period draws are excluded so clear-then-recompute is idempotent).
            prior = credit.draws.filter(draw_period__lt=period).aggregate(
                total=Sum("amount_af")
            )["total"] or Decimal("0")
            available = gross - prior
            if available <= 0:
                continue
            draw = min(available, remaining).quantize(Decimal("0.0001"))
            if draw <= 0:
                continue
            if commit:
                WaterCreditDraw.objects.create(
                    credit=credit, draw_period=period, amount_af=draw
                )
            drawn_total += draw
            remaining -= draw
        final_af = remaining

    return final_af, {"deposited": deposited, "drawn": drawn_total}


def _persist_calculation_run(
    parcel, period, gross_af, net_af, breakdown, info, plan_id, plan_name, plan_hash
):
    """Write the one CalculationRun for this (parcel, period) — the audit trail.

    Delete-then-insert so a re-run leaves exactly one run with identical values
    (mirrors the calculated ledger row's idempotency). All AF figures are quantized
    to 4dp the same way the ledger row is, so ``final_af`` equals
    ``-ledger.amount_acre_feet`` exactly. Input magnitudes come straight off the
    breakdown the runner already evaluated; a step that did not run in this chain
    (e.g. effective precip disabled) stores NULL rather than a fabricated zero.

    MUST be called inside the per-parcel transaction.atomic() block.
    """
    quant = Decimal("0.0001")
    precip_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_effective_precip"), None
    )
    surface_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_surface_water"), None
    )

    effective_precip_af = None
    if precip_step is not None:
        effective_precip_af = Decimal(
            str(precip_step["detail"]["effective_precip_af"])
        ).quantize(quant)

    surface_water_af = None
    if surface_step is not None:
        surface_water_af = Decimal(
            str(surface_step["detail"]["surface_water_af"])
        ).quantize(quant)

    CalculationRun.objects.filter(parcel=parcel, period=period).delete()
    CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=gross_af.quantize(quant),
        effective_precip_af=effective_precip_af,
        surface_water_af=surface_water_af,
        banked_af=info["deposited"],
        drawn_af=info["drawn"],
        final_af=net_af.quantize(quant),
        breakdown=breakdown,
        methodology_plan_id=plan_id,
        methodology_plan_name=plan_name,
        config_hash=plan_hash,
    )


class Command(BaseCommand):
    help = (
        "Evaluate the active CalculationPlan and write one idempotent "
        "`calculated` ledger row per parcel-month (with WaterCredit banking)."
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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute even if the period's ReportingPeriod is finalized. "
            "Overwrites a filed number — use deliberately.",
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

        # Finalized-period write guard (ISS-020 #1). A finalized ReportingPeriod
        # is a number already filed with the state; re-running would silently
        # overwrite it. Refuse unless --force, and shout when forced. Guard ONCE
        # before the loop: finalization is a property of the period, not the
        # parcel, so a per-parcel raise would half-write the period. dry_run is
        # always allowed (it writes nothing — previewing a finalized recompute is
        # safe). A month with no ReportingPeriod has nothing to finalize: proceed.
        if (
            reporting_period is not None
            and reporting_period.is_finalized
            and not dry_run
        ):
            if not options["force"]:
                filed = (
                    f" (filed {reporting_period.finalized_at:%Y-%m-%d})"
                    if reporting_period.finalized_at
                    else ""
                )
                raise CommandError(
                    f"Refusing to recompute {period}: reporting period "
                    f"'{reporting_period.name}' is finalized{filed}. "
                    f"Re-running would overwrite the filed number. "
                    f"Pass --force to override."
                )
            self.stderr.write(
                self.style.WARNING(
                    f"--force: OVERWRITING finalized period {period} "
                    f"('{reporting_period.name}'). A number already filed with "
                    f"the state is being recomputed — this changes a filed figure."
                )
            )

        # Snapshot the methodology ONCE: the active plan is identical for every
        # parcel in a single run, so hashing per-parcel would be wasted work and
        # could tear if the plan were edited mid-run. These copied values (not a
        # FK) are stamped onto each CalculationRun so the filed number names its
        # recipe even after the live plan changes (ISS-020 #2).
        active_plan = CalculationPlan.active()
        plan_hash = plan_config_hash(active_plan) if active_plan else ""
        plan_id = active_plan.id if active_plan else None
        plan_name = active_plan.name if active_plan else ""

        # ISS-032: a clamp_floor configured with expiry_months <= 0 makes a
        # just-banked credit expire the very month it is deposited
        # (_add_months(period, 0) == period, and is_expired is `current >=
        # expires`), silently destroying the surplus it was meant to carry
        # forward. Reject it at config-validation time — before any row is
        # written — the same way the finalized-period guard refuses up front.
        if active_plan is not None:
            for step in active_plan.steps.filter(
                enabled=True, step_type="clamp_floor"
            ):
                expiry = (step.config or {}).get("expiry_months")
                if expiry is not None and int(expiry) <= 0:
                    raise CommandError(
                        f"clamp_floor step '{step.label}' has expiry_months="
                        f"{expiry}: a banked credit would expire the month it is "
                        f"deposited. Use a positive month-count, or leave it blank "
                        f"to never expire."
                    )

        written = 0
        skipped_no_et = 0
        banked = 0
        drew = 0
        for parcel in parcels:
            final_af, breakdown = evaluate_chain(parcel, period)

            et_step = next(
                (s for s in breakdown if s["step_type"] == "et_gross"), None
            )
            # ISS-025: gate on months_matched (items actually date-matched for THIS
            # month), NOT rows (the span-row count). A cache row can span the period
            # yet carry no item dated in it (months_matched==0, rows>0); gating on
            # rows would file a fabricated 0-AF `calculated` row for a parcel with
            # no real ET — the silent-zero trap Phase 38 exists to kill.
            months_matched = (
                et_step["detail"].get("months_matched", 0) if et_step else 0
            )
            has_et = bool(et_step and months_matched > 0)
            if not has_et:
                skipped_no_et += 1
                continue

            gross_af = Decimal(et_step["output_af"]) if et_step else Decimal("0")

            if dry_run:
                net_af, info = _apply_banking(
                    parcel, period, final_af, breakdown, commit=False
                )
                extra = ""
                if info["deposited"] > 0:
                    extra += f"; would bank {info['deposited']} AF"
                if info["drawn"] > 0:
                    extra += f"; would draw {info['drawn']} AF"
                self.stdout.write(
                    f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                    f"net {net_af} AF (would write {-net_af} AF){extra}"
                )
                written += 1
                continue

            with transaction.atomic():
                net_af, info = _apply_banking(
                    parcel, period, final_af, breakdown, commit=True
                )
                # ISS-025 invariant, explicit at the write site: a `calculated`
                # row is only ever written for a parcel with real matched ET. The
                # gate above already guarantees months_matched>0; assert it here so
                # a future refactor of that gate can never silently resurrect a
                # filed 0-AF row. A can't-happen guard, not flow control.
                if months_matched <= 0:  # pragma: no cover - guaranteed by the gate
                    raise CommandError(
                        f"internal invariant violated: refusing to write a "
                        f"`calculated` row for {parcel.parcel_number} {period} "
                        f"with months_matched={months_matched}"
                    )
                ParcelLedger.objects.filter(
                    parcel=parcel,
                    effective_date=eff_date,
                    source_type="calculated",
                ).delete()
                ParcelLedger.objects.create(
                    parcel=parcel,
                    transaction_date=dt.date.today(),
                    effective_date=eff_date,
                    amount_acre_feet=(-net_af).quantize(Decimal("0.0001")),
                    source_type="calculated",
                    description="Derived extraction estimate (calculation engine)",
                    reporting_period=reporting_period,
                    water_type=None,
                )
                # 38-05: persist the reconstructable audit record in the SAME
                # transaction, delete-then-insert per (parcel, period) so re-runs
                # stay 1:1 with the calculated row and never drift. Input
                # magnitudes are pulled off the breakdown the command already has
                # (no re-derivation); steps absent from the chain store NULL.
                _persist_calculation_run(
                    parcel, period, gross_af, net_af, breakdown, info,
                    plan_id, plan_name, plan_hash,
                )
            extra = ""
            if info["deposited"] > 0:
                extra += f"; banked {info['deposited']} AF"
                banked += 1
            if info["drawn"] > 0:
                extra += f"; drew {info['drawn']} AF"
                drew += 1
            self.stdout.write(
                f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                f"net {net_af} AF (wrote {-net_af} AF){extra}"
            )
            written += 1

        verb = "Would write" if dry_run else "Wrote"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {written} calculated row(s) for {period}; "
                f"{skipped_no_et} parcel(s) skipped (no ET data); "
                f"{banked} banked, {drew} drew."
            )
        )
