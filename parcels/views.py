# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcels views.

The parcel list and detail surfaces. The detail page is the per-parcel
water-balance view: it reconciles the parcel's estimated consumptive use (ET)
against its supplies for a reporting period (consumptive balance + mass
balance), lists the recent ledger rows, shows zone memberships and the wells
that irrigate it, and inline-edits the parcel's editable fields.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from core.access import public_in_open_demo
from core.workspace import list_response, redirect_to_selected

from accounting.models import ReportingPeriod
from accounting.services import (
    parcel_consumptive_balance,
    parcel_over_delivery_shown,
    parcel_receipt_periods,
    parcel_run_periods,
    parcel_unmet_demand,
    parcel_water_use_months,
)
from core.map_labels import map_label
from core.modules import is_enabled
from core.validation import FieldValidationError, coerce_decimal, coerce_int
from parcels.forms import FallowPeriodForm
from parcels.models import (
    IrrigationMethod,
    Parcel,
    ParcelIrrigationMethod,
    ParcelLedger,
)


EDITABLE_FIELDS = {
    "owner_name": {"label": "Owner", "type": "text", "max_length": 200},
    "area_acres": {
        "label": "Area (acres)", "type": "number", "step": "0.01",
        "min_value": 0, "min_exclusive": True,
    },
    "status": {"label": "Status", "type": "select", "choices": Parcel.STATUS_CHOICES},
    "address": {"label": "Address", "type": "textarea"},
    "notes": {"label": "Notes", "type": "textarea"},
}

#: Not a Parcel column, so not in EDITABLE_FIELDS: the
#: method is its own row (parcels.ParcelIrrigationMethod). Offered on every
#: deployment, because the row lives in `parcels`, not `surface`: a field
#: watered from a well has an irrigation method too.
IRRIGATION_METHOD = "irrigation_method"


def _editable_fields():
    """EDITABLE_FIELDS, plus the irrigation method.

    The select's choices are read per call: the table is data, seeded by
    migration, and an agency may edit it.
    """
    fields = dict(EDITABLE_FIELDS)
    fields[IRRIGATION_METHOD] = {
        "label": "Irrigation method",
        "type": "select",
        "choices": [("", "Not set")]
        + [(str(m.pk), str(m)) for m in IrrigationMethod.objects.all()],
    }
    return fields


def _field_value(parcel, field):
    """``(value, display)`` for one editable field.

    ``value`` is what the edit form's input holds; ``display`` is what the
    page shows. They differ only for the irrigation method, whose value is the
    method's pk and whose display is "<name>, <n>%" (blank when not set).
    """
    if field == IRRIGATION_METHOD:
        link = (
            ParcelIrrigationMethod.objects.filter(parcel=parcel)
            .select_related("method")
            .first()
        )
        if link is None:
            return "", ""
        return str(link.method_id), str(link.method)
    value = getattr(parcel, field)
    return value, value


def _save_irrigation_method(parcel, method_pk):
    """Set the use area's method, or clear it when ``method_pk`` is blank."""
    if method_pk:
        ParcelIrrigationMethod.objects.update_or_create(
            parcel=parcel, defaults={"method_id": int(method_pk)}
        )
    else:
        ParcelIrrigationMethod.objects.filter(parcel=parcel).delete()
    parcel.save(update_fields=["updated_at"])


