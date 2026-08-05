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

#: Stable id. Django reserves ``security.*``, ``models.*`` and friends for
#: itself, so project checks live under the project's own namespace.
DEBUG_WARNING_ID = "openh2o.W001"


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
