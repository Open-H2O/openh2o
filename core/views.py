# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app team management (ISS-021, 41-02).

A deliberately small Users area so non-technical district staff never have to
touch the developer-facing Django back-end (/admin/). It manages exactly two
things per user -- a role of three (administrator, operator or viewer; 147-02)
and active-or-not -- not a general RBAC scheme (the dormant Role/UserRole
models are DEPRECATED; see core.models).

Every view stacks @login_required + @admin_required, so the whole area rides the
same ACCESS_CONTROL_ENFORCED master switch as the rest of Phase 41: invisible
while the switch is OFF for the demo, admin-only once it flips at go-live.

Two lock-out guards run on every state change:
  - self-guard: you can't change your own role or deactivate your own account.
  - last-admin guard: the final administrator can't be demoted or deactivated,
    so the platform can never end up with no one who can reach the admin screens.
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST, require_safe

from core.access import admin_required
from core.forms import (
    ROLE_ADMINISTRATOR,
    ROLE_CHOICES,
    UserCreateForm,
    UserRoleForm,
    apply_role,
    role_of,
)
from core.identifiers import jsonld_for, resolve
from core.models import User


ROLE_SENTENCES = {
    "administrator": "an administrator",
    "operator": "an operator",
    "viewer": "a viewer (read only)",
}


def _administrators():
    """Users who currently satisfy User.is_administrator, at the DB level.

    Mirrors the property (active AND (is_staff OR agency_admin)) as a queryset so
    the last-admin guard can count without pulling every row into Python.
    """
    return User.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(agency_admin=True)
    )


@login_required
@admin_required
def users_list(request):
    """List every user with role (Administrator / Operator / Viewer) and state."""
    users = list(User.objects.all().order_by("first_name", "last_name", "email"))
    for user in users:
        user.role_value = role_of(user)
    return render(
        request,
        "core/users_list.html",
        {"users": users, "role_choices": ROLE_CHOICES},
    )


@login_required
@admin_required
def user_create(request):
    """Add a user who can then sign in by email (password set by the admin)."""
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Added {user.email}.")
            return redirect("core:users_list")
    else:
        form = UserCreateForm()
    return render(request, "core/user_form.html", {"form": form})


@login_required
@admin_required
@require_POST
def user_set_role(request, pk):
    """Make another non-staff user an administrator, an operator or a viewer.

    One control of three (147-02) in place of the old administrator toggle.
    The change is recorded in the change history by the User tracking
    (147-01), with the administrator who made it.
    """
    target = get_object_or_404(User, pk=pk)
    form = UserRoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a role: administrator, operator or viewer.")
        return redirect("core:users_list")
    if target == request.user:
        messages.error(request, "You can't change your own role.")
        return redirect("core:users_list")
    # Django staff/superusers get their admin status from is_staff, which is
    # managed in the developer back-end, not here. Changing agency_admin on
    # them would be a confusing no-op for access.
    if target.is_staff:
        messages.error(
            request,
            "That user is a system administrator; manage them in the Django admin.",
        )
        return redirect("core:users_list")
    role = form.cleaned_data["role"]
    if (
        role != ROLE_ADMINISTRATOR
        and target.is_administrator
        and _administrators().count() <= 1
    ):
        messages.error(request, "You can't remove the last administrator.")
        return redirect("core:users_list")
    target.save(update_fields=apply_role(target, role))
    messages.success(request, f"{target.email} is now {ROLE_SENTENCES[role]}.")
    return redirect("core:users_list")


@login_required
@admin_required
@require_POST
def user_toggle_active(request, pk):
    """Deactivate or reactivate another user's account."""
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("core:users_list")
    if target.is_active and target.is_administrator and _administrators().count() <= 1:
        messages.error(request, "You can't deactivate the last administrator.")
        return redirect("core:users_list")
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    state = "reactivated" if target.is_active else "deactivated"
    messages.success(request, f"{target.email} {state}.")
    return redirect("core:users_list")


# ---------------------------------------------------------------------------
# Persistent identifiers (146-06 Task 1, ISS-019)
# ---------------------------------------------------------------------------
#
# Not part of the Users area above: it lives here because `core` is the one
# module every deployment runs, and the address has to answer whatever set of
# modules is switched on. The route is top-level (`/id/`, config/urls.py)
# because core's own prefix is `users/`. It is deliberately NOT behind sign-in:
# the address is the thing a harvester and a colleague cite, and the document
# carries a record's name, geometry and crosswalk identifiers only.

JSONLD_TYPE = "application/ld+json"


def _wants_jsonld(request):
    """JSON-LD on ``?format=jsonld`` or when the Accept header prefers it.

    Quality values are read, not just the type names: Geoconnex's harvester
    sends ``application/ld+json;q=1.0, text/html;q=0.8`` (146-06-EVIDENCE-T1.md),
    which names both. ``text/html`` is listed first so a tie (a bare ``*/*``,
    or no header at all) goes to the page, the way a geoconnex.us address
    itself answers.
    """
    if request.GET.get("format") == "jsonld":
        return True
    return request.get_preferred_type(["text/html", JSONLD_TYPE]) == JSONLD_TYPE


@require_safe
def persistent_identifier(request, kind, pk):
    """``/id/<kind>/<pk>/``: 303 to the record's page, or its JSON-LD.

    Every answer, a miss included, varies on Accept, so a cache in front of
    the site never hands a browser the machine's document or the reverse. A
    miss is plain text naming why (the kind, the module, or the row), because
    the site's 404 page deliberately shows no detail.
    """
    try:
        record = resolve(kind, pk)
    except Http404 as exc:
        response = HttpResponseNotFound(
            f"{exc}\n", content_type="text/plain; charset=utf-8"
        )
    else:
        if _wants_jsonld(request):
            response = HttpResponse(
                json.dumps(jsonld_for(record, request), indent=2),
                content_type=JSONLD_TYPE,
            )
        else:
            response = HttpResponseRedirect(record.get_absolute_url())
            response.status_code = 303
    patch_vary_headers(response, ["Accept"])
    return response


# -- Change history (147-01) ----------------------------------------------------


def _parse_date(value):
    import datetime as dt

    try:
        return dt.date.fromisoformat((value or "").strip())
    except ValueError:
        return None


@login_required
@require_safe
def change_history(request):
    """Every recorded change, newest first, 50 to a page (147-01, ISS-177).

    Readable by everyone signed in, whatever their role: the record of who
    changed a figure is not an administrator's private file. Filters: record
    type, person (or commands), date range, and one record (the History panel's
    "See all" link). ``core/changes.py`` builds the rows.
    """
    from core import changes

    record_type = request.GET.get("type", "")
    person = request.GET.get("person", "")
    since = _parse_date(request.GET.get("from"))
    until = _parse_date(request.GET.get("to"))
    object_id = request.GET.get("record", "")
    filters = changes.build_filters(
        record_type=record_type,
        person=person,
        since=since,
        until=until,
        object_id=int(object_id) if object_id.isdigit() else None,
    )
    page = changes.recent_changes(filters, page=request.GET.get("page") or 1)

    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "core/changes.html",
        {
            "page_obj": page,
            "record_types": changes.record_types(),
            "people": changes.people_choices(),
            "command_filter": changes.COMMAND_FILTER,
            "record_type": filters.get("record_type", ""),
            "person": person,
            "since": since.isoformat() if since else "",
            "until": until.isoformat() if until else "",
            "record_filtered": "object_id" in filters,
            "record_has_links": "object_id" in filters
            and bool(changes.related_records(filters["record_type"])),
            "querystring": query.urlencode(),
        },
    )
