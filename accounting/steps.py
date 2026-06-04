# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calculation-engine step primitives and the registry that names them.

Each primitive is a pure-ish function with the signature

    (running_af, parcel, period, ctx, config) -> (new_running_af, step_record)

where:
  - running_af : Decimal, the POSITIVE extraction magnitude (acre-feet) flowing
    through the chain. The ledger's sign convention (consumption is negative) is
    applied exactly once, when run_calculations writes the final row — never here.
  - parcel     : a parcels.models.Parcel instance.
  - period     : a "YYYY-MM" string.
  - ctx        : a shared dict the evaluator threads through every step (scratch
    space for cross-step data; unused by the simple primitives but part of the
    contract 38-03/38-04 steps will lean on).
  - config     : the step's JSON config dict (knobs).

step_record is a JSON-serializable dict
    {"step_type", "label", "input_af", "output_af", "detail"}
so 38-04's CalculationRun can persist the breakdown verbatim.

subtract_effective_precip (added 38-03, TDD) nets effective rainfall out of gross
ET. Its contested USDA-SCS / TR-21 math lives in the Django-free
accounting/precip_math.py (proven against published vectors); this module is only
the thin DB-bound wrapper that reads precip + ET from the cache and converts to AF.

OpenETCache shape (verified against live Butler data, 2026-05-31):
  - et_data is a LIST of dicts:
      ET     rows: [{"et": 170.02,  "date": "2024-06", "unit": "mm"}, ...]   var="ET"/model="Ensemble"
      precip rows: [{"precip": 75.0, "date": "2024-02", "unit": "mm"}, ...]   var="precip"/model="GRIDMET"
  - a single cache row can span multiple months (e.g. Jun–Aug in one row)
  - the precip value key is "precip", NOT "et" or "value" (38-01 build_precip_data)
