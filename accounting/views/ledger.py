# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parcel ledger: the filtered list, adding a row by hand, CSV upload, the CSV template and the export."""
from datetime import date
from decimal import Decimal

import csv as csv_module

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from core.csv_safe import safe_row
from accounting.engine_run import recalculation_sentence, request_for_months
from accounting.locks import (
    PeriodFinalized,
    refuse_if_finalized,
    refuse_if_period_finalized,
)
from accounting.forms import CsvUploadForm, ParcelLedgerForm
from accounting.models import ReportingPeriod, WaterType
from accounting.ledger_words import DEMONSTRATION_FILE_LINE
from core.models import SiteConfig
from core.modules import is_enabled
from accounting.services import (
    current_period_id as compute_current_period_id,
    parse_ledger_csv,
)
from geography.models import Zone
from parcels.models import Parcel, ParcelLedger


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

# Whitelist of sortable columns → ORM fields. An unbounded order_by() fed from a
# GET param is a 500 / injection vector, so we map a small set of safe keys and
# fail closed to the newest-first default for anything else.
LEDGER_SORTABLE = {
    "date": "effective_date",
    "parcel": "parcel__parcel_number",
    "amount": "amount_acre_feet",
    "source": "source_type",
    "water_type": "water_type__name",
}


# Page-size options offered in the ledger toolbar. 100 is the at-scale default
# (replaces the historic hardcoded 50); anything outside the set falls back to 100.
LEDGER_PAGE_SIZES = (25, 100, 500)


#: Which module owns each ledger source type, for the Source FILTER only.
#:
#: ``ParcelLedger.SOURCE_TYPE_CHOICES`` is the full historical vocabulary and has
#: to stay that way. A ``surface_diversion`` row written before the module was
#: switched off is still a real row, ``accounting/ledger_words.py::
#: ledger_row_words`` still names it, and hiding it would be lying about the
#: ledger. What this table gates is the OFFER: on a
#: deployment with no Surface module, a "Surface Diversion" option in the filter
#: invites an operator to filter for a row type this deployment can never
#: produce.
#:
#: **Declared, never derived.** A source type absent from this table is offered
#: in every configuration, which is the safe direction to fail;
#: ``tests/test_module_template_guards.py::
#: test_ledger_source_owners_still_describe_real_source_types`` fails if a row
#: outlives the choice it names.
LEDGER_SOURCE_TYPE_OWNERS = {
    "surface_diversion": "surface",
    "recharge": "recharge",
}


#: The Source FILTER's option words.
#: The filter still narrows on the stored ``source_type`` value; only the
#: option LABELS changed, to the shortest true words
#: (a filter option is one word or a short phrase, not the fuller
#: "{Water type}, metered" sentence the merged Water column prints per row:
#: that sentence needs the row's own water type, which no single filter
#: option can name). Keep this table in sync with
#: ``accounting/ledger_words.py`` by hand; a value missing here falls back to
#: the model's own label below.
LEDGER_SOURCE_TYPE_LABELS = {
    "meter_reading": "Metered",
    "calculated": "Estimated",
    "et_estimate": "ET estimate",
    "surface_diversion": "Diverted",
    "manual_entry": "Entered by hand",
    "csv_import": "Imported from CSV",
    "adjustment": "Adjusted",
    "allocation": "Allocation",
    "recharge": "Recharge credit",
}


def ledger_source_type_choices():
    """``SOURCE_TYPE_CHOICES`` minus the ones whose module this deployment lacks,
    with the Source filter's own sentence-case words (``LEDGER_SOURCE_TYPE_LABELS``)."""
    return [
        (value, LEDGER_SOURCE_TYPE_LABELS.get(value, label))
        for value, label in ParcelLedger.SOURCE_TYPE_CHOICES
        if value not in LEDGER_SOURCE_TYPE_OWNERS
        or is_enabled(LEDGER_SOURCE_TYPE_OWNERS[value])
    ]