@login_required
def parcels_list(request):
    """Use Areas overview: the list is the page.

    A Bucket-3 finder, the shape every other list on the platform now uses:
    the overview map card (count line + key, following the list) above
    a one-row toolbar above the table, a row opening the use area's own detail
    page. This list replaces the earlier master-detail workspace
    (`workspace.html`), which had a narrow rail and an empty resting pane.

    A `?selected=<pk>` query param (the old workspace's deep-link shape)
    redirects to the use area's own detail page so a bookmarked link still
    lands somewhere real.

    Returns the `_list_results` partial for an HTMX list refresh (search /
    filter / pagination, which target `#results`), and the full page
    otherwise.
    """
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        return redirect_to_selected(request, "parcels:detail", selected_raw)

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = Parcel.objects.order_by("parcel_number")

    if q:
        queryset = queryset.filter(
            Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # The overview map card's counts (see `_map_card_head.html`):
    # `located_count` is what the map can draw AT ALL (unfiltered), which is
    # what decides whether the page builds a map host at all; `result_pks` /
    # `result_located_count` are the CURRENT filter's, which is what the map
    # follows on every swap (OH2O.followResults, rule 19).
    status_label = dict(Parcel.STATUS_CHOICES).get(status, "")
    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "all_count": Parcel.objects.count(),
        "located_count": Parcel.objects.filter(geometry__isnull=False).count(),
        "result_pks": list(queryset.values_list("pk", flat=True)),
        "result_located_count": queryset.filter(geometry__isnull=False).count(),
        "filter_words": f"with status “{status_label}”" if status_label else "",
        "hx_request": bool(request.headers.get("HX-Request")),
        "q": q,
        "status": status,
        "status_choices": Parcel.STATUS_CHOICES,
    }

    return list_response(
        request,
        page_template="parcels/list.html",
        results_template="parcels/partials/_list_results.html",
        context=context,
    )


#: The month table's figure columns, in the order of its `All N months` row.

def _parcel_detail_context(parcel, period_id=None):
    """Build the per-parcel water-balance context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded `?selected=` pane so all three are identical —
    including the period, which is why ``period_id`` is an argument here rather
    than a lookup inside one of the three.

    ``period_id`` is the raw ``?period=`` string, or None.
    """
    zone_memberships = parcel.parcel_zones.select_related("zone").all()
    related_wells = parcel.wellirrigatedparcel_set.select_related("well").all()

    all_periods = list(ReportingPeriod.objects.order_by("-start_date"))
    balance_period = _balance_period(parcel, all_periods, period_id)

    # Only the no-run branch reads the consumptive balance (its recorded supplies).
    consumptive_balance = parcel_consumptive_balance(parcel, balance_period)
    # Months this parcel was engine-run: none means ET was never computed, which the
    # card says in a sentence rather than printing a table of zeros.
    run_periods = parcel_run_periods(parcel, balance_period)
    # The months that link to a calculation receipt are only those
    # with a well and no meter; a field with none shows no link block at all.
    receipt_periods = parcel_receipt_periods(parcel, balance_period)
    # Canal water beyond what the crop could use, on a run stamped
    # to show it as its own named line rather than a credit.
    over_delivery_shown_af = parcel_over_delivery_shown(parcel, balance_period)

    has_well = is_enabled("wells") and related_wells.exists()
    water_use = None
    if run_periods and balance_period is not None:
        water_use = parcel_water_use_months(parcel, balance_period, with_groundwater=has_well)
    water_use_lines = _water_use_lines(parcel, balance_period, water_use, has_well)

    recent_ledger = _recent_ledger(parcel, balance_period)
    geojson = _parcel_geojson(parcel)
    editable_fields = _editable_fields()
    editable_fields_with_values = _editable_fields_with_values(parcel, editable_fields)

    context = {
        "parcel": parcel,
        "zone_memberships": zone_memberships,
        "related_wells": related_wells,
        "recent_ledger": recent_ledger,
        "balance_period": balance_period,
        # Every period, newest first — the options of the pane's period control.
        "all_periods": all_periods,
        "consumptive_balance": consumptive_balance,
        "water_use": water_use,
        "water_use_lines": water_use_lines,
        "serving_points": _serving_points(parcel),
        "receipt_periods": receipt_periods,
        "over_delivery_shown_af": over_delivery_shown_af,
        "editable_fields": editable_fields,
        "editable_fields_with_values": editable_fields_with_values,
        "fallow": fallow_row_context(parcel),
        # Pass the Python object (or None); the template escapes it via
        # json_script so operator free-text can't break out of <script>.
        "geojson": geojson,
    }
    return context


