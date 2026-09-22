# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Surface views.

The surface-water browsing and entry surfaces. pod_list and pod_detail are the
primary entry point for surface diversions — pod_detail renders the one-hop water
journey from a point of diversion through the parcels it serves. water_rights_list
and water_right_detail expose the underlying entitlements, diversion_record_create
records a diversion event, and pods_geojson feeds the diversion map.

146-02 Task 2 (D2, D3) adds the doors between the two: pod_link_right lets a
point of diversion name its right, water_right_assign_parcel /
water_right_remove_parcel / water_right_search_parcels are the right's places
of use (the account page's search-parcels / assign fragment shape,
accounting/views.py, reused as a shape rather than imported), and
pod_parcel_edit_share is the inline fraction editor on a POD's linked use
areas (the wells:edit_field GET/PATCH pattern, wells/views.py).
"""
import json
import logging
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from core.access import public_in_open_demo
from core.map_labels import map_label

from accounting.models import ReportingPeriod
from accounting.services import current_period_id as compute_current_period_id
from core.modules import is_enabled
from core.validation import FieldValidationError, coerce_decimal
from core.workspace import detail_response, list_response
from parcels.models import Parcel
from surface import importer
from surface import diversion_import as diversion_import_service
from surface.curtailments import orders_that_may_apply
from surface.forms import (
    CurtailmentOrderForm,
    DiversionRecordForm,
    MeasuringDeviceForm,
    PointOfDiversionForm,
    WaterRightForm,
)
from surface.models import (
    CurtailmentOrder,
    DiversionRecord,
    MeasuringDevice,
    PointOfDiversion,
    PointOfDiversionDevice,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 143-10: the water-year grouping shared by the diversion page, its add-record
# view, and the water right page. Rule 7 (DESIGN.md): two kinds of row are
# said once, with a divider naming the condition (a reporting period covers
# these rows), never a note repeated on every one. The list handed in MUST
# already be ordered so a reporting period's rows are contiguous (``-month``
# alone for a POD, which carries one diversion_type per record per month;
# ``-month, point_of_diversion__name`` for a right's records, R-122, so ties
# in a month read in POD-name order) -- this function does not re-sort, it
# only partitions what it is given, so it never disagrees with the table it
# groups (ISS-154, 137-02; 143-05: the panel's figures are the SAME queryset
# the table prints, never a second derivation).
# ---------------------------------------------------------------------------
def _group_diversion_records(records):
    """Partition ordered ``DiversionRecord`` rows into water-year groups.

    Each group carries its own ``diverted`` / ``returned`` / ``retained``
    sums and ``count``, computed once in Python from the rows already
    fetched -- never a second query. A record with no reporting period
    (its FK is null) closes into its own "No water year assigned" group
    rather than being silently dropped or merged into a neighbour.
    """
    groups = []
    current = None
    for record in records:
        period = record.reporting_period
        period_key = period.pk if period else None
        if current is None or current["period_key"] != period_key:
            current = {
                "period_key": period_key,
                "period": period,
                "period_name": period.name if period else "No water year assigned",
                "rows": [],
                "diverted": Decimal("0"),
                "returned": Decimal("0"),
                "retained": Decimal("0"),
                "count": 0,
            }
            groups.append(current)
        current["rows"].append(record)
        current["diverted"] += abs(record.volume_acre_feet)
        current["returned"] += record.returned_af
        current["count"] += 1
    for group in groups:
        group["retained"] = group["diverted"] - group["returned"]
    return groups


# ---------------------------------------------------------------------------
# POD-centric views (primary entry point for Surface Diversions)
# ---------------------------------------------------------------------------


@login_required
def pod_list(request):
    """Surface Diversions OVERVIEW: a map of every diversion point + a list.

    Points of diversion are a Bucket-3 screen (few items, each heavy): a district
    has a handful, and each one's detail is rich (its location mapped on the
    stream/canal network, diversion records, linked use areas, compliance). So
    this screen is a finder, not a master-detail half-pane: the map up top shows
    every diversion point at once, the full-width list below is for finding one
    fast, and clicking a row (or a point on the map) opens that diversion's own
    full-width detail page. See ``docs/2.0-UX-PATTERN-SPEC.md`` for why this is
    Bucket 3, not master-detail.

    Returns the ``_pod_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page otherwise.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = (
        PointOfDiversion.objects
        .select_related("water_right")
        .annotate(diversion_count=Count("diversionrecord"))
        .order_by("name")
    )

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(stream_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    # Diversion points are bounded and few, so show them all on one page; finding
    # one is a glance plus a type-to-filter. Pagination stays as a graceful
    # fallback for an unusually large district.
    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # The map card's head and the map that follows the list (143-07). The
    # results partial emits the WHOLE filtered queryset's pks, never the
    # page's, and the head counts what the list counts against everything;
    # ``located_count`` is what the map can draw at all (a location is required
    # on this model, so it equals ``all_count`` here; the shared head partial
    # still branches on it because the other overview pages' geometries are
    # optional). ``filter_words`` is the status facet as the head says it.
    status_label = dict(PointOfDiversion.STATUS_CHOICES).get(status, "")
    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "all_count": PointOfDiversion.objects.count(),
        "located_count": PointOfDiversion.objects.filter(location__isnull=False).count(),
        "result_pks": list(queryset.values_list("pk", flat=True)),
        "result_located_count": queryset.filter(location__isnull=False).count(),
        "filter_words": f"with status “{status_label}”" if status_label else "",
        "hx_request": bool(request.headers.get("HX-Request")),
        "q": q,
        "status": status,
        "status_choices": PointOfDiversion.STATUS_CHOICES,
    }

    return list_response(
        request,
        page_template="surface/pod_list.html",
        results_template="surface/partials/_pod_list_results.html",
        context=context,
    )


