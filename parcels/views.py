# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcels views.

The parcel list and detail surfaces. The detail page is the per-parcel
water-balance view: it reconciles the parcel's estimated consumptive use (ET)
against its supplies for a reporting period (consumptive balance + mass
balance), lists the recent ledger rows, shows zone memberships and the wells
that irrigate it, and inline-edits the parcel's editable fields.
"""
import json
from urllib.parse import parse_qs

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods
from core.access import public_in_open_demo

from accounting.models import ReportingPeriod
from accounting.services import (
    parcel_consumptive_balance,
    parcel_mass_balance,
    parcel_run_periods,
    parcel_unmet_demand,
)
from core.validation import FieldValidationError, coerce_decimal, coerce_int
from parcels.models import Parcel, ParcelLedger


EDITABLE_FIELDS = {
    "owner_name": {"label": "Owner Name", "type": "text", "max_length": 200},
    "area_acres": {
        "label": "Area (Acres)", "type": "number", "step": "0.01",
        "min_value": 0, "min_exclusive": True,
    },
    "status": {"label": "Status", "type": "select", "choices": Parcel.STATUS_CHOICES},
    "address": {"label": "Address", "type": "textarea"},
    "notes": {"label": "Notes", "type": "textarea"},
}


@login_required
def parcels_list(request):
    """Master-detail workspace for use areas.

    Left pane: the HTMX-searchable parcel list. Right pane: the selected
    parcel's detail, swapped in place when a row is clicked. A `?selected=<pk>`
    query param pre-renders that parcel server-side so a reload or a deep link
    lands on the same workspace view (the row click pushes that URL).

    Returns the `_list_results` partial for an HTMX list refresh (search /
    filter / pagination, which target `#results`), and the full workspace page
    otherwise.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = Parcel.objects.prefetch_related("parcel_zones__zone").order_by(
        "parcel_number"
    )

    if q:
        queryset = queryset.filter(
            Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Pre-load the selected parcel (deep link / reload) into the detail pane.
    selected_parcel = None
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        selected_parcel = Parcel.objects.filter(pk=selected_raw).first()

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": Parcel.STATUS_CHOICES,
        "selected_parcel": selected_parcel,
    }
    if selected_parcel is not None:
        context.update(
            _parcel_detail_context(
                selected_parcel, period_id=request.GET.get("period", "").strip()
            )
        )

    if request.headers.get("HX-Request"):
        return render(request, "parcels/partials/_list_results.html", context)

    return render(request, "parcels/list.html", context)


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

    # Which period the pane opens on (ISS-147). Four steps, in order, and the
    # ORDER is the whole fix:
    #
    #   1. An explicit `?period=` the reader chose. An unknown or malformed pk
    #      falls through rather than 404ing — a stale bookmark should show the
    #      pane, not an error page.
    #   2. The most recent period this parcel has a CalculationRun for. A run
    #      with demand and no supply is exactly the state ISS-147 wants shown:
    #      the six curtailed Merced fields have their finding in the dry year,
    #      and step 3 could not see it because the dry year carries no delivery
    #      row of their own.
    #   3. The old default: the most recent period with REAL (non-allocation)
    #      ledger activity. Still right for a surface-only field the engine has
    #      never run, which is the ISS-054 case.
    #   4. The most recent period overall.
    #
    # ⛔ Step 2 is NOT "the most recent period". Flipping the default outright
    # would hide the wet year with no way back, which is ISS-147's own warning;
    # the control below is the way back, and step 1 is what it drives.
    all_periods = list(ReportingPeriod.objects.order_by("-start_date"))
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

    # The corrected v1.10 lens (57-01) + the closing identity (52.6-03), both
    # read from the same source fields so the card is internally consistent.
    consumptive_balance = parcel_consumptive_balance(parcel, balance_period)
    mass_balance = parcel_mass_balance(parcel, balance_period)
    # Months this parcel was engine-run — each links to its own audit waterfall
    # (Task 2). Empty when ET was never computed (surface-only ISS-054 case),
    # which the template renders as an honest "ET not yet computed" state rather
    # than a scary red residual.
    run_periods = parcel_run_periods(parcel, balance_period)
    # ISS-157: what the platform already stored and no screen had ever shown.
    unmet_demand_af = parcel_unmet_demand(parcel, balance_period)

    # ISS-165 / R-107. This queryset used to run above, before `balance_period`
    # was resolved, and filtered on the parcel ONLY. So the water balance and the
    # ledger card beside it — two surfaces a hand's width apart on one screen —
    # answered for different years, and neither said which: measured 2026-09-08,
    # the balance stood at WY 2025-2026 while nine of the card's ten rows were
    # dated October 2024 to June 2025.
    #
    # It is built HERE, after the four-step period resolution above, because the
    # period is the filter. `balance_period` is None only when no reporting
    # period exists at all, and then there is nothing to bound by and the card
    # falls back to the parcel's whole history — the same rows it would have
    # shown anyway, on a deployment that has not set a period up yet.
    # select_related("water_type"): 143-05's merged Water column
    # (ledger_row_words) reads entry.water_type on every row, which this
    # query did not join before that column existed.
    recent_ledger = ParcelLedger.objects.filter(parcel=parcel).select_related(
        "water_type"
    )
    if balance_period is not None:
        recent_ledger = recent_ledger.filter(reporting_period=balance_period)
    recent_ledger = recent_ledger.order_by("-effective_date", "-created_at")[:10]

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

    # Build editable field list with current values for the template
    editable_fields_with_values = [
        {
            "name": fname,
            "label": fmeta["label"],
            "type": fmeta["type"],
            "choices": fmeta.get("choices", []),
            "value": getattr(parcel, fname),
        }
        for fname, fmeta in EDITABLE_FIELDS.items()
    ]

    context = {
        "parcel": parcel,
        "zone_memberships": zone_memberships,
        "related_wells": related_wells,
        "recent_ledger": recent_ledger,
        "balance_period": balance_period,
        # Every period, newest first — the options of the pane's period control.
        "all_periods": all_periods,
        "consumptive_balance": consumptive_balance,
        "mass_balance": mass_balance,
        "run_periods": run_periods,
        "unmet_demand_af": unmet_demand_af,
        "editable_fields": EDITABLE_FIELDS,
        "editable_fields_with_values": editable_fields_with_values,
        # Pass the Python object (or None); the template escapes it via
        # json_script so operator free-text can't break out of <script>.
        "geojson": geojson,
    }
    return context


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
        return render(request, "parcels/partials/_detail_pane.html", context)
    return render(request, "parcels/detail.html", context)