def _ledger_filters(request: HttpRequest) -> dict[str, str]:
    """The ledger's text filters and sort, read from the query string.

    Keys: q, period_id, source_type, water_type_id, start_date, end_date,
    active_areas, sort, direction, zone_id. They are also the context keys.
    """
    q = request.GET.get("q", "").strip()
    period_id = request.GET.get("period", "").strip()
    source_type = request.GET.get("source_type", "").strip()
    water_type_id = request.GET.get("water_type", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    # "Active Use Areas" preset chip: restrict to ledger rows on a parcel whose
    # status is active (an inactive use area is not a live water user). Any
    # truthy value means "on"; the chip sends "1".
    active_areas = request.GET.get("active_areas", "").strip()

    # Navigation params: sort column + direction, Zone facet, page size.
    sort = request.GET.get("sort", "").strip()
    direction = request.GET.get("dir", "desc").strip()
    if direction not in ("asc", "desc"):
        direction = "desc"
    zone_id = request.GET.get("zone", "").strip()
    return {
        "q": q,
        "period_id": period_id,
        "source_type": source_type,
        "water_type_id": water_type_id,
        "start_date": start_date,
        "end_date": end_date,
        "active_areas": active_areas,
        "sort": sort,
        "direction": direction,
        "zone_id": zone_id,
    }


def _ledger_page_size(request: HttpRequest) -> int:
    """The requested page size, or 100 when it is missing or not one of the offered sizes."""
    try:
        page_size = int(request.GET.get("page_size", 100))
    except (TypeError, ValueError):
        page_size = 100
    if page_size not in LEDGER_PAGE_SIZES:
        page_size = 100
    return page_size


def _ledger_default_period(
    filters: dict[str, str], period_present: bool, periods: QuerySet[ReportingPeriod]
) -> tuple[str, bool, str, bool, int | None]:
    """Resolve the period filter, defaulting a bare landing to the current period.

    Returns (period_id, auto_defaulted, auto_default_period_name,
    auto_default_calculated, default_period_id).
    """
    # Landing on the ledger with no filters at all should not bury the
    # audit trail. The "How was this calculated?" links only render on
    # calculated rows, so default to the most recent period that HAS calculated
    # rows (falling back to the most recent period with any rows, then to no
    # filter on an empty table). An explicit "All Periods" (period=) is honored.
    # The "current" period: the most recent period with calculated records, then
    # any activity, then simply the most recent period. This single value is both
    # the auto-default target on a bare landing AND the destination of the "This
    # Period" preset chip, so the two always point at the same period.
    #
    # The three-fallback derivation itself lives in
    # accounting.services.current_period_id(), which the allocations view (and
    # the zone view) call too, so "current period" cannot mean two things
    # on two screens. calculated_period_id stays a query of its own here only
    # because auto_default_calculated below needs to know which fallback rung
    # produced the default, a distinction the shared helper has no reason to
    # expose.
    calculated_period_id = (
        ParcelLedger.objects.filter(
            source_type="calculated", reporting_period__isnull=False
        )
        .order_by("-reporting_period__start_date")
        .values_list("reporting_period_id", flat=True)
        .first()
    )
    default_period_id = compute_current_period_id()

    period_id = filters["period_id"]
    period_auto_defaulted = False
    auto_default_period_name = ""
    auto_default_calculated = calculated_period_id is not None
    no_other_filters = not (
        filters["q"] or filters["source_type"] or filters["water_type_id"]
        or filters["start_date"] or filters["end_date"] or filters["zone_id"]
        or filters["active_areas"]
    )
    if not period_present and no_other_filters and default_period_id is not None:
        period_id = str(default_period_id)
        period_auto_defaulted = True
        default_period = next(
            (p for p in periods if p.pk == default_period_id), None
        )
        auto_default_period_name = default_period.name if default_period else ""
    return (
        period_id,
        period_auto_defaulted,
        auto_default_period_name,
        auto_default_calculated,
        default_period_id,
    )


def _apply_ledger_filters(
    queryset: QuerySet[ParcelLedger], filters: dict[str, str]
) -> QuerySet[ParcelLedger]:
    """Narrow the ledger rows by search text, period, source, water type, dates, status and zone."""
    q = filters["q"]
    if q:
        queryset = queryset.filter(
            Q(parcel__parcel_number__icontains=q) | Q(description__icontains=q)
        )
    if filters["period_id"]:
        queryset = queryset.filter(reporting_period_id=filters["period_id"])
    if filters["source_type"]:
        queryset = queryset.filter(source_type=filters["source_type"])
    if filters["water_type_id"]:
        queryset = queryset.filter(water_type_id=filters["water_type_id"])
    if filters["start_date"]:
        queryset = queryset.filter(effective_date__gte=filters["start_date"])
    if filters["end_date"]:
        queryset = queryset.filter(effective_date__lte=filters["end_date"])
    if filters["active_areas"]:
        queryset = queryset.filter(parcel__status="active")
    if filters["zone_id"]:
        # A field is in a zone for a span of dates, so the filter asks who was
        # a member in the span the screen is looking at: the chosen water year,
        # else the dates typed, else all time. zone_parcel_ids is the reader the
        # zone page uses, so the two screens agree on who belonged.
        from accounting.services import zone_parcel_ids

        def _day(text, fallback):
            try:
                return date.fromisoformat(text)
            except ValueError:
                return fallback

        zone = Zone.objects.filter(pk=filters["zone_id"]).first()
        period = (
            ReportingPeriod.objects.filter(pk=filters["period_id"]).first()
            if filters["period_id"]
            else None
        )
        members = (
            []
            if zone is None
            else zone_parcel_ids(
                zone,
                period,
                date_start=_day(filters["start_date"], date.min),
                date_end=_day(filters["end_date"], date.max),
            )
        )
        queryset = queryset.filter(parcel_id__in=members)
    return queryset


def _apply_ledger_sort(
    queryset: QuerySet[ParcelLedger], sort: str, direction: str
) -> QuerySet[ParcelLedger]:
    """Re-order by a whitelisted sort key, with a stable tiebreak."""
    # Sort: only a whitelisted key re-orders; everything else keeps the
    # newest-first default set on the queryset above. A stable
    # parcel__parcel_number, -created_at tiebreak keeps pagination
    # deterministic when the sort field ties, and reproduces the same
    # use-area ordering the default view carries; skipped for the "parcel"
    # key itself, which already sorts by that field.
    if sort in LEDGER_SORTABLE:
        field = LEDGER_SORTABLE[sort]
        prefix = "-" if direction == "desc" else ""
        order_fields = [f"{prefix}{field}"]
        if field != "parcel__parcel_number":
            order_fields.append("parcel__parcel_number")
        order_fields.append("-created_at")
        queryset = queryset.order_by(*order_fields)
    return queryset


def _ledger_footer_totals(queryset: QuerySet[ParcelLedger]) -> dict[str, Decimal | None]:
    """The credits and water subtotals over the whole filtered set."""
    # Two subtotals over the WHOLE filtered set (every matching row, not just the
    # visible page), named by kind and never netted. Credits
    # are the allocation and recharge rows, paper or banked water (DESIGN.md
    # rule 12, "Credit"). The water figure is every other source type: canal
    # deliveries, pumping and the corrections an operator makes to them,
    # stored negative by the ledger's convention and handed to the template as
    # a positive magnitude. The two are told apart by SOURCE TYPE,
    # never by sign. Splitting on the sign put a positive manual correction
    # under Credits; manual entries, CSV imports and adjustments are
    # deliberately unconstrained in sign (parcels/models.py), so a sign says
    # nothing about which kind a row is. The two are not addable, so there is
    # no net: a net would disagree with the dashboard, which calls a
    # delivery a supply where this footer would call it a debit (DESIGN.md
    # rule 12, review question 3). Re-filter by PK to drop
    # the zone M2M join, whose row duplication (a parcel in N zones) would
    # otherwise multiply amounts in SUM.
    #
    # The water figure is what was delivered and pumped, so an estimated row
    # counts at the pumping its run stamped (the water lifted), not at the
    # consumption it was made from. A row from a run that stamped no pumping
    # (a run from before the stamp existed) counts as recorded.
    from django.db.models import Case, DecimalField, F, OuterRef, Subquery, When

    from accounting.models import CalculationRun

    credit_rows = Q(source_type__in=ParcelLedger.POSITIVE_SOURCE_TYPES)
    rows = ParcelLedger.objects.filter(pk__in=queryset.values("pk")).annotate(
        run_pumped_af=Subquery(
            CalculationRun.objects.filter(
                parcel_id=OuterRef("parcel_id"),
                period_start=OuterRef("effective_date"),
            )
            .order_by("-created_at")
            .values("gw_extracted_af")[:1]
        )
    )
    water_amount = Case(
        When(
            Q(source_type="calculated") & Q(run_pumped_af__isnull=False),
            then=F("run_pumped_af") * -1,
        ),
        default=F("amount_acre_feet"),
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )
    return rows.aggregate(
        credits=Sum("amount_acre_feet", filter=credit_rows),
        water=Sum(water_amount, filter=~credit_rows),
    )


#: The query-string keys the Download CSV link carries, in the order the filter
#: bar shows them. ``ledger_export`` reads them through ``_ledger_filters``.
_DOWNLOAD_KEYS = (
    ("period", "period_id"),
    ("zone", "zone_id"),
    ("q", "q"),
    ("source_type", "source_type"),
    ("water_type", "water_type_id"),
    ("start_date", "start_date"),
    ("end_date", "end_date"),
    ("active_areas", "active_areas"),
)


def _ledger_download_query(filters: dict[str, str]) -> str:
    """The query string that makes the export match the screen's filters."""
    return urlencode([(key, filters[name]) for key, name in _DOWNLOAD_KEYS])


def _ledger_active_filter_labels(
    filters: dict[str, str],
    zones: QuerySet[Zone],
    water_types: QuerySet[WaterType],
    source_type_choices: list[tuple[str, str]],
) -> list[str]:
    """Labels for every facet currently narrowing the set, in filter-bar order."""
    q = filters["q"]
    zone_id = filters["zone_id"]
    source_type = filters["source_type"]
    water_type_id = filters["water_type_id"]
    start_date = filters["start_date"]
    end_date = filters["end_date"]
    active_filter_labels = []
    if q:
        active_filter_labels.append('Search "{}"'.format(q))
    if zone_id:
        zone_name = next((z.name for z in zones if str(z.pk) == zone_id), None)
        if zone_name:
            active_filter_labels.append(f"Zone {zone_name}")
    if source_type:
        source_type_label = next(
            (label for val, label in source_type_choices if val == source_type),
            source_type,
        )
        active_filter_labels.append(source_type_label)
    if water_type_id:
        water_type_name = next(
            (wt.name for wt in water_types if str(wt.pk) == water_type_id), None
        )
        if water_type_name:
            active_filter_labels.append(water_type_name)
    if start_date and end_date:
        active_filter_labels.append(f"{start_date} to {end_date}")
    elif start_date:
        active_filter_labels.append(f"From {start_date}")
    elif end_date:
        active_filter_labels.append(f"Through {end_date}")
    if filters["active_areas"]:
        active_filter_labels.append("Active use areas")
    return active_filter_labels


@login_required
def ledger_list(request):
    """Paginated list of ledger entries with HTMX search and filters."""
    filters = _ledger_filters(request)
    # "period" absent entirely (bare landing) is distinct from "period="
    # (the "All Periods" choice, which the HTMX filters always send). Only the
    # former gets an auto-default applied below.
    period_present = "period" in request.GET
    page_size = _ledger_page_size(request)

    # The tiebreak orders by use-area number ascending, not
    # just -created_at, so within one date a reader sees a field's meter
    # reading beside its delivery instead of raw seed-insertion order.
    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "parcel__parcel_number", "-created_at")

    periods = ReportingPeriod.objects.order_by("-start_date")
    water_types = WaterType.objects.order_by("name")
    zones = Zone.objects.order_by("name")

    (
        period_id,
        period_auto_defaulted,
        auto_default_period_name,
        auto_default_calculated,
        default_period_id,
    ) = _ledger_default_period(filters, period_present, periods)
    filters["period_id"] = period_id

    queryset = _apply_ledger_filters(queryset, filters)
    queryset = _apply_ledger_sort(queryset, filters["sort"], filters["direction"])
    ledger_totals = _ledger_footer_totals(queryset)

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # The subtitle line names the period and the active filters
    # instead of the template re-deriving them from raw ids. period_name is
    # "All periods" on an explicit ?period= (or no period at all); on a bare
    # auto-defaulted landing the template folds in the separate auto-default
    # sentence instead of using this value. active_filter_labels lists every
    # OTHER facet currently narrowing the set, in filter-bar order, so
    # "filtered: Zone Halvern, Active use areas" always names what changed.
    source_type_choices = ledger_source_type_choices()
    period_name = "All water years"
    if period_id:
        period_name = next(
            (p.name for p in periods if str(p.pk) == period_id), period_name
        )
    active_filter_labels = _ledger_active_filter_labels(
        filters, zones, water_types, source_type_choices
    )

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "ledger_total_credits": ledger_totals["credits"] or Decimal("0"),
        "ledger_total_water": abs(ledger_totals["water"] or Decimal("0")),
        **filters,
        "period_name": period_name,
        "active_filter_labels": active_filter_labels,
        "periods": periods,
        "water_types": water_types,
        "zones": zones,
        "page_size": page_size,
        "page_sizes": LEDGER_PAGE_SIZES,
        "source_type_choices": source_type_choices,
        "period_auto_defaulted": period_auto_defaulted,
        "auto_default_period_name": auto_default_period_name,
        "auto_default_calculated": auto_default_calculated,
        "current_period_id": default_period_id,
        # The page description names "recharge" (copy rule 11's settled
        # sentence); a deployment without the recharge module must not see
        # that noun (tests/droppability/checks.py::
        # test_kept_pages_never_name_a_dropped_module), so the template
        # drops the clause rather than the view rewriting the whole sentence.
        "recharge_enabled": is_enabled("recharge"),
    }

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_ledger_list_results.html", context
        )

    return render(request, "accounting/ledger_list.html", context)


