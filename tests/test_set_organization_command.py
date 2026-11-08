# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1 step D: ``set_organization`` sets the organization's name and time zone.

The command saves the ``SiteConfig`` row and calls ``core.site_identity.apply_site_identity``
itself, so no ``migrate`` is needed after it. Messages are copied from the approved
rows in ``152-03.1-ROWS.md`` (row numbers named beside each); the W002 hint is row 73.

Test data is INVENTED: "Example Ditch Company" at ditch.example.org.
"""
from io import StringIO

import pytest
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from core.checks import SITE_IDENTITY_WARNING_ID, check_site_identity_is_set
from core.models import SiteConfig
from core.site_identity import PLACEHOLDER

pytestmark = pytest.mark.django_db

NAME = "Example Ditch Company"
HOST = "ditch.example.org"

ROW_37 = "Give the organization's name after --name."
ROW_73 = (
    "The site's name comes from the organization's name. Set the organization's name "
    "with 'docker compose exec web python manage.py set_organization --name' followed "
    "by the name. The site's address comes from ALLOWED_HOSTS in .env. A site used only "
    "on its own computer can have localhost as its only address. After a change to "
    "ALLOWED_HOSTS, run 'docker compose exec web python manage.py migrate'. The migrations "
    "replace the placeholder address example.com with the address from ALLOWED_HOSTS. "
    "See section 10 of DEPLOY.md."
)


@pytest.fixture
def placeholder_site(db):
    SiteConfig.objects.all().delete()
    site, _ = Site.objects.update_or_create(
        pk=1, defaults={"name": PLACEHOLDER, "domain": PLACEHOLDER}
    )
    Site.objects.clear_cache()
    yield site
    Site.objects.clear_cache()


def _run(*args):
    out = StringIO()
    call_command("set_organization", *args, stdout=out)
    return out.getvalue()


def _check_output():
    out, err = StringIO(), StringIO()
    call_command("check", stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


@override_settings(ALLOWED_HOSTS=[HOST])
def test_with_no_site_config_the_command_creates_one_and_names_the_site(placeholder_site):
    assert SiteConfig.objects.count() == 0

    _run("--name", NAME)

    assert SiteConfig.objects.get().agency_name == NAME
    Site.objects.clear_cache()
    assert Site.objects.get(pk=1).name == NAME, "the Site row still reads example.com (no migrate was run)"


@override_settings(ALLOWED_HOSTS=[HOST])
def test_check_stops_reporting_w002_once_the_name_is_set(placeholder_site):
    assert SITE_IDENTITY_WARNING_ID in _check_output(), "precondition: the placeholder site must warn"

    _run("--name", NAME)
    Site.objects.clear_cache()

    assert SITE_IDENTITY_WARNING_ID not in _check_output()


@override_settings(ALLOWED_HOSTS=[HOST])
def test_the_command_prints_row_36(placeholder_site):
    out = " ".join(_run("--name", NAME).split())

    assert (
        f"The organization's name is now {NAME}. "
        "The site's time zone is America/Los_Angeles. "
        f"Emails from this site start their subject line with {NAME}."
    ) in out


@override_settings(ALLOWED_HOSTS=[HOST])
def test_a_new_site_takes_the_time_zone_given(placeholder_site):
    out = " ".join(_run("--name", NAME, "--time-zone", "America/Denver").split())

    assert SiteConfig.objects.get().timezone == "America/Denver"
    assert "The site's time zone is America/Denver." in out


@override_settings(ALLOWED_HOSTS=[HOST])
def test_with_a_site_config_only_the_name_changes(placeholder_site):
    SiteConfig.objects.create(
        agency_name="Old Name", timezone="America/Denver", native_srid=3310,
        contact_email="office@example.org", contact_phone="555-0100",
        demonstration_mode=True,
    )

    _run("--name", NAME)

    config = SiteConfig.objects.get()
    assert config.agency_name == NAME
    assert (config.timezone, config.native_srid, config.contact_email,
            config.contact_phone, config.demonstration_mode) == (
        "America/Denver", 3310, "office@example.org", "555-0100", True)
    assert SiteConfig.objects.count() == 1


@override_settings(ALLOWED_HOSTS=[HOST])
def test_with_a_site_config_the_name_and_the_zone_change_when_a_zone_is_given(placeholder_site):
    SiteConfig.objects.create(
        agency_name="Old Name", timezone="America/Denver", contact_email="office@example.org"
    )

    _run("--name", NAME, "--time-zone", "America/Phoenix")

    config = SiteConfig.objects.get()
    assert (config.agency_name, config.timezone, config.contact_email) == (
        NAME, "America/Phoenix", "office@example.org")


@override_settings(ALLOWED_HOSTS=[HOST])
def test_an_unknown_time_zone_is_refused_with_row_38(placeholder_site):
    with pytest.raises(CommandError) as err:
        _run("--name", NAME, "--time-zone", "Not/AZone")

    assert str(err.value) == (
        "OpenH2O cannot use the time zone Not/AZone. Give a name such as America/Denver."
    )
    assert SiteConfig.objects.count() == 0


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_name_is_refused_with_row_37(placeholder_site, blank):
    with pytest.raises(CommandError) as err:
        _run("--name", blank)

    assert str(err.value) == ROW_37
    assert SiteConfig.objects.count() == 0


def test_the_w002_hint_is_row_73(placeholder_site):
    warnings = check_site_identity_is_set(None)

    assert len(warnings) == 1
    assert warnings[0].hint == ROW_73


def test_a_rename_reaches_the_site_name_the_emails_use(db):
    # Main session, 152-03.1 re-read: apply_site_identity writes the name only
    # over example.com, so a rename must be written by the command itself.

    call_command("set_organization", "--name", "Example Ditch Company", stdout=StringIO())
    call_command("set_organization", "--name", "Example Irrigation Company", stdout=StringIO())

    Site.objects.clear_cache()
    assert Site.objects.get_current().name == "Example Irrigation Company"


def test_the_time_zone_alone_changes_once_the_organization_has_a_record(db):

    call_command("set_organization", "--name", "Example Ditch Company", stdout=StringIO())
    call_command("set_organization", "--time-zone", "America/Denver", stdout=StringIO())

    config = SiteConfig.objects.get()
    assert (config.agency_name, config.timezone) == ("Example Ditch Company", "America/Denver")


def test_the_time_zone_alone_on_a_site_with_no_record_asks_for_the_name(db):

    with pytest.raises(CommandError) as err:
        call_command("set_organization", "--time-zone", "America/Denver", stdout=StringIO())
    assert str(err.value) == "Give the organization's name after --name."
