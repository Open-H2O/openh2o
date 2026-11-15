# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import accounts: the Accounts page's bulk action (``accounting/account_import.py``).

The Import use areas page's pattern: the upload is stored and previewed, and Import
starts the commit in its own process (``core/pending_imports.py``).
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from accounting import account_import
from accounting.models import UNIT_KIND_CHOICES, ReportingPeriod
from core import pending_imports

RESULT_TEMPLATE = "accounting/partials/_account_import_result.html"
PREVIEW_TEMPLATE = "accounting/partials/_account_import_preview.html"


@login_required
@require_GET
def account_import_page(request):
    """The page that takes a CSV file of parcel numbers and accounts."""
    return render(request, "accounting/account_import.html")


def _listed(items):
    shown, not_listed = pending_imports.cap_error_rows(items)
    return {"items": shown, "total": len(items), "not_listed": not_listed}


def _preview_context(pending, read, mapping, unit_kind=""):
    rows = read["rows"]
    plan = account_import.plan_accounts(rows, mapping)
    finalized = ReportingPeriod.objects.filter(is_finalized=True).order_by("start_date")
    return {
        "token": pending.token,
        "file_name": pending.original_name,
        "row_count": len(rows),
        "columns": read["columns"],
        "field_rows": [
            {
                "field": field,
                "label": label,
                "required": required,
                "guess": mapping.get(field, ""),
                "sample": account_import.first_values(rows, mapping.get(field, "")),
            }
            for field, label, required in account_import.FIELDS
        ],
        "new_count": len(plan["new_accounts"]),
        "unit_kind": unit_kind,
        "unit_kinds": UNIT_KIND_CHOICES,
        "account_lines": account_import.account_lines(plan),
        "differing_sentence": account_import.differing_sentence(plan) if plan["differing"] else "",
        "differing": _listed(account_import.differing_items(plan)),
        "bad_email_sentence": account_import.bad_email_sentence(plan) if plan["bad_email"] else "",
        "bad_email": _listed(plan["bad_email"]),
        "row_lines": [
            {"count": count, "what": what, "action": action, "listed": _listed(items), "lines": lines}
            for count, what, action, items, lines in account_import.row_lines(plan)
        ],
        "finalized": pending_imports.finalized_sentences(
            list(finalized.values_list("name", flat=True)), "this import changes"
        ),
        "has_work": account_import.has_work(plan),
    }


@login_required
@require_POST
def account_import_preview(request):
    """Read the upload (or the stored file again, with changed matches) and show what Import would do."""
    uploaded = request.FILES.get("file")
    if uploaded:
        try:
            pending, read = pending_imports.receive(request, "accounts", uploaded, account_import.read_file)
        except ImportError as exc:
            return render(request, RESULT_TEMPLATE, {"error": str(exc)})
        mapping = account_import.auto_map(read["columns"])
    elif request.POST.get("token"):
        pending = pending_imports.previewed(request, "accounts")
        if pending is None:
            return pending_imports.refused(request, "accounts")
        try:
            with pending_imports.stored_file(pending) as file:
                read = account_import.read_file(file)
        except FileNotFoundError:
            return pending_imports.refused(request, "accounts")
        except ImportError as exc:
            return render(request, RESULT_TEMPLATE, {"error": str(exc)})
        mapping = account_import.posted_mapping(request.POST, read["columns"])
    else:
        return render(request, RESULT_TEMPLATE, {"error": account_import.NO_FILE_MESSAGE})
    return render(
        request, PREVIEW_TEMPLATE, _preview_context(pending, read, mapping, request.POST.get("unit_kind", ""))
    )


@login_required
@require_POST
def account_import_commit(request):
    """Start writing the stored file with the confirmed matches and account type."""
    unit_kind = request.POST.get("unit_kind", "")
    pending = pending_imports.previewed(request, "accounts")
    if pending is not None and unit_kind not in dict(UNIT_KIND_CHOICES):
        try:
            with pending_imports.stored_file(pending) as file:
                read = account_import.read_file(file)
        except (FileNotFoundError, ImportError):
            return pending_imports.refused(request, "accounts")
        mapping = account_import.posted_mapping(request.POST, read["columns"])
        if account_import.plan_accounts(read["rows"], mapping)["new_accounts"]:
            context = _preview_context(pending, read, mapping)
            context["type_error"] = account_import.NO_TYPE_MESSAGE
            return render(request, PREVIEW_TEMPLATE, context)
    mapping = {
        field: request.POST.get(f"map:{field}", "") for field, _, _ in account_import.FIELDS
    }
    return pending_imports.start_import(request, "accounts", {"mapping": mapping, "unit_kind": unit_kind})