@login_required
@require_http_methods(["GET", "PATCH"])
def parcel_edit_field(request, pk):
    """Inline field editor: GET returns form, PATCH saves and returns updated value."""
    parcel = get_object_or_404(Parcel, pk=pk)

    if request.method == "GET":
        field = request.GET.get("field", "")
        if field not in EDITABLE_FIELDS:
            return HttpResponseBadRequest("Invalid field.")

        context = {
            "parcel": parcel,
            "field": field,
            "field_meta": EDITABLE_FIELDS[field],
            "value": getattr(parcel, field),
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

    if field not in EDITABLE_FIELDS:
        return HttpResponseBadRequest("Invalid field.")

    field_meta = EDITABLE_FIELDS[field]
    if field_meta["type"] == "select":
        valid_choices = [c[0] for c in field_meta["choices"]]
        if new_value not in valid_choices:
            return HttpResponseBadRequest("Invalid choice.")

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
        "field_meta": EDITABLE_FIELDS[field],
        "value": getattr(parcel, field),
    }
    return render(request, "parcels/partials/_field_value.html", context)





@public_in_open_demo
def parcels_geojson(request):
    """Return all parcels as a GeoJSON FeatureCollection."""
    raw = serialize(
        "geojson",
        Parcel.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["parcel_number", "owner_name", "area_acres", "status"],
    )
    data = json.loads(raw)
    for f in data["features"]:
        f["properties"]["pk"] = f.get("id")
    return HttpResponse(json.dumps(data), content_type="application/json")
