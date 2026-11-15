# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Zones page's two bulk actions: Import zones and Assign use areas to zones.

Import zones follows the Import use areas page: the upload is stored and previewed, and
Import starts the commit in its own process (``core/pending_imports.py``). Assign use
areas to zones answers inside the request: at Merced size (8,906 use areas, three zones)
its query takes about 3.4 s.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import pending_imports
from core.modules import is_enabled
from geography import zone_assign, zone_import
from geography.models import Boundary, Zone

ZONE_RESULT_TEMPLATE = "geography/partials/_zone_import_result.html"
ZONE_PREVIEW_TEMPLATE = "geography/partials/_zone_import_preview.html"


@login_required
@require_GET
def zone_import_page(request):
    """The page that takes a map file of zone outlines."""
    return render(request, "geography/zone_import.html")


def _zone_preview_context(pending, read, name_column, zone_type):
    features = read["features"]
    plan = zone_import.plan_zones(features, name_column, zone_type)
    unreadable, unreadable_not_listed = pending_imports.cap_error_rows(plan["unreadable"])
    used, used_not_listed = pending_imports.cap_error_rows(plan["used"])
    return {
        "token": pending.token,
        "file_name": pending.original_name,
        "outline_count": len(features),
        "columns": read["columns"],
        "name_column": name_column,
        "name_sample": zone_import.map_file.first_values(features, name_column),
        "zone_type": zone_type,
        "zone_types": zone_import.zone_types(),
        "new_count": len(plan["new"]),
        "used_count": plan["used_outlines"],
        "used": used,
        "used_total": len(plan["used"]),
        "used_not_listed": used_not_listed,
        "no_name_count": plan["no_name"],
        "unreadable_count": len(plan["unreadable"]),
        "unreadable": unreadable,
        "unreadable_not_listed": unreadable_not_listed,
        "too_long_count": plan["too_long"],
        "name_max_length": zone_import.NAME_MAX_LENGTH,
        "shared": [zone_import.shared_sentence(name, n) for name, n in plan["shared"]],
    }


@login_required
@require_POST
def zone_import_preview(request):
    """Read the upload (or the stored file again, with changed choices) and show what Import would do."""
    if not Boundary.objects.exists():
        return render(request, ZONE_RESULT_TEMPLATE, {"error": zone_import.NO_BOUNDARY_MESSAGE})
    uploaded = request.FILES.get("file")
    if uploaded:
        try:
            pending, read = pending_imports.receive(request, "zones", uploaded, zone_import.read_file)
        except ImportError as exc:
            return render(request, ZONE_RESULT_TEMPLATE, {"error": str(exc)})
    elif request.POST.get("token"):
        pending = pending_imports.previewed(request, "zones")
        if pending is None:
            return pending_imports.refused(request, "zones")
        try:
            with pending_imports.stored_file(pending) as file:
                read = zone_import.read_file(file)
        except FileNotFoundError:
            return pending_imports.refused(request, "zones")
        except ImportError as exc:
            return render(request, ZONE_RESULT_TEMPLATE, {"error": str(exc)})
    else:
        return render(request, ZONE_RESULT_TEMPLATE, {"error": zone_import.NO_FILE_MESSAGE})
    name_column = request.POST.get("name_column", "")
    if name_column not in read["columns"]:
        name_column = zone_import.guess_name_column(read["columns"])
    zone_type = zone_import.valid_zone_type(request.POST.get("zone_type", ""))
    return render(request, ZONE_PREVIEW_TEMPLATE, _zone_preview_context(pending, read, name_column, zone_type))


@login_required
@require_POST
def zone_import_commit(request):
    """Start making the zones of the stored file with the confirmed choices."""
    return pending_imports.start_import(
        request,
        "zones",
        {
            "name_column": request.POST.get("name_column", ""),
            "zone_type": zone_import.valid_zone_type(request.POST.get("zone_type", "")),
        },
    )


# ---------------------------------------------------------------------------
# Assign use areas to zones
# ---------------------------------------------------------------------------

NO_ZONES = "No zones are on file yet. Import zones or add a zone first."
NO_TYPED_ZONES = "No zone has a type yet. Choose each zone's type on its page, then come back."
NO_USE_AREAS = "No use areas are on file yet. Import use areas first."
NOTHING_TO_ASSIGN = "Every use area is already in a zone of this type or outside every zone."
EACH_ASSIGNMENT = "Each assignment holds for every water year, past years included."


def _assign_context(request, zone_type_param):
    types = zone_assign.types_with_zones()
    context = {"types": types, "zone_type": "", "message": ""}
    if not Zone.objects.exists():
        context["message"] = NO_ZONES
        return context
    if not types:
        context["message"] = NO_TYPED_ZONES
        return context
    from parcels.models import Parcel

    if not is_enabled("parcels") or not Parcel.objects.current().exists():
        context["message"] = NO_USE_AREAS
        return context
    values = [value for value, _ in types]
    context["zone_type"] = zone_type_param if zone_type_param in values else values[0]
    return context


def _listed(items):
    shown, not_listed = pending_imports.cap_error_rows(items)
    return {"items": shown, "total": len(items), "not_listed": not_listed}


@login_required
def zones_assign(request):
    """Assign use areas to zones: GET shows what Assign would do; POST assigns."""
    zone_type = request.POST.get("zone_type") if request.method == "POST" else request.GET.get("zone_type", "")
    context = _assign_context(request, zone_type)
    if context["zone_type"]:
        planned = zone_assign.plan(context["zone_type"])
        if request.method == "POST":
            created = zone_assign.assign(planned)
            context["result"] = zone_assign.result_sentence(created)
            if planned["outside"]:
                context["result_outside"] = zone_assign.outside_sentence(len(planned["outside"]))
        else:
            context.update(
                {
                    "per_zone": [
                        {"count": row["count"], "what": zone_assign.use_areas(row["count"]),
                         "action": f"Assigned to {row['zone'].name}"}
                        for row in planned["per_zone"]
                    ],
                    "outside_count": len(planned["outside"]),
                    "outside_what": f"{zone_assign.use_areas(len(planned['outside']))} outside every zone",
                    "outside": _listed(planned["outside"]),
                    "already_count": planned["already"],
                    "already_what": f"{zone_assign.use_areas(planned['already'])} already in a zone of this type",
                    "across_sentence": zone_assign.across_sentence(len(planned["across"]), planned["to_assign"])
                    if planned["across"] else "",
                    "across": _listed(planned["across"]),
                    "to_assign": planned["to_assign"],
                    "to_assign_what": zone_assign.use_areas(planned["to_assign"]),
                    "each_assignment": EACH_ASSIGNMENT,
                    "finalized": pending_imports.finalized_sentences(zone_assign.finalized_year_names(), "these assignments change"),
                    "nothing": NOTHING_TO_ASSIGN if not planned["to_assign"] else "",
                }
            )
    return render(request, "geography/zones_assign.html", context)
