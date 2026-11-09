# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import the state's sampling schedule: choose a file, preview, press Import."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import pending_imports
from drinking import schedule_import as schedule_import_service
from drinking.models import WaterSystem

_RESULT = "drinking/partials/_schedule_import_result.html"
_NO_SYSTEM = "This site has no water system yet. Add a water system first."


def _system():
    return WaterSystem.objects.order_by("pwsid").first()


def _parse_stored(pending):
    """The stored schedule file, read again: (columns, rows)."""
    with pending_imports.stored_file(pending) as file:
        return schedule_import_service.parse_csv(file, pending.original_name)


def _listed(plan):
    """The plan as the preview and the result show it, error rows capped."""
    errors, not_listed = pending_imports.cap_error_rows(plan["errors"])
    return {
        "row_count": plan["row_count"],
        "new_count": len(plan["new"]),
        "changed_count": len(plan["changed"]),
        "unchanged_count": plan["unchanged"],
        "repeat_count": plan["repeats"],
        "error_count": len(plan["errors"]),
        "errors": errors,
        "errors_not_listed": not_listed,
        "changes": [
            {
                "point": schedule_import_service.point_text(entry["existing"]),
                "label": entry["existing"].label,
                "lines": [
                    f"{field}: {old} to {new}" for field, old, new in entry["changes"]
                ],
            }
            for entry in plan["changed"]
        ],
        "left_out": [
            {
                "point": schedule_import_service.point_text(row),
                "label": row.label,
            }
            for row in plan["left_out"]
        ],
    }


@login_required
@require_GET
def schedule_import_page(request):
    """The upload page."""
    return render(request, "drinking/schedule_import.html", {})


@login_required
@require_POST
def schedule_import_preview(request):
    """Read the upload and show what Import would add and change. Saves no row."""
    system = _system()
    if system is None:
        return render(request, _RESULT, {"error": _NO_SYSTEM})

    uploaded = request.FILES.get("file")
    if not uploaded:
        return render(request, _RESULT, {"error": "Choose a CSV file to upload."})

    try:
        pending, (columns, rows) = pending_imports.receive(
            request,
            "schedule",
            uploaded,
            lambda file: schedule_import_service.parse_csv(file, uploaded.name),
        )
    except ImportError as exc:
        return render(request, _RESULT, {"error": str(exc)})

    missing = schedule_import_service.missing_columns(columns)
    if missing:
        pending_imports.discard(pending)
        return render(
            request,
            _RESULT,
            {"error": schedule_import_service.missing_columns_message(missing)},
        )

    plan = schedule_import_service.import_schedule_rows(
        columns, rows, system=system, dry_run=True
    )
    context = _listed(plan)
    context["token"] = pending.token
    return render(request, "drinking/partials/_schedule_import_preview.html", context)


def commit_stored_schedule(pending):
    """Write the stored schedule file; the result block's context.

    Runs in the import worker (core/pending_imports.py).
    """
    system = _system()
    if system is None:
        return {"error": _NO_SYSTEM}
    try:
        columns, rows = _parse_stored(pending)
        plan = schedule_import_service.import_schedule_rows(
            columns, rows, system=system, dry_run=False
        )
    except ImportError as exc:
        return {"error": str(exc)}
    context = _listed(plan)
    context["added_count"] = plan["added"]
    context["changed_count"] = plan["changed_count"]
    return context


@login_required
@require_POST
def schedule_import_commit(request):
    """Start writing the stored file."""
    return pending_imports.start_import(request, "schedule", {})
