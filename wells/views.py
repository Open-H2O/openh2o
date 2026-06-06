# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Wells views.

The well list and detail surfaces. The list offers HTMX search and status
filtering across the agency's extraction wells; the detail page presents a
single well's construction, registry identity, and measurement method, with
inline editing of its editable fields.
"""
import json
from urllib.parse import parse_qs

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.validation import FieldValidationError, coerce_decimal, coerce_int
from wells.models import MEASUREMENT_METHOD_CHOICES, PUMP_TYPE_CHOICES, Well


EDITABLE_FIELDS = {
    "name": {"label": "Name", "type": "text", "max_length": 200},
    "owner_name": {"label": "Owner Name", "type": "text", "max_length": 200},
    "wcr_number": {"label": "WCR Number", "type": "text", "max_length": 50},
    "state_well_number": {"label": "State Well Number", "type": "text", "max_length": 50},
    "status": {"label": "Status", "type": "select", "choices": Well.STATUS_CHOICES},
    "capacity_gpm": {"label": "Capacity (gpm)", "type": "number", "step": "0.01", "min_value": 0},
    "year_pumping_began": {
        "label": "Year Pumping Began", "type": "number", "step": "1", "integer": True,
        "min_value": 1850, "max_is_current_year": True,
    },
    "measurement_method": {
        "label": "Measurement Method", "type": "select",
        "choices": MEASUREMENT_METHOD_CHOICES,
    },
    "depth_ft": {"label": "Depth (ft)", "type": "number", "step": "0.01", "min_value": 0},
    "casing_diameter_in": {"label": "Casing Diameter (in)", "type": "number", "step": "0.01", "min_value": 0},
    "casing_material": {"label": "Casing Material", "type": "text", "max_length": 50},
    "screen_top_ft": {"label": "Screen Top (ft)", "type": "number", "step": "0.01", "min_value": 0},
    "screen_bottom_ft": {"label": "Screen Bottom (ft)", "type": "number", "step": "0.01", "min_value": 0},
    "tested_yield_gpm": {"label": "Tested Yield (gpm)", "type": "number", "step": "0.01", "min_value": 0},
    "pump_type": {"label": "Pump Type", "type": "select", "choices": PUMP_TYPE_CHOICES},
    "notes": {"label": "Notes", "type": "textarea"},
}


@login_required
def wells_list(request):
    """List view with HTMX search and status filter."""
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = Well.objects.select_related("well_type").order_by("name")

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(well_registration_id__icontains=q)
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
        "status_choices": Well.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "wells/partials/_list_results.html", context)

    return render(request, "wells/list.html", context)


@login_required
def well_detail(request, pk):
    """Detail view for a single well."""
    well = get_object_or_404(Well.objects.select_related("well_type"), pk=pk)
    current_meters = well.wellmeter_set.filter(is_current=True).select_related("meter")
    irrigated_parcels = well.wellirrigatedparcel_set.select_related("parcel").all()
    monitoring = getattr(well, "monitoringwell", None)

    geojson = None
    if well.location:
        geojson = json.loads(
            serialize(
                "geojson",
                [well],
                geometry_field="location",
                fields=["name", "well_registration_id"],
            )
        )

    # Build editable fields keyed by name so the template can place each one
    # under the right section heading (Identification / State Reporting / Construction).
    editable_fields_map = {
        fname: {
            "name": fname,
            "label": fmeta["label"],
            "type": fmeta["type"],
            "choices": fmeta.get("choices", []),
            "integer": fmeta.get("integer", False),
            "value": getattr(well, fname),
        }
        for fname, fmeta in EDITABLE_FIELDS.items()
    }

    context = {
        "well": well,
        "current_meters": current_meters,
        "irrigated_parcels": irrigated_parcels,
        "monitoring": monitoring,
        "ef": editable_fields_map,
        # Pass the Python object (or None); the template escapes it via
        # json_script so a malicious place-name can't break out of <script>.
        "geojson": geojson,
    }
    return render(request, "wells/detail.html", context)


@login_required
@require_http_methods(["GET", "PATCH"])
def well_edit_field(request, pk):
    """Inline field editor: GET returns form, PATCH saves and returns updated value."""
    well = get_object_or_404(Well, pk=pk)

    if request.method == "GET":
        field = request.GET.get("field", "")
        if field not in EDITABLE_FIELDS:
            return HttpResponseBadRequest("Invalid field.")

        context = {
            "well": well,
            "field": field,
            "field_meta": EDITABLE_FIELDS[field],
            "value": getattr(well, field),
        }
        # Cancel action: return the value display
        if request.GET.get("cancel"):
            return render(request, "wells/partials/_field_value.html", context)
        return render(request, "wells/partials/_field_edit.html", context)

    # PATCH: parse URL-encoded body manually
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
                max_value = field_meta.get("max_value")
                if field_meta.get("max_is_current_year"):
                    max_value = timezone.now().year
                save_value = coerce_int(
                    new_value, field_meta["label"],
                    min_value=field_meta.get("min_value"),
                    max_value=max_value,
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
                "well": well,
                "field": field,
                "field_meta": field_meta,
                "value": new_value,
                "error": str(exc),
            }
            return render(request, "wells/partials/_field_edit.html", context)
    else:
        save_value = new_value
    setattr(well, field, save_value)
    well.save(update_fields=[field, "updated_at"])

    context = {
        "well": well,
        "field": field,
        "field_meta": EDITABLE_FIELDS[field],
        "value": getattr(well, field),
    }
    return render(request, "wells/partials/_field_value.html", context)


@login_required
def wells_geojson(request):
    """Return all wells as a GeoJSON FeatureCollection."""
    raw = serialize(
        "geojson",
        Well.objects.all(),
        geometry_field="location",
        fields=["name", "well_registration_id", "status", "depth_ft", "capacity_gpm"],
    )
    data = json.loads(raw)
    for f in data["features"]:
        f["properties"]["pk"] = f.get("id")
    return HttpResponse(json.dumps(data), content_type="application/json")
