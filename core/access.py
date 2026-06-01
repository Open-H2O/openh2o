# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two-tier access control: one rule, one master switch.

This module is the single home for "who counts as an administrator" plus the
switch-aware ``admin_required`` decorator that gates the dangerous screens
(Setup Wizard, Methodology). It lives in ``core`` rather than any one app's
views because several apps now share the same gate.

The master switch is ``settings.ACCESS_CONTROL_ENFORCED`` (default ``False``):

  - OFF (default): the decorator is a pass-through for any logged-in user, so
    the live demo behaves exactly as it did before this module existed.
  - ON: enforce the two-tier model — only administrators reach gated screens.

Flip the switch to ``True`` at go-live. See ISS-021.
"""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def is_administrator(user):
    """Anonymous-safe mirror of ``User.is_administrator``.

    Returns True only for an active, authenticated user who is either Django
    staff/superuser OR carries ``agency_admin=True``. Safe to call on
    ``AnonymousUser`` (returns False) — that is why the decorator uses this
    function rather than the model property.
    """
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and (user.is_staff or getattr(user, "agency_admin", False))
    )


def admin_required(view_func):
    """Gate a view behind the two-tier administrator rule, switch-aware.

    Behavior:
      - anonymous / inactive              → redirect to LOGIN (with ?next=).
      - authenticated + switch OFF        → ALLOW (pass-through; preserves the demo).
      - authenticated + switch ON + admin → ALLOW.
      - authenticated + switch ON + non-admin
            → redirect to the app dashboard with a messages.error.

    Deliberately NOT Django's ``staff_member_required``, which bounces to the
    ``/admin/`` login page; an already-logged-in non-admin should land back in
    the app, not face a second login prompt.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not (getattr(user, "is_authenticated", False) and user.is_active):
            return redirect_to_login(request.get_full_path())
        if not settings.ACCESS_CONTROL_ENFORCED:
            return view_func(request, *args, **kwargs)
        if is_administrator(user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "That screen is for administrators.")
        return redirect("accounting:dashboard")

    return _wrapped
