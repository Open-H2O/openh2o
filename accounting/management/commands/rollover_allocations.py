# SPDX-License-Identifier: AGPL-3.0-or-later
"""Roll a closed water year's leftover (or over-drawn) groundwater into the next year.

Groundwater only: surface water does not carry over, so no surface row is
written whatever a zone's recovery horizon says. For each zone that had a
groundwater budget in the requested water year, the remainder is the year's
allocation plus the amount carried INTO that year, less its billable usage
(carryover_math). It is written as one AllocationCarryover row for the NEXT
water year, the opening balance that year inherits. A positive row is a surplus
carried forward; a negative row is a debt, carried one for one until it is
repaid. Each water account carries its own remainder the same way, written as an
AccountCredit row of origin ``carried_forward``.

Idempotent like run_calculations: the rows this command owns for the target year
(delete-then-insert inside one transaction) are cleared and rewritten, so running
twice yields identical totals and never double-banks.

Finalized-year guard: this command operates on a CLOSED prior water year and only READS
its allocations + usage, then WRITES new carry-over rows for the NEXT year. It
never mutates a finalized period's ledger rows, so a re-run cannot rewrite filed
numbers. If the source year is not yet finalized the carry-over is provisional and
the command says so loudly (but still computes it, so a demo/preview works).

Water-year boundary is the site's water year start month (default 10 =
California's Oct 1 start); --anchor-month overrides it for one run. The rule is
carryover_math.water_year_of.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet, Sum

from accounting.carryover_math import available_with_carryover, water_year_label
from accounting.models import (
    AccountCredit,
    AllocationCarryover,
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterType,
)
from accounting.services import (
    account_allocation,
    account_consumptive_balance,
    account_parcel_ids,
    resolve_recovery_horizon,
    water_year_periods,
    water_year_usage_by_type,
)
from core.constants import CARRY_FORWARD, SAME_WATER_YEAR
from core.models import SiteConfig
from core.water_year import water_year_start_month
from geography.models import ParcelZone, Zone


_Result = tuple[Zone, WaterType, Decimal, Decimal, Decimal]
_Decided = tuple[Zone, WaterType, Decimal, Decimal, Decimal, bool]


def _budget_rows(periods: list[ReportingPeriod], source_wy: int) -> QuerySet[AllocationPlan]:
    """The summed allocation per (zone, water type) for the source year's periods."""
    # (zone, water_type) pairs that had a budget this year, with the summed
    # allocation. A pair with usage but no budget has no "leftover budget" to
    # carry, so it is intentionally not rolled forward.
    if not AllocationPlan.objects.filter(reporting_period__in=periods).exists():
        raise CommandError(
            f"no AllocationPlan exists for water year {source_wy}; "
            "nothing to roll over"
        )
    alloc_rows = (
        AllocationPlan.objects.filter(
            reporting_period__in=periods, water_type__code__iexact="GW"
        )
        .values("zone_id", "water_type_id")
        .annotate(allocation=Sum("allocation_acre_feet"))
        .order_by("zone_id", "water_type_id")
    )
    return alloc_rows


