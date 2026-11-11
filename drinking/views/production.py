# SPDX-License-Identifier: AGPL-3.0-or-later
"""Water production by month and source: the year table, the by-hand form and the file import."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from core import corrections, pending_imports
from core.corrections_views import mark_actions
from drinking import production_import as production_import_service
from drinking.forms import SystemProductionForm
from drinking.models import (
    PRODUCTION_TYPE_CHOICES,
    PRODUCTION_TYPE_NS,
    PRODUCTION_TYPE_SO,
    PRODUCTION_UNIT_CHOICES,
    SystemProduction,
    WaterSystem,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Production by month and source
# ---------------------------------------------------------------------------
#
# The record shape 2's operator never had: what the system produced, by
# month and by source. Same three-step shape as the lab import above (page,
# preview, commit) for the bulk door; a plain ModelForm for the by-hand door.
# The importer's own rules -- two layouts, unit conversions, dedup -- live in
# ``drinking/production_import.py``.

PRODUCTION_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
    12: "December",
}


#: What a record with no facility is listed as, under a month that holds several records.
WHOLE_SYSTEM_NAME = "Whole system"

#: Water sold to another system: left out of the year's produced-or-purchased
#: total and named on its own.
SOLD_TYPE_CODES = frozenset({PRODUCTION_TYPE_SO, PRODUCTION_TYPE_NS})


def _selected_production_year(request: HttpRequest, years: list[int]) -> int | None:
    """The year asked for in the query string, else the latest year on file."""
    year_param = request.GET.get("year", "").strip()
    if year_param.isdigit():
        return int(year_param)
    return years[0] if years else None


def _production_rows(by_key: dict, type_codes: list[str], voided_by_key: dict | None = None) -> list[dict]:
    """The table rows: one per month, plus a whole-year row when a record has no month.

    ``by_key`` maps (month, type code) to every current record of that month and source.
    """
    # A record with month=None (the whole year reported as one figure) is
    # its own row at the foot of the table, never folded into a numbered
    # month it was never attached to.
    voided_by_key = voided_by_key or {}
    has_annual_row = any(
        month is None for month, _type_code in list(by_key) + list(voided_by_key)
    )

    def row_for(month_num, label):
        # ``voided_cells`` holds, per type column, the latest voided record of that
        # month when nothing counting stands in its place: its figure prints struck.
        return {
            "month": month_num,
            "label": label,
            "records": [by_key.get((month_num, code), []) for code in type_codes],
            "voided_cells": [
                None if by_key.get((month_num, code)) else (voided_by_key.get((month_num, code)) or [None])[0]
                for code in type_codes
            ],
            "voided_all": [voided_by_key.get((month_num, code), []) for code in type_codes],
        }

    rows = [row_for(month_num, PRODUCTION_MONTH_NAMES[month_num]) for month_num in range(1, 13)]
    if has_annual_row:
        rows.append(row_for(None, "Whole year (one figure)"))
    return rows


def _production_totals(by_key: dict, type_codes: list[str]) -> list[dict]:
    """One footer total per type code, in gallons, whole gallons and acre-feet."""
    totals = []
    for code in type_codes:
        column = [record for (_month, t), records in by_key.items() if t == code for record in records]
        gallons = sum((r.volume_gallons for r in column), Decimal("0"))
        totals.append(
            {
                "type_code": code,
                # Gallons are the state's own reported unit and arrive as
                # whole numbers (`Water Produced or Delivered` carries no
                # fractional gallon in either layout), so this is rounded in
                # the view rather than through `floatformat`; there is
                # nothing a formatter would do here that `int()` does not.
                # Acre-feet is different: it is a conversion this platform
                # performs (325,851 gallons per acre-foot), so it goes
                # through `floatformat:2` in the template.
                "gallons": gallons,
                "gallons_whole": int(gallons.to_integral_value()),
                "acre_feet": sum((r.volume_acre_feet for r in column), Decimal("0")),
            }
        )
    return totals


def _facility_name(record) -> str:
    """The name a record is listed under: its facility's, or "Whole system" when it has none."""
    facility = record.facility
    if facility is None:
        return WHOLE_SYSTEM_NAME
    return facility.name or facility.facility_id


