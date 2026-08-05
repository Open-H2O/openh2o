# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the platform's own name and web address come from (ISS-125).

Every message django-allauth sends is subject-prefixed with the current
``Site`` row's **name**. ``config/settings/base.py`` sets ``SITE_ID = 1`` and
nothing has ever populated that row, so it still holds the two values Django
ships in its own migration — ``example.com`` for both name and domain — and
every password-reset email openh2o.com has ever sent went out titled
``[example.com]``.

**Derived, never configured.** There is deliberately no
``OPENH2O_SITE_DOMAIN`` environment variable. The operators are water-district
engineers who will not know such a setting exists, let alone that a wrong value
shows up in a stranger's inbox. The platform already holds both facts:
``SiteConfig.agency_name`` is the agency's own name, typed into the setup
wizard, and ``ALLOWED_HOSTS`` is the address the deployment answers on. This
module is the arithmetic between them.

**Why a ``post_migrate`` receiver and not something simpler.** Recorded so it
is not re-litigated:

* ``AppConfig.ready()`` must not touch the database. It runs before migrations,
  so a fresh install would crash on a table that does not exist yet.
* A data migration cannot see a ``SiteConfig`` row, because seeding creates
  that row *after* the migration has run.
* ``post_migrate`` fires on every ``manage.py migrate``, which ``DEPLOY.md`` §6
  already tells every operator to run, and again on every upgrade. So the
  derivation gets a second chance the day the agency name is finally filled in.

**It never overwrites an operator.** The only row this writes to is one still
holding Django's untouched placeholder. A value that is anything else is the
operator's — including a value this code itself wrote on an earlier run, which
is what makes running it twice a no-op.
"""

from dataclasses import dataclass

from django.conf import settings

#: The pair Django's own ``django.contrib.sites`` migration writes. Both fields
#: hold this string on an untouched install, which is exactly what makes it a
#: safe "nobody has set this" sentinel.
PLACEHOLDER = "example.com"

#: Addresses that are real entries in ``ALLOWED_HOSTS`` and useless as a public
#: identity. ``config/settings/production.py`` *appends* the first two after the
#: operator's own values so the in-container health probe can reach the site, so
#: they are present on every production deployment and must be skipped rather
#: than treated as the answer.
NON_PUBLIC_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}  # noqa: S104
)


@dataclass(frozen=True)
class SiteIdentity:
    """What the platform can work out about itself. Either field may be None.

    ``None`` is a legitimate answer, not a failure: a deployment that has not
    been through the setup wizard has no agency name, and
    ``config/settings/local.py`` defaults ``ALLOWED_HOSTS`` to ``["*"]``, which
    names no host at all. Both cases leave the row alone rather than raising.
    """

    name: str | None
    domain: str | None


def derive_domain(allowed_hosts=None) -> str | None:
    """The first entry of ALLOWED_HOSTS that is a real, public hostname.

    Skips the loopback names production appends for its own health probe, and
    skips wildcards — ``*`` (development's default) and Django's leading-dot
    subdomain form, whose leading dot is stripped rather than rejected because
    ``.water.example.org`` does name a real host.
    """
    if allowed_hosts is None:
        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])

    for entry in allowed_hosts:
        host = (entry or "").strip().lstrip(".")
        if not host or "*" in host:
            continue
        if host.lower() in NON_PUBLIC_HOSTS:
            continue
        return host

    return None


def derive_name() -> str | None:
    """The agency's own name, as typed into the setup wizard."""
    from core.models import SiteConfig

    config = SiteConfig.objects.first()
    if config is None:
        return None

    name = (config.agency_name or "").strip()
    return name or None


def resolve_site_identity() -> SiteIdentity:
    """The name and address the platform should be presenting itself under."""
    return SiteIdentity(name=derive_name(), domain=derive_domain())


def apply_site_identity(**kwargs) -> bool:
    """Write the derived identity onto the ``Site`` row, if it is untouched.

    Returns True when the row was changed, so a caller (and a test) can tell a
    real write from a deliberate no-op. Connected to ``post_migrate`` in
    ``core.apps.CoreConfig.ready``; the keyword arguments that signal carries
    are accepted and ignored.
    """
    from django.contrib.sites.models import Site

    site = Site.objects.filter(pk=settings.SITE_ID).first()
    if site is None or site.domain != PLACEHOLDER:
        # No row at all, or a row somebody has already set. Either way this
        # code has nothing to say about it.
        return False

    identity = resolve_site_identity()
    changed = []

    if identity.domain:
        site.domain = identity.domain
        changed.append("domain")
    # The name is protected separately: an operator who typed a name and left
    # the address alone still owns that name.
    if identity.name and site.name == PLACEHOLDER:
        site.name = identity.name
        changed.append("name")

    if not changed:
        return False

    site.save(update_fields=changed)
    # Django caches the Site per SITE_ID for the life of the process, so a
    # stale cached row would otherwise keep answering `example.com` to anything
    # running in this same process after the write.
    Site.objects.clear_cache()
    return True
