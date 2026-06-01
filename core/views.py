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
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.access import admin_required
from core.forms import UserCreateForm
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
