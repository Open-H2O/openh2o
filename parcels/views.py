# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcels views.

The parcel list and detail surfaces. The detail page is the per-parcel
water-balance view: it reconciles the parcel's measured consumptive use (ET)
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

from accounting.models import ReportingPeriod
from accounting.services import (
    parcel_consumptive_balance,
    parcel_mass_balance,
    parcel_run_periods,
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
    """List view with HTMX search and status filter."""
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

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": Parcel.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "parcels/partials/_list_results.html", context)

    return render(request, "parcels/list.html", context)


@login_required
def parcel_detail(request, pk):
    """Detail view for a single parcel."""
    parcel = get_object_or_404(Parcel, pk=pk)
    zone_memberships = parcel.parcel_zones.select_related("zone").all()
    related_wells = parcel.wellirrigatedparcel_set.select_related("well").all()
    recent_ledger = ParcelLedger.objects.filter(parcel=parcel).order_by(
        "-effective_date", "-created_at"
    )[:10]

    # Resolve the period the same way the account page does: the most recent
    # period carrying REAL (non-allocation) activity for THIS parcel, so the
    # balance card opens where the data is and never on an empty open year.
    # Fall back to the most recent period overall when the parcel has no
    # billable rows yet. Mirrors accounting.views.account_detail's default.
    balance_period = None
    activity_period_id = (
        ParcelLedger.objects.filter(parcel=parcel, reporting_period__isnull=False)
        .exclude(source_type="allocation")
        .order_by("-reporting_period__start_date")
        .values_list("reporting_period_id", flat=True)
        .first()
    )
    if activity_period_id:
        balance_period = ReportingPeriod.objects.filter(pk=activity_period_id).first()
    else:
        balance_period = ReportingPeriod.objects.order_by("-start_date").first()

    # The corrected v1.10 lens (57-01) + the closing identity (52.6-03), both
    # read from the same source fields so the card is internally consistent.
    consumptive_balance = parcel_consumptive_balance(parcel, balance_period)
    mass_balance = parcel_mass_balance(parcel, balance_period)
    # Months this parcel was engine-run — each links to its own audit waterfall
    # (Task 2). Empty when ET was never computed (surface-only ISS-054 case),
    # which the template renders as an honest "ET not yet computed" state rather
    # than a scary red residual.
    run_periods = parcel_run_periods(parcel, balance_period)

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
        "consumptive_balance": consumptive_balance,
        "mass_balance": mass_balance,
        "run_periods": run_periods,
        "editable_fields": EDITABLE_FIELDS,
        "editable_fields_with_values": editable_fields_with_values,
        # Pass the Python object (or None); the template escapes it via
        # json_script so operator free-text can't break out of <script>.
        "geojson": geojson,
    }
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





@login_required
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
