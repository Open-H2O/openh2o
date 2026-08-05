# SPDX-License-Identifier: AGPL-3.0-or-later
"""The platform must stop introducing itself as ``example.com`` (ISS-125).

``core/site_identity.py`` derives the pair from configuration the platform
already holds — the agency name from ``SiteConfig``, the web address from
``ALLOWED_HOSTS`` — because the alternative was one more environment variable
that a water-district engineer would never know to set.

These tests cover the derivation, the two filters that make it safe on a real
production deployment, the guard that keeps it away from a value an operator
set on purpose, and both directions of the ``manage.py check`` warning. The
guards were mutation-proved: each was deleted in turn, the run went red, and it
went green again on restore.
"""

import pytest
from django.contrib.sites.models import Site
from django.test import override_settings

from core.checks import SITE_IDENTITY_WARNING_ID, check_site_identity_is_set
from core.models import SiteConfig
from core.site_identity import (
    PLACEHOLDER,
    apply_site_identity,
    derive_domain,
    resolve_site_identity,
)

AGENCY = "Merced Irrigation-Urban GSA"
REAL_HOST = "water.example.org"


@pytest.fixture
def placeholder_site(db):
    """The ``Site`` row exactly as Django's own migration leaves it."""
    site, _ = Site.objects.update_or_create(
        pk=1, defaults={"name": PLACEHOLDER, "domain": PLACEHOLDER}
    )
    Site.objects.clear_cache()
    yield site
    Site.objects.clear_cache()


# -- Working out the address -------------------------------------------------


class TestDerivingTheAddress:
    def test_it_takes_the_first_real_hostname(self):
        assert derive_domain([REAL_HOST, "other.example.org"]) == REAL_HOST

    def test_it_skips_the_loopback_names_production_appends(self):
        # config/settings/production.py appends these AFTER the operator's own
        # values, so they are present on every production deployment.
        assert derive_domain(["127.0.0.1", "localhost", REAL_HOST]) == REAL_HOST

    def test_it_skips_the_wildcard_development_defaults_to(self):
        # config/settings/local.py defaults the whole list to ["*"].
        assert derive_domain(["*"]) is None

    def test_it_reads_djangos_leading_dot_subdomain_form(self):
        assert derive_domain([f".{REAL_HOST}"]) == REAL_HOST

    def test_a_list_naming_no_real_host_is_an_answer_not_a_crash(self):
        assert derive_domain([]) is None
        assert derive_domain(["", "localhost", "*.example.org"]) is None

    @override_settings(ALLOWED_HOSTS=[REAL_HOST, "127.0.0.1"])
    def test_it_reads_the_live_setting_when_given_no_list(self):
        assert derive_domain() == REAL_HOST


# -- Working out the name ----------------------------------------------------


class TestDerivingTheName:
    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_it_uses_the_agency_name_and_the_web_address(self, db):
        SiteConfig.objects.create(agency_name=AGENCY)

        identity = resolve_site_identity()

        assert identity.name == AGENCY
        assert identity.domain == REAL_HOST

    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_no_site_config_row_is_survivable(self, db):
        assert SiteConfig.objects.count() == 0

        identity = resolve_site_identity()

        assert identity.name is None
        assert identity.domain == REAL_HOST


# -- Writing it onto the row -------------------------------------------------


class TestApplyingIt:
    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_it_fills_in_an_untouched_row(self, placeholder_site):
        SiteConfig.objects.create(agency_name=AGENCY)

        assert apply_site_identity() is True

        site = Site.objects.get(pk=1)
        assert site.name == AGENCY
        assert site.domain == REAL_HOST

    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_it_leaves_a_value_the_operator_set_alone(self, placeholder_site):
        SiteConfig.objects.create(agency_name=AGENCY)
        Site.objects.filter(pk=1).update(
            name="Chosen By Hand", domain="chosen-by-hand.example.org"
        )
        Site.objects.clear_cache()

        assert apply_site_identity() is False

        site = Site.objects.get(pk=1)
        assert site.name == "Chosen By Hand"
        assert site.domain == "chosen-by-hand.example.org"

    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_running_it_twice_changes_nothing_the_second_time(
        self, placeholder_site
    ):
        SiteConfig.objects.create(agency_name=AGENCY)

        assert apply_site_identity() is True
        assert apply_site_identity() is False

        site = Site.objects.get(pk=1)
        assert (site.name, site.domain) == (AGENCY, REAL_HOST)

    @override_settings(ALLOWED_HOSTS=[REAL_HOST])
    def test_the_real_deployment_sequence_fills_in_both_halves(
        self, placeholder_site
    ):
        # scripts/rebuild-golden.sh runs `migrate` on an empty database and
        # seeds afterwards, so the first firing knows the web address and not
        # yet the agency name. A guard shared between the two fields would
        # strand the name at example.com for the life of the deployment — and
        # the name is the half that reaches the subject line.
        assert apply_site_identity() is True

        site = Site.objects.get(pk=1)
        assert (site.domain, site.name) == (REAL_HOST, PLACEHOLDER)

        SiteConfig.objects.create(agency_name=AGENCY)

        assert apply_site_identity() is True
        assert Site.objects.get(pk=1).name == AGENCY

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_it_does_not_raise_when_nothing_can_be_derived(
        self, placeholder_site
    ):
        assert apply_site_identity() is False

        site = Site.objects.get(pk=1)
        assert (site.name, site.domain) == (PLACEHOLDER, PLACEHOLDER)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_the_name_alone_is_worth_writing(self, placeholder_site):
        # The subject-line prefix is the NAME. An address we cannot derive is
        # no reason to leave outbound mail titled [example.com].
        SiteConfig.objects.create(agency_name=AGENCY)

        assert apply_site_identity() is True

        site = Site.objects.get(pk=1)
        assert site.name == AGENCY
        assert site.domain == PLACEHOLDER


# -- What `manage.py check` says ---------------------------------------------


class TestTheWarning:
    def test_it_fires_on_a_placeholder_row_and_names_the_subject_line(
        self, placeholder_site
    ):
        warnings = check_site_identity_is_set(None)

        assert len(warnings) == 1, f"expected one warning, got {warnings!r}"
        warning = warnings[0]
        assert warning.id == SITE_IDENTITY_WARNING_ID
        assert PLACEHOLDER in warning.msg
        assert "subject line" in warning.msg, (
            "the warning must name the consequence an operator can recognise, "
            f"not the database row; message was: {warning.msg!r}"
        )

    def test_it_is_silent_once_the_row_is_real(self, placeholder_site):
        Site.objects.filter(pk=1).update(name=AGENCY, domain=REAL_HOST)
        Site.objects.clear_cache()

        assert check_site_identity_is_set(None) == [], (
            "the warning fired on a correctly configured row, so it says "
            "nothing about whether the identity is set and is not a measurement"
        )
