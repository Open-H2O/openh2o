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
from core.access import public_in_open_demo

from core.validation import FieldValidationError, coerce_decimal, coerce_int
from core.workspace import detail_response, list_response, redirect_to_selected
from wells import measurement_history
from wells.models import (
    ACCURACY_BAND_CHOICES,
    DWR_DIRECT_OR_ESTIMATE_CHOICES,
    DWR_EXTRACTION_METHOD_CHOICES,
    MEASUREMENT_METHOD_CHOICES,
    PUMP_TYPE_CHOICES,
    Well,
    WellIrrigatedParcel,
    WellType,
)


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
    # 146-05 S2: DWR's own annual-report row (23 CCR 356.2(b)(2)), derived
    # once from measurement_method above and editable independently after
    # that. Each carries a blank option so the row can be cleared, unlike
    # measurement_method's editor, which was never given one.
    "dwr_extraction_method": {
        "label": "Extraction Method (DWR)", "type": "select",
        "choices": [("", "Not stated")] + DWR_EXTRACTION_METHOD_CHOICES,
    },
    "dwr_direct_or_estimate": {
        "label": "Direct or Estimate", "type": "select",
        "choices": [("", "Not stated")] + DWR_DIRECT_OR_ESTIMATE_CHOICES,
    },
    "accuracy_band": {
        "label": "Accuracy Band", "type": "select",
        "choices": [("", "Not stated")] + ACCURACY_BAND_CHOICES,
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


def _editable_fields():
    """EDITABLE_FIELDS, plus `well_type` (ISS-189: "Well type" printed with
    no editor, because `well_type` was not in EDITABLE_FIELDS).

    Its choices are read per call, the same reason `parcels._editable_fields`
    reads `IrrigationMethod` per call: `WellType` is seeded reference data an
    agency can add rows to. Marked `fk` so the PATCH handler assigns the id
    rather than treating the submitted string as the field's own value.
    """
    fields = dict(EDITABLE_FIELDS)
    fields["well_type"] = {
        "label": "Well Type", "type": "select", "fk": True,
        "choices": [("", "Not set")]
        + [(str(wt.pk), wt.name) for wt in WellType.objects.order_by("name")],
    }
    return fields


def _field_value(well, field):
    """The raw value an editable field's template comparisons need.

    Every field but `well_type` is a plain attribute. `well_type` is a
    ForeignKey, and the select's option-matching (`_editable_field.html`,
    `_field_edit.html`) compares against a stringified id, not the WellType
    instance itself.
    """
    if field == "well_type":
        return well.well_type_id
    return getattr(well, field)


def _dwr_extraction_line(well):
    """"Extraction: <method>, <direct/estimate>, ±<band>" -- DWR's three-part
    identity for how a well's pumping is known (23 CCR 356.2(b)(2)).

    Each part reads "not stated" on its own when blank, so a well missing one
    part is never read as though the whole line were unset.
    """
    method = dict(DWR_EXTRACTION_METHOD_CHOICES).get(well.dwr_extraction_method)
    direct_or_estimate = dict(DWR_DIRECT_OR_ESTIMATE_CHOICES).get(well.dwr_direct_or_estimate)
    if well.accuracy_band:
        band = f"±{well.accuracy_band.replace('_', ' ')}%"
    else:
        band = "not stated"
    return ", ".join([
        method if method else "not stated",
        direct_or_estimate.lower() if direct_or_estimate else "not stated",
        band,
    ])


@login_required
def wells_list(request):
    """Wells overview (143-13, candidate A: the list is the page).

    A Bucket-3 finder, the shape every other list on the platform now uses:
    the 143-07 overview map card (count line + key, following the list) above
    a one-row toolbar above the table, a row opening the well's own detail
    page. Replaces the earlier master-detail workspace (`workspace.html`),
    whose narrow rail and empty resting pane were the worst-named fault on
    this page since 143-02 (the "workspace FRAME" ruling, R-105 / R-106).

    A `?selected=<pk>` query param (the old workspace's deep-link shape)
    redirects to the well's own detail page so a bookmarked link still lands
    somewhere real.

    Returns the ``_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page
    otherwise.
    """
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        return redirect_to_selected(request, "wells:detail", selected_raw)

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = Well.objects.order_by("name")

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q)
            | Q(well_registration_id__icontains=q)
            | Q(owner_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # The overview map card's counts (143-07 shape, `_map_card_head.html`):
    # `located_count` is what the map can draw AT ALL (unfiltered), which is
    # what decides whether the page builds a map host at all; `result_pks` /
    # `result_located_count` are the CURRENT filter's, which is what the map
    # follows on every swap (OH2O.followResults, rule 19).
    status_label = dict(Well.STATUS_CHOICES).get(status, "")
    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "all_count": Well.objects.count(),
        "located_count": Well.objects.filter(location__isnull=False).count(),
        "result_pks": list(queryset.values_list("pk", flat=True)),
        "result_located_count": queryset.filter(location__isnull=False).count(),
        "filter_words": f"with status “{status_label}”" if status_label else "",
        "hx_request": bool(request.headers.get("HX-Request")),
        "q": q,
        "status": status,
        "status_choices": Well.STATUS_CHOICES,
    }

    return list_response(
        request,
        page_template="wells/list.html",
        results_template="wells/partials/_list_results.html",
        context=context,
    )