def _listed_lines(row: dict, shown: list[int], type_columns: list, year: int) -> list[dict]:
    """The lines under a month that holds two or more records of a source, one per facility.

    A facility's line carries its figure in each source column where the month holds two or
    more records, and the lines of voided or replaced records of that facility and source.
    """
    multi = [i for i in range(len(shown)) if len(row["records"][shown[i]]) > 1]
    if not multi:
        return []
    by_name: dict[str, dict] = {}
    for position in multi:
        for record in row["records"][shown[position]]:
            name = _facility_name(record)
            group = by_name.setdefault(name, {"name": name, "columns": {p: [] for p in multi}, "gone": []})
            group["columns"][position].append(record)
    for position in multi:
        label = type_columns[position][1]
        for record in row["voided_all"][shown[position]]:
            name = _facility_name(record)
            group = by_name.setdefault(name, {"name": name, "columns": {p: [] for p in multi}, "gone": []})
            group["gone"].append((record, f"{label}, {name}"))
    ordered = sorted(by_name.values(), key=lambda g: (g["name"] == WHOLE_SYSTEM_NAME, g["name"]))
    lines = []
    for group in ordered:
        depth = max((len(records) for records in group["columns"].values()), default=0)
        for n in range(max(depth, 1)):
            pairs = []
            for position, column in enumerate(type_columns):
                records = group["columns"].get(position, [])
                cell = records[n] if n < len(records) else None
                pairs.append({
                    "cell": cell,
                    "label": f"{row['label']} {year} {column[1].lower()} record, {group['name']}",
                })
            lines.append({
                "name": group["name"],
                "pairs": pairs,
                # The voided lines of the facility sit under its first line.
                "gone": group["gone"] if n == 0 else [],
            })
    return lines


def _shown_columns(by_key: dict, type_codes: list[str]) -> tuple[list[int], list[str]]:
    """The indexes of the type columns worth showing, and the lower-case labels of the sources among them."""
    # A source reported as zero, or not
    # at all, in every month of the year is one sentence above the table, not
    # a column of twelve zeros. Le Grand's real eAR carries five such columns
    # beside its one groundwater column, which would leave most of the
    # table's width as dead space. The grand total
    # still sums every source column, so nothing drops out of the arithmetic.
    shown = [
        i for i, code in enumerate(type_codes)
        if any(
            r.volume_as_reported for (_m, t), records in by_key.items() if t == code for r in records
        )
    ]
    # Named in lower case because they are read mid-sentence in the head line.
    # The sold columns are not where the water came from, so the "from" list
    # leaves them out; the head line names sold water on its own.
    shown_labels = [
        PRODUCTION_TYPE_CHOICES[i][1].lower() for i in shown
        if type_codes[i] not in SOLD_TYPE_CODES
    ]
    if not shown:
        shown = list(range(len(type_codes)))
    return shown, shown_labels


