# SPDX-License-Identifier: AGPL-3.0-or-later
"""Water production by month and source: the year table, the by-hand form and the file import."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from core import pending_imports
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


#: Water sold to another system: left out of the year's produced-or-purchased
#: total and named on its own.
SOLD_TYPE_CODES = frozenset({PRODUCTION_TYPE_SO, PRODUCTION_TYPE_NS})


def _selected_production_year(request: HttpRequest, years: list[int]) -> int | None:
    """The year asked for in the query string, else the latest year on file."""
    year_param = request.GET.get("year", "").strip()
    if year_param.isdigit():
        return int(year_param)
    return years[0] if years else None


def _production_rows(by_key: dict, type_codes: list[str]) -> list[dict]:
    """The table rows: one per month, plus a whole-year row when a record has no month."""
    # A record with month=None (the whole year reported as one figure) is
    # its own row at the foot of the table, never folded into a numbered
    # month it was never attached to.
    has_annual_row = any(month is None for month, _type_code in by_key)

    rows = []
    for month_num in range(1, 13):
        rows.append(
            {
                "month": month_num,
                "label": PRODUCTION_MONTH_NAMES[month_num],
                "cells": [by_key.get((month_num, code)) for code in type_codes],
            }
        )
    if has_annual_row:
        rows.append(
            {
                "month": None,
                "label": "Whole year (one figure)",
                "cells": [by_key.get((None, code)) for code in type_codes],
            }
        )
    return rows


def _production_totals(by_key: dict, type_codes: list[str]) -> list[dict]:
    """One footer total per type code, in gallons, whole gallons and acre-feet."""
    totals = []
    for code in type_codes:
        column = [record for (_month, t), record in by_key.items() if t == code]
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
            r.volume_as_reported for (_m, t), r in by_key.items() if t == code
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

    type_codes = [code for code, _label in PRODUCTION_TYPE_CHOICES]
    records = (
        SystemProduction.objects.filter(system=system, year=year)
        if year is not None
        else SystemProduction.objects.none()
    )
    by_key = {(r.month, r.type_code): r for r in records}

    rows = _production_rows(by_key, type_codes)
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
    for row in rows:
        row["cells"] = [row["cells"][i] for i in shown]
    totals = [totals[i] for i in shown]

    return render(
        request,
        "drinking/production.html",
        {
            "system": system,
            "years": years,
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
            "has_any": SystemProduction.objects.filter(system=system).exists(),
        },
    )


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
                                          operator_unit="G"):
    return {
        "unit_choices": PRODUCTION_UNIT_CHOICES,
        "unit_for_blank": unit_for_blank,
        "operator_year": operator_year,
        "operator_unit": operator_unit,
    }


def _posted_production_settings(data):
    """The mapping-step settings as posted, as the stored upload remembers them."""
    return {
        "unit_for_blank": data.get("unit_for_blank", "").strip(),
        "operator_year": data.get("operator_year", "").strip(),
        "operator_unit": data.get("operator_unit", "").strip() or "G",
    }


def _production_run_settings(page_settings):
    """The importer's keyword arguments for a set of stored settings."""
    year = page_settings.get("operator_year", "")
    return {
        "unit_for_blank": page_settings.get("unit_for_blank") or None,
        "operator_year": int(year) if year.isdigit() else None,
        "operator_unit": page_settings.get("operator_unit") or "G",
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

    result = production_import_service.import_production_rows(
        columns, rows, system=system, layout=layout,
        **_production_run_settings(page_settings),
        dry_run=True,
    )

    context = _production_import_settings_context(**page_settings)
    context.update(_capped_errors(result))
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

    result = production_import_service.import_production_rows(
        columns, rows, system=system, layout=layout,
        **_production_run_settings(pending.settings),
        dry_run=False,
    )
    return _capped_errors(result)


@login_required
@require_POST
def production_import_commit(request):
    """Start writing the stored file with the confirmed mapping-step settings."""
    page_settings = _posted_production_settings(request.POST)

    # A log with no year imports nothing: show the preview again, with the
    # year box asking for it.
    if not page_settings["operator_year"].isdigit():
        pending = pending_imports.previewed(request, "production")
        if pending is not None:
            try:
                columns, _rows = parse_stored_production(pending)
                layout = production_import_service.recognise_layout(columns)
            except FileNotFoundError:
                return pending_imports.refused(request, "production")
            except ImportError as exc:
                return render(
                    request,
                    "drinking/partials/_production_import_result.html",
                    {"error": str(exc)},
                )
            if layout == "operator_log":
                return production_import_preview(request)

    return pending_imports.start_import(request, "production", page_settings)
