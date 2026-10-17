# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting is off unless a site names it (2026-10-12).

The reporting pages risk reading as a working path to the state, which
OpenH2O is not.

So: a deployment with ``OPENH2O_MODULES`` unset runs without ``reporting``; the
sidebar shows Reports greyed and unlinked as "Under development"; and no page
such a deployment serves names GEARS or CalWATRS. The droppability harness reads
list pages only, so the detail pages and forms that carried the two names are
read here. The suite itself runs with ``OPENH2O_MODULES=all`` (Makefile, CI).
"""

import pytest
from django.test import Client
from django.urls import get_resolver

from core import modules as mod
from tests.factories import WellFactory

WITHOUT_REPORTING = [name for name in mod.ALL_MODULE_NAMES if name != "reporting"]


def _admin():
    from core.models import User

    return User.objects.create_superuser(
        username="reportingoff", email="reportingoff@example.com", password="x-not-used"
    )


@pytest.fixture
def client_without_reporting(settings):
    get_resolver().url_patterns  # build the URLconf under the full set first
    settings.OPENH2O_MODULES = WITHOUT_REPORTING
    c = Client()
    c.force_login(_admin())
    return c


@pytest.fixture
def client_with_reporting(settings):
    get_resolver().url_patterns
    settings.OPENH2O_MODULES = list(mod.ALL_MODULE_NAMES)
    c = Client()
    c.force_login(_admin())
    return c


def test_default_module_list_leaves_reporting_out():
    assert "reporting" not in mod.DEFAULT_MODULE_NAMES
    assert set(mod.ALL_MODULE_NAMES) - set(mod.DEFAULT_MODULE_NAMES) == {"reporting"}


@pytest.mark.parametrize("raw", ["", "   "])
def test_unset_env_means_the_default_list(raw):
    assert mod.module_names_from_env(raw) == list(mod.DEFAULT_MODULE_NAMES)


@pytest.mark.parametrize("raw", ["all", "ALL", " all "])
def test_all_means_every_module(raw):
    assert mod.module_names_from_env(raw) == list(mod.ALL_MODULE_NAMES)


def test_a_named_list_is_taken_as_written():
    assert mod.module_names_from_env("core, geography,reporting") == [
        "core", "geography", "reporting",
    ]


def test_sidebar_shows_reports_greyed_and_unlinked(client_without_reporting):
    html = client_without_reporting.get("/about/").content.decode()
    assert 'href="/reporting/' not in html
    assert 'class="sidebar-link sidebar-link-disabled" aria-disabled="true"' in html
    assert '<span class="sidebar-link-note">Under development</span>' in html


def test_sidebar_links_reports_when_reporting_is_on(client_with_reporting):
    html = client_with_reporting.get("/about/").content.decode()
    assert 'href="/reporting/reports/"' in html
    assert "sidebar-link-disabled" not in html


@pytest.mark.skipif(not mod.is_enabled("wells"), reason="wells module is not enabled")
def test_well_page_names_no_reporting_system(client_without_reporting):
    well = WellFactory()
    html = client_without_reporting.get(f"/wells/{well.pk}/").content.decode()
    assert "GEARS" not in html
    assert '<h2 class="section-header mt-lg">Pumping</h2>' in html


@pytest.mark.skipif(not mod.is_enabled("wells"), reason="wells module is not enabled")
def test_well_page_keeps_gears_when_reporting_is_on(client_with_reporting):
    well = WellFactory()
    html = client_with_reporting.get(f"/wells/{well.pk}/").content.decode()
    assert "State reporting (GEARS, State Water Board)" in html


@pytest.mark.skipif(not mod.is_enabled("surface"), reason="surface module is not enabled")
def test_water_right_form_offers_no_calwatrs_pin(client_without_reporting):
    html = client_without_reporting.get("/surface/rights/add/").content.decode()
    assert "CalWATRS" not in html


@pytest.mark.skipif(not mod.is_enabled("surface"), reason="surface module is not enabled")
def test_the_water_right_form_never_offers_a_pin(settings):
    """Removed everywhere on 2026-10-12, Reports on or off; a stored PIN stays put."""
    from surface.forms import WaterRightForm
    from tests.factories import WaterRightFactory

    right = WaterRightFactory(calwatrs_pin="PIN-123")
    for names in (WITHOUT_REPORTING, list(mod.ALL_MODULE_NAMES)):
        settings.OPENH2O_MODULES = names
        assert "calwatrs_pin" not in WaterRightForm(instance=right).fields
    right.refresh_from_db()
    assert right.calwatrs_pin == "PIN-123"


def test_glossary_names_no_reporting_system(client_without_reporting):
    html = client_without_reporting.get("/help/glossary/").content.decode()
    assert "GEARS" not in html
    assert "CalWATRS" not in html


def test_about_page_says_nothing_about_filing(client_without_reporting):
    html = client_without_reporting.get("/about/").content.decode()
    for phrase in ("report layout", "files them", "GEARS", "CalWATRS"):
        assert phrase not in html, phrase



@pytest.mark.skipif(not mod.is_enabled("surface"), reason="surface module is not enabled")
def test_a_rights_data_document_never_names_a_pin(settings):
    """The record's JSON-LD is read by programs, not people, but it is still the
    record published under the site's own address."""
    from core.identifiers import jsonld_for
    from tests.factories import WaterRightFactory

    right = WaterRightFactory(calwatrs_pin="PIN-123")
    for names in (WITHOUT_REPORTING, list(mod.ALL_MODULE_NAMES)):
        settings.OPENH2O_MODULES = names
        doc = jsonld_for(right, base="https://x.test")
        assert "calwatrs_pin" not in [i["schema:propertyID"] for i in doc["schema:identifier"]]