_NUMBER_WORDS = (
    "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "eleven", "twelve",
)


def _in_words(n):
    """``n`` as a word from one to twelve, as digits above that."""
    return _NUMBER_WORDS[n - 1] if 1 <= n <= len(_NUMBER_WORDS) else str(n)


def _acre_feet(value):
    """``value`` to two places, half up, with thousands separators."""
    return f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _serving_points(parcel):
    """The points of diversion that serve ``parcel``, by name, as ``(pk, label)``; none where surface is off."""
    if not is_enabled("surface"):
        return []
    from surface.models import PointOfDiversionParcel

    links = PointOfDiversionParcel.objects.filter(parcel=parcel).select_related(
        "point_of_diversion"
    ).order_by("point_of_diversion__name", "point_of_diversion__pk")
    return [
        (link.point_of_diversion.pk, map_label(link.point_of_diversion.name)) for link in links
    ]


def _unmet_sentence(parcel, balance_period, unmet_months):
    """The line saying how much of the period's crop ET no supply on record met, or "".

    ``unmet_months`` are the first days of the months whose run recorded unmet demand above 0.
    """
    total = parcel_unmet_demand(parcel, balance_period)
    if total <= 0 or not unmet_months:
        return ""
    ending = "OpenH2O records the difference as water use recorded, no supply reported."
    if len(unmet_months) == 1:
        return (
            f"Crop ET exceeded the supplies on record in {unmet_months[0]:%B %Y} "
            f"by {_acre_feet(total)} AF. {ending}"
        )
    return (
        f"Crop ET exceeded the supplies on record in {_in_words(len(unmet_months))} months, "
        f"{_acre_feet(total)} AF in all. {ending}"
    )


def _points_that_divided(parcel, fallow_months):
    """The labels of the points of diversion whose water was divided among other fields in ``fallow_months``."""
    from surface.models import PointOfDiversionParcel
    from surface.services import fallow_fields_left_out

    links = PointOfDiversionParcel.objects.filter(parcel=parcel).select_related(
        "point_of_diversion"
    ).order_by("point_of_diversion__name", "point_of_diversion__pk")
    labels = []
    for link in links:
        left_out = fallow_fields_left_out(link.point_of_diversion, fallow_months)
        if any(parcel in fields for fields in left_out.values()):
            labels.append(map_label(link.point_of_diversion.name))
    return labels


def _fallow_sentence(parcel, fallow_months):
    """The line saying what OpenH2O did in the period's fallow months, or "".

    Names each point of diversion whose water was divided among the other use areas
    in those months (any month, whether or not the months are next to each other).
    """
    if not fallow_months:
        return ""
    noun = "fallow month" if len(fallow_months) == 1 else "fallow months"
    sentence = f"In the {noun} OpenH2O counted crop ET as 0"
    if is_enabled("surface"):
        from surface.services import fallow_months_without_share

        if fallow_months_without_share(parcel, fallow_months):
            labels = _points_that_divided(parcel, fallow_months)
            if len(labels) == 1:
                return (
                    f"{sentence} and divided {labels[0]}'s water among the other use areas on it."
                )
            if labels:
                possessive = [f"{label}'s" for label in labels]
                named = ", ".join(possessive[:-1]) + f" and {possessive[-1]}"
                return f"{sentence} and divided {named} water among the other use areas on them."
    return f"{sentence}."


def _estimate_sentence(water_use, has_well):
    """The line saying the groundwater extraction includes OpenH2O's estimate, or ""."""
    if not has_well or not water_use["gw_is_estimated"]:
        return ""
    if water_use["gw_is_metered"]:
        return (
            "OpenH2O estimated the groundwater extraction in the months with no meter "
            "reading on record."
        )
    return (
        "OpenH2O estimated the groundwater extraction, because no meter readings are on "
        "record for the water year."
    )


