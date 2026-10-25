# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab-file import: choose a file, preview what it would write, then commit."""
import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from drinking import importer
from drinking.ps_codes import uses_california_ps_codes
from drinking.models import WaterSystem
from drinking.views.common import _ROWS_NOT_RECEIVED


# ---------------------------------------------------------------------------
# Lab-file import: page -> preview -> commit
# ---------------------------------------------------------------------------
#
# Thin glue over ``drinking.importer``'s four functions, mirroring the
# infrastructure import flow's shape and error idiom. The one deliberate
# difference: infrastructure offers a manual column-mapping step, and this does
# not. The DDW SDWIS.CSV layout is a published spec, so auto-mapping is right
# essentially always; a mapping UI would be five clicks of ceremony to confirm
# what the header row already said. When a REQUIRED column cannot be found, the
# preview says exactly which one rather than offering a grid of dropdowns.


@login_required
@require_GET
def import_page(request):
    """The lab-file upload page (the dropzone)."""
    return render(request, "drinking/import.html", {"max_rows": importer.MAX_ROWS})


def _unknown_ps_code_routes(validated):
    """Which PS Codes the file names that this deployment does not carry.

    The single most likely real-world failure: a partially-walked system. On its
    own that dead-ends in a row error with nowhere to go, so each unknown code is
    resolved back to the system it belongs to and, when that system is onboarded,
    to the sampling-point builder that can create it.

    Detected structurally — a row that carried a PS Code but got no
    ``sampling_point_id`` — rather than by matching the error string, so a
    reworded message cannot silently switch this off.

    A California code's PWSID is its first segment by construction (DDW's
    ``{pwsid}_{facility_id}_{point_number}``). Another state's code is stored as
    its lab file writes it and need not contain a PWSID at all (ISS-077), so a
    first segment counts as a PWSID only when it looks like California's or
    names a system this site carries. Any other code is still reported, without
    a link.
    """
    unknown = sorted(
        {
            item["data"]["ps_code"]
            for item in validated
            if item["data"].get("ps_code")
            and item["data"].get("sampling_point_id") is None
        }
    )
    if not unknown:
        return []

    onboarded = set(WaterSystem.objects.values_list("pwsid", flat=True))
    routes = []
    for ps_code in unknown:
        first = ps_code.split("_")[0] if "_" in ps_code else ""
        pwsid = (
            first if first in onboarded or uses_california_ps_codes(first) else ""
        )
        routes.append(
            {
                "ps_code": ps_code,
                "pwsid": pwsid,
                "is_onboarded": pwsid in onboarded,
            }
        )
    return routes


def _preview_rows(rows, mapping, validated):
    """Zip validated rows back to their source values for the preview table."""
    def src(row, field):
        col = mapping.get(field)
        return (row.get(col) or "").strip() if col else ""

    shaped = []
    for item in validated:
        row = rows[item["index"]]
        shaped.append(
            {
                # The spreadsheet's row number, the column names being row 1.
                "index": item["index"] + 2,
                "ps_code": src(row, "ps_code"),
                "sample_date": src(row, "sample_date"),
                "analyte": src(row, "analyte_name"),
                "result": src(row, "result"),
                "unit": src(row, "unit"),
                "errors": item["errors"],
                "warnings": item["warnings"],
                # Message M row 10: already on file or repeated in the file.
                "skip": bool(item["data"].get("is_duplicate")),
            }
        )
    return shaped


@login_required
@require_POST
def import_preview(request):
    """Parse, auto-map and validate the upload; show what a commit would do."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": "Choose a lab results file to upload."},
        )

    try:
        parsed = importer.parse_upload(uploaded, uploaded.name)
    except ImportError as exc:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": str(exc)},
        )

    columns = parsed["columns"]
    rows = parsed["rows"]
    mapping = importer.auto_map_columns(columns)

    missing = [f for f in importer.REQUIRED_FIELDS if not mapping.get(f)]
    if missing:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": importer.missing_columns_message(missing)},
        )

    validated = importer.validate_rows(rows, mapping)
    preview = _preview_rows(rows, mapping, validated)

    error_rows = [r for r in preview if r["errors"]]
    warning_rows = [r for r in preview if r["warnings"] and not r["errors"]]
    repeat_count = sum(
        1 for item in validated if item["data"].get("repeat_in_file")
    )
    duplicate_count = sum(
        1 for item in validated if item["data"].get("is_duplicate")
    ) - repeat_count
    new_analytes = sorted(
        {
            item["data"]["analyte_name"]
            for item in validated
            if not item["errors"] and item["data"].get("analyte_id") is None
            and item["data"].get("analyte_name")
        }
    )
    committable = sum(
        1
        for item in validated
        if not item["errors"] and not item["data"].get("is_duplicate")
    )
    # Results already on file that predate the limits and will gain them from
    # this file (146-04). A file that creates nothing but fills
    # these still has something to commit.
    limits_fill_count = sum(
        1
        for item in validated
        if not item["errors"] and item["data"].get("fill_limits_pk") is not None
    )

    return render(
        request,
        "drinking/partials/_import_preview.html",
        {
            "recognised": [
                (importer.FIELD_LABELS[field], col)
                for field, col in mapping.items()
            ],
            "preview_rows": preview[:200],
            "shown_count": min(len(preview), 200),
            "error_rows": error_rows,
            "warning_rows": warning_rows,
            "row_count": len(rows),
            "error_count": len(error_rows),
            "duplicate_count": duplicate_count,
            "repeat_count": repeat_count,
            "new_analytes": new_analytes,
            "committable": committable,
            "limits_fill_count": limits_fill_count,
            "unknown_ps_codes": _unknown_ps_code_routes(validated),
            # 150-04 V3: the regulating-agency line the commit will print,
            # decided by the same function the commit calls; nothing written.
            "agency": importer.regulating_agency_outcomes(rows, mapping, validated),
            "rows_json": json.dumps(rows),
            # Carried to the commit so each result can say which file the
            # limits it carries arrived in (ISS-140, "beside").
            "source_file": uploaded.name,
        },
    )


@login_required
@require_POST
def import_commit(request):
    """Re-validate the posted rows and write them."""
    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": _ROWS_NOT_RECEIVED},
        )

    # Re-enforce the row cap on COMMIT, not just on preview. `rows_json` is a
    # hidden field the browser posts back, so a logged-in user can hand-edit it
    # to submit far more rows than the upload parser allowed. The upload cap is
    # meaningless if commit does not check it too.
    if len(rows) > importer.MAX_ROWS:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": importer.row_cap_message(len(rows))},
        )

    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": _ROWS_NOT_RECEIVED},
        )

    # Re-derive the mapping and re-validate from scratch. The preview's verdict
    # is never trusted: between preview and commit another operator may have
    # added the very sampling point a row was rejected for, or the duplicate a
    # row is about to become.
    columns = list(rows[0].keys())
    mapping = importer.auto_map_columns(columns)
    validated = importer.validate_rows(rows, mapping)
    counts = importer.commit_rows(
        validated,
        source_file=(request.POST.get("source_file", "") or "").strip()[:255],
    )
    # After the commit, so a file that lands nothing still records the agency
    # it names for the system its rows resolved to (146-04 Task 3).
    agency = importer.record_regulating_agency(rows, mapping, validated)

    skipped = [
        {"index": item["index"] + 2, "errors": item["errors"]}
        for item in validated
        if item["errors"]
    ]

    return render(
        request,
        "drinking/partials/_import_result.html",
        {
            "counts": counts,
            "on_file": counts["duplicates"] - counts["repeats"],
            "skipped": skipped,
            "total": len(validated),
            "agency": agency,
        },
    )
