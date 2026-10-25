# SPDX-License-Identifier: AGPL-3.0-or-later
"""Roll a closed water year's leftover (or over-drawn) budget into the next year.

For each (zone, water_type) that had a budget in the requested water year, sum
that year's AllocationPlan allocation and its billable usage, compute the SIGNED
remainder (carryover_math.net_carryover), and write one AllocationCarryover row
for the NEXT water year — the opening balance that year inherits. A positive row
is a surplus carried forward; a negative row is a debt borrowed against next year.

Idempotent like run_calculations: the rows this command owns for the target year
(delete-then-insert inside one transaction) are cleared and rewritten, so running
twice yields identical totals and never double-banks.

ISS-020 guard: this command operates on a CLOSED prior water year and only READS
its allocations + usage, then WRITES new carry-over rows for the NEXT year. It
never mutates a finalized period's ledger rows, so a re-run cannot rewrite filed
numbers. If the source year is not yet finalized the carry-over is provisional and
the command says so loudly (but still computes it, so a demo/preview works).

Water-year boundary is configurable via --anchor-month (default 10 = California's
Oct 1 start), matching carryover_math.water_year_of.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet, Sum

from accounting.carryover_math import net_carryover
from accounting.models import (
    AllocationCarryover,
    AllocationPlan,
    ReportingPeriod,
    WaterType,
)
from accounting.services import (
    resolve_recovery_horizon,
    water_year_periods,
    water_year_usage_by_type,
)
from core.constants import CARRY_FORWARD, SAME_WATER_YEAR
from core.models import SiteConfig
from geography.models import Zone


_Result = tuple[Zone, WaterType, Decimal, Decimal, Decimal]
_Decided = tuple[Zone, WaterType, Decimal, Decimal, Decimal, bool]


def _budget_rows(periods: list[ReportingPeriod], source_wy: int) -> QuerySet[AllocationPlan]:
    """The summed allocation per (zone, water type) for the source year's periods."""
    # (zone, water_type) pairs that had a budget this year, with the summed
    # allocation. A pair with usage but no budget has no "leftover budget" to
    # carry, so it is intentionally not rolled forward.
    alloc_rows = (
        AllocationPlan.objects.filter(reporting_period__in=periods)
        .values("zone_id", "water_type_id")
        .annotate(allocation=Sum("allocation_acre_feet"))
        .order_by("zone_id", "water_type_id")
    )
    if not alloc_rows:
        raise CommandError(
            f"no AllocationPlan exists for water year {source_wy}; "
            "nothing to roll over"
        )
    return alloc_rows


def _budget_results(
    alloc_rows: QuerySet[AllocationPlan], date_start: date, date_end: date
) -> list[_Result]:
    """Each pair's ``(zone, water_type, allocation, usage, net)`` for the year."""
    zones = {z.id: z for z in Zone.objects.all()}
    water_types = {w.id: w for w in WaterType.objects.all()}
    usage_cache = {}  # zone_id -> {code: usage}

    results = []
    for row in alloc_rows:
        zone = zones[row["zone_id"]]
        water_type = water_types[row["water_type_id"]]
        allocation = row["allocation"] or Decimal("0")

        if zone.id not in usage_cache:
            usage_cache[zone.id] = water_year_usage_by_type(
                zone, date_start, date_end
            )
        usage = usage_cache[zone.id].get(water_type.code, Decimal("0"))

        net = net_carryover(allocation, usage)
        results.append((zone, water_type, allocation, usage, net))
    return results


def _decide_expiring_surplus(results: list[_Result]) -> list[_Decided]:
    """Append, to each result, whether a same-water-year district lets its surplus expire."""
    # Resolve the agency-wide default recovery horizon ONCE; a district may
    # override it on its Zone (55-02). A SURPLUS in a "same_water_year"
    # (expire) district is use-it-or-lose-it and is NOT carried; a DEBT is
    # ALWAYS carried, because an overdraw is a real obligation that does not
    # vanish on a policy that only governs surplus recovery.
    cfg = SiteConfig.objects.first()
    agency_default = cfg.default_recovery_horizon if cfg else CARRY_FORWARD

    decided = []
    for zone, water_type, allocation, usage, net in results:
        horizon = resolve_recovery_horizon(zone, agency_default=agency_default)
        expires_surplus = horizon == SAME_WATER_YEAR and net > 0
        decided.append(
            (zone, water_type, allocation, usage, net, expires_surplus)
        )
    return decided