def _efficiency_sentence(parcel, water_use):
    """The foot's sentence on the efficiency delivered water counts at, or "" where none was delivered."""
    efficiencies = water_use["efficiencies"]
    if not is_enabled("surface") or not efficiencies:
        return ""
    if len(efficiencies) > 1:
        return "Surface water counts toward crop ET at each month's irrigation efficiency."
    (efficiency,) = efficiencies
    if efficiency is None:
        return ""
    percent = format((efficiency * 100).normalize(), "f")
    if ParcelIrrigationMethod.objects.filter(parcel=parcel).exists():
        return f"Surface water counts toward crop ET at this use area's {percent}% irrigation efficiency."
    return (
        f"Surface water counts toward crop ET at the {percent}% irrigation efficiency "
        "on Delivery Settings."
    )


def _water_use_lines(parcel, balance_period, water_use, has_well):
    """The sentences the Water use card prints under its figures and in its foot; empty without a run."""
    lines = {"unmet": "", "fallow": "", "estimate": "", "efficiency": ""}
    if water_use is None:
        return lines
    lines["unmet"] = _unmet_sentence(parcel, balance_period, water_use["unmet_months"])
    lines["fallow"] = _fallow_sentence(
        parcel, [m["month"] for m in water_use["months"] if m["fallow"]]
    )
    lines["estimate"] = _estimate_sentence(water_use, has_well)
    lines["efficiency"] = _efficiency_sentence(parcel, water_use)
    return lines


def _balance_period(
    parcel: Parcel, all_periods: list[ReportingPeriod], period_id: str | None
) -> ReportingPeriod | None:
    """The reporting period the parcel pane opens on, by the four steps below."""
    # Which period the pane opens on. Four steps, in order, and the
    # ORDER matters:
    #
    #   1. An explicit `?period=` the reader chose. An unknown or malformed pk
    #      falls through rather than 404ing — a stale bookmark should show the
    #      pane, not an error page.
    #   2. The most recent period this parcel has a CalculationRun for. A run
    #      with demand and no supply is exactly the state this pane should show:
    #      the six curtailed Merced fields have their finding in the dry year,
    #      and step 3 could not see it because the dry year carries no delivery
    #      row of their own.
    #   3. The old default: the most recent period with REAL (non-allocation)
    #      ledger activity. Still right for a surface-only field the engine has
    #      never run.
    #   4. The most recent period overall.
    #
    # ⛔ Step 2 is NOT "the most recent period". Flipping the default outright
    # would hide the wet year with no way back;
    # the control below is the way back, and step 1 is what it drives.
    by_pk = {period.pk: period for period in all_periods}

    balance_period = None
    if period_id:
        try:
            balance_period = by_pk.get(int(period_id))
        except (TypeError, ValueError):
            balance_period = None

    if balance_period is None:
        # `parcel_run_periods` is THE selector for "which runs belong to this
        # period" (it wraps `runs_in_period`), so asking it per period keeps
        # this in step with the balance read instead of re-deriving month
        # membership here. At most a handful of periods exist.
        for period in all_periods:
            if parcel_run_periods(parcel, period):
                balance_period = period
                break

    if balance_period is None:
        activity_period_id = (
            ParcelLedger.objects.filter(parcel=parcel, reporting_period__isnull=False)
            .exclude(source_type="allocation")
            .order_by("-reporting_period__start_date")
            .values_list("reporting_period_id", flat=True)
            .first()
        )
        if activity_period_id:
            balance_period = by_pk.get(activity_period_id)

    if balance_period is None and all_periods:
        balance_period = all_periods[0]
    return balance_period


