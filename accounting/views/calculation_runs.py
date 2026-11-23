# SPDX-License-Identifier: AGPL-3.0-or-later
"""The "How was this calculated?" page: one parcel's engine run, step by step, with the plain-words sentence for each step."""
import datetime as dt
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounting.models import CalculationRun, ReportingPeriod
from accounting.ledger_words import DELIVERY_SHARE_BY_FIXED, DELIVERY_SHARE_BY_USE
from accounting.precip_math import METHOD_LABELS
from core.modules import is_enabled
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
    rows = ParcelLedger.objects.current().filter(
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
        pe_in = _mm_to_in(detail.get("effective_precip_mm"))
        p_in = _mm_to_in(detail.get("precip_mm"))
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
                "the use area's irrigation method"
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
    if step_type == "clamp_floor":
        surplus = Decimal(str(detail.get("surplus_af", "0") or "0"))
        base = f"floor {_fmt(detail.get('floor'), 2)}"
        if surplus > 0:
            return f"{base}; {_fmt(surplus)} AF below the floor, not carried forward"
        return base
    return ""


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


def _irrigation_method_name(
    parcel: Parcel, irrigation_efficiency_source: object, period: str | None = None
) -> str | None:
    """The name of the irrigation method in force in the run's month when the efficiency came from the method, else None."""
    from parcels.services import irrigation_row_in_force

    irrigation_method_name = None
    if irrigation_efficiency_source == "method":
        link = irrigation_row_in_force(parcel, period)
        if link is not None and link.method is not None:
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


def _parts_adding_to(parts: list[Decimal], figure: Decimal) -> list[Decimal]:
    """``parts`` rounded to two places so they add exactly to ``figure`` as the page prints it.

    The parts were stamped by the step that booked ``figure`` and add to it to within a few
    ten-thousandths (the column stores four places); the largest part takes that difference
    before the column is rounded, so the column and the figure above it agree to the cent.
    """
    from accounting.services import round_to_total

    exact = list(parts)
    largest = max(range(len(exact)), key=lambda i: exact[i])
    exact[largest] += figure - sum(exact, Decimal("0"))
    return round_to_total(exact)


def _field_list(
    run: CalculationRun, crop_et_af: Decimal | None, rainfall_af: Decimal | None
) -> dict[str, object] | None:
    """The OpenET fields the month was figured from, read ONLY from the run's own stamp.

    Never read live: a figure OpenET revises later must not change what a past month's page
    says it was made of. None when the run carries no stamp (an older run, a use area with no
    OpenET field, a fallow month, or a month whose fields no longer added to its crop ET).
    Each column adds to the figure above it: crop ET to the run's crop ET, rainfall to the
    receipt's Rainfall row. ``crop_et_af`` is the Crop ET figure the page prints; the parts
    are listed only when it is the run's own crop ET to the cent. The outside row prints only
    when it rounds to 0.01 acres or more.
    """
    detail = next(
        (step.get("detail") or {} for step in run.breakdown or [] if step.get("step_type") == "et_gross"),
        {},
    )
    stamped = detail.get("fields")
    if not stamped or run.gross_et_af is None or crop_et_af is None:
        return None
    if abs(crop_et_af - run.gross_et_af) > Decimal("0.005"):
        return None
    crop = _parts_adding_to([Decimal(r["crop_et_af"]) for r in stamped], crop_et_af)
    rain = None
    if rainfall_af is not None and all(r.get("rainfall_af") is not None for r in stamped):
        rain = _parts_adding_to([Decimal(r["rainfall_af"]) for r in stamped], rainfall_af)
    rows = [
        {
            "field_id": r["field_id"],
            "acres": Decimal(r["acres"]),
            "crop_et_af": crop[i],
            "rainfall_af": None if rain is None else rain[i],
        }
        for i, r in enumerate(stamped)
    ]
    outside = detail.get("outside_acres")
    outside = Decimal(outside).quantize(Decimal("0.01")) if outside is not None else None
    return {
        "rows": rows,
        "outside_acres": outside if outside is not None and outside >= Decimal("0.01") else None,
        "has_rainfall": rain is not None,
    }


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
    irrigation_method_name = _irrigation_method_name(parcel, irrigation_efficiency_source, run.period)

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
    }


