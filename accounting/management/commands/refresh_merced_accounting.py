# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refresh the Merced demo's ACCOUNTING layer under the corrected v1.10 model.

WHY this command exists — the ordering trap. Phases 54-57 rebuilt the accounting
model around measured consumptive use: net consumptive use (gross ET minus
effective precip) is the source-agnostic spine (54-01), unmetered district
deliveries are allocated to crop-varied parcels BY ET demand (55), and the
per-parcel books are meant to close (``parcel_mass_balance``). But the live demo
was seeded BEFORE that work, so its persisted ``CalculationRun`` rows carry
``net_consumptive_use_af = 0``. A naive single re-seed therefore CANNOT close the
per-parcel books, because of an ordering dependency:

  * Demand-weighted surface allocation (``allocate_district_delivery``) needs each
    parcel's ``net_consumptive_use_af`` to exist — that is the weight it splits by.
  * With net CU still 0, the allocation kernel returns ``{}`` and the service falls
    back to the STATIC ``PointOfDiversionParcel.fraction`` split. A static split
    does not match each parcel's ET demand, so per-parcel mass balance won't close.

Because net consumptive use is computed gross-ET-minus-precip and is INDEPENDENT
of surface delivery (54-01), the fix is a deterministic TWO-PASS refresh:

  1. ``run_calculations`` — populate ``net_consumptive_use_af`` for every
     parcel-month from the OpenET cache. Valid to run before surface is allocated,
     precisely because net CU does not depend on surface.
  2. ``seed_merced_ledgers`` — with net CU now present, its
     ``allocate_district_delivery`` call writes demand-weighted ``surface_diversion``
     rows (the kernel's demand path, not the static-fraction fallback).
  3. ``run_calculations`` AGAIN — recompute each parcel's residual disposition
     (groundwater vs. unmet demand) and incidental recharge against the
     now-demand-weighted surface rows, so the books close.

Do NOT "optimize" this down to one pass: the engine must run a SECOND time after
the demand-weighted surface rows exist, or the residual/recharge terms are stale.

SCOPE — accounting layer ONLY. This command refreshes the engine output and the
ledger re-allocation. It does NOT re-seed the physical/spatial layer (parcels,
points of diversion, wells, boundaries) — those are stable and owned by
``seed_merced`` and its sub-commands. Run those first if the demo does not exist.

Idempotent: every underlying command is delete-then-insert, so re-running this
sequence reproduces the same end state. The Merced demo's prior water year
(``WY 2024-2025``) is FINALIZED, so ``run_calculations`` is invoked with
``--force`` — this command deliberately recomputes the in-development demo's
figures (the v1.9/v1.10 demo is framed as not-yet-submittable).
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from accounting.models import ReportingPeriod

DEFAULT_PERIOD = "WY 2024-2025"


def _months_in(reporting_period):
    """The ordered list of ``"YYYY-MM"`` month strings the period spans.

    ``run_calculations`` computes a single month at a time, so the two engine
    passes iterate every month from the period's start to its end (inclusive),
    matching how the demo's water year is run month-by-month.
    """
    start, end = reporting_period.start_date, reporting_period.end_date
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return months


class Command(BaseCommand):
    help = (
        "Refresh the Merced demo accounting layer with the corrected two-pass "
        "sequence (run_calculations -> seed_merced_ledgers -> run_calculations), "
        "so per-parcel mass balance closes. Accounting layer only; idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            default=DEFAULT_PERIOD,
            help=(
                "Name of the ReportingPeriod to refresh (default "
                f"'{DEFAULT_PERIOD}'). The engine runs each month it spans."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the planned three-step sequence without executing it.",
        )

    def handle(self, *args, **options):
        period_name = options["period"]
        dry_run = options["dry_run"]

        reporting_period = ReportingPeriod.objects.filter(name=period_name).first()
        if reporting_period is None:
            raise CommandError(
                f"No ReportingPeriod named {period_name!r}. Seed the Merced demo "
                f"first (`python manage.py seed_merced`), or pass --period."
            )

        months = _months_in(reporting_period)

        if dry_run:
            self._print_plan(period_name, months)
            return

        # Pass 1 — populate net_consumptive_use_af (surface-independent, 54-01).
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== Pass 1/3: run_calculations — populate net consumptive use "
            f"({len(months)} months) ==="
        ))
        self._run_engine(months)

        # Pass 2 — re-allocate surface BY DEMAND now that net CU exists.
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Pass 2/3: seed_merced_ledgers — demand-weighted surface "
            "re-allocation ==="
        ))
        call_command("seed_merced_ledgers", stdout=self.stdout)

        # Pass 3 — recompute residual disposition + incidental recharge against
        # the demand-weighted surface rows, so the per-parcel books close.
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== Pass 3/3: run_calculations — recompute residual/recharge "
            f"({len(months)} months) ==="
        ))
        self._run_engine(months)

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced accounting layer refreshed for '{period_name}' "
            f"({len(months)} months, two engine passes around the ledger "
            f"re-allocation). Per-parcel mass balance should now close."
        ))

    def _run_engine(self, months):
        """Run ``run_calculations --force`` for each month, threading stdout.

        ``--force`` because the demo's prior water year is finalized; this command
        deliberately recomputes the in-development demo (not a filed number).
        """
        for month in months:
            call_command(
                "run_calculations", period=month, force=True, stdout=self.stdout
            )

    def _print_plan(self, period_name, months):
        span = f"{months[0]}..{months[-1]}" if months else "(no months)"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nrefresh_merced_accounting --dry-run — planned sequence for "
            f"'{period_name}' ({len(months)} months: {span})"
        ))
        self.stdout.write(
            f"  1. run_calculations --force, each month {span} "
            f"(populate net_consumptive_use_af; surface-independent)"
        )
        self.stdout.write(
            "  2. seed_merced_ledgers "
            "(demand-weighted surface re-allocation via allocate_district_delivery)"
        )
        self.stdout.write(
            f"  3. run_calculations --force, each month {span} "
            f"(recompute residual disposition + incidental recharge)"
        )
        self.stdout.write(
            "\nAccounting layer only — does NOT re-seed parcels/PODs/wells. "
            "Idempotent."
        )