def _production_table_context(system, year, *, void_key=None, void_reason="", void_error="", notice="", warning=""):
    """What the year table shows for ``system`` and ``year``.

    Figures and totals come from the records that count. A voided record stays
    on the table: where nothing counting stands in its place its figure prints
    struck in its cell, and one line under the month says when it was voided.
    Each counting record takes the "..." menu for a writer (one
    ``finalized_ranges()`` for the table).
    """
    type_codes = [code for code, _label in PRODUCTION_TYPE_CHOICES]
    records = (
        SystemProduction.objects.current().filter(system=system, year=year).select_related("facility").order_by("pk")
        if year is not None
        else SystemProduction.objects.none()
    )
    # Every current record of a month and source counts, so each key holds a list.
    by_key: dict = {}
    for r in records:
        by_key.setdefault((r.month, r.type_code), []).append(r)
    voided_by_key: dict = {}
    if year is not None:
        # Voided, or replaced by a corrected record: struck, with a line under the month.
        voided = SystemProduction.objects.filter(system=system, year=year).select_related("facility").filter(
            Q(voided_at__isnull=False) | Q(replaced_at__isnull=False)
        ).order_by("-pk")
        for record in voided:
            voided_by_key.setdefault((record.month, record.type_code), []).append(record)

    marked = [r for rows in by_key.values() for r in rows] + [r for rows in voided_by_key.values() for r in rows]
    mark_actions(
        marked, can_write=True, finalized=corrections.finalized_ranges(), void_key=void_key
    )

    rows = _production_rows(by_key, type_codes, voided_by_key)
    totals = _production_totals(by_key, type_codes)

    # The year
    # total is water produced or purchased. Water sold to another system came
    # out of that water, so adding the two sold columns counted it twice; they
    # are totalled on their own and named after it. Each column's own total in
    # the table foot is unchanged.
    supply = [t for t in totals if t["type_code"] not in SOLD_TYPE_CODES]
    sold = [t for t in totals if t["type_code"] in SOLD_TYPE_CODES]
    grand_total_gallons = sum((t["gallons"] for t in supply), Decimal("0"))
    grand_total_af = sum((t["acre_feet"] for t in supply), Decimal("0"))
    sold_total_gallons = sum((t["gallons"] for t in sold), Decimal("0"))

    shown, shown_labels = _shown_columns(by_key, type_codes)
    zero_labels = [
        label.lower()
        for i, (_code, label) in enumerate(PRODUCTION_TYPE_CHOICES)
        if i not in shown
    ]
    type_columns = [PRODUCTION_TYPE_CHOICES[i] for i in shown]
    for index, row in enumerate(rows):
        row["listed"] = _listed_lines(row, shown, type_columns, year)
        # Records of a month and source that sit in a listed line are printed there.
        listed_positions = {
            position for position in range(len(shown)) if len(row["records"][shown[position]]) > 1
        }
        # One entry per shown column for the template: the counting record, the voided
        # one that stands in its place (or None), the month's sum when it holds several
        # records, and the menu's name for the record.
        row["pairs"] = []
        for position, column in enumerate(type_columns):
            column_records = row["records"][shown[position]]
            pair = {
                "cell": column_records[0] if len(column_records) == 1 else None,
                "voided": row["voided_cells"][shown[position]],
                "sum": None,
                "label": f"{row['label']} {year} {column[1].lower()} record",
            }
            if len(column_records) > 1:
                gallons = sum((r.volume_gallons for r in column_records), Decimal("0"))
                pair["sum"] = {
                    "gallons_whole": int(gallons.to_integral_value()),
                    "count": len(column_records),
                    "word": "facilities" if all(r.facility_id for r in column_records) else "records",
                }
            row["pairs"].append(pair)
        # The month's own voided lines: the ones whose source is not listed below it.
        listed_indexes = {shown[position] for position in listed_positions}
        row["voided"] = [
            r
            for column_index, records_gone in enumerate(row["voided_all"]) if column_index not in listed_indexes
            for r in records_gone
        ]
        # A listed line shares its month's stripe: the stripe counts month rows only.
        row["listed_class"] = "row-listed row-listed-shaded" if index % 2 else "row-listed"
    totals = [totals[i] for i in shown]

    return {
        "system": system,
        "year": year,
        "type_codes": type_codes,
        "type_columns": type_columns,
        "zero_labels": zero_labels,
        "shown_labels": shown_labels,
        "rows": rows,
        "totals": totals,
        "grand_total_gallons": grand_total_gallons,
        "grand_total_gallons_whole": int(grand_total_gallons.to_integral_value()),
        "grand_total_af": grand_total_af,
        "sold_total_gallons_whole": int(sold_total_gallons.to_integral_value()),
        "void_key": void_key,
        "void_reason": void_reason,
        "void_error": void_error,
        "notice": notice,
        "warning": warning,
    }


def render_production_table(
    request, row, *, void_key=None, void_reason="", void_error="", notice="", warning=""
):
    """The year table the production record ``row`` is in (core.corrections_views.TABLES)."""
    context = _production_table_context(
        row.system, row.year, void_key=void_key, void_reason=void_reason,
        void_error=void_error, notice=notice, warning=warning,
    )
    return render(request, "drinking/partials/_production_table.html", context)


@login_required
def production(request):
    """The year table: production and delivery by month and source.

    Months down, type codes across, in the unit each type was reported in
    plus acre-feet -- the shape a small system's operator wants: the same
    figures the state's own eAR already has from them, read back in one
    table instead of scattered across a year of import rows.

    No system onboarded yet: the empty state names the two files this door
    takes (the eAR export, the operator's own log) rather than an empty
    table with nothing to explain it.
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(request, "drinking/production.html", {"system": None})

    years = list(
        SystemProduction.objects.filter(system=system)
        .order_by("-year")
        .values_list("year", flat=True)
        .distinct()
    )

    year = _selected_production_year(request, years)
    context = _production_table_context(system, year)
    context["years"] = years
    context["has_any"] = SystemProduction.objects.filter(system=system).exists()
    return render(request, "drinking/production.html", context)


@login_required
def production_add(request):
    """Add one month's production or delivery by hand.

    No system onboarded yet: the page itself says so and links to Onboard,
    the same way the year table's own empty state does, rather than bouncing
    the visitor away from the page they asked for -- a redirect is a page
    nobody can read, and `/drinking/onboard/` is not what "Add month"
    promised (`tests/test_platform_readability.py`).
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(request, "drinking/production_form.html", {"system": None})

    if request.method == "POST":
        form = SystemProductionForm(request.POST, system=system)
        if form.is_valid():
            record = form.save()
            return redirect(f"{reverse('drinking:production')}?year={record.year}")
    else:
        form = SystemProductionForm(system=system)

    return render(
        request, "drinking/production_form.html", {"form": form, "system": system}
    )


