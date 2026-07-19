# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django template context processors that inject site-wide values everywhere.

Each function returns a dict merged into every template's context: site config,
access-control/admin flags for sidebar gating, a fresh-install setup prompt, and
opt-in Umami analytics and in-app feedback endpoints.
"""
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


def nav_mode(request):
    """Operations (default) vs Admin sidebar density.

    Operations mode shows only the everyday working tools and hides the
    Administration section (accounts, water years, allocations, zones, users,
    methodology, delivery settings, site health, setup). One click flips to
    Admin to bring the configuration tools back. Cookie-backed so the choice
    survives logout without needing a DB migration; unknown values fall back to
    the safe default.
    """
    mode = request.COOKIES.get("nav_mode", "operations")
    if mode not in ("operations", "admin"):
        mode = "operations"
    return {"nav_mode": mode}


def modules(request):
    """Expose the enabled-module list and the composed nav to every template.

    ``nav_sections`` is the sidebar rebuilt from the registry: sections in
    display order, each carrying its ordered entries. Visibility is deliberately
    NOT evaluated here — every entry carries its predicate key (``always``,
    ``admin_mode``, ``agency_admin``, ``setup_gate``) and the template applies
    it, exactly as the hand-written sidebar does today.

    ``module_dashboard_cards`` is the flat list of template partials the enabled
    modules contribute to the overview dashboard, in registry order. It is empty
    on a default deployment — no module ships a dashboard card today, and the
    honest answer for a module without one is nothing at all rather than an
    invented tile. Phase 78's drinking-water module adds the first real entry.
    """
    from core.modules import dashboard_cards_for, enabled_modules, nav_sections_for

    specs = enabled_modules()
    return {
        "enabled_modules": [spec.name for spec in specs],
        "nav_sections": nav_sections_for(specs),
        "module_dashboard_cards": dashboard_cards_for(specs),
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


def feedback(request):
    """Expose whether the in-app feedback widget should render. The widget now
    POSTs to the platform's own intake endpoint, so it works on any deployment;
    FEEDBACK_ENABLED (default True) just lets a deployment hide the button. The
    optional downstream forward (FEEDBACK_ENDPOINT) is handled server-side and
    is intentionally not exposed to templates."""
    return {"feedback_enabled": settings.FEEDBACK_ENABLED}


def app_version(request):
    """Expose the build version (git describe, baked into the image at build time)
    to templates, so the footer can name the exact commit a deployment is running —
    the first question on any bug report. "dev" for un-stamped local builds."""
    return {"app_version": settings.APP_VERSION}