_read_cache_mm honors all of this for BOTH faucets so et_gross and the precip step
can never drift on the read; getting any string wrong silently zeroes the parcel.
"""

import logging
from decimal import Decimal

from django.db.models import Sum

from accounting.services import et_mm_to_acre_feet

logger = logging.getLogger(__name__)


def _period_year_month(period):
    """Parse a 'YYYY-MM' period string into (year, month) ints."""
    year_str, month_str = period.split("-")
    return int(year_str), int(month_str)


def _item_in_span(item_date, start_date, end_date):
    """Whether an et_data item's 'YYYY-MM' date lies within [start_date, end_date].

    Compared at month granularity: the item's month-first-day must be >= the
    span start's month-first-day and <= the span end_date. A malformed or
    unparseable date returns False (treated as out-of-span so it is caught and
    logged rather than silently summed). See ISS-032 / F-math-03.
    """
    import datetime as dt

    parts = item_date.split("-")
    if len(parts) < 2:
        return False
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    item_first = dt.date(year, month, 1)
    span_start_first = dt.date(start_date.year, start_date.month, 1)
    return span_start_first <= item_first <= end_date


def _record(step_type, input_af, output_af, detail):
    return {
        "step_type": step_type,
        "label": step_type,  # evaluator overrides with the configured label
        "input_af": str(input_af),
        "output_af": str(output_af),
        "detail": detail,
    }


def _read_cache_mm(parcel, period, variable, model, key):
    """Sum OpenETCache <key> values (mm) for one parcel-month.

    The single shared cache read behind BOTH et_gross and the precip step, so the
    two can never drift on the variable/model/key strings (the silent-zero trap of
    38-01/38-02: a wrong string matches zero rows and quietly zeroes the parcel).
    Matches rows whose [start_date, end_date] span covers the period, then sums the
    et_data list items whose "date" starts with the period and whose <key> is set.

    Returns (total_mm: Decimal, months_matched: int, row_count: int).
    A parcel with no matching rows returns (Decimal("0"), 0, 0).
    """
    import datetime as dt

    from datasync.models import OpenETCache

    year, month = _period_year_month(period)
    period_first = dt.date(year, month, 1)

    rows = OpenETCache.objects.filter(
        parcel=parcel,
        variable=variable,
        model_name=model,
        start_date__lte=period_first,
        end_date__gte=period_first,
    )

    total_mm = Decimal("0")
    matched = 0
    for row in rows:
        for item in row.et_data or []:
            if not isinstance(item, dict):
                continue
            item_date = str(item.get("date", ""))
            # F-math-03 (ISS-032): an item whose date falls OUTSIDE its own cache
            # row's [start_date, end_date] span is malformed data. The period
            # predicates downstream can only be trusted if each row's items live
            # within the row's span (surface water matches the DB effective_date,
            # ET matches this embedded date string — a mismatch could net gross ET
            # against the wrong surface month). Catch and skip it loudly rather
            # than let a wrong-month value sum in silently.
            if item_date and not _item_in_span(
                item_date, row.start_date, row.end_date
            ):
                logger.warning(
                    "OpenETCache row %s (parcel=%s, span %s..%s) carries item "
                    "dated %s outside its span — skipping (malformed cache row)",
                    row.pk,
                    getattr(parcel, "parcel_number", parcel),
                    row.start_date,
                    row.end_date,
                    item_date,
                )
                continue
            if item_date.startswith(period) and item.get(key) is not None:
                total_mm += Decimal(str(item[key]))
                matched += 1

    return total_mm, matched, rows.count()


def et_gross(running_af, parcel, period, ctx, config):
    """Seed the chain with the parcel's gross ET for the period (positive AF).

    Reads OpenETCache rows matching the configured model/variable for this parcel
    via the shared _read_cache_mm helper, summing the et_data items keyed "et" for
    the period month. Converts the mm total to a POSITIVE acre-foot magnitude using
    the same mm->AF math as et_mm_to_acre_feet (which returns a negative usage
    value; we take abs). Ignores the incoming running_af — this primitive starts
    the chain.
    """
    model = config.get("model", "Ensemble")
    variable = config.get("variable", "ET")

    total_mm, matched, row_count = _read_cache_mm(
        parcel, period, variable, model, "et"
    )

    area = parcel.area_acres or Decimal("0")
    # et_mm_to_acre_feet returns negative (usage); the chain threads positive
    # magnitudes, so take the absolute value here.
    af = abs(et_mm_to_acre_feet(total_mm, area))

    # Stash the gross-ET magnitude in the shared ctx so a downstream step can
    # decompose a below-floor surplus into genuine rain surplus vs. surface
    # over-delivery (clamp_floor / ISS-052). Cross-step data is exactly what ctx
    # is for; the detail dict below is unchanged so audit/tests stay stable.
    ctx["et_gross_af"] = af

    detail = {
        "model": model,
        "variable": variable,
        "rows": row_count,
        "months_matched": matched,
        "et_mm": str(total_mm),
        "area_acres": str(area),
    }
    return af, _record("et_gross", running_af, af, detail)


def subtract_surface_water(running_af, parcel, period, ctx, config):
    """Subtract surface water delivered to this parcel in the period.

    surface_diversion ledger rows are stored NEGATIVE (delivered magnitude as a
    negative number); take the absolute value of their sum and subtract it. Does
    NOT floor the result — clamp_floor owns the floor.
    """
    from parcels.models import ParcelLedger

    year, month = _period_year_month(period)
    agg = ParcelLedger.objects.filter(
        parcel=parcel,
        source_type="surface_diversion",
        effective_date__year=year,
        effective_date__month=month,
    ).aggregate(total=Sum("amount_acre_feet"))
    surface_af = abs(agg["total"] or Decimal("0"))

    new_running = running_af - surface_af
    detail = {"surface_water_af": str(surface_af)}
    return new_running, _record(
        "subtract_surface_water", running_af, new_running, detail
    )


def facility_only_zero(running_af, parcel, period, ctx, config):
    """Force running_af to 0 for facility-only parcels (no irrigated usage).

    A parcel is facility-only when it has no UsageLocation with a non-null
    crop_type — those parcels pump nothing billable. Otherwise pass through.
    """
    from parcels.models import UsageLocation

    has_irrigation = UsageLocation.objects.filter(
        parcel=parcel, crop_type__isnull=False
    ).exists()
    facility_only = not has_irrigation

    new_running = Decimal("0") if facility_only else running_af
    detail = {"facility_only": facility_only}
    return new_running, _record(
        "facility_only_zero", running_af, new_running, detail
    )


def clamp_floor(running_af, parcel, period, ctx, config):
    """Floor running_af at config['floor'] (default 0), surfacing any surplus.

    Side-effect-FREE by contract: this primitive is also called by --dry-run and
    the live preview screen, so it must never write a WaterCredit. It only SIGNALS
    intent — the surplus magnitudes and the credit levers — in step_record["detail"];
    run_calculations reads that and does the actual banking + recharge writes
    inside its transaction.

    A *total surplus* is the chain coming in BELOW the floor (effective precip +
    surface water exceeded gross ET): total_surplus = max(0, floor - running_af).
    ISS-052 splits that total into two physically distinct parts:

      - **precip_surplus_af** — genuine rainfall that exceeded crop ET on its own
        (max(0, Pe - ET)). This is real saved water; run_calculations BANKS it as
        a WaterCredit to draw down in a later dry month.
      - **incidental_recharge_af** — the remainder, which is surface water
        delivered beyond crop demand. Physically this is deep percolation that
        recharges the aquifer, NOT a conservation credit. run_calculations writes
        it as a positive groundwater recharge ledger row. Banking it (the pre-052
        behavior) silently masked summer pumping via phantom credit draws.

    The genuine-precip portion is CAPPED at the total surplus
    (min(total_surplus, max(0, Pe - ET))) so a parcel whose running was forced to
    the floor by an earlier step (e.g. facility_only_zero) never banks a phantom
    rain credit. ET and Pe are read from the shared ctx (stashed by et_gross and
    subtract_effective_precip). If either is absent — a plan without those steps,
    or an isolated unit call — we fall back to the pre-052 behavior: the whole
    surplus is treated as precip_surplus and incidental recharge is zero, so
    existing chains and tests are unchanged.

    The credit levers (depreciation_rate, expiry_months) are passed straight
    through from config so the runner reads them off the breakdown without
    re-querying the step.
    """
    floor = Decimal(str(config.get("floor", 0)))
    bank = bool(config.get("bank", False))

    total_surplus = floor - running_af
    if total_surplus < 0:
        total_surplus = Decimal("0")

    # Split the surplus (ISS-052). ctx carries the gross-ET and effective-precip
    # magnitudes when the full chain ran; absent them, fall back to "all surplus
    # is precip" so legacy/no-precip plans behave exactly as before.
    et_af = ctx.get("et_gross_af")
    pe_af = ctx.get("effective_precip_af")
    if et_af is not None and pe_af is not None:
        genuine_precip = pe_af - et_af
        if genuine_precip < 0:
            genuine_precip = Decimal("0")
        precip_surplus_af = min(total_surplus, genuine_precip)
    else:
        precip_surplus_af = total_surplus
    incidental_recharge_af = total_surplus - precip_surplus_af

    new_running = running_af if running_af >= floor else floor
    detail = {
        "floor": str(floor),
        "bank": bank,
        # surplus_af retained for backward compatibility (it equals the total).
        "surplus_af": str(total_surplus),
        "precip_surplus_af": str(precip_surplus_af),
        "incidental_recharge_af": str(incidental_recharge_af),
        # Credit levers passed through for run_calculations (38-04 banking).
        "depreciation_rate": config.get("depreciation_rate", 0),
        "expiry_months": config.get("expiry_months", None),
    }
    return new_running, _record("clamp_floor", running_af, new_running, detail)


def subtract_effective_precip(running_af, parcel, period, ctx, config):
    """Subtract effective precipitation (AF) from gross ET — net consumptive use.

    The contested math (raw / fraction / usda_scs TR-21) lives in the Django-free
    accounting/precip_math.py, proven against published reference vectors. This
    wrapper only does the I/O and units:

      1. Read parcel-month precip mm  (variable="precip", model="GRIDMET", key "precip")
         and gross ET mm (variable="ET", model="Ensemble", key "et") from the cache.
         Reading ET here independently keeps the step order-agnostic — it does NOT
         trust running_af, which depends on where in the chain it sits.
      2. mm -> inches (÷25.4), call effective_precip_inches(p_in, et_in, **config).
      3. inches -> mm (×25.4) -> AF via the one shared mm->AF helper.
      4. new_running = running_af − Pe_af. Does NOT floor (clamp_floor owns that);
         usda_scs caps Pe at ET so its own output stays ≥ 0, but raw/fraction may
         drive running_af negative — correct, clamp_floor catches it later.

    No precip row -> Pe = 0 -> running_af passes through unchanged (zero effective
    precip is a valid, correct outcome, e.g. a dry summer month).
    """
    from accounting.precip_math import effective_precip_inches

    precip_mm, _, _ = _read_cache_mm(parcel, period, "precip", "GRIDMET", "precip")
    et_mm, _, _ = _read_cache_mm(parcel, period, "ET", "Ensemble", "et")

    mm_per_in = Decimal("25.4")
    p_in = precip_mm / mm_per_in
    et_in = et_mm / mm_per_in

    pe_in = effective_precip_inches(p_in, et_in, **config)
    pe_mm = pe_in * mm_per_in

    area = parcel.area_acres or Decimal("0")
    # abs(): et_mm_to_acre_feet returns a negative usage value; we want the
    # positive effective-precip magnitude to subtract from the running total.
    pe_af = abs(et_mm_to_acre_feet(pe_mm, area))
    new_running = running_af - pe_af

    # Stash the effective-precip magnitude for clamp_floor's surplus split
    # (genuine rain surplus banks; surface over-delivery routes to recharge —
    # ISS-052). Kept OUT of the detail dict below so the pinned audit-key set
    # (test_detail_dict_carries_the_audit_keys) is unchanged.
    ctx["effective_precip_af"] = pe_af

    detail = {
        "method": config.get("method", "usda_scs"),
        "precip_mm": str(precip_mm),
        "et_mm": str(et_mm),
        "effective_precip_mm": str(pe_mm),
        "effective_precip_af": str(pe_af),
    }
    return new_running, _record(
        "subtract_effective_precip", running_af, new_running, detail
    )


# Maps step_type -> primitive. subtract_effective_precip joined the registry in
# 38-03 (implemented test-first against published TR-21 vectors).
STEP_REGISTRY = {
    "et_gross": et_gross,
    "subtract_effective_precip": subtract_effective_precip,
    "subtract_surface_water": subtract_surface_water,
    "facility_only_zero": facility_only_zero,
    "clamp_floor": clamp_floor,
}
