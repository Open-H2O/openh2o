# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app team management (ISS-021, 41-02).

A deliberately small Users area so non-technical district staff never have to
touch the developer-facing Django back-end (/admin/). It manages exactly two
states per user -- administrator-or-not and active-or-not -- not a general RBAC
scheme (the dormant Role/UserRole models are DEPRECATED; see core.models).

Every view stacks @login_required + @admin_required, so the whole area rides the
same ACCESS_CONTROL_ENFORCED master switch as the rest of Phase 41: invisible
while the switch is OFF for the demo, admin-only once it flips at go-live.

Two lock-out guards run on every state change:
  - self-guard: you can't strip your own admin or deactivate your own account.
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
from core.forms import UserCreateForm
from core.identifiers import jsonld_for, resolve
from core.models import User


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
    """List every user with role (Administrator / Operator) and active state."""
    users = User.objects.all().order_by("first_name", "last_name", "email")
    return render(request, "core/users_list.html", {"users": users})


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
def user_toggle_admin(request, pk):
    """Grant or revoke agency_admin on another non-staff user."""
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "You can't change your own administrator status.")
        return redirect("core:users_list")
    # Django staff/superusers get their admin status from is_staff, which is
    # managed in the developer back-end, not here. Toggling agency_admin on them
    # would be a confusing no-op for access.
    if target.is_staff:
        messages.error(
            request,
            "That user is a system administrator; manage them in the Django admin.",
        )
        return redirect("core:users_list")
    if target.is_administrator and _administrators().count() <= 1:
        messages.error(request, "You can't remove the last administrator.")
        return redirect("core:users_list")
    target.agency_admin = not target.agency_admin
    target.save(update_fields=["agency_admin"])
    role = "an administrator" if target.agency_admin else "an operator"
    messages.success(request, f"{target.email} is now {role}.")
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