@login_required
def calculation_run_detail(request, parcel_id, period):
    """One month's calculation receipt: where the estimated pumping came from.

    Keyed on the STABLE (parcel, period), not the run's pk: the calculated ledger
    row can be removed and written again (an archetype flip) and the ledger list iterates
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
        return _no_figure_page(request, parcel, period)

    context = {
        "parcel": parcel,
        "period": period,
        "run": run,
        "month_label": (
            run.period_start.strftime("%B %Y") if run.period_start else period
        ),
        # The method as the ledger file names it: the plan name, then the run's
        # config_hash (a 12-character settings fingerprint). The export's
        # calculation_method column carries the same text, so a row in a
        # downloaded file can be matched to this page.
        "methodology_plan_name": run.methodology_plan_name,
        "methodology_settings_code": run.config_hash,
        "receipt": False,
    }
    if run.residual_disposition == "groundwater":
        context.update(_receipt_context(parcel, run, period))
    context["crop_et"] = _crop_et_context(request.user, parcel, period, request.GET.get("open", ""))
    # The receipt prints the run's crop ET; the short page prints the recorded figure.
    if context["receipt"]:
        printed = run.gross_et_af
    elif context["crop_et"] is not None:
        printed = Decimal(str(context["crop_et"]["figure"]).replace(",", ""))
    else:
        printed = None
    context["field_list"] = _field_list(run, printed, context.get("rainfall_af"))
    if not context["receipt"]:
        context["month_ledger"] = _month_ledger(parcel, _first_of(period))
    return render(request, "accounting/calculation_run_detail.html", context)


def _first_of(period):
    """The first day of a ``"YYYY-MM"`` month."""
    return dt.date(int(period[:4]), int(period[5:7]), 1)


def _month_ledger(parcel, first):
    """The second card of a short month page: the month's ledger entries and the water year's months.

    Each month of the water year holding ``first`` is listed in order. A month links to its own
    page when it has one: a calculation for the use area and month, or a month waiting for
    OpenET. The month on screen is marked and not linked. With no water year on record the
    months are left out.
    """
    entries = list(
        ParcelLedger.objects.current()
        .filter(parcel=parcel, effective_date__year=first.year, effective_date__month=first.month)
        .select_related("water_type")
        .order_by("effective_date", "pk")
    )
    year = ReportingPeriod.objects.filter(start_date__lte=first, end_date__gte=first).first()
    months = []
    if year is not None:
        firsts = []
        month = year.start_date.replace(day=1)
        while month <= year.end_date:
            firsts.append(month)
            month = (month + dt.timedelta(days=32)).replace(day=1)
        periods = [f"{m:%Y-%m}" for m in firsts]
        calculated = set(
            CalculationRun.objects.filter(parcel=parcel, period__in=periods).values_list("period", flat=True)
        )
        waiting = None
        if is_enabled("datasync"):
            from datasync.crop_et import no_figure_context

            waiting = no_figure_context
        for m, period in zip(firsts, periods):
            current = m == first
            has_page = not current and (
                period in calculated or (waiting is not None and waiting(parcel, period) is not None)
            )
            months.append({"label": f"{m:%b}", "period": period, "current": current, "has_page": has_page})
    return {"label": f"{first:%B %Y}", "entries": entries, "water_year": year, "months": months}


def _no_figure_page(request, parcel, period):
    """The page of a month OpenET was asked about and sent no crop ET for; Not found otherwise.

    The month has no calculation, so the page names the month and lists its ledger supplies.
    A month OpenET was never asked about stays Not found.
    """
    from datasync.crop_et import month_first, no_figure_context

    try:
        first = month_first(period)
    except (TypeError, ValueError):
        raise Http404("No calculation run for this parcel and period.") from None
    found = no_figure_context(parcel, period)
    if found is None:
        raise Http404("No calculation run for this parcel and period.")
    context = {
        "parcel": parcel,
        "period": period,
        "run": None,
        "month_label": first.strftime("%B %Y"),
        "receipt": False,
        "no_figure": found,
        "crop_et": None,
        "month_ledger": _month_ledger(parcel, first),
    }
    return render(request, "accounting/calculation_run_detail.html", context)


def _crop_et_context(user, parcel, period, open_action=""):
    """The month's recorded crop ET, its bands, and whether this person sees their buttons.

    A band's button follows the site's rule for correcting records: a person who can
    write, and in a finalized year an administrator only. ``open_action`` (the ``open``
    query value the button sends) opens that band's correction row in place of the
    button; for anyone who may not act it opens nothing.
    """
    from accounting.locks import period_for
    from core.access import may_override
    from datasync.crop_et import page_context

    found = page_context(parcel, period)
    if found is None:
        return None
    year = period_for(found["record"].month)
    closed = year is not None and year.is_finalized
    can_act = bool(getattr(user, "can_write", False)) and (not closed or may_override(user))
    band = found["newer"]
    if band is not None:
        band["can_act"] = can_act
        band["open"] = bool(can_act and band["action"] == open_action)
    return found


@login_required
@require_POST
def crop_et_accept(request, parcel_id, period):
    """Accept OpenET's newer figure for the month.

    It is a recorded correction with the person's reason, and the month is
    recalculated at once (the same request Correct this record starts). In a
    finalized year only an administrator, through the recorded door.
    """
    from accounting.locks import PeriodFinalized, period_for
    from core import corrections
    from core.access import may_override, read_only_response
    from core.corrections_views import _door, _recalculate
    from datasync import crop_et
    from datasync.models import CropETFigure

    if not request.user.can_write:
        return read_only_response(request)
    parcel = get_object_or_404(Parcel, pk=parcel_id)
    # Only a crop ET record has a newer figure to accept; a month's rain record has none.
    record = get_object_or_404(
        CropETFigure, pk=request.POST.get("record") or 0, parcel=parcel,
        month=crop_et.month_first(period), variable="ET", model_name="Ensemble",
    )
    page = reverse("accounting:calculation_run_detail", args=[parcel.pk, period])
    reason = request.POST.get("reason", "")
    year = period_for(record.month)
    closed = year is not None and year.is_finalized
    admin = may_override(request.user)
    if closed and not admin:
        messages.error(
            request,
            f"Nothing was corrected. {year.name} is finalized. "
            "An administrator can correct or void a record in it.",
        )
        return redirect(page)
    try:
        with _door(reason.strip() or "Reason not given.", closed):
            with transaction.atomic():
                months = crop_et.accept_newer_figure(record, user=request.user, reason=reason)
                covered = _recalculate(
                    request, months, "record_corrected", reason.strip() if closed else ""
                )
    except (corrections.AlreadyVoided, corrections.AlreadyReplaced, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(page)
    except PeriodFinalized as exc:
        messages.error(request, f"Nothing was corrected. {exc}")
        return redirect(page)
    messages.success(request, _corrected_words(covered))
    return redirect(page)


def _corrected_words(covered):
    from core.corrections_views import _corrected_sentence

    return _corrected_sentence(None, covered, [])