def _replace_carryover_rows(decided: list[_Decided], source_wy: int, target_wy: int) -> None:
    """Delete-then-insert the target year's carry-over rows in one transaction."""
    with transaction.atomic():
        # Delete-then-insert the rows THIS command owns (the target year).
        # Only source_wy = target_wy - 1 can produce target_wy, so the
        # target-year rows are exactly this command's output — clearing
        # them makes a re-run identical (idempotent, no duplicates). The
        # contract is unchanged; expire districts just insert FEWER rows.
        # ISS-055: scope the delete to this command's OWN origin so a
        # basin_recharge_pool deposit that lands in the target year (the
        # Phase 62 re-seed) is never collateral damage of the rollover.
        AllocationCarryover.objects.filter(
            water_year=target_wy, origin="allocation_carryover"
        ).delete()
        AllocationCarryover.objects.bulk_create(
            [
                AllocationCarryover(
                    zone=zone,
                    water_type=water_type,
                    water_year=target_wy,
                    source_water_year=source_wy,
                    amount_af=net,
                )
                for zone, water_type, _alloc, _usage, net, expires in decided
                if not expires
            ]
        )


class Command(BaseCommand):
    help = (
        "Roll a closed water year's signed budget remainder forward as "
        "AllocationCarryover rows for the next water year (idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--water-year",
            type=int,
            required=True,
            help="The closed water year to roll forward (e.g. 2025). Produces "
            "carry-over rows for water_year + 1.",
        )
        parser.add_argument(
            "--anchor-month",
            type=int,
            default=10,
            help="Water-year start month (default 10 = Oct 1, California).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the computed carry-over without writing any rows.",
        )

    def handle(self, *args, **options):
        source_wy = options["water_year"]
        anchor = options["anchor_month"]
        dry_run = options["dry_run"]
        target_wy = source_wy + 1

        periods = water_year_periods(source_wy, anchor)
        if not periods:
            raise CommandError(
                f"no reporting period falls in water year {source_wy} "
                f"(anchor month {anchor}); nothing to roll over"
            )

        date_start = min(p.start_date for p in periods)
        date_end = max(p.end_date for p in periods)
        self._warn_if_not_finalized(periods, source_wy)

        alloc_rows = _budget_rows(periods, source_wy)
        results = _budget_results(alloc_rows, date_start, date_end)
        decided = _decide_expiring_surplus(results)

        verb = "Would write" if dry_run else "Wrote"
        if not dry_run:
            _replace_carryover_rows(decided, source_wy, target_wy)

        written, skipped = self._report_rows(decided, target_wy)

        suffix = (
            f" ({skipped} expiring surplus not carried)" if skipped else ""
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {written} carry-over row(s) from WY{source_wy} "
                f"into WY{target_wy}.{suffix}"
            )
        )

    def _warn_if_not_finalized(self, periods: list[ReportingPeriod], source_wy: int) -> None:
        """Say loudly that the carry-over is provisional when the source year is still open."""
        all_finalized = all(p.is_finalized for p in periods)
        if not all_finalized:
            self.stdout.write(
                self.style.WARNING(
                    f"WARNING: water year {source_wy} is not finalized "
                    f"({', '.join(p.name for p in periods if not p.is_finalized)}). "
                    "The carry-over is PROVISIONAL and will change as the year "
                    "closes."
                )
            )

    def _report_rows(self, decided: list[_Decided], target_wy: int) -> tuple[int, int]:
        """Print one line per (zone, water type); returns ``(written, skipped)`` counts."""
        written = 0
        skipped = 0
        for zone, water_type, allocation, usage, net, expires in decided:
            if expires:
                skipped += 1
                self.stdout.write(
                    f"  {zone.name} {water_type.code}: "
                    f"alloc {allocation} - usage {usage} = {net} AF (surplus) "
                    f"-> EXPIRES — not carried, per district policy"
                )
            else:
                written += 1
                kind = "surplus" if net > 0 else ("debt" if net < 0 else "even")
                self.stdout.write(
                    f"  {zone.name} {water_type.code}: "
                    f"alloc {allocation} - usage {usage} = {net} AF ({kind}) "
                    f"-> WY{target_wy}"
                )
        return written, skipped