def _recent_ledger(parcel: Parcel, balance_period: ReportingPeriod | None) -> Any:
    """The parcel's ten most recent ledger rows in ``balance_period`` (its whole history when None)."""
    # Filtering on the parcel ONLY would let the water balance and the ledger
    # card beside it — two surfaces a hand's width apart on one screen —
    # answer for different years, and neither would say which.
    #
    # It is built HERE, after the four-step period resolution above, because the
    # period is the filter. `balance_period` is None only when no reporting
    # period exists at all, and then there is nothing to bound by and the card
    # falls back to the parcel's whole history — the same rows it would have
    # shown anyway, on a deployment that has not set a period up yet.
    # select_related("water_type"): the merged Water column
    # (ledger_row_words) reads entry.water_type on every row.
    recent_ledger = ParcelLedger.objects.filter(parcel=parcel).select_related(
        "water_type"
    )
    if balance_period is not None:
        recent_ledger = recent_ledger.filter(reporting_period=balance_period)
    recent_ledger = recent_ledger.order_by("-effective_date", "-created_at")[:10]
    return recent_ledger


def _parcel_geojson(parcel: Parcel) -> dict[str, Any] | None:
    """The parcel as a one-feature collection for the detail map, or None without geometry."""
    geojson = None
    if parcel.geometry:
        geojson = json.loads(
            serialize(
                "geojson",
                [parcel],
                geometry_field="geometry",
                fields=["parcel_number", "owner_name"],
            )
        )
    return geojson