def _recalculate_ledger_months(request, months):
    """Start the calculation for the months a saved delivery row touches.

    A field's own delivery record changes what is left of the canal total for
    its neighbours, so the month is recalculated. Adds the one line beneath
    the success message; a month inside a finalized water year is left alone.
    """
    started = request_for_months("ledger_saved", months, requested_by=request.user)
    covered = sorted({m for r in started for m in r.months})
    if covered:
        messages.success(request, recalculation_sentence(covered))


@login_required
def ledger_create(request):
    """Create a single ParcelLedger entry."""
    if request.method == "POST":
        form = ParcelLedgerForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.created_by = request.user
            try:
                refuse_if_finalized(entry.effective_date)
                refuse_if_period_finalized(entry.reporting_period)
            except PeriodFinalized as exc:
                form.add_error("effective_date", str(exc))
            else:
                entry.save()
                messages.success(request, "Entry saved.")
                if entry.source_type == "surface_diversion" and is_enabled("surface"):
                    _recalculate_ledger_months(
                        request, [f"{entry.effective_date:%Y-%m}"]
                    )
                return redirect("accounting:ledger_list")
    else:
        form = ParcelLedgerForm()
        # Pre-fill parcel if provided via query string
        parcel_pk = request.GET.get("parcel", "").strip()
        if parcel_pk:
            try:
                parcel = Parcel.objects.get(pk=parcel_pk)
                form.initial["parcel"] = parcel.pk
            except Parcel.DoesNotExist:
                pass

    return render(request, "accounting/ledger_create.html", {"form": form})