def _budget_results(
    alloc_rows: QuerySet[AllocationPlan], date_start: date, date_end: date, source_wy: int
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

        # What the zone's page calls Available: the allocation plus what was
        # carried into the year. A debt carried in is still owed, so the
        # remainder carries it on.
        carried_in = AllocationCarryover.objects.filter(
            zone=zone, water_type=water_type, water_year=source_wy, origin="allocation_carryover"
        ).aggregate(total=Sum("amount_af"))["total"] or Decimal("0")
        net = (available_with_carryover(allocation, carried_in) - usage).quantize(Decimal("0.0001"))
        results.append((zone, water_type, allocation, usage, net))
    return results


def _decide_expiring_surplus(results: list[_Result]) -> list[_Decided]:
    """Append, to each result, whether a same-water-year district lets its surplus expire."""
    # Resolve the agency-wide default recovery horizon ONCE; a district may
    # override it on its Zone. A SURPLUS in a "same_water_year"
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
        # Scope the delete to this command's OWN origin so a
        # basin_recharge_pool deposit that lands in the target year (the
        # demonstration re-seed) is never collateral damage of the rollover.
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


def _water_year_label(water_year: int) -> str:
    """The water year as the screens name it: 2025 is "WY 2024-2025", or "2025" from a January start."""
    return water_year_label(water_year, water_year_start_month())


_AccountResult = tuple[WaterAccount, Decimal, Decimal, bool]


def _account_results(
    periods: list[ReportingPeriod], source_wy: int, water_type: WaterType | None
) -> list[_AccountResult]:
    """Each account's ``(account, remainder, used, expires_surplus)`` for the year.

    The remainder is its share of the groundwater allocations, plus its credit
    rows for the year (last year's carried amount among them), less the
    groundwater it was charged: the same sum the accounts table prints as
    Remaining. A surplus expires only where every zone the account has a
    groundwater plan in lets surplus expire; a debt is always carried.
    """
    if water_type is None:
        return []
    cfg = SiteConfig.objects.first()
    agency_default = cfg.default_recovery_horizon if cfg else CARRY_FORWARD
    results = []
    for account in WaterAccount.objects.order_by("account_number"):
        allocation = None
        used = Decimal("0")
        for period in periods:
            share = account_allocation(account, period)
            if share is not None:
                allocation = (allocation or Decimal("0")) + share
            used += account_consumptive_balance(account, period)["groundwater_charged"]
        if allocation is None:
            continue
        credits = AccountCredit.objects.filter(
            water_account=account, water_year=source_wy, water_type=water_type
        ).aggregate(total=Sum("amount_af"))["total"] or Decimal("0")
        net = (allocation + credits - used).quantize(Decimal("0.0001"))
        parcel_ids = account_parcel_ids(account, periods[0])
        zone_ids = set(
            ParcelZone.objects.filter(parcel_id__in=parcel_ids).values_list("zone_id", flat=True)
        ) & set(
            AllocationPlan.objects.filter(reporting_period__in=periods, water_type=water_type)
            .values_list("zone_id", flat=True)
        )
        horizons = [
            resolve_recovery_horizon(z, agency_default=agency_default)
            for z in Zone.objects.filter(pk__in=zone_ids)
        ]
        expires = bool(horizons) and all(h == SAME_WATER_YEAR for h in horizons) and net > 0
        results.append((account, net, used, expires))
    return results


def _replace_account_credits(
    results: list[_AccountResult], water_type: WaterType | None, source_wy: int, target_wy: int
) -> None:
    """Delete-then-insert the carried-forward rows this command wrote for the target year."""
    source_key = f"rollover:{source_wy}"
    with transaction.atomic():
        AccountCredit.objects.filter(
            water_year=target_wy, origin="carried_forward", source_key=source_key
        ).delete()
        AccountCredit.objects.bulk_create(
            [
                AccountCredit(
                    water_account=account,
                    water_type=water_type,
                    water_year=target_wy,
                    origin="carried_forward",
                    amount_af=net,
                    source_key=source_key,
                    description=f"Carried forward from {_water_year_label(source_wy)}",
                )
                for account, net, _used, expires in results
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
            default=None,
            help="Water-year start month. Left out, the site's setting is used "
            "(10 = Oct 1 unless it was changed).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the computed carry-over without writing any rows.",
        )

    def handle(self, *args, **options):
        source_wy = options["water_year"]
        anchor = options["anchor_month"] or water_year_start_month()
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
        results = _budget_results(alloc_rows, date_start, date_end, source_wy)
        decided = _decide_expiring_surplus(results)

        verb = "Would write" if dry_run else "Wrote"
        if not dry_run:
            _replace_carryover_rows(decided, source_wy, target_wy)

        written, skipped = self._report_rows(decided, target_wy)

        groundwater = WaterType.objects.filter(code__iexact="GW").first()
        account_results = _account_results(periods, source_wy, groundwater)
        if not dry_run:
            _replace_account_credits(account_results, groundwater, source_wy, target_wy)
        for account, net, used, expires in account_results:
            self.stdout.write(
                f"  {account.account_number} GW: remainder {net} AF, used {used} AF -> "
                + ("EXPIRES, not carried" if expires else f"WY{target_wy}")
            )

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
