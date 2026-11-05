# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django template context processors that inject site-wide values everywhere.

Each function returns a dict merged into every template's context: site config,
access-control/admin flags for the Settings button and page, whether Google sign-in exists on
this deployment, a fresh-install setup prompt, and opt-in Umami analytics and
in-app feedback endpoints.
"""
from django.conf import settings

from core.access import is_administrator, is_viewer
from core.models import SiteConfig


def site_config(request):
    return {"site_config": SiteConfig.objects.first()}


def access_flags(request):
    """Expose the access-control switch + the viewer's admin status to templates.

    Drives the Settings button, the Settings page's rows and the write controls:
      - ``access_enforced`` mirrors the ACCESS_CONTROL_ENFORCED master switch.
      - ``user_is_admin`` is the anonymous-safe two-tier check (core.access).
      - ``user_can_write`` is False for a Viewer (read-only) account and on a past reading;
        every control that changes a record sits inside it.

    The Settings page's admin-only rows (Users, Methodology, Delivery Settings)
    show only when ``user_is_admin``; the Setup Wizard row is visible to everyone
    while the switch is OFF, then narrows to admins once it flips.
    """
    return {
        "access_enforced": settings.ACCESS_CONTROL_ENFORCED,
        "user_is_admin": is_administrator(getattr(request, "user", None)),
        # A past reading (core.as_of_views) has no writing controls, as a Viewer has none.
        "user_can_write": not is_viewer(getattr(request, "user", None))
        and getattr(request, "as_of_reading", None) is None,
        "site_sends_email": site_sends_email(),
    }


def as_of_flags(request):
    """What the as-of line, the box and a refused date need (set by ``core.as_of_views.reads_as_of``).

    ``as_of_value`` is the date of a reading ("" otherwise); ``as_of_line`` its sentence;
    ``as_of_notice`` the sentence of a date that could not be used; ``as_of_today_href`` the
    same page with ``as_of`` removed and every other parameter kept.
    """
    day = getattr(request, "as_of_day", None)
    query = request.GET.copy() if hasattr(request, "GET") else None
    href = ""
    if query is not None and day is not None:
        query.pop("as_of", None)
        href = request.path + (f"?{query.urlencode()}" if query else "")
    return {
        "as_of_value": day.isoformat() if day else "",
        "as_of_line": getattr(request, "as_of_line", ""),
        "as_of_notice": getattr(request, "as_of_notice", ""),
        "as_of_today_href": href,
    }


#: Email backends that deliver nothing: the console backend prints a message
#: into the server log, the dummy one drops it.
_NO_DELIVERY_BACKENDS = (
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.dummy.EmailBackend",
)


def site_sends_email() -> bool:
    """False on a site with no mail server.

    Production defaults to the SMTP backend, so a site with no EMAIL_HOST would
    show the form and then fail with a 500."""
    if not settings.EMAIL_HOST:
        return False
    return settings.EMAIL_BACKEND not in _NO_DELIVERY_BACKENDS


def _lit_entry(request):
    """The one sidebar entry this request's page lights, or None.

    The path that decides it is ``request.nav_lights_path`` when a view sets
    one (the infrastructure add and import pages name the list they return
    to), else the request's own path. Computed once per request and kept on
    it.
    """
    if not hasattr(request, "_openh2o_nav_lit"):
        from core.modules import enabled_modules, lit_entry, sidebar_entries

        path = getattr(request, "nav_lights_path", None) or getattr(request, "path", "") or ""
        request._openh2o_nav_lit = lit_entry(path, sidebar_entries(enabled_modules()))
    return request._openh2o_nav_lit


def modules(request):
    """Expose the enabled-module list and the composed nav to every template.

    ``nav_sections`` is the sidebar rebuilt from the registry: sections in
    display order, each carrying its ordered entries. Visibility is deliberately
    NOT evaluated here: every entry carries its predicate key (``always``,
    ``agency_admin``, ``setup_gate``) and the template applies it.

    ``module_dashboard_cards`` is the flat list of template partials the enabled
    modules contribute to the overview dashboard, in registry order. It is empty
    when no enabled module contributes a card: a module without one adds
    nothing rather than an invented tile. The drinking-water module contributes
    the one real card.

    ``nav_lit_section_label`` is the heading of the section the lit entry
    belongs to, which the breadcrumb's root repeats. ``drinking_group_open`` is
    whether the sidebar draws the Drinking water group open: the lit entry's
    section when it is drinking water, else the reader's ``sidebar_drinking``
    cookie, else open exactly when water accounting is not enabled.
    """
    from core.modules import (
        NAV_SECTIONS,
        SECTION_DRINKING_WATER,
        dashboard_cards_for,
        enabled_modules,
        nav_sections_for,
    )

    specs = enabled_modules()
    sections = nav_sections_for(specs)
    lit = _lit_entry(request)
    names = [spec.name for spec in specs]
    labels = {section.key: section.label for section in NAV_SECTIONS}
    stored = (getattr(request, "COOKIES", None) or {}).get("sidebar_drinking")
    if lit is not None and lit.section == SECTION_DRINKING_WATER:
        drinking_open = True
    elif stored in ("open", "closed"):
        drinking_open = stored == "open"
    else:
        drinking_open = "accounting" not in names
    return {
        "enabled_modules": names,
        "nav_sections": sections,
        "module_dashboard_cards": dashboard_cards_for(specs),
        # The url_name of the one entry this page lights, and its
        # section key; `_sidebar.html` marks that link active and opens Help
        # when it is one of Help's own.
        "nav_lit": lit.url_name if lit is not None else None,
        "nav_lit_section": lit.section if lit is not None else "",
        "nav_lit_section_label": labels[lit.section] if lit is not None else "",
        "drinking_group_open": drinking_open,
        "page_section": _page_section(lit),
    }


def _page_section(lit):
    """The nav section key this page belongs to, or "" when it belongs to none.

    The section of the entry the page lights, when that entry is a module's
    (the composed deployment's own, so a dropped module never names a section
    with no sidebar). Home and the Help pages light fixed entries, and their
    pages carry no section class.

    Visibility predicates are applied in the template, not here, so an entry
    hidden from THIS viewer still counts. That is deliberate: the value
    describes the page, not the sidebar the viewer happens to see.
    """
    from core.modules import FIXED_NAV_ENTRIES

    if lit is None or lit in FIXED_NAV_ENTRIES:
        return ""
    return lit.section


def setup_status(request):
    """Flag a brand-new install so the dashboard can point an admin at setup.

    ``needs_setup`` is True only when there are zero ``Boundary`` rows — the
    wizard's first output, so "no boundary" unambiguously means "nothing has
    been set up yet". The cheap ``exists()`` query is gated
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
    """Expose Umami config to templates. Both values are blank on a fresh
    clone, so the tracking tag stays absent unless a deployment sets both
    UMAMI_WEBSITE_ID and UMAMI_SCRIPT_URL in its environment."""
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


def source_code(request):
    """The address the footer's "Source code" link points at.

    A value that is not an http:// or https:// address (the openh2o.W003 check
    reports it) is not used: the link keeps the default."""
    from core.checks import is_web_address

    configured = (settings.SOURCE_CODE_URL or "").strip()
    if configured and is_web_address(configured):
        return {"source_code_url": configured}
    return {"source_code_url": settings.SOURCE_CODE_URL_DEFAULT}


def google_sign_in(request):
    """Expose whether Google sign-in actually exists on this deployment.

    ``google_sign_in_available`` is the SAME predicate the URL guards in
    ``config/urls.py`` use (``core.oauth``), which is the point: the button and
    the endpoint cannot drift apart, because there is only one answer to drift.
    Without one shared answer, the templates could read the flag while the
    routes read nothing.

    It is not enough to leave this to the templates' old
    ``site_config.allow_google_oauth`` test. That test rendered
    ``{% provider_login_url 'google' %}`` whenever the flag was on, and with no
    credentials configured the tag raises an uncaught ``SocialApp.DoesNotExist``
    — taking down the whole login page, not just the button on it.
    """
    from core.oauth import google_sign_in_available

    return {"google_sign_in_available": google_sign_in_available()}
