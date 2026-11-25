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

from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.core.checks import register
from django.db import DatabaseError

#: Stable id. Django reserves ``security.*``, ``models.*`` and friends for
#: itself, so project checks live under the project's own namespace.
DEBUG_WARNING_ID = "openh2o.W001"

#: The site-identity placeholder warning.
SITE_IDENTITY_WARNING_ID = "openh2o.W002"

#: The source-code link setting.
SOURCE_CODE_URL_WARNING_ID = "openh2o.W003"


def is_web_address(value):
    """True for an http:// or https:// address with a host."""
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def check_development_settings_in_use(app_configs, **kwargs):
    """Warn, in this platform's own words, when development settings are live."""
    if not settings.DEBUG:
        return []

    return [
        CheckWarning(
            "The development settings (config.settings.local, DEBUG=True) are "
            "running, so any error page shows the site's internals (stack traces, "
            "settings and SQL queries) to whoever is looking at it.",
            hint=(
                "A real deployment runs DJANGO_SETTINGS_MODULE=config.settings.production, "
                "and so does a deployment that serves only a single computer. The "
                "production settings keep DEBUG off. They refuse to start while "
                "ALLOWED_HOSTS is empty. They also refuse to start while the database "
                "password is empty or is one of openh2o, postgres, password or changeme. "
                "Where the site does not have HTTPS (only this computer or the office "
                "network), turn off SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE and "
                "CSRF_COOKIE_SECURE in .env and add OPENH2O_FORWARDED_PROTO=http. Each "
                "change is in docs/AI-OPERATOR-GUIDE.md, Phase 2 (\"Secure it\"). Step 1 "
                "covers the database password and the secret key. Step 2 covers "
                "ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS. Step 3 covers HTTPS and the three "
                "settings that depend on HTTPS, and gives the lines for a site without HTTPS."
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
            "This deployment is still introducing itself as 'example.com'. Every email "
            "the site sends starts its subject line with the site's name in brackets, "
            f"so while the name is '{PLACEHOLDER}', every email starts with "
            f"'[{PLACEHOLDER}]', password resets included.",
            hint=(
                "The site's name comes from the organization's name. Set the "
                "organization's name with 'docker compose exec web python "
                "manage.py set_organization --name' followed by the name. The "
                "site's address comes from ALLOWED_HOSTS in .env. A site used "
                "only on its own computer can have localhost as its only "
                "address. After a change to ALLOWED_HOSTS, run 'docker compose "
                "exec web python manage.py migrate'. The migrations replace the "
                "placeholder address example.com with the address from "
                "ALLOWED_HOSTS. See section 10 of DEPLOY.md."
            ),
            id=SITE_IDENTITY_WARNING_ID,
        )
    ]


# Registered here, where the check is defined, so the module that loads this
# file needs no second line for it.
@register()
def check_source_code_url(app_configs, **kwargs):
    """Warn when SOURCE_CODE_URL is set and is not a web address.

    The footer link then keeps the default, so the page is never left with a link
    that goes nowhere or runs script. An empty value counts as not set."""
    if not settings.SOURCE_CODE_URL or is_web_address(settings.SOURCE_CODE_URL.strip()):
        return []

    return [
        CheckWarning(
            "SOURCE_CODE_URL is not an http:// or https:// address, so the "
            "Source code link at the foot of every page points at "
            f"{settings.SOURCE_CODE_URL_DEFAULT}.",
            hint=(
                "Set SOURCE_CODE_URL in .env to the full web address of the "
                "repository this site runs from, starting with https://, or remove "
                "the line to use the default."
            ),
            id=SOURCE_CODE_URL_WARNING_ID,
        )
    ]
