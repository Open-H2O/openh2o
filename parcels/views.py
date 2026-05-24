import json
from urllib.parse import parse_qs

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from parcels.models import Parcel, ParcelLedger


EDITABLE_FIELDS = {
    "owner_name": {"label": "Owner Name", "type": "text", "max_length": 200},
    "area_acres": {"label": "Area (Acres)", "type": "number", "step": "0.01"},
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
        "editable_fields": EDITABLE_FIELDS,
        "editable_fields_with_values": editable_fields_with_values,
        "geojson": json.dumps(geojson) if geojson else None,
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
        save_value = None if not new_value else new_value
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
    data = serialize(
        "geojson",
        Parcel.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["parcel_number", "owner_name", "area_acres", "status"],
    )
    return HttpResponse(data, content_type="application/json")