@login_required
@require_GET
def production_import_page(request):
    """The production-import landing page: the eAR export, or the operator's own log."""
    return render(request, "drinking/production_import.html", {})


def _production_import_settings_context(*, unit_for_blank="", operator_year="",
                                          operator_unit="G", month_column="",
                                          column_types=None):
    return {
        "unit_choices": PRODUCTION_UNIT_CHOICES,
        "type_choices": PRODUCTION_TYPE_CHOICES,
        "unit_for_blank": unit_for_blank,
        "operator_year": operator_year,
        "operator_unit": operator_unit,
        "month_column": month_column,
        "column_types": column_types or {},
    }


_COLUMN_TYPE_PREFIX = "column_type:"


def _posted_production_settings(data):
    """The mapping-step settings as posted, as the stored upload remembers them.

    ``operator_unit`` stays blank when it is not chosen: the Section 5 log reads
    a blank as gallons, a log with its own headings refuses it.
    """
    valid_types = {code for code, _label in PRODUCTION_TYPE_CHOICES}
    column_types = {
        key[len(_COLUMN_TYPE_PREFIX):]: value.strip()
        for key, value in data.items()
        if key.startswith(_COLUMN_TYPE_PREFIX) and value.strip() in valid_types
    }
    return {
        "unit_for_blank": data.get("unit_for_blank", "").strip(),
        "operator_year": data.get("operator_year", "").strip(),
        "operator_unit": data.get("operator_unit", "").strip(),
        "month_column": data.get("month_column", "").strip(),
        "column_types": column_types,
    }


def _production_mapping(page_settings):
    """The importer's ``mapping`` for a set of stored settings."""
    month = page_settings.get("month_column", "")
    return {
        "month": month,
        "columns": {
            heading: code
            for heading, code in (page_settings.get("column_types") or {}).items()
            if heading != month
        },
    }


def _production_run_settings(page_settings):
    """The importer's keyword arguments for a set of stored settings."""
    year = page_settings.get("operator_year", "")
    return {
        "unit_for_blank": page_settings.get("unit_for_blank") or None,
        "operator_year": int(year) if year.isdigit() else None,
        "operator_unit": page_settings.get("operator_unit") or None,
        "mapping": _production_mapping(page_settings),
    }


def _capped_errors(result):
    """``result`` with its error rows capped, the full count kept beside them."""
    errors, not_listed = pending_imports.cap_error_rows(result["errors"])
    return {
        **result,
        "errors": errors,
        "error_count": len(result["errors"]),
        "errors_not_listed": not_listed,
    }


def parse_stored_production(pending):
    """The stored production file, read again: (columns, rows)."""
    with pending_imports.stored_file(pending) as file:
        return production_import_service.parse_csv(file, pending.original_name)


