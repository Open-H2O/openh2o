# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings

from core.access import is_administrator
from core.models import SiteConfig


def site_config(request):
    return {"site_config": SiteConfig.objects.first()}


def access_flags(request):
    """Expose the access-control switch + the viewer's admin status to templates.

    Drives the admin-only sidebar grouping (ISS-021, 41-02):
      - ``access_enforced`` mirrors the ACCESS_CONTROL_ENFORCED master switch.
      - ``user_is_admin`` is the anonymous-safe two-tier check (core.access).

    Admin-only links (Users, Methodology) show only when ``user_is_admin``; the
    Setup Wizard stays visible to everyone while the switch is OFF so the demo's
    navigation is byte-for-byte unchanged, then narrows to admins once it flips.
    """
    return {
        "access_enforced": settings.ACCESS_CONTROL_ENFORCED,
        "user_is_admin": is_administrator(getattr(request, "user", None)),
    }


def setup_status(request):
    """Flag a brand-new install so the dashboard can point an admin at setup.

    ``needs_setup`` is True only when there are zero ``Boundary`` rows — the
    wizard's first output, so "no boundary" unambiguously means "nothing has
    been set up yet" (Phase 48 / ISS-046). The cheap ``exists()`` query is gated
    to viewers who can actually run setup — admins, or anyone while the access
    switch is OFF — mirroring the Setup Wizard's own sidebar visibility rule. So
    a read-only operator on an enforced deployment never triggers the extra query
    and never sees a call-to-action they cannot act on.
    """
    user = getattr(request, "user", None)
    can_run_setup = (not settings.ACCESS_CONTROL_ENFORCED) or is_administrator(user)
    needs_setup = False
    if can_run_setup and getattr(user, "is_authenticated", False):
        from geography.models import Boundary

        needs_setup = not Boundary.objects.exists()
    return {"needs_setup": needs_setup}


def analytics(request):
    """Expose Umami config to templates. Both values are blank/default on a
    fresh clone, so the tracking tag stays absent unless a deployment opts in
    by setting UMAMI_WEBSITE_ID in its environment."""
    return {
        "umami_website_id": settings.UMAMI_WEBSITE_ID,
        "umami_script_url": settings.UMAMI_SCRIPT_URL,
    }
