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


def analytics(request):
    """Expose Umami config to templates. Both values are blank/default on a
    fresh clone, so the tracking tag stays absent unless a deployment opts in
    by setting UMAMI_WEBSITE_ID in its environment."""
    return {
        "umami_website_id": settings.UMAMI_WEBSITE_ID,
        "umami_script_url": settings.UMAMI_SCRIPT_URL,
    }