def _editable_fields_with_values(
    parcel: Parcel, editable_fields: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each editable field's metadata with the parcel's current value and display text."""
    # Build editable field list with current values for the template
    editable_fields_with_values = []
    for fname, fmeta in editable_fields.items():
        value, display = _field_value(parcel, fname)
        editable_fields_with_values.append({
            "name": fname,
            "label": fmeta["label"],
            "type": fmeta["type"],
            "choices": fmeta.get("choices", []),
            "value": value,
            "display": display,
        })
    return editable_fields_with_values


@login_required
def parcel_detail(request, pk):
    """A single parcel's water-balance detail.

    On an HTMX request it returns just the `_detail_pane` fragment (the
    workspace swaps this into `#detail-pane`); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    parcel = get_object_or_404(Parcel, pk=pk)
    context = _parcel_detail_context(
        parcel, period_id=request.GET.get("period", "").strip()
    )
    if request.headers.get("HX-Request"):
        # The period control swaps this fragment into the standalone page too, which
        # carries its own head, so the fragment leaves out the pane's head there.
        current_path = urlsplit(request.headers.get("HX-Current-URL", "")).path
        context["on_full_page"] = current_path == reverse("parcels:detail", args=[parcel.pk])
        return render(request, "parcels/partials/_detail_pane.html", context)
    return render(request, "parcels/detail.html", context)


@login_required
@require_http_methods(["GET", "PATCH"])
def parcel_edit_field(request, pk):
    """Inline field editor: GET returns form, PATCH saves and returns updated value."""
    parcel = get_object_or_404(Parcel, pk=pk)
    editable_fields = _editable_fields()

    if request.method == "GET":
        field = request.GET.get("field", "")
        if field not in editable_fields:
            return HttpResponseBadRequest("Invalid field.")

        value, display = _field_value(parcel, field)
        context = {
            "parcel": parcel,
            "field": field,
            "field_meta": editable_fields[field],
            "value": value,
            "display": display,
        }
        # Cancel action: return the value display instead of the edit form
        if request.GET.get("cancel"):
            return render(request, "parcels/partials/_field_value.html", context)
        return render(request, "parcels/partials/_field_edit.html", context)

    # PATCH: Django doesn't parse PATCH bodies into request.POST automatically.
    # Parse the URL-encoded body manually.
    body_params = parse_qs(request.body.decode("utf-8"))
    field = body_params.get("field", [""])[0]
    new_value = body_params.get("value", [""])[0].strip()

    if field not in editable_fields:
        return HttpResponseBadRequest("Invalid field.")

    field_meta = editable_fields[field]
    if field_meta["type"] == "select":
        valid_choices = [c[0] for c in field_meta["choices"]]
        if new_value not in valid_choices:
            return HttpResponseBadRequest("Invalid choice.")

    if field == IRRIGATION_METHOD:
        _save_irrigation_method(parcel, new_value)
        value, display = _field_value(parcel, field)
        context = {
            "parcel": parcel,
            "field": field,
            "field_meta": field_meta,
            "value": value,
            "display": display,
        }
        return render(request, "parcels/partials/_field_value.html", context)

    if field_meta["type"] == "number":
        try:
            if field_meta.get("integer"):
                save_value = coerce_int(
                    new_value, field_meta["label"],
                    min_value=field_meta.get("min_value"),
                    max_value=field_meta.get("max_value"),
                )
            else:
                save_value = coerce_decimal(
                    new_value, field_meta["label"],
                    min_value=field_meta.get("min_value"),
                    min_exclusive=field_meta.get("min_exclusive", False),
                )
        except FieldValidationError as exc:
            # Re-render the edit form (HTMX swaps it back into #field-X) with the
            # entered value preserved and a friendly error — never a 500.
            context = {
                "parcel": parcel,
                "field": field,
                "field_meta": field_meta,
                "value": new_value,
                "error": str(exc),
            }
            return render(request, "parcels/partials/_field_edit.html", context)
    else:
        save_value = new_value
    setattr(parcel, field, save_value)
    parcel.save(update_fields=[field, "updated_at"])

    context = {
        "parcel": parcel,
        "field": field,
        "field_meta": field_meta,
        "value": getattr(parcel, field),
    }
    return render(request, "parcels/partials/_field_value.html", context)





def _span_key(period):
    return (period.start_month or dt.date.min, period.end_month or dt.date.max)


def _months_text(period):
    """``(start, end)`` as month names; None for an empty side."""
    start = f"{period.start_month:%B %Y}" if period.start_month else None
    end = f"{period.end_month:%B %Y}" if period.end_month else None
    return start, end


def fallow_row_context(parcel):
    """What the Fallow row shows: the latest period in words, a note, and the earlier ones.

    ``can_end`` is True when a period is still open; the row then offers to
    end it and not to add another (periods of one use area may not overlap).
    """
    periods = sorted(parcel.fallow_periods.all(), key=_span_key)
    if not periods:
        return {"value": "Not fallow", "note": "", "earlier": [], "can_end": False}
    latest = periods[-1]
    start, end = _months_text(latest)
    if start and end and start == end:
        value = f"Fallow in {start}"
        note = f"crop ET is counted as 0 in {start} in this use area's calculation"
    elif start and end:
        value = f"Fallow from {start} to {end}"
        note = f"crop ET is counted as 0 from {start} through {end} in this use area's calculation"
    elif start:
        value = f"Fallow from {start}"
        note = f"crop ET is counted as 0 from {start} in this use area's calculation"
    elif end:
        value = f"Fallow until {end}"
        note = f"crop ET is counted as 0 through {end} in this use area's calculation"
    else:
        value = "Fallow"
        note = "crop ET is counted as 0 in this use area's calculation"
    earlier = []
    for period in reversed(periods[:-1]):
        start, end = _months_text(period)
        if start and end and start == end:
            earlier.append(f"Earlier: {start}")
        elif start and end:
            earlier.append(f"Earlier: {start} to {end}")
        elif end:
            earlier.append(f"Earlier: fallow until {end}")
        else:
            earlier.append(f"Earlier: fallow from {start}")
    return {"value": value, "note": note, "earlier": earlier, "can_end": latest.end_month is None}


def _fallow_response(request, parcel, *, form=None, ending=False, status_line=""):
    """The Fallow row: the form when ``form`` is given, otherwise the row and its notes."""
    context = {
        "parcel": parcel,
        "fallow": fallow_row_context(parcel),
        "fallow_status_line": status_line,
        "form": form,
        "ending": ending,
        "error": form.first_error() if form is not None and form.is_bound else "",
    }
    template = (
        "parcels/partials/_fallow_form.html" if form is not None
        else "parcels/partials/_fallow_row_swap.html"
    )
    return render(request, template, context)


def _open_fallow_period(parcel):
    return parcel.fallow_periods.filter(end_month__isnull=True).first()


def _save_fallow(request, parcel, ending):
    """Check, save and recalculate: the one path behind adding and ending a period."""
    form = FallowPeriodForm(request.POST, parcel=parcel, ending=ending)
    if not form.is_valid():
        return _fallow_response(request, parcel, form=form, ending=ending is not None)
    months = form.months_to_recalculate()
    form.save(user=request.user)
    status_line = ""
    if months:
        from accounting.engine_run import recalculating_months_sentence, request_for_months

        started = request_for_months("ledger_saved", months, requested_by=request.user)
        covered = sorted({m for r in started for m in r.months})
        if covered:
            status_line = recalculating_months_sentence(covered)
    return _fallow_response(request, parcel, status_line=status_line)


@login_required
@require_http_methods(["GET", "POST"])
def fallow_period_add(request, pk):
    """Add a fallow period: GET returns the form (or the row, on cancel), POST saves it."""
    parcel = get_object_or_404(Parcel, pk=pk)
    if request.method == "POST":
        return _save_fallow(request, parcel, ending=None)
    if request.GET.get("cancel"):
        return _fallow_response(request, parcel)
    return _fallow_response(request, parcel, form=FallowPeriodForm(parcel=parcel))


@login_required
@require_http_methods(["GET", "POST"])
def fallow_period_end_edit(request, pk):
    """End the open fallow period: GET returns the end form (or the row, on cancel), POST saves it."""
    parcel = get_object_or_404(Parcel, pk=pk)
    ending = _open_fallow_period(parcel)
    if ending is None or request.GET.get("cancel"):
        return _fallow_response(request, parcel)
    if request.method == "POST":
        return _save_fallow(request, parcel, ending=ending)
    return _fallow_response(
        request, parcel, form=FallowPeriodForm(parcel=parcel, ending=ending), ending=True
    )


@public_in_open_demo
def parcels_geojson(request):
    """Return the located parcels as a GeoJSON FeatureCollection.

    With no parameter: every parcel that has a geometry (the overview map's one
    unfiltered source, filtered client-side by ``OH2O.followResults``).

    ``?account=<id>``: only the parcels that water account
    holds now, through its active ``accounting.WaterAccountParcel`` rows
    (``removed_date`` empty, the same rows the account page counts), in ONE
    query. An integer that names no account, or an account with no located
    parcel, gives the empty FeatureCollection with 200, the house answer on
    the map endpoints for "nothing matches". A value that is not an integer
    gives 400 with a one-line body: it is a malformed request, not an empty
    result. With the ``accounting`` module off the parameter is ignored and the
    response is the unfiltered one.
    """
    parcels = Parcel.objects.filter(geometry__isnull=False)
    account_param = request.GET.get("account")
    if account_param is not None and is_enabled("accounting"):
        try:
            account_id = int(account_param)
        except ValueError:
            return HttpResponseBadRequest("The account parameter must be an integer id.")
        # Function scope and guarded: `accounting` is schema-resident, so with it
        # off this module must not reach into it (CLAUDE.md, the composition rule).
        from accounting.models import WaterAccountParcel

        parcels = parcels.filter(
            pk__in=WaterAccountParcel.objects.filter(
                water_account_id=account_id, removed_date__isnull=True
            ).values("parcel_id")
        )
    raw = serialize(
        "geojson",
        parcels,
        geometry_field="geometry",
        fields=["parcel_number", "owner_name", "area_acres", "status"],
    )
    data = json.loads(raw)
    for f in data["features"]:
        f["properties"]["pk"] = f.get("id")
    return HttpResponse(json.dumps(data), content_type="application/json")
