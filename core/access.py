# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two-tier access control: one rule, one master switch.

This module is the single home for "who counts as an administrator" plus the
switch-aware ``admin_required`` decorator that gates the dangerous screens
(Setup Wizard, Methodology). It lives in ``core`` rather than any one app's
views because several apps now share the same gate.

The master switch is ``settings.ACCESS_CONTROL_ENFORCED`` (default ``True``):

  - OFF: the decorator is a pass-through for any logged-in user, so the
    hosted demonstration behaves exactly as it did before this module existed.
  - ON (default): enforce the two-tier model; only administrators reach gated
    screens. See ISS-021.

The third role, Viewer (147-02), is enforced by :class:`ReadOnlyMiddleware`
below, and holds whichever way the switch is set.
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


def public_in_open_demo(view_func):
    """``login_required``, except when this deployment is an open demonstration.

    ``ACCESS_CONTROL_ENFORCED=False`` is the documented open-demo posture (the
    live openh2o.com instance): a visitor evaluating the platform may browse
    without an account. On an agency deployment — the default, ``True`` —
    these views require login exactly as they always did.

    Apply this ONLY to read-only surfaces a prospect needs in order to
    evaluate the platform: the Help explainers, the glossary, the map page
    and the GeoJSON layers that draw it. Never apply it to a view that
    writes, or that exposes per-user data.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not settings.ACCESS_CONTROL_ENFORCED:
            return view_func(request, *args, **kwargs)
        user = request.user
        if getattr(user, "is_authenticated", False) and user.is_active:
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path())

    return _wrapped


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


# -- The Viewer role (147-02) ----------------------------------------------------

#: Methods that change something. A viewer's request with any other method
#: (GET, HEAD, OPTIONS) goes through untouched.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: URL names a viewer may still POST to: their own sign-in and account, the
#: feedback button, the sidebar density switch and their own contact details.
#: None of them changes a record. Matched by URL NAME, never by path, so a
#: moved route cannot quietly fall out of (or into) the list.
#: ``tests/test_viewer_role.py`` pins this set.
VIEWER_ALLOWED_URL_NAMES = frozenset(
    {"feedback:submit", "set_nav_mode", "profile"}
)

#: allauth's own account views (sign out, password change, email addresses,
#: re-authentication) are all named ``account_*``; every one of them is about
#: the viewer's own sign-in.
VIEWER_ALLOWED_URL_NAME_PREFIX = "account_"

READ_ONLY_MESSAGE = (
    "Your account can read but not change records. An administrator can "
    "change your role on the Users page."
)


def is_viewer(user):
    """True for a signed-in, active account holding the Viewer role."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and getattr(user, "read_only", False)
    )


def viewer_may_post(view_name):
    """Whether a viewer's unsafe request to ``view_name`` goes through."""
    if not view_name:
        return False
    if view_name in VIEWER_ALLOWED_URL_NAMES:
        return True
    return view_name.startswith(VIEWER_ALLOWED_URL_NAME_PREFIX)


class ReadOnlyMiddleware:
    """Refuse every unsafe request a viewer makes, on every route.

    Sits after authentication. Deliberately independent of
    ``ACCESS_CONTROL_ENFORCED``: that switch opens the administrator screens
    on the hosted demonstration, but a viewer is an explicit assignment by an
    administrator, so it holds on every deployment. Covers ``/admin/`` and
    every HTMX endpoint too, because it runs before any view.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in UNSAFE_METHODS and is_viewer(
            getattr(request, "user", None)
        ):
            from django.urls import Resolver404, resolve

            try:
                view_name = resolve(request.path_info).view_name
            except Resolver404:
                view_name = ""
            if not viewer_may_post(view_name):
                return read_only_response(request)
        return self.get_response(request)


def read_only_response(request):
    """The 403 page a viewer sees for a refused change."""
    from django.shortcuts import render

    return render(
        request,
        "403_read_only.html",
        {"read_only_message": READ_ONLY_MESSAGE},
        status=403,
    )
