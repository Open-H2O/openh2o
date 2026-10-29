# SPDX-License-Identifier: AGPL-3.0-or-later
"""The "How was this calculated?" page: one parcel's engine run, step by step, with the plain-words sentence for each step."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from accounting.models import CalculationRun
from accounting.ledger_words import DELIVERY_SHARE_BY_FIXED, DELIVERY_SHARE_BY_USE
from accounting.precip_math import METHOD_LABELS
from parcels.models import Parcel, ParcelLedger


# ---------------------------------------------------------------------------
# Calculation Run audit trail — "How was this calculated?"
# ---------------------------------------------------------------------------


def _fmt(value, places=4):
    """Round a Decimal-ish breakdown value to `places` for display, defaulting
    to a dash when the value is missing."""
    if value is None or value == "":
        return "—"
    try:
        return f"{Decimal(str(value)):.{places}f}"
    except (ArithmeticError, ValueError, TypeError):
        return str(value)


def _mm_to_in(mm):
    """Convert a millimeter breakdown value to inches (÷25.4), or None if missing.

    Kept out of a template filter on purpose: this conversion feeds a
    derivation sentence in `_step_detail_summary`, not a figure of its own.
    """
    if mm is None or mm == "":
        return None
    try:
        return Decimal(str(mm)) / Decimal("25.4")
    except (ArithmeticError, ValueError, TypeError):
        return None


def _delivery_split_kind(parcel, period):
    """How the month's canal delivery to this field was arrived at, off its ledger rows.

    The calculation page's canal line says, in the ledger's own words, when
    the field's delivered figure was divided up from a headgate's canal total
    rather than read from the field's own gate record. The run stores no such
    flag, so this reads the month's ``surface_diversion`` rows (the
    ones the canal split wrote, ``divided_from_headgate``, not told
    apart by the wording of their description). ``"fixed"`` when any of them
    carries the fixed-share tail ``delivery_share_words`` writes (in the
    middle of the sentence, followed by the percentage and where the share
    came from, hence ``description__contains``), ``"use"`` for any other split
    row (a share weighted by crop water use), ``None`` when the field has no
    split row (its own recorded delivery, or no delivery at all).
    """
    try:
        year, month = (int(part) for part in period.split("-")[:2])
    except (AttributeError, ValueError):
        return None
    rows = ParcelLedger.objects.filter(
        parcel=parcel,
        source_type="surface_diversion",
        divided_from_headgate=True,
        effective_date__year=year,
        effective_date__month=month,
    )
    if rows.filter(description__contains=DELIVERY_SHARE_BY_FIXED).exists():
        return "fixed"
    if rows.exists():
        return "use"
    return None


def _step_detail_summary(step, *, delivery_split=None):
    """The salient, human-readable detail for one breakdown step.

    Each primitive stores different keys (et_gross has et_mm/area; the precip step
    has the method + effective_precip_af; clamp_floor has floor/surplus), so we
    surface only the line that explains what THAT step did to the running total.
    ``delivery_split`` is ``_delivery_split_kind``'s answer for the month and
    is read by the canal step only.
    """
    detail = step.get("detail", {}) or {}
    step_type = step.get("step_type")

    if step_type == "et_gross":
        # The inches figure closes the arithmetic a reader can
        # check by hand (4.8058 in × 109.80 ac ÷ 12 in/ft = 43.9731 AF, the Out
        # cell). Four places on et_in (this page's four-place convention); et_mm
        # and area keep their existing two places (unchanged figures).
        et_in = _mm_to_in(detail.get("et_mm"))
        et_in_text = f"{et_in:.4f}" if et_in is not None else "not recorded"
        return (
            f"{et_in_text} in of ET ({_fmt(detail.get('et_mm'), 2)} mm) × "
            f"{_fmt(detail.get('area_acres'), 2)} ac ÷ 12 in/ft"
        )
    if step_type == "subtract_effective_precip":
        method = detail.get("method", "usda_scs")
        method_label = METHOD_LABELS.get(method, "Method not recorded")
        af_clause = f"{_fmt(detail.get('effective_precip_af'))} AF subtracted"
        # A pre-38 run recorded no precip_mm; fall back to the AF clause alone
        # rather than printing a dash where an inches figure should be.
        pe_in = _mm_to_in(detail.get("effective_precip_mm"))
        p_in = _mm_to_in(detail.get("precip_mm"))
        if pe_in is None or p_in is None:
            return f"{method_label}: {af_clause}"
        return (
            f"{method_label}: {pe_in:.4f} in of the {p_in:.4f} in of rain "
            f"counted as effective; {af_clause}"
        )
    if step_type == "subtract_surface_water":
        # With the field's efficiency applied, the subtracted figure is
        # the delivery times the efficiency, not the delivery; say both. A
        # delivery that was a share of a headgate total says how the share
        # was made, in the ledger's own words (`delivery_split`, read off the month's
        # ledger rows by `_delivery_split_kind`; the run stores no split flag).
        if detail.get("delivered_af") is not None and detail.get("efficiency"):
            whose = (
                "the field's irrigation method"
                if detail.get("efficiency_source") == "method"
                else "the Delivery Settings default"
            )
            # Written as the formula with its real signs.
            if delivery_split == "use":
                split = f", {DELIVERY_SHARE_BY_USE},"
            elif delivery_split == "fixed":
                split = f", divided up from the canal total by {DELIVERY_SHARE_BY_FIXED},"
            else:
                split = ""
            return (
                f"{_fmt(detail.get('delivered_af'))} AF delivered{split} \u00d7 "
                f"irrigation efficiency {_fmt(detail.get('efficiency'), 2)} ({whose}) "
                f"= {_fmt(detail.get('consumed_af'))} AF"
            )
        return f"{_fmt(detail.get('surface_water_af'))} AF delivered and subtracted in full"
    if step_type == "facility_only_zero":
        return "no crop on record, set to zero" if detail.get("facility_only") else "has a crop on record, unchanged"
    if step_type == "clamp_floor":
        surplus = Decimal(str(detail.get("surplus_af", "0") or "0"))
        base = f"floor {_fmt(detail.get('floor'), 2)}"
        if surplus > 0:
            # A run from an older engine with banking on did bank it; a new run
            # carries the figure as information only.
            if detail.get("bank"):
                return f"{base}; {_fmt(surplus)} AF surplus banked"
            return f"{base}; {_fmt(surplus)} AF below the floor, not carried forward"
        return base
    return ""


def _over_delivery_left_af(run):
    """What the run's own two stamped figures leave in the basin.

    ``over_delivery_af`` and ``over_delivery_credited_af`` are both read off
    THIS run, never the live setting (the same rule that protects
    ``gw_extracted_af``), so a later change to Delivery Settings moves
    nothing this page says about a run already computed. None whenever
    nothing was actually credited this run: not_credited, named_line, or a
    "credited" run that credited nothing (no over-delivery to apply the
    share to, or a no-well field with no zone to hold its share). The
    template reads that state the same way it reads not_credited.
    """
    if run.over_delivery_treatment != "credited" or run.over_delivery_credited_af is None:
        return None
    return (run.over_delivery_af - run.over_delivery_credited_af).quantize(Decimal("0.0001"))


def _over_delivery_share_pct(run):
    """The stamped leave-behind share, as a percent number for the
    template's own ``floatformat:0`` (never a pre-formatted string, so the
    share is formatted the same way as every other number on this page)."""
    if run.over_delivery_leave_behind is None:
        return None
    return run.over_delivery_leave_behind * 100


def _breakdown_facts(run: CalculationRun) -> dict[str, object]:
    """The efficiency source, precip method, rainfall, area and floor read off the run's steps."""
    irrigation_efficiency_source = None
    precip_method = None
    rainfall_mm = None
    area_acres = None
    floor = None
    for step in run.breakdown:
        detail = step.get("detail") or {}
        step_type = step.get("step_type")
        if step_type == "subtract_surface_water" and irrigation_efficiency_source is None:
            irrigation_efficiency_source = detail.get("efficiency_source")
        elif step_type == "subtract_effective_precip":
            precip_method = detail.get("method", "usda_scs")
            rainfall_mm = detail.get("precip_mm")
        elif step_type == "clamp_floor":
            floor = detail.get("floor")
        elif step_type == "et_gross":
            area_acres = detail.get("area_acres")
    return {
        "irrigation_efficiency_source": irrigation_efficiency_source,
        "precip_method": precip_method,
        "rainfall_mm": rainfall_mm,
        "area_acres": area_acres,
        "floor": floor,
    }


