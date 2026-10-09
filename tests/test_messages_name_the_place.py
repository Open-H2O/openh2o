# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-03 Task 5: a message that names a requirement names the place (ISS-182),
the identifier card says what it is for (ISS-224), and the CalWATRS line shows
only where CalWATRS reporting is on (ISS-194).

ISS-182's walkers met "No water year on record", "No water right linked",
"Reporting period not found" and "assign a zone" with no word on where any of
those records live. Each message below is asserted for its words AND for the
link it renders, read from the message's own fragment of the page rather than
the whole body, because the sidebar already carries most of these addresses
and a whole-body check would pass with no link in the message at all. Where
the linked page is a create form, a Viewer (who is refused on it,
core/access.py) gets the list instead, and that branch is asserted too.

One requirement has no place: no screen sets a recharge site's zone
(RechargeSite.zone is written only by seed commands and the Django admin). The
flash says so plainly, and the test pins that it sends the reader nowhere.
"""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse

from core.modules import ALL_MODULE_NAMES
from tests.factories import PointOfDiversionFactory, RechargeSiteFactory, WaterRightFactory
from tests.test_drinking_onboard import PWSID, epa  # noqa: F401  (epa is a fixture)

pytestmark = pytest.mark.django_db

User = get_user_model()

NO_WATER_YEAR = "No water year on record."

#: Nothing in core/modules.py requires `reporting`, so it drops alone.
WITHOUT_REPORTING = tuple(n for n in ALL_MODULE_NAMES if n != "reporting")


def _client(username, **flags):
    user = User.objects.create_user(
        username=username, email=f"{username}@example.org",
        password="a-good-passw0rd", is_active=True, **flags,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def writer():
    return _client("place-writer")


@pytest.fixture
def viewer():
    return _client("place-viewer", read_only=True)


def _fragment(body, start, length=600):
    """The page from ``start`` on: the message and the markup it carries."""
    assert start in body, f"{start!r} is not on the page"
    return body[body.index(start):body.index(start) + length]


# -- ISS-182: "No water year on record." -------------------------------------


def _water_year_pages():
    right = WaterRightFactory(face_value_acre_feet=100)
    pod = PointOfDiversionFactory()
    site = RechargeSiteFactory()
    return [
        reverse("surface:detail", args=[right.pk]),
        reverse("surface:pod_detail", args=[pod.pk]),
        reverse("recharge:detail", args=[site.pk]),
    ]


class TestNoWaterYearNamesWaterYears:
    def test_a_writer_is_sent_to_add_one(self, writer):
        for path in _water_year_pages():
            body = writer.get(path).content.decode()
            fragment = _fragment(body, NO_WATER_YEAR)
            assert (
                f'No water year on record. <a href="{reverse("accounting:period_create")}" '
                'class="text-accent">Add one</a> under Administration &gt; '
                f'<a href="{reverse("accounting:periods_list")}" '
                'class="text-accent">Water Years</a>.'
            ) in fragment, path

    def test_a_viewer_is_shown_where_they_are_kept_and_no_create_form(self, viewer):
        for path in _water_year_pages():
            body = viewer.get(path).content.decode()
            fragment = _fragment(body, NO_WATER_YEAR)
            assert (
                "No water year on record. Water years are kept under "
                f'Administration &gt; <a href="{reverse("accounting:periods_list")}" '
                'class="text-accent">Water Years</a>.'
            ) in fragment, path
            assert reverse("accounting:period_create") not in fragment, path

    def test_both_linked_pages_open_for_the_account_they_are_shown_to(
        self, writer, viewer
    ):
        assert writer.get(reverse("accounting:period_create")).status_code == 200
        assert viewer.get(reverse("accounting:periods_list")).status_code == 200


# -- ISS-182: "No water right is linked." ------------------------------------


class TestNoWaterRightNamesWaterRights:
    LINE = "No water right is linked."

    def _expected(self):
        return (
            "No water right is linked. Rights are kept under Administration &gt; "
            f'<a href="{reverse("surface:water_rights_list")}" '
            'class="text-accent">Water Rights</a>.'
        )

    def test_the_pod_page_names_and_links_water_rights(self, writer):
        pod = PointOfDiversionFactory(water_right=None)
        body = writer.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert self._expected() in _fragment(body, self.LINE)

    def test_the_unlink_response_carries_it_too(self, writer):
        pod = PointOfDiversionFactory()
        body = writer.post(
            reverse("surface:pod_link_right", args=[pod.pk]), {"water_right_id": ""}
        ).content.decode()
        assert self._expected() in body

    def test_a_viewer_gets_the_same_link_because_the_list_is_readable(self, viewer):
        pod = PointOfDiversionFactory(water_right=None)
        body = viewer.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert self._expected() in _fragment(body, self.LINE)
        assert viewer.get(reverse("surface:water_rights_list")).status_code == 200


# -- ISS-194: the CalWATRS line follows the reporting module -----------------


class TestTheCalwatrsLineFollowsTheReportingModule:
    LINE = "CalWATRS reports will flag this diversion as [INCOMPLETE]."

    def test_it_shows_with_reporting_on(self, writer):
        pod = PointOfDiversionFactory(water_right=None)
        body = writer.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert self.LINE in body

    @override_settings(OPENH2O_MODULES=WITHOUT_REPORTING)
    def test_it_is_gone_with_reporting_off_and_the_rest_of_the_panel_stays(
        self, writer
    ):
        pod = PointOfDiversionFactory(water_right=None)
        body = writer.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert "CalWATRS" not in _fragment(body, "No water right is linked.")
        assert self.LINE not in body
        assert 'name="water_right_id"' in body

    @override_settings(OPENH2O_MODULES=WITHOUT_REPORTING)
    def test_the_unlink_response_follows_the_module_too(self, writer):
        pod = PointOfDiversionFactory()
        body = writer.post(
            reverse("surface:pod_link_right", args=[pod.pk]), {"water_right_id": ""}
        ).content.decode()
        assert "No water right is linked." in body
        assert self.LINE not in body


# -- ISS-182: the recharge site with no zone ---------------------------------


class TestTheNoZoneMessageSaysThereIsNoScreen:
    def test_the_flash_is_complete_sentences_with_no_dash(self, writer):
        site = RechargeSiteFactory(zone=None)
        body = writer.post(
            reverse("recharge:event_create", args=[site.pk]),
            {"start_date": "2024-02-01", "volume_acre_feet": "12.5"},
        ).content.decode()
        message = (
            "Event saved. This site has no zone, so no ledger entries were "
            "written. No screen sets a recharge site's zone yet."
        )
        assert message.replace("'", "&#x27;") in body
        flash = _fragment(body, "Event saved.", 160)
        assert "\u2014" not in flash and "&mdash;" not in flash
        assert "auto-distribute" not in body
        assert "<a " not in flash, "the flash links a page that cannot set a zone"


# -- ISS-182: import_ledger_csv's missing water year -------------------------


class TestTheImportCommandNamesWhereAWaterYearIsCreated:
    def test_the_error_names_water_years_and_the_create_path(self, tmp_path):
        csv_path = tmp_path / "ledger.csv"
        csv_path.write_text("parcel_number,transaction_date,amount_acre_feet\n")
        with pytest.raises(CommandError) as raised:
            call_command(
                "import_ledger_csv", str(csv_path),
                reporting_period="2025 Water Year", stdout=StringIO(),
            )
        assert str(raised.value) == (
            "Water year not found: 2025 Water Year. Create it first under "
            "Administration > Water Years (/accounting/reporting-periods/create/), "
            "or pass an existing water year's name."
        )
        assert reverse("accounting:period_create") == "/accounting/reporting-periods/create/"


# -- ISS-183: the drinking pages no longer name the Django admin -------------


class TestTheDrinkingPagesNameTheirOwnScreens:
    def test_the_onboard_page_sends_well_links_to_facilities(self, writer):
        body = writer.get(reverse("drinking:onboard")).content.decode()
        assert "Django admin" not in body
        assert (
            "Set on each facility's page under "
            f'<a href="{reverse("drinking:facilities")}" class="data-table-link">'
            "Facilities</a>, with Edit local name; a second lookup never changes "
            "a link already made"
        ) in body

    def test_the_review_says_the_same(self, writer, epa):
        body = writer.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()
        assert "Django admin" not in body
        fragment = _fragment(body, "Links to wells")
        assert f'href="{reverse("drinking:facilities")}"' in fragment
        assert "with Edit local name; a link already made is left alone" in fragment

    def test_the_edit_door_on_a_facility_page_is_named_edit_local_name(self, writer):
        """The cell names a button; the button must say those words."""
        from tests.factories import SystemFacilityFactory

        facility = SystemFacilityFactory()
        assert not facility.added_by_hand
        body = writer.get(
            reverse("drinking:facility_detail", args=[facility.pk])
        ).content.decode()
        assert ">Edit local name</a>" in body

    def test_the_empty_state_fallback_says_no_screen_adds_it(self):
        html = render_to_string(
            "drinking/partials/_empty_drinking.html",
            {"what": "No widgets yet.", "user_can_write": True},
        )
        assert "No screen adds one of these yet." in html
        assert "Django admin" not in html


# -- ISS-224: the identifier card's title ------------------------------------


class TestTheIdentifierCardSaysWhatItIsFor:
    def test_the_title_and_the_help_text(self, admin_client):
        """Only the title changed: the field's help line already says what the
        setting does and that it matters before registering with Geoconnex, so
        no second line restates it (the line appears exactly once)."""
        body = admin_client.get(reverse("accounting:delivery_settings")).content.decode()
        assert '<h2 class="section-header">Web addresses for your records</h2>' in body
        assert "Record addresses" not in body
        assert body.count("Set it before registering with Geoconnex") == 1