@login_required
def csv_upload(request):
    """Upload a CSV file to bulk-import ledger entries."""
    if request.method == "POST":
        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["file"]
            period = form.cleaned_data.get("reporting_period")
            dry_run = form.cleaned_data.get("dry_run", False)
            results = parse_ledger_csv(csv_file, reporting_period=period, dry_run=dry_run)
            context = {"form": form, "results": results, "dry_run": dry_run}
            months = results.get("surface_diversion_months") or []
            if months and not dry_run and is_enabled("surface"):
                started = request_for_months(
                    "ledger_saved", months, requested_by=request.user
                )
                covered = sorted({m for r in started for m in r.months})
                if covered:
                    context["recalculation_line"] = recalculation_sentence(covered)
            if request.headers.get("HX-Request"):
                return render(request, "accounting/partials/_csv_upload_results.html", context)
            return render(request, "accounting/csv_upload.html", context)
        else:
            context = {"form": form}
            # An HTMX submit targets #upload-results: return just the results
            # partial (carrying the form errors), never the full page — grafting
            # the whole document in would nest a <form> and duplicate IDs.
            if request.headers.get("HX-Request"):
                return render(request, "accounting/partials/_csv_upload_results.html", context)
            return render(request, "accounting/csv_upload.html", context)

    form = CsvUploadForm()
    return render(request, "accounting/csv_upload.html", {"form": form})