def _irrigation_method_name(parcel: Parcel, irrigation_efficiency_source: object) -> str | None:
    """The field's irrigation method name when the efficiency came from the method, else None."""
    irrigation_method_name = None
    if irrigation_efficiency_source == "method":
        link = getattr(parcel, "irrigation", None)
        if link is not None:
            irrigation_method_name = link.method.name
    return irrigation_method_name


def _rainfall_acre_feet(rainfall_mm: object, area_acres: object) -> Decimal | None:
    """The month's rainfall in acre-feet over the field, or None when either input is missing."""
    # The month's gridMET rainfall in acre-feet over the field, by the same
    # conversion and the same area the run used for crop ET, so it reads
    # beside effective precipitation in one unit.
    rainfall_af = None
    if rainfall_mm is not None and area_acres is not None:
        from accounting.services import et_mm_to_acre_feet

        rainfall_af = abs(
            et_mm_to_acre_feet(Decimal(str(rainfall_mm)), Decimal(str(area_acres)))
        )
    return rainfall_af


def _receipt_context(parcel, run, period):
    """The equation panel's figures for one run with a well and no meter reading.

    The page shows three equations in the
    engineer's terms (crop ET, effective
    precipitation, ETAW, ETAW met by surface water, ETAW met by groundwater,
    the field's irrigation efficiency, groundwater extraction (estimated),
    surface water in excess of ETAW):

        Crop ET - Effective precipitation = ETAW
        ETAW - ETAW met by surface water = ETAW met by groundwater
        ETAW met by groundwater / the field's irrigation efficiency
            = groundwater extraction (estimated)

    Every figure is the run's own stamped column or is worked from them; the
    two percentages are read back off the run (the irrigation efficiency its
    canal water was multiplied by; the one ETAW met by groundwater was
    divided by), never off the live setting, so a change to
    Delivery Settings moves nothing a month already run says about itself.

    ``surface_water_af`` is the delivery times the irrigation efficiency, NOT
    capped at ETAW (accounting/steps.py::subtract_surface_water); ETAW met by
    surface water is that figure up to ETAW, and the part above ETAW is the
    run's own ``over_delivery_af`` (the floor step's incidental_recharge_af).
    """
    facts = _breakdown_facts(run)
    irrigation_efficiency_source = facts["irrigation_efficiency_source"]
    precip_method = facts["precip_method"]
    floor = facts["floor"]
    irrigation_method_name = _irrigation_method_name(parcel, irrigation_efficiency_source)

    # The field's irrigation efficiency the run stamped (a run from
    # before the stamp reads it back off final_af / gw_extracted_af).
    from accounting.services import (
        groundwater_efficiency_method_name,
        stamped_groundwater_efficiency,
    )

    gw_efficiency = stamped_groundwater_efficiency(run)

    zero = Decimal("0")
    etaw = run.net_consumptive_use_af
    surface = run.surface_water_af or zero
    etaw_met_by_surface = min(surface, max(etaw, zero))
    # ETAW met by groundwater before the floor step is never below zero here,
    # since ETAW met by surface water never exceeds ETAW. The floor raises
    # final_af above it only where a district set a floor above zero; the
    # panel then names the floor. Compared with the floor itself, not by
    # difference: the stored ETAW and final_af are rounded separately and
    # can differ by 0.0001 AF with no floor involved (41 of 439 demo runs).
    floor_value = Decimal(str(floor)) if floor is not None else zero
    floor_raised = (
        floor_value > zero
        and run.final_af == floor_value
        and etaw - etaw_met_by_surface < floor_value
    )

    rainfall_af = _rainfall_acre_feet(facts["rainfall_mm"], facts["area_acres"])

    return {
        "receipt": True,
        "etaw_af": etaw,
        "etaw_met_by_surface_af": etaw_met_by_surface,
        "floor_raised": floor_raised,
        "floor_af": floor_value,
        "precip_method_label": (
            METHOD_LABELS.get(precip_method, "Method not recorded")
            if precip_method
            else None
        ),
        "rainfall_af": rainfall_af,
        "gw_efficiency_pct": (
            gw_efficiency * 100 if gw_efficiency is not None else None
        ),
        "gw_efficiency_source": run.groundwater_efficiency_source,
        "gw_efficiency_method_name": groundwater_efficiency_method_name(run),
        "irrigation_efficiency_pct": (
            run.surface_efficiency * 100 if run.surface_efficiency is not None else None
        ),
        "irrigation_efficiency_source": irrigation_efficiency_source,
        "irrigation_method_name": irrigation_method_name,
        # "use" / "fixed" / None, off the month's ledger rows (the run stores
        # no split flag): whether the delivery was a share of a headgate total.
        "delivery_split": _delivery_split_kind(parcel, period),
        # What happened to surface water in excess of ETAW, by the
        # run's own stamp. None whenever nothing was credited.
        "over_delivery_left_af": _over_delivery_left_af(run),
        "over_delivery_share_pct": _over_delivery_share_pct(run),
    }