def _device_panel_context(pod):
    """Build the "Measuring device" panel's context for ``pod`` (146-03 T1).

    Shared by ``_pod_detail_context`` (the full page) and
    ``device_mark_removed`` (the HTMX re-render of just this panel), so the
    two can never disagree about which link is current. ``needs_evidence``
    reads ``MeasuringDevice.needs_evidence()`` -- the model, not a second
    calculation here -- so the 934(d) five-year sentence is derived in one
    place only.
    """
    current_link = (
        PointOfDiversionDevice.objects
        .filter(point_of_diversion=pod, is_current=True)
        .select_related("device")
        .first()
    )
    device = current_link.device if current_link else None
    return {
        "pod": pod,
        "current_device_link": current_link,
        "device": device,
        "needs_evidence": device.needs_evidence() if device else False,
    }


def _pod_detail_context(pod):
    """Build the per-POD detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    # Diversion records for this POD, oldest-year-last so a reporting period's
    # rows stay contiguous for _group_diversion_records.
    diversion_records = list(
        DiversionRecord.objects
        .filter(point_of_diversion=pod)
        .select_related("reporting_period")
        .order_by("-month")
    )

    # 143-10 (R-115, R-055): the table's own water-year groups, and the
    # CURRENT period's figures read off that SAME grouping -- no second
    # query, so the lead panel can never disagree with the table under it
    # (a guard asserts this). accounting.services.current_period_id is the
    # helper 143-06 extracted so the diversion page, the zone page and the
    # ledger land on the same idea of "current" (surface `requires`
    # accounting, core/modules.py, so this import needs no module gate).
    record_groups = _group_diversion_records(diversion_records)
    current_period_pk = compute_current_period_id()
    current_period = (
        ReportingPeriod.objects.filter(pk=current_period_pk).first()
        if current_period_pk is not None
        else None
    )
    current_totals = next(
        (
            g for g in record_groups
            if g["period_key"] == (current_period.pk if current_period else None)
        ),
        None,
    )

    # Linked use areas (parcel connections). 146-02 D3: the share is now shown
    # and edited as the raw fraction (four decimals, "share 1.0000"), not a
    # rounded whole percent -- see _pod_parcel_share_value.html.
    pod_parcels = list(
        PointOfDiversionParcel.objects
        .filter(point_of_diversion=pod)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    # Recharge areas this diversion fills (Phase 62). For a dual-purpose Merced
    # River diversion this lists the Flood-MAR areas it floods, right next to the
    # cropland it irrigates above.
    #
    # `basin_links` is a REVERSE ACCESSOR created by recharge.models.RechargeSitePOD,
    # not an import -- which is why grepping for `from recharge` never found this
    # coupling. Drop the module and the attribute simply does not exist, so this
    # page raises AttributeError (ISS-072).
    #
    # Gated on is_enabled, deliberately NOT on getattr(pod, "basin_links", None):
    # a silent getattr fallback would also swallow a genuine future rename of the
    # relation, turning a loud bug into a quietly empty table.
    basin_links = []
    if is_enabled("recharge"):
        basin_links = (
            pod.basin_links
            .select_related("recharge_site")
            .order_by("recharge_site__name")
        )

    # One-hop water journey (Phase 67-03). rediverted_from is the upstream source
    # this POD re-diverts; rediversions is the reverse — downstream PODs that draw
    # on this POD's return flow. One hop only — no route-resolver graph this phase.
    rediverted_from = pod.rediverted_from
    rediversions = pod.rediversions.order_by("name")

    # Water right info (may be None). all_water_rights feeds the "Water right"
    # panel's select (146-02 D2) -- ordered by right_id, same as the water
    # rights list, so a district with a handful of rights reads them in the
    # order it already knows them.
    water_right = pod.water_right
    all_water_rights = WaterRight.objects.order_by("right_id")

    # Inline form for adding diversion records
    form = DiversionRecordForm(pod=pod)

    # GeoJSON for the persistent detail map. A FeatureCollection (not a bare
    # Feature) because OH2O.detailPaneMap frames the map off geojson.features.
    # Python object (not a json.dumps string): the template escapes it via
    # json_script so pod.name / stream_name can't break out of <script>.
    geojson = None
    if pod.location:
        geojson = json.loads(
            serialize(
                "geojson",
                [pod],
                geometry_field="location",
                fields=["name", "stream_name"],
            )
        )

    return {
        "pod": pod,
        "diversion_records": diversion_records,
        "record_groups": record_groups,
        "current_period": current_period,
        "current_totals": current_totals,
        "pod_parcels": pod_parcels,
        "basin_links": basin_links,
        "rediverted_from": rediverted_from,
        "rediversions": rediversions,
        "water_right": water_right,
        "all_water_rights": all_water_rights,
        "form": form,
        "geojson": geojson,
        **_device_panel_context(pod),
    }


@login_required
def pod_detail(request, pk):
    """A single point of diversion's detail.

    On an HTMX request it returns just the ``_detail_pane`` fragment (the
    workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    pod = get_object_or_404(
        PointOfDiversion.objects.select_related("water_right"), pk=pk
    )
    context = _pod_detail_context(pod)
    return detail_response(
        request,
        pane_template="surface/partials/_detail_pane.html",
        page_template="surface/pod_detail.html",
        context=context,
    )


@login_required
def pod_edit(request, pk):
    """Edit a point of diversion's own fields (146-03 Task 3): its identity,

    the canal-loss fractions and bands, and the crosswalk layer's local
    name / contract unit. Mirrors ``water_right_edit``'s shape.
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    if request.method == "POST":
        form = PointOfDiversionForm(request.POST, instance=pod)
        if form.is_valid():
            form.save()
            return redirect("surface:pod_detail", pk=pod.pk)
    else:
        form = PointOfDiversionForm(instance=pod)

    return render(request, "surface/pod_form.html", {"form": form, "pod": pod})


@login_required
@require_POST
def pod_link_right(request, pk):
    """HTMX POST: link or unlink a point of diversion's water right (146-02 D2).

    The POD page's "Water right" panel is a select of every WaterRight,
    ordered by right_id, with a blank "No right linked" option. A blank
    submit clears the FK (an operator un-linking a mistaken match); any other
    value must resolve to a real right -- ``get_object_or_404`` rather than a
    silent no-op if the pk is stale.
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    raw = request.POST.get("water_right_id", "").strip()
    if raw:
        pod.water_right = get_object_or_404(WaterRight, pk=raw)
    else:
        pod.water_right = None
    pod.save(update_fields=["water_right"])

    return render(request, "surface/partials/_pod_water_right_panel.html", {
        "pod": pod,
        "water_right": pod.water_right,
        "all_water_rights": WaterRight.objects.order_by("right_id"),
        "basin_links": pod.basin_links.exists() if is_enabled("recharge") else False,
    })


# ---------------------------------------------------------------------------
# Measuring device registry (146-03 Task 1, door S3): a point of diversion's
# 23 CCR 934(b)(1) device, entered and edited through full-page forms on the
# `period_create` pattern, and "Mark removed" as an HTMX POST that re-renders
# just the panel (the pod_link_right shape above).
# ---------------------------------------------------------------------------


@login_required
def device_add(request, pk):
    """Add a measuring device to a point of diversion and make it current.

    Only reachable from the panel when the point has no current device (the
    template hides "Add device" otherwise); the defensive close-out below
    still guards the one-current-device-per-point invariant against a stale
    tab or a direct POST.
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    if request.method == "POST":
        form = MeasuringDeviceForm(request.POST, pod=pod)
        if form.is_valid():
            device = form.save()
            PointOfDiversionDevice.objects.filter(
                point_of_diversion=pod, is_current=True,
            ).update(is_current=False, removed_on=date.today())
            PointOfDiversionDevice.objects.create(
                point_of_diversion=pod,
                device=device,
                installed_on=device.installed_on,
                is_current=True,
            )
            return redirect("surface:pod_detail", pk=pod.pk)
    else:
        form = MeasuringDeviceForm(pod=pod)

    return render(
        request, "surface/device_form.html", {"form": form, "pod": pod, "device": None},
    )


@login_required
def device_edit(request, pk):
    """Edit a measuring device in place.

    The device is not itself scoped to a point (a ``MeasuringDevice`` row has
    no FK to one -- ``PointOfDiversionDevice`` is the link), so the point to
    redirect back to, and to scope the rights-served field against, is read
    off the most relevant link: the current one, or else the most recently
    installed.
    """
    device = get_object_or_404(MeasuringDevice, pk=pk)
    link = (
        PointOfDiversionDevice.objects
        .filter(device=device)
        .select_related("point_of_diversion")
        .order_by("-is_current", "-installed_on")
        .first()
    )
    pod = link.point_of_diversion if link else None

    if request.method == "POST":
        form = MeasuringDeviceForm(request.POST, instance=device, pod=pod)
        if form.is_valid():
            form.save()
            if pod:
                return redirect("surface:pod_detail", pk=pod.pk)
            return redirect("surface:pod_list")
    else:
        form = MeasuringDeviceForm(instance=device, pod=pod)

    return render(
        request, "surface/device_form.html", {"form": form, "pod": pod, "device": device},
    )


@login_required
@require_POST
def device_mark_removed(request, pk):
    """HTMX POST: close out a point's current device link.

    Sets ``removed_on`` to today and ``is_current`` to False on the current
    link only -- the ``MeasuringDevice`` row itself is untouched, since the
    same physical device could be re-installed, or moved to another point,
    later. Re-renders the device panel, which then reads "no current device".
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    link = PointOfDiversionDevice.objects.filter(
        point_of_diversion=pod, is_current=True,
    ).first()
    if link:
        link.is_current = False
        link.removed_on = date.today()
        link.save(update_fields=["is_current", "removed_on"])

    return render(
        request, "surface/partials/_device_panel.html", _device_panel_context(pod),
    )


def _render_diversion_records_section(
    request, pod, *, form=None, edit_record=None, edit_form=None, period_warning=None,
):
    """Render ``_diversion_records.html`` for ``pod`` (146-02 Task 3).

    The one shared builder behind create, edit (GET and POST) and delete, so
    the table's grouping, current-period figures and lead-panel totals are
    computed identically for all four -- never re-derived per view. ``form``
    is the "Add diversion record" form (bound, on an invalid create submit,
    or fresh otherwise); ``edit_record``/``edit_form`` swap that form out for
    an "Edit diversion record" one when a row's Edit action is in play.
    """
    diversion_records = list(
        DiversionRecord.objects
        .filter(point_of_diversion=pod)
        .select_related("reporting_period")
        .order_by("-month")
    )

    # 143-10: the same grouping _pod_detail_context uses, so a POST that
    # swaps this partial back in renders the identical shape (row-group
    # dividers, subtotal rows) the full page load does.
    record_groups = _group_diversion_records(diversion_records)
    current_period_pk = compute_current_period_id()
    current_period = (
        ReportingPeriod.objects.filter(pk=current_period_pk).first()
        if current_period_pk is not None
        else None
    )
    current_totals = next(
        (
            g for g in record_groups
            if g["period_key"] == (current_period.pk if current_period else None)
        ),
        None,
    )

    return render(request, "surface/partials/_diversion_records.html", {
        "pod": pod,
        "diversion_records": diversion_records,
        "record_groups": record_groups,
        "current_period": current_period,
        "current_totals": current_totals,
        "form": form if form is not None else DiversionRecordForm(pod=pod),
        "period_warning": period_warning,
        "edit_record": edit_record,
        "edit_form": edit_form,
    })


#: The message a unique-constraint violation on (point_of_diversion, month,
#: diversion_type) shows instead of the raw IntegrityError a bare .save()
#: would otherwise raise as a 500 (146-02 Task 3, ISS-181).
_DUPLICATE_RECORD_ERROR = "A record for that month and type exists; edit that one."


@login_required
@require_POST
def diversion_record_create(request, pk):
    """HTMX POST endpoint: create a DiversionRecord for a POD."""
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    form = DiversionRecordForm(request.POST, pod=pod)
    period_warning = None

    if form.is_valid():
        record = form.save(commit=False)
        record.point_of_diversion = pod

        # Auto-assign reporting_period from the record's month
        month = record.month
        period = ReportingPeriod.objects.filter(
            start_date__lte=month,
            end_date__gte=month,
        ).first()
        record.reporting_period = period

        # point_of_diversion is not a form field, so Django's own ModelForm
        # unique_together check (which excludes fields absent from the form)
        # never runs it -- without this, a duplicate (POD, month, type) hit
        # the database's own constraint as a raw IntegrityError, a 500.
        try:
            record.validate_unique()
        except ValidationError:
            form.add_error(None, _DUPLICATE_RECORD_ERROR)
        else:
            record.save()
            if period is None:
                # The record saved, but with no reporting period it is invisible to
                # every period-scoped filing — say so now, not at filing time.
                period_warning = (
                    f"Saved, but no reporting period covers {month:%B %Y} — this "
                    "record will not appear in any CalWATRS filing until a period "
                    "covering that month exists. It attaches automatically once "
                    "such a period is created, or you can open and save it "
                    "yourself after one exists."
                )
            # Saved cleanly — hand back a blank form for the next entry.
            form = DiversionRecordForm(pod=pod)

    # On an invalid submit, `form` is still the BOUND form: re-rendering it
    # preserves the user's typed values and surfaces the field errors, so a
    # failed save reads as a visible error rather than a silent reset.
    return _render_diversion_records_section(
        request, pod, form=form, period_warning=period_warning,
    )


@login_required
@require_http_methods(["GET", "POST"])
def diversion_record_edit(request, pk, rpk):
    """Edit one diversion record (146-02 Task 3, ISS-181, D... "edit or delete").

    GET shows an "Edit diversion record" form in place of the "Add" one, at
    the bottom of the section (never inline in the table row: the add and
    edit forms share the same field ids, and this codebase renders exactly
    one of the two at a time rather than giving the edit form a second
    auto_id namespace for no reader-visible benefit). POST re-runs the
    period lookup for the (possibly changed) month -- an edit can move a
    record into a different water year, so this always re-renders the whole
    section rather than just the one row, keeping the table's totals and the
    lead panel's figures in agreement with the row that changed.
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    record = get_object_or_404(DiversionRecord, pk=rpk, point_of_diversion=pod)

    if request.method == "GET":
        return _render_diversion_records_section(
            request, pod, edit_record=record,
            edit_form=DiversionRecordForm(instance=record, pod=pod),
        )

    form = DiversionRecordForm(request.POST, instance=record, pod=pod)
    if form.is_valid():
        updated = form.save(commit=False)
        month = updated.month
        updated.reporting_period = ReportingPeriod.objects.filter(
            start_date__lte=month,
            end_date__gte=month,
        ).first()
        try:
            updated.validate_unique()
        except ValidationError:
            form.add_error(None, _DUPLICATE_RECORD_ERROR)
        else:
            updated.save()
            return _render_diversion_records_section(request, pod)

    # Invalid, or a duplicate caught above: keep the row in edit mode so the
    # error and the user's typed values are visible, not silently discarded.
    return _render_diversion_records_section(
        request, pod, edit_record=record, edit_form=form,
    )


@login_required
@require_POST
def diversion_record_delete(request, pk, rpk):
    """Delete one diversion record (146-02 Task 3, ISS-181)."""
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    record = get_object_or_404(DiversionRecord, pk=rpk, point_of_diversion=pod)
    record.delete()
    return _render_diversion_records_section(request, pod)


@login_required
@require_http_methods(["GET", "PATCH"])
def pod_parcel_edit_share(request, pk, pp_pk):
    """Inline fraction editor for a POD's linked use area (146-02 D3).

    The wells:edit_field GET/PATCH pattern (wells/views.py), scoped to one
    PointOfDiversionParcel row rather than a field on the parent model. GET
    returns the edit form (or, with ``?cancel=1``, the plain value); PATCH
    validates and saves. 0 < fraction <= 1 -- a share of exactly 0 means
    nothing is served and belongs to removing the link, not a fraction, and a
    share over 1 would claim more than the whole point delivers.
    """
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    pp = get_object_or_404(PointOfDiversionParcel, pk=pp_pk, point_of_diversion=pod)

    if request.method == "GET":
        context = {"pod": pod, "pp": pp}
        if request.GET.get("cancel"):
            return render(request, "surface/partials/_pod_parcel_share_value.html", context)
        return render(request, "surface/partials/_pod_parcel_share_edit.html", context)

    body_params = parse_qs(request.body.decode("utf-8"))
    raw_value = body_params.get("value", [""])[0].strip()
    try:
        fraction = coerce_decimal(
            raw_value, "Share", min_value=0, min_exclusive=True, allow_blank=False
        )
    except FieldValidationError as exc:
        return render(request, "surface/partials/_pod_parcel_share_edit.html", {
            "pod": pod, "pp": pp, "value": raw_value, "error": str(exc),
        })
    if fraction > Decimal("1"):
        return render(request, "surface/partials/_pod_parcel_share_edit.html", {
            "pod": pod, "pp": pp, "value": raw_value,
            "error": "Share must be greater than 0 and no more than 1.",
        })

    pp.fraction = fraction
    pp.save(update_fields=["fraction"])
    return render(request, "surface/partials/_pod_parcel_share_value.html", {"pod": pod, "pp": pp})


# ---------------------------------------------------------------------------
# Water Rights views (kept for compliance-focused navigation)
# ---------------------------------------------------------------------------


@login_required
def water_rights_list(request):
    """Water Rights OVERVIEW: a searchable full-width list of every right.

    Water rights are a Bucket-3 screen (few items, each heavy): a district has a
    handful, and each right's detail is rich (its points of diversion mapped,
    diversion records, active curtailments, place of use). So this screen is a
    finder, not a master-detail half-pane: the full-width list is for finding one
    fast, and clicking a row opens that right's own full detail page. Unlike the
    other Bucket-3 screens there is NO overview map — a water right is a legal
    entitlement with no geometry of its own; its spatial footprint (the diversion
    points it authorizes) is shown on its detail page where it has meaning. See
    ``docs/2.0-UX-PATTERN-SPEC.md``.

    Returns the ``_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page otherwise.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = WaterRight.objects.select_related("right_type").order_by("right_id")

    if q:
        queryset = queryset.filter(
            Q(right_id__icontains=q) | Q(holder_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    # Water rights are bounded and few, so show them all on one page; finding one
    # is a glance plus a type-to-filter. Pagination stays as a graceful fallback.
    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": WaterRight.STATUS_CHOICES,
    }

    return list_response(
        request,
        page_template="surface/water_rights_list.html",
        results_template="surface/partials/_list_results.html",
        context=context,
    )


@login_required
def water_right_create(request):
    """Create a water right (146-02 door D1), the `period_create` full-page pattern."""
    if request.method == "POST":
        form = WaterRightForm(request.POST)
        if form.is_valid():
            water_right = form.save()
            return redirect("surface:detail", pk=water_right.pk)
    else:
        form = WaterRightForm()

    return render(request, "surface/right_form.html", {"form": form, "water_right": None})


@login_required
def water_right_edit(request, pk):
    """Edit a water right (146-02 door D1)."""
    water_right = get_object_or_404(WaterRight, pk=pk)
    if request.method == "POST":
        form = WaterRightForm(request.POST, instance=water_right)
        if form.is_valid():
            form.save()
            return redirect("surface:detail", pk=water_right.pk)
    else:
        form = WaterRightForm(instance=water_right)

    return render(
        request, "surface/right_form.html", {"form": form, "water_right": water_right}
    )


# ---------------------------------------------------------------------------
# Water rights bulk import: page -> preview/mapping -> commit (door D1)
# ---------------------------------------------------------------------------


@login_required
@require_GET
def water_right_import(request):
    """Bulk import landing page for the state's own rights LIST export."""
    return render(request, "surface/right_import.html", {})


def _rights_columns_from_rows(rows):
    seen = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _rights_mapping_context(columns, rows, mapping, error=None):
    field_rows = [
        {"field": field, "label": label, "guess": mapping.get(field, "")}
        for field, label in importer.import_fields()
    ]
    sample_table = [[row.get(col, "") for col in columns] for row in rows[:5]]
    context = {
        "columns": columns,
        "field_rows": field_rows,
        "sample_table": sample_table,
        "sample_count": len(sample_table),
        "row_count": len(rows),
        "rows_json": json.dumps(rows),
    }
    if error:
        context["error"] = error
    return context


@login_required
@require_POST
def water_right_import_preview(request):
    """Parse the uploaded CSV, auto-map its columns, return the mapping UI."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return render(
            request,
            "surface/partials/_right_import_result.html",
            {"error": "No file provided. Choose the state's rights LIST CSV export."},
        )

    try:
        parsed = importer.parse_upload(uploaded, uploaded.name)
    except ImportError as exc:
        return render(
            request, "surface/partials/_right_import_result.html", {"error": str(exc)},
        )

    columns = parsed["columns"]
    rows = parsed["rows"]
    mapping = importer.auto_map_columns(columns)

    return render(
        request,
        "surface/partials/_right_import_mapping.html",
        _rights_mapping_context(columns, rows, mapping),
    )


@login_required
@require_POST
def water_right_import_commit(request):
    """Validate the confirmed mapping against the parsed rows and bulk-create."""
    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request,
            "surface/partials/_right_import_result.html",
            {"error": "No rows to import -- please re-upload your file and try again."},
        )

    if len(rows) > importer.MAX_ROWS:
        return render(
            request,
            "surface/partials/_right_import_result.html",
            {"error": (
                f"Import is {len(rows)} rows, over the {importer.MAX_ROWS}-row "
                "cap. Re-upload a smaller file."
            )},
        )

    mapping = {
        key[len("map:"):]: val
        for key, val in request.POST.items()
        if key.startswith("map:") and val
    }

    existing_right_ids = set(WaterRight.objects.values_list("right_id", flat=True))

    try:
        results = importer.validate_rows(rows, mapping, existing_right_ids)
        created = importer.commit_rows(results)
    except Exception as exc:
        logger.exception("water right import commit failed")
        columns = _rights_columns_from_rows(rows)
        return render(
            request,
            "surface/partials/_right_import_mapping.html",
            _rights_mapping_context(
                columns, rows, mapping,
                error=f"Nothing was created: {type(exc).__name__}: {exc}",
            ),
            status=200,
        )
    skipped = [r for r in results if r["errors"]]

    return render(
        request,
        "surface/partials/_right_import_result.html",
        {"created": created, "skipped": skipped, "total": len(results)},
    )


# ---------------------------------------------------------------------------
# 146-03 Task 4 (D4): diversion volumes in bulk against a point of diversion.
# ---------------------------------------------------------------------------


def _diversion_import_settings_context(points, *, selected_point=None, method="",
                                        data_state="provisional"):
    return {
        "points": points,
        "selected_point": selected_point,
        "method": method,
        "data_state": data_state,
        "method_choices": DiversionRecord.METHOD_CHOICES,
        "data_state_choices": DiversionRecord.DATA_STATE_CHOICES,
    }


@login_required
@require_GET
def diversion_import(request):
    """Bulk import landing page for diversion volumes (D4): the state's

    Water Use Reported layout, or a ditch tender's own book.
    """
    points = PointOfDiversion.objects.filter(status="active").order_by("name")
    return render(
        request, "surface/diversion_import.html",
        _diversion_import_settings_context(points),
    )


@login_required
@require_POST
def diversion_import_preview(request):
    """Parse the upload (or re-run with changed settings) and show the

    mapping step: the whole-file point, method and data state, every
    conversion, every combined month, every unresolved row and every error
    -- before anything is written (dry_run=True throughout).
    """
    points = PointOfDiversion.objects.filter(status="active").order_by("name")
    uploaded = request.FILES.get("file")
    rows_json_raw = request.POST.get("rows_json", "")

    if uploaded:
        try:
            columns, rows = diversion_import_service.parse_csv(uploaded, uploaded.name)
        except ImportError as exc:
            return render(
                request, "surface/partials/_diversion_import_result.html",
                {"error": str(exc)},
            )
    elif rows_json_raw:
        try:
            rows = json.loads(rows_json_raw)
        except json.JSONDecodeError:
            rows = []
        if not rows:
            return render(
                request, "surface/partials/_diversion_import_result.html",
                {"error": "No rows to preview -- please re-upload your file and try again."},
            )
        columns = list(rows[0].keys())
    else:
        return render(
            request, "surface/partials/_diversion_import_result.html",
            {"error": "No file provided. Choose a diversion volume CSV."},
        )

    if len(rows) > diversion_import_service.MAX_ROWS:
        return render(
            request, "surface/partials/_diversion_import_result.html",
            {"error": (
                f"Import is {len(rows)} rows, over the "
                f"{diversion_import_service.MAX_ROWS}-row cap. Re-upload a smaller file."
            )},
        )

    try:
        layout = diversion_import_service.recognise_layout(columns)
    except ImportError as exc:
        return render(
            request, "surface/partials/_diversion_import_result.html",
            {"error": str(exc)},
        )

    point_pk = request.POST.get("point", "")
    whole_file_point = PointOfDiversion.objects.filter(pk=point_pk).first() if point_pk else None
    method = request.POST.get("method", "")
    data_state = request.POST.get("data_state", "") or "provisional"

    result = diversion_import_service.import_diversion_rows(
        columns, rows, layout=layout, whole_file_point=whole_file_point,
        method=method, data_state=data_state, dry_run=True,
    )

    context = _diversion_import_settings_context(
        points, selected_point=whole_file_point, method=method, data_state=data_state,
    )
    context.update(result)
    context["rows_json"] = json.dumps(rows)
    context["row_count"] = len(rows)
    return render(request, "surface/partials/_diversion_import_preview.html", context)


@login_required
@require_POST
def diversion_import_commit(request):
    """Re-run the confirmed settings against the parsed rows and write them."""
    points = PointOfDiversion.objects.filter(status="active").order_by("name")
    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request, "surface/partials/_diversion_import_result.html",
            {"error": "No rows to import -- please re-upload your file and try again."},
        )

    columns = list(rows[0].keys())
    try:
        layout = diversion_import_service.recognise_layout(columns)
    except ImportError as exc:
        return render(
            request, "surface/partials/_diversion_import_result.html",
            {"error": str(exc)},
        )

    point_pk = request.POST.get("point", "")
    whole_file_point = PointOfDiversion.objects.filter(pk=point_pk).first() if point_pk else None
    method = request.POST.get("method", "")
    data_state = request.POST.get("data_state", "") or "provisional"

    try:
        result = diversion_import_service.import_diversion_rows(
            columns, rows, layout=layout, whole_file_point=whole_file_point,
            method=method, data_state=data_state, dry_run=False,
        )
    except Exception as exc:
        logger.exception("diversion import commit failed")
        context = _diversion_import_settings_context(
            points, selected_point=whole_file_point, method=method, data_state=data_state,
        )
        context["rows_json"] = json.dumps(rows)
        context["row_count"] = len(rows)
        context["error"] = f"Nothing was created: {type(exc).__name__}: {exc}"
        return render(request, "surface/partials/_diversion_import_preview.html", context)

    return render(request, "surface/partials/_diversion_import_result.html", result)


def _water_right_detail_context(water_right):
    """Build the per-right detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    pods = PointOfDiversion.objects.filter(water_right=water_right).order_by("name")

    # 143-10 (R-121, R-122, R-055): every record, not the last 12 -- a
    # right's records are monthly per point, a few dozen a year, so the
    # count belongs in the card head rather than a silent truncation.
    # Ordered by month, then by POD name (R-122): the previous "-month" alone
    # left ties between two PODs recording in the same month swap order from
    # render to render, because the database gives no guarantee for equal
    # keys with no secondary sort.
    all_records = list(
        DiversionRecord.objects.filter(point_of_diversion__water_right=water_right)
        .select_related("point_of_diversion")
        .order_by("-month", "point_of_diversion__name")
    )
    record_groups = _group_diversion_records(all_records)
    current_period_pk = compute_current_period_id()
    current_period = (
        ReportingPeriod.objects.filter(pk=current_period_pk).first()
        if current_period_pk is not None
        else None
    )
    current_totals = next(
        (
            g for g in record_groups
            if g["period_key"] == (current_period.pk if current_period else None)
        ),
        None,
    )

    # Remaining = face value less the current period's recorded volume,
    # across every point of diversion under this right -- never re-derived
    # from anything but the SAME rows the table under the panel prints
    # (ISS-154, 137-02; 143-05).
    remaining = None
    if water_right.face_value_acre_feet is not None:
        diverted_so_far = current_totals["diverted"] if current_totals else Decimal("0")
        remaining = water_right.face_value_acre_feet - diverted_so_far

    # "By point of diversion": the current period's rows broken down by the
    # POD that recorded them, so the panel's Recorded segment can show where
    # the sum came from without a second query against the database.
    pod_breakdown = []
    if current_totals:
        totals_by_pod = {}
        for record in current_totals["rows"]:
            name = record.point_of_diversion.name
            totals_by_pod[name] = totals_by_pod.get(name, Decimal("0")) + abs(
                record.volume_acre_feet
            )
        pod_breakdown = [
            {"name": name, "total": total}
            for name, total in sorted(totals_by_pod.items())
        ]

    # Curtailment orders that may apply to this right (146-02 Task 4, ISS-180
    # D6): the rule lives in surface/curtailments.py, grounded and verified
    # per 146-02-EVIDENCE.md Task 4 -- never re-derived here.
    active_curtailments, unmatched_curtailments = orders_that_may_apply(water_right)

    # GeoJSON for the PODs this right serves — a FeatureCollection (the right maps
    # multiple diversion points, so OH2O.detailPaneMap frames the map across all of
    # them via geojson.features). Python object (not a dumped string): the template
    # escapes it via json_script so POD names can't break out of <script>.
    pods_with_location = [p for p in pods if p.location]
    pods_geojson = None
    if pods_with_location:
        pods_geojson = json.loads(
            serialize(
                "geojson",
                pods_with_location,
                geometry_field="location",
                fields=["name", "stream_name", "max_rate_cfs", "status"],
            )
        )
        # R-123: the serializer puts pk at the feature's top level, not in
        # properties, the same reason the general `pods_geojson` endpoint
        # injects it below — this map's popup needs it to link out.
        for f in pods_geojson["features"]:
            f["properties"]["pk"] = f.get("id")

    return {
        "water_right": water_right,
        "pods": pods,
        "record_groups": record_groups,
        "record_count": len(all_records),
        "current_period": current_period,
        "current_totals": current_totals,
        "remaining": remaining,
        "pod_breakdown": pod_breakdown,
        "active_curtailments": active_curtailments,
        "unmatched_curtailments": unmatched_curtailments,
        "pods_geojson": pods_geojson,
        # 146-02 D3: this right's places of use. Gated on `parcels` for the
        # same reason `basin_links` above is gated on `recharge` -- surface
        # requires parcels (core/modules.py), so this is always True in a
        # valid deployment; the guard is defensive documentation, not a
        # reachable branch.
        "places_of_use": _water_right_places_of_use(water_right) if is_enabled("parcels") else [],
    }


def _water_right_places_of_use(water_right):
    """This right's WaterRightParcel rows, parcel-number order.

    Shared by the detail context and by assign/remove, which re-render just
    the `_places_of_use_list.html` fragment (146-02 D3, the account page's
    search-parcels / assign fragment shape -- accounting/views.py -- reused as
    a shape, never its views).
    """
    return list(
        WaterRightParcel.objects.filter(water_right=water_right)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )


@login_required
def water_right_detail(request, pk):
    """A single water right's detail.

    On an HTMX request it returns just the ``_water_right_detail_pane`` fragment
    (the workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    water_right = get_object_or_404(
        WaterRight.objects.select_related("right_type"), pk=pk
    )
    context = _water_right_detail_context(water_right)
    return detail_response(
        request,
        pane_template="surface/partials/_water_right_detail_pane.html",
        page_template="surface/water_right_detail.html",
        context=context,
    )


# ---------------------------------------------------------------------------
# Places of use (146-02 D3): the account page's search-parcels / assign
# fragment shape (accounting/views.py::assign_parcel / remove_parcel /
# parcel_search_for_assignment), reused as a shape only -- WaterRightParcel
# has no soft-delete columns (no added_date/removed_date), so "remove" here
# is a real delete, not a tombstone.
# ---------------------------------------------------------------------------


@login_required
@require_POST
def water_right_assign_parcel(request, pk):
    """Assign a parcel as a place of use for a water right."""
    water_right = get_object_or_404(WaterRight, pk=pk)
    parcel = get_object_or_404(Parcel, pk=request.POST.get("parcel_id"))
    WaterRightParcel.objects.get_or_create(water_right=water_right, parcel=parcel)

    return render(request, "surface/partials/_places_of_use_list.html", {
        "water_right": water_right,
        "places_of_use": _water_right_places_of_use(water_right),
    })


@login_required
@require_POST
def water_right_remove_parcel(request, pk, wrp_pk):
    """Remove a place of use from a water right (a real delete: no soft-delete column)."""
    water_right = get_object_or_404(WaterRight, pk=pk)
    wrp = get_object_or_404(WaterRightParcel, pk=wrp_pk, water_right=water_right)
    wrp.delete()

    return render(request, "surface/partials/_places_of_use_list.html", {
        "water_right": water_right,
        "places_of_use": _water_right_places_of_use(water_right),
    })


@login_required
@require_GET
def water_right_search_parcels(request, pk):
    """HTMX endpoint: search for parcels to add as a place of use."""
    water_right = get_object_or_404(WaterRight, pk=pk)
    q = request.GET.get("q", "").strip()

    results = []
    if q:
        already = WaterRightParcel.objects.filter(
            water_right=water_right
        ).values_list("parcel_id", flat=True)
        results = (
            Parcel.objects.filter(
                Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
            )
            .exclude(pk__in=already)
            .order_by("parcel_number")[:10]
        )

    return render(request, "surface/partials/_places_of_use_search_results.html", {
        "water_right": water_right, "results": results, "q": q,
    })


# ---------------------------------------------------------------------------
# Curtailment orders (146-02 Task 4, door D6, ISS-180). The matching rule
# these orders feed into is `surface/curtailments.py::orders_that_may_apply`,
# grounded on a real instance and an order's own text -- see
# 146-02-EVIDENCE.md Task 4. These three doors only take an order's own
# fields down; the list and the right's page are what read them.
# ---------------------------------------------------------------------------


@login_required
def curtailments_list(request):
    """All curtailment orders, newest effective date first."""
    orders = CurtailmentOrder.objects.order_by("-effective_date")
    return render(request, "surface/curtailments_list.html", {"orders": orders})


@login_required
def curtailment_create(request):
    """Create a curtailment order (146-02 door D6), the `right_form.html` full-page pattern."""
    if request.method == "POST":
        form = CurtailmentOrderForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("surface:curtailments_list")
    else:
        form = CurtailmentOrderForm()

    return render(request, "surface/curtailment_form.html", {"form": form, "order": None})


@login_required
def curtailment_edit(request, pk):
    """Edit a curtailment order (146-02 door D6)."""
    order = get_object_or_404(CurtailmentOrder, pk=pk)
    if request.method == "POST":
        form = CurtailmentOrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            return redirect("surface:curtailments_list")
    else:
        form = CurtailmentOrderForm(instance=order)

    return render(request, "surface/curtailment_form.html", {"form": form, "order": order})


@public_in_open_demo
def pods_geojson(request):
    """Return all points of diversion as a GeoJSON FeatureCollection."""
    raw = serialize(
        "geojson",
        PointOfDiversion.objects.all(),
        geometry_field="location",
        fields=["name", "stream_name", "max_rate_cfs", "status"],
    )
    data = json.loads(raw)
    for f in data["features"]:
        # Inject pk so the full-map popup can link to the POD detail page.
        f["properties"]["pk"] = f.get("id")
        # 143-07 Step 0: the map label, code prefix stripped. labelField reads
        # this first and falls back to the existing expression, so an older
        # cached response still labels the way it always has.
        f["properties"]["label"] = map_label(f["properties"].get("name") or "")
    return HttpResponse(json.dumps(data), content_type="application/json")