@login_required
@require_POST
def production_import_preview(request):
    """Parse the upload (or re-run with changed mapping-step settings) and

    show what a commit would do -- every skipped row and every error -- with
    nothing written yet (dry_run=True throughout). The first call saves the
    upload; a settings change posts the same token and re-reads the stored
    file.
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "This site has no water system yet. Add a water system first."},
        )

    uploaded = request.FILES.get("file")
    new_upload = bool(uploaded)

    if uploaded:
        try:
            pending, (columns, rows) = pending_imports.receive(
                request,
                "production",
                uploaded,
                lambda file: production_import_service.parse_csv(file, uploaded.name),
            )
        except ImportError as exc:
            return render(
                request,
                "drinking/partials/_production_import_result.html",
                {"error": str(exc)},
            )
    elif request.POST.get("token"):
        pending = pending_imports.previewed(request, "production")
        if pending is None:
            return pending_imports.refused(request, "production")
        try:
            columns, rows = parse_stored_production(pending)
        except FileNotFoundError:
            return pending_imports.refused(request, "production")
        except ImportError as exc:
            return render(
                request,
                "drinking/partials/_production_import_result.html",
                {"error": str(exc)},
            )
    else:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "Choose a CSV file to upload."},
        )

    try:
        layout = production_import_service.recognise_layout(columns)
    except ImportError as exc:
        if new_upload:
            pending_imports.discard(pending)
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": str(exc)},
        )

    page_settings = _posted_production_settings(request.POST)
    pending.settings = page_settings
    pending.save(update_fields=["settings"])

    if layout == "mapped" and new_upload and not page_settings["month_column"]:
        # A heading that is plainly the month is chosen on the first look; the
        # person can change it before pressing Update preview.
        guess = next(
            (c for c in columns if c.strip().lower() in ("month", "date", "date/month", "month/year")),
            "",
        )
        page_settings = {**page_settings, "month_column": guess}
    try:
        result = production_import_service.import_production_rows(
            columns, rows, system=system, layout=layout,
            **_production_run_settings(page_settings),
            dry_run=True,
        )
    except ImportError as exc:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": str(exc)},
        )

    if layout == "operator_log" and not page_settings["operator_unit"]:
        page_settings = {**page_settings, "operator_unit": "G"}
    context = _production_import_settings_context(**page_settings)
    context.update(_capped_errors(result))
    if layout == "mapped":
        month = page_settings["month_column"]
        context["mapped_columns"] = [
            {"heading": column, "type": page_settings["column_types"].get(column, "")}
            for column in columns
            if column != month
        ]
        # The refusals are said once the person has pressed Update preview,
        # never on the first look at the file.
        context["show_refusals"] = not new_upload
        context["needs_year"] = production_import_service.month_needs_year(rows, month)
        context["can_import"] = not result["refusals"] and not result["year_missing"]
    context["token"] = pending.token
    context["row_count"] = len(rows)
    # The file's own rows under its own column names, bounded.
    context["preview_columns"] = columns
    context["preview_rows"] = [
        [row.get(column, "") for column in columns]
        for row in rows[: pending_imports.PREVIEW_ROW_LIMIT]
    ]
    return render(
        request, "drinking/partials/_production_import_preview.html", context
    )


def commit_stored_production(pending):
    """Write the stored production file; the result block's context.

    Runs in the import worker (core/pending_imports.py).
    """
    system = WaterSystem.objects.first()
    if system is None:
        return {"error": "This site has no water system yet. Add a water system first."}

    columns, rows = parse_stored_production(pending)
    try:
        layout = production_import_service.recognise_layout(columns)
    except ImportError as exc:
        return {"error": str(exc)}

    try:
        result = production_import_service.import_production_rows(
            columns, rows, system=system, layout=layout,
            **_production_run_settings(pending.settings),
            dry_run=False,
        )
    except ImportError as exc:
        return {"error": str(exc)}
    return _capped_errors(result)


@login_required
@require_POST
def production_import_commit(request):
    """Start writing the stored file with the confirmed mapping-step settings."""
    page_settings = _posted_production_settings(request.POST)

    # A log with no year, a log with its own headings that is not fully
    # mapped, or one with no unit chosen imports nothing: show the preview
    # again, with the step asking.
    needs_check = (
        not page_settings["operator_year"].isdigit()
        or "month_column" in request.POST
    )
    if needs_check:
        pending = pending_imports.previewed(request, "production")
        if pending is not None:
            try:
                columns, rows = parse_stored_production(pending)
                layout = production_import_service.recognise_layout(columns)
            except FileNotFoundError:
                return pending_imports.refused(request, "production")
            except ImportError as exc:
                return render(
                    request,
                    "drinking/partials/_production_import_result.html",
                    {"error": str(exc)},
                )
            if layout == "operator_log" and not page_settings["operator_year"].isdigit():
                return production_import_preview(request)
            if layout == "mapped":
                run = _production_run_settings(page_settings)
                try:
                    unit = production_import_service.normalise_unit(run["operator_unit"])
                except ImportError:
                    return production_import_preview(request)
                mapping = run["mapping"]
                if (
                    production_import_service.mapping_refusals(mapping, unit)
                    or (
                        run["operator_year"] is None
                        and production_import_service.month_needs_year(
                            rows, mapping["month"]
                        )
                    )
                ):
                    return production_import_preview(request)

    return pending_imports.start_import(request, "production", page_settings)
