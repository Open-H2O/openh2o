# SPDX-License-Identifier: AGPL-3.0-or-later
"""Project-specific system checks — warnings written in this platform's own words.

Django already emits ``security.W018`` for ``DEBUG=True``. A clean-room
deployment read that warning, recognised it as Django's standard output, and
carried on running an agency-shaped instance on development settings. Generic
wording earns that response.

``openh2o.W001`` says the same thing in terms an operator of THIS platform can
act on: which settings module they are on, what ``DEBUG=True`` actually exposes,
and the supported single-computer posture that replaces it — production settings
with the three plain-HTTP flips, which is what ``docs/AI-OPERATOR-GUIDE.md``
Phase 2 already documents.

**It is a Warning and never an Error.** The whole test suite runs pinned to
``config.settings.local``; an ``Error`` would fail ``manage.py check``, break CI
and block every developer. The point is a message somebody can act on, not a
blocked workflow.
"""

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.db import DatabaseError

#: Stable id. Django reserves ``security.*``, ``models.*`` and friends for
#: itself, so project checks live under the project's own namespace.
DEBUG_WARNING_ID = "openh2o.W001"

#: The site-identity placeholder warning (ISS-125).
SITE_IDENTITY_WARNING_ID = "openh2o.W002"


def check_development_settings_in_use(app_configs, **kwargs):
    """Warn, in this platform's own words, when development settings are live."""
    if not settings.DEBUG:
        return []

    return [
        CheckWarning(
            "Development settings are running (DEBUG=True). This is "
            "config.settings.local, which is for working on the code — not for "
            "holding an agency's records.",
            hint=(
                "DEBUG=True prints the site's internals — stack traces, "
                "settings, SQL queries — onto any error page, to whoever is "
                "looking at it. The supported posture for a real deployment, "
                "including one that only ever serves a single computer, is "
                "DJANGO_SETTINGS_MODULE=config.settings.production with "
                "SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE and "
                "CSRF_COOKIE_SECURE set to False in .env when there is no "
                "HTTPS to redirect to. Production settings keep DEBUG off, "
                "require a real ALLOWED_HOSTS and a strong database password, "
                "and still work on one computer. See docs/AI-OPERATOR-GUIDE.md, "
                "Phase 2 ('Secure it'), step 3."
            ),
            id=DEBUG_WARNING_ID,
        )
    ]


def check_site_identity_is_set(app_configs, **kwargs):
    """Warn while the platform is still introducing itself as ``example.com``.

    ``DEPLOY.md`` §10 already tells every operator to run ``manage.py check``,
    which makes this the last place the platform can catch the defect before a
    recipient does. The message therefore names the consequence — the subject
    line of outbound mail — rather than the database row.

    Reading a row inside a system check is deliberate but guarded: ``check``
    runs on a fresh clone before ``migrate`` has created a single table, and a
    check that crashes there would block the very command that reports it.
    """
    from core.site_identity import PLACEHOLDER

    try:
        from django.contrib.sites.models import Site

        site = Site.objects.filter(pk=settings.SITE_ID).first()
    except DatabaseError:
        # No database yet, or no sites table yet. Nothing to report and
        # nothing worth failing over.
        return []

    if site is None or PLACEHOLDER not in (site.name, site.domain):
        return []

    return [
        CheckWarning(
            "This deployment is still introducing itself as 'example.com'. "
            "Every email it sends — including every password reset — goes out "
            f"with '[{PLACEHOLDER}]' at the front of the subject line, to "
            "whoever asked for it.",
            hint=(
                "The name and web address are worked out from settings this "
                "platform already holds: the agency name from the Setup "
                "Wizard, and the web address from ALLOWED_HOSTS in .env. Fill "
                "in whichever is still blank, then run "
                "'docker compose exec web python manage.py migrate' — that is "
                "what applies it. See DEPLOY.md, section 10."
            ),
            id=SITE_IDENTITY_WARNING_ID,
        )
    ]
