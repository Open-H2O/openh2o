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

NOTE: subtract_effective_precip is intentionally ABSENT. 38-03 implements it
test-first and registers it. The default plan ships that step disabled, so the
evaluator (which only looks up enabled steps) never tries to resolve it here.

OpenETCache shape (verified against live Butler data, 2026-05-31):
  - et_data is a LIST of dicts: [{"et": 170.02, "date": "2024-06", "unit": "mm"}, ...]
  - a single cache row can span multiple months (e.g. Jun–Aug in one row)
  - real strings are variable="ET", model_name="Ensemble" (capitalized)
et_gross honors all three facts; getting any wrong silently zeroes the parcel.
"""

from decimal import Decimal

from django.db.models import Sum

from accounting.services import et_mm_to_acre_feet


def _period_year_month(period):
    """Parse a 'YYYY-MM' period string into (year, month) ints."""
    year_str, month_str = period.split("-")
    return int(year_str), int(month_str)


def _record(step_type, input_af, output_af, detail):
    return {
        "step_type": step_type,
        "label": step_type,  # evaluator overrides with the configured label
        "input_af": str(input_af),
        "output_af": str(output_af),
        "detail": detail,
    }


def et_gross(running_af, parcel, period, ctx, config):
    """Seed the chain with the parcel's gross ET for the period (positive AF).

    Reads OpenETCache rows matching the configured model/variable for this
    parcel whose [start_date, end_date] span covers the period, then sums the
    et_data list items whose "date" matches the period month. Converts the mm
    total to a POSITIVE acre-foot magnitude using the same mm->AF math as
    et_mm_to_acre_feet (which returns a negative usage value; we take abs).
    Ignores the incoming running_af — this primitive starts the chain.
    """
    import datetime as dt

    from datasync.models import OpenETCache

    model = config.get("model", "Ensemble")
    variable = config.get("variable", "ET")
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
            if str(item.get("date", "")).startswith(period) and item.get("et") is not None:
                total_mm += Decimal(str(item["et"]))
                matched += 1

    area = parcel.area_acres or Decimal("0")
    # et_mm_to_acre_feet returns negative (usage); the chain threads positive
    # magnitudes, so take the absolute value here.
    af = abs(et_mm_to_acre_feet(total_mm, area))

    detail = {
        "model": model,
        "variable": variable,
        "rows": rows.count(),
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
    """Floor running_af at config['floor'] (default 0).

    config knob "bank" (bool) is accepted and recorded but is a NO-OP in 38-02:
    banking would deposit a WaterCredit, which does not exist until 38-04.
    """
    floor = Decimal(str(config.get("floor", 0)))
    bank = bool(config.get("bank", False))

    new_running = running_af if running_af >= floor else floor
    # 38-04: deposit floored surplus as WaterCredit when bank=on
    detail = {"floor": str(floor), "bank": bank}
    return new_running, _record("clamp_floor", running_af, new_running, detail)


# Maps step_type -> primitive. subtract_effective_precip is deliberately not
# here; 38-03 adds it test-first.
STEP_REGISTRY = {
    "et_gross": et_gross,
    "subtract_surface_water": subtract_surface_water,
    "facility_only_zero": facility_only_zero,
    "clamp_floor": clamp_floor,
}