def published_source_publisher(well):
    """The publisher of this well's identity, or ``None`` if nobody published it.

    A well that a drinking-water system lists as one of its facilities is a
    MUNICIPAL SUPPLY SOURCE with a published record behind it: in the Merced
    demonstration those 21 rows carry the state's own name for the source (from
    the DDW lab file), the system's name from EPA Envirofacts, and a real GAMA
    coordinate. Nothing about them is invented, and until Phase 101 every one of
    them wore an unconditional "sample data" pill on its Identification header —
    the inverse of the truth, live on the public demo.

    **The signal is the foreign key, never the ``MER-PWS-`` prefix.** That prefix
    is a demonstration seed constant
    (``drinking/management/commands/seed_merced_drinking.py``); hardcoding it here
    would make a real agency's behaviour depend on our demo's naming. The FK is
    the general fact.

    **Guarded on the module, because ``drinking`` is truly optional** — not
    schema-resident. Dropped, its app leaves ``INSTALLED_APPS`` entirely, so
    ``well.drinking_facilities`` is not merely empty, it does not exist. Phase 88
    softened ``drinking.requires`` to ``("standards",)``, so wells-without-drinking
    is a real deployment and it must render exactly as it did before this
    function existed.

    One ``EXISTS`` query per rendered pane, and the pane renders one well at a
    time (``well_detail`` and the workspace's pre-loaded ``?selected=``), so
    there is no N+1 here to prefetch away.
    """
    from core.modules import is_enabled

    if not is_enabled("drinking"):
        return None
    if not well.drinking_facilities.exists():
        return None

    from drinking.provenance import PUBLISHED_SUPPLY_SOURCE

    return PUBLISHED_SUPPLY_SOURCE