@login_required
def csv_template(request):
    """Download a blank CSV template with the required column headers."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ledger_import_template.csv"'
    writer = csv_module.writer(response)
    # A blank template holds no figures, so it carries no demonstration line
    # (2026-10-18).
    writer.writerow([
        "parcel_number",
        "effective_date",
        "amount_acre_feet",
        "source_type",
        "water_type_code",
        "description",
        "transaction_date",
    ])
    return response


@login_required
def ledger_export(request):
    """Export filtered ledger entries as CSV."""
    q = request.GET.get("q", "").strip()
    period_id = request.GET.get("period", "").strip()
    source_type = request.GET.get("source_type", "").strip()
    water_type_id = request.GET.get("water_type", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    active_areas = request.GET.get("active_areas", "").strip()

    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "-created_at")

    if q:
        queryset = queryset.filter(
            Q(parcel__parcel_number__icontains=q) | Q(description__icontains=q)
        )
    if period_id:
        queryset = queryset.filter(reporting_period_id=period_id)
    if source_type:
        queryset = queryset.filter(source_type=source_type)
    if water_type_id:
        queryset = queryset.filter(water_type_id=water_type_id)
    if start_date:
        queryset = queryset.filter(effective_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(effective_date__lte=end_date)
    if active_areas:
        queryset = queryset.filter(parcel__status="active")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ledger_export.csv"'
    writer = csv_module.writer(response)
    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow([DEMONSTRATION_FILE_LINE])
    # Round-trip contract: emit EXACTLY the columns the importer reads
    # (import_ledger_csv / parse_ledger_csv), in their order, so a downloaded
    # export re-imports losslessly. Previously this wrote a water_type *name* and a
    # reporting_period the importer ignores, and omitted transaction_date — so the
    # app's own export could not be fed back into its own import.
    writer.writerow([
        "parcel_number", "effective_date", "amount_acre_feet", "source_type",
        "water_type_code", "description", "transaction_date",
    ])
    for entry in queryset.iterator():
        # safe_row neutralizes CSV formula injection in the free-text cells
        # (parcel_number, water_type code, description) without touching the
        # numeric/date cells. See core.csv_safe.
        writer.writerow(safe_row([
            entry.parcel.parcel_number,
            entry.effective_date,
            entry.amount_acre_feet,
            entry.source_type,
            entry.water_type.code if entry.water_type else "",
            entry.description,
            entry.transaction_date,
        ]))
    return response