@login_required
def calculation_run_detail(request, parcel_id, period):
    """One month's calculation receipt: where the estimated pumping came from.

    Keyed on the STABLE (parcel, period), not the run's pk: the calculated ledger
    row is delete-recreated every run (its pk churns) and the ledger list iterates
    rows, not runs, so this key lets a ledger link resolve without threading a run
    pk through the list and survives re-runs. Most-recent run wins if more than one
    ever exists; 404 when none.

    Only a month with a well and no meter reading
    (``residual_disposition == "groundwater"``) has a receipt. A metered or
    no-well month is a short page (one sentence and a link back to the field),
    not a 404: the field page no longer links those months, but a direct URL
    still answers.
    """
    parcel = get_object_or_404(Parcel, pk=parcel_id)
    run = (
        CalculationRun.objects.filter(parcel=parcel, period=period)
        .order_by("-created_at")
        .first()
    )
    if run is None:
        raise Http404("No calculation run for this parcel and period.")

    context = {
        "parcel": parcel,
        "period": period,
        "run": run,
        "month_label": (
            run.period_start.strftime("%B %Y") if run.period_start else period
        ),
        # The run's config_hash (a 12-character fingerprint) is NOT printed:
        # no page compares two runs by it.
        "methodology_plan_name": run.methodology_plan_name,
        "receipt": False,
    }
    if run.residual_disposition == "groundwater":
        context.update(_receipt_context(parcel, run, period))
    return render(request, "accounting/calculation_run_detail.html", context)