def _well_detail_context(well):
    """Build the per-well detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    current_meters = well.wellmeter_set.filter(is_current=True).select_related("meter")
    # 146-02 D3: the raw fraction (four decimals, "share 1.0000") is now shown
    # and edited directly -- see _irrigated_parcel_share_value.html -- rather
    # than a rounded whole percent computed here.
    irrigated_parcels = list(well.wellirrigatedparcel_set.select_related("parcel").all())
    monitoring = getattr(well, "monitoringwell", None)
    # ISS-145 (137-03). The page's own description promises "measurement
    # history"; these two are it. Both are built in wells/measurement_history.py,
    # grouped by water year and newest first, never assembled in the template.
    meter_history = measurement_history.meter_history(well)
    water_levels = measurement_history.water_level_history(well)

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
            "value": _field_value(well, fname),
        }
        for fname, fmeta in _editable_fields().items()
    }

    return {
        "well": well,
        "current_meters": current_meters,
        "irrigated_parcels": irrigated_parcels,
        "monitoring": monitoring,
        "meter_history": meter_history,
        "water_levels": water_levels,
        "ef": editable_fields_map,
        # 146-05 S2: DWR's three-part identity line, computed once here so
        # the template states it rather than re-deriving it (rule 12).
        "dwr_extraction_line": _dwr_extraction_line(well),
        # Pass the Python object (or None); the template escapes it via
        # json_script so a malicious place-name can't break out of <script>.
        "geojson": geojson,
        # Both None for an ordinary well, which is what keeps the pre-Phase-101
        # rendering byte-identical there. Resolved in Python rather than in the
        # template because a `wells` template must not `{% load drinking_display %}`
        # — loading a dropped app's tag library is a TemplateSyntaxError, not a
        # missing label. The second one rides on the first: the composed
        # registration ID only needs a label where the section above it has just
        # claimed a publisher.
        **_identity_provenance(well),
    }


def _identity_provenance(well):
    """The two provenance strings the Identification section needs, or two Nones."""
    published = published_source_publisher(well)
    if published is None:
        return {"published_source": None, "local_registry_source": None}

    from drinking.provenance import LOCAL_REGISTRY

    return {"published_source": published, "local_registry_source": LOCAL_REGISTRY}


@login_required
def well_detail(request, pk):
    """A single well's detail.

    On an HTMX request it returns just the ``_detail_pane`` fragment (the
    workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    well = get_object_or_404(Well.objects.select_related("well_type"), pk=pk)
    context = _well_detail_context(well)
    return detail_response(
        request,
        pane_template="wells/partials/_detail_pane.html",
        page_template="wells/detail.html",
        context=context,
    )


@login_required
@require_http_methods(["GET", "PATCH"])
def well_edit_field(request, pk):
    """Inline field editor: GET returns form, PATCH saves and returns updated value."""
    well = get_object_or_404(Well, pk=pk)
    editable_fields = _editable_fields()

    if request.method == "GET":
        field = request.GET.get("field", "")
        if field not in editable_fields:
            return HttpResponseBadRequest("Invalid field.")

        context = {
            "well": well,
            "field": field,
            "field_meta": editable_fields[field],
            "value": _field_value(well, field),
        }
        # Cancel action: return the value display
        if request.GET.get("cancel"):
            return render(request, "wells/partials/_field_value.html", context)
        return render(request, "wells/partials/_field_edit.html", context)

    # PATCH: parse URL-encoded body manually
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

    if field_meta.get("fk"):
        # well_type (ISS-189): the submitted value is a WellType id, not the
        # field's own value -- assign the `_id` attribute so Django does not
        # try to interpret a raw string as a model instance.
        setattr(well, f"{field}_id", int(save_value) if save_value else None)
        update_field_name = f"{field}_id"
    else:
        setattr(well, field, save_value)
        update_field_name = field
    well.save(update_fields=[update_field_name, "updated_at"])

    context = {
        "well": well,
        "field": field,
        "field_meta": field_meta,
        "value": _field_value(well, field),
    }
    return render(request, "wells/partials/_field_value.html", context)


@login_required
@require_http_methods(["GET", "PATCH"])
def well_irrigated_parcel_edit_share(request, pk, wip_pk):
    """Inline fraction editor for a well's linked use area (146-02 D3).

    Same GET/PATCH pattern as well_edit_field above, scoped to one
    WellIrrigatedParcel row rather than a field on the well itself.
    0 < fraction <= 1, four decimals -- the surface app's identical
    pod_parcel_edit_share (surface/views.py) is the other half of this door.
    """
    well = get_object_or_404(Well, pk=pk)
    wip = get_object_or_404(WellIrrigatedParcel, pk=wip_pk, well=well)

    if request.method == "GET":
        context = {"well": well, "wip": wip}
        if request.GET.get("cancel"):
            return render(request, "wells/partials/_irrigated_parcel_share_value.html", context)
        return render(request, "wells/partials/_irrigated_parcel_share_edit.html", context)

    body_params = parse_qs(request.body.decode("utf-8"))
    raw_value = body_params.get("value", [""])[0].strip()
    try:
        fraction = coerce_decimal(
            raw_value, "Share", min_value=0, min_exclusive=True, allow_blank=False
        )
    except FieldValidationError as exc:
        return render(request, "wells/partials/_irrigated_parcel_share_edit.html", {
            "well": well, "wip": wip, "value": raw_value, "error": str(exc),
        })
    if fraction > 1:
        return render(request, "wells/partials/_irrigated_parcel_share_edit.html", {
            "well": well, "wip": wip, "value": raw_value,
            "error": "Share must be greater than 0 and no more than 1.",
        })

    wip.fraction = fraction
    wip.save(update_fields=["fraction"])
    return render(request, "wells/partials/_irrigated_parcel_share_value.html", {"well": well, "wip": wip})


@public_in_open_demo
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
