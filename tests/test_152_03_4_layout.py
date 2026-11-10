# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.4: four drinking-water pages rearranged, layout only.

Every assertion is about where an element sits, never about what a sentence
says. No test here requires a domain description to be present.

* The facilities list: the filter card is gone, the three controls and the
  coverage note sit in the map card's left column, + Add facility is in the
  page actions, and the note still follows an htmx swap (out of band).
* A facility's page: the card head carries the Edit button, and a 3 : 2 split
  holds the record's fields at the left and an inset at the right.
* The add-a-system review: one head line for "Not saved yet" and the Preview
  tag, a colgroup on the cases table, and a two-column "What EPA holds".
* The sampling-points table is covered in
  tests/test_drinking_lists_explain_their_columns.py.
"""

import re

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from drinking.models import SystemFacility, WaterSystem
from tests.factories import (
    SystemFacilityFactory,
    WaterSystemFactory,
)

MERCED = (-120.4829, 37.3022)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"layout1520{n}")
    email = factory.Sequence(lambda n: f"layout1520{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _point(offset=0.0):
    return Point(MERCED[0] + offset, MERCED[1] + offset, srid=4326)


@pytest.fixture
def mapped_system(db):
    """Two located wells and one facility with no location."""
    SystemFacility.objects.all().delete()
    WaterSystem.objects.all().delete()
    system = WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
    SystemFacilityFactory(
        system=system,
        facility_id="010",
        name="Well 08",
        facility_type="WL",
        location=_point(),
    )
    SystemFacilityFactory(
        system=system,
        facility_id="020",
        name="Well 12",
        facility_type="WL",
        location=_point(0.01),
    )
    SystemFacilityFactory(
        system=system,
        facility_id="DST",
        name="DISTRIBUTION SYSTEM",
        facility_type="DS",
        location=None,
    )
    return system


@pytest.fixture
def unmapped_system(db):
    SystemFacility.objects.all().delete()
    WaterSystem.objects.all().delete()
    system = WaterSystemFactory(pwsid="CA2410010", name="Hollow Water District")
    SystemFacilityFactory(
        system=system, facility_id="010", facility_type="WL", location=None
    )
    return system


def _page(client):
    return client.get(reverse("drinking:facilities")).content.decode()


def _htmx(client, **params):
    return client.get(
        reverse("drinking:facilities"), params, headers={"hx-request": "true"}
    ).content.decode()


def _element(html, element_id):
    """The `<div id=...>` element's source, up to its closing tag."""
    start = html.index(f'id="{element_id}"')
    start = html.rindex("<div", 0, start)
    return html[start : html.index("</div>", start) + len("</div>")]


CONTROLS = (
    'id="filter-search"',
    'id="filter-facility-type"',
    'id="filter-activity-status"',
)


# -- The facilities list -------------------------------------------------------


class TestFacilitiesList:
    def test_add_facility_is_in_the_page_actions(self, client_in, mapped_system):
        html = _page(client_in)
        actions = html.split('class="page-head-actions"', 1)[1].split("</div>", 1)[0]
        assert "+ Add facility" in actions
        assert reverse("drinking:facility_add") in actions
        assert "btn-secondary btn-sm" in actions
        # And nowhere else on the page.
        assert html.count("+ Add facility") == 1

    def test_the_controls_and_the_note_sit_in_the_map_cards_left_column(
        self, client_in, mapped_system
    ):
        html = _page(client_in)
        # The filter card is gone.
        assert '<div class="card-raised toolbar-row">' not in html
        card = html.split('id="facilities-map-head"', 1)[1]
        split = card.split('class="facility-map-split"', 1)[1].split("</section>", 1)[0]
        aside, map_host = split.split('id="drinking-facilities-map"', 1)
        for control in CONTROLS:
            assert control in aside, control
        assert 'id="facilities-map-note"' in aside
        # The note follows the controls, and the map comes after both.
        assert aside.index('id="filter-activity-status"') < aside.index(
            'id="facilities-map-note"'
        )
        assert 'id="facilities-map-note"' not in map_host

    def test_the_map_is_400_px_tall(self, client_in, mapped_system):
        html = _page(client_in)
        assert re.search(
            r'id="drinking-facilities-map" style="height: 400px; width: 100%;"', html
        )

    def test_the_controls_keep_their_ids_and_their_include_lists(
        self, client_in, mapped_system
    ):
        html = _page(client_in)
        assert 'hx-include="#filter-facility-type, #filter-activity-status"' in html
        assert 'hx-include="#filter-search, #filter-activity-status"' in html
        assert 'hx-include="#filter-search, #filter-facility-type"' in html
        assert html.count('hx-target="#results"') >= 3

    def test_the_note_is_re_rendered_out_of_band_with_a_filter_set(
        self, client_in, mapped_system
    ):
        partial = _htmx(client_in, q="Well")
        note = _element(partial, "facilities-map-note")
        assert 'hx-swap-oob="true"' in note
        assert "showing 2 facilities" in " ".join(note.split())
        # The same block on the full page is not an out-of-band swap.
        assert "hx-swap-oob" not in _element(_page(client_in), "facilities-map-note")

    def test_the_out_of_band_note_follows_the_filter_it_was_sent_with(
        self, client_in, mapped_system
    ):
        wide = _element(_htmx(client_in, q="Well"), "facilities-map-note")
        narrow = _element(_htmx(client_in, q="Well 08"), "facilities-map-note")
        assert "showing 2 facilities" in " ".join(wide.split())
        assert "showing 1 facility" in " ".join(narrow.split())
        unfiltered = _element(_htmx(client_in), "facilities-map-note")
        assert "The map follows the list" not in unfiltered

    def test_no_located_facility_has_no_map_column(self, client_in, unmapped_system):
        html = _page(client_in)
        assert "facility-map-split" not in html
        assert 'id="drinking-facilities-map"' not in html
        card = html.split('id="facilities-map-head"', 1)[1]
        row = card.split('class="toolbar-row facility-map-toolbar"', 1)[1]
        for control in CONTROLS:
            assert control in row, control
        # The no-location sentence follows the row, inside the same card.
        assert row.index('id="filter-activity-status"') < row.index(
            'id="facilities-map-note"'
        )
        note = _element(html, "facilities-map-note")
        assert "facility-map-note--wide" in note
        assert "no facility on this site has a location recorded" in " ".join(
            note.lower().split()
        )
        # It follows an htmx swap too.
        assert 'hx-swap-oob="true"' in _element(_htmx(client_in), "facilities-map-note")

    def test_no_facility_at_all_keeps_the_plain_filter_card(self, client_in, db):
        SystemFacility.objects.all().delete()
        html = _page(client_in)
        assert '<div class="card-raised toolbar-row">' in html
        assert 'id="facilities-map-head"' not in html
        assert 'id="facilities-map-note"' not in html
        for control in CONTROLS:
            assert control in html, control


# -- A facility's page ---------------------------------------------------------


def _detail(client, facility):
    return client.get(
        reverse("drinking:facility_detail", args=[facility.pk])
    ).content.decode()


class TestFacilityPage:
    def test_the_head_holds_the_heading_and_the_edit_button_on_one_line(
        self, client_in, mapped_system
    ):
        facility = SystemFacility.objects.get(facility_id="DST")
        html = _detail(client_in, facility)
        head = html.split(
            '<div class="record-card-head row-between card-header-ruled">', 1
        )[1]
        head = head.split("</div>", 1)[0]
        assert 'class="section-header"' in head
        assert reverse("drinking:facility_edit", args=[facility.pk]) in head
        assert "btn-secondary btn-sm" in head
        assert head.index("<h2") < head.index("btn-secondary")

    def test_the_inset_holds_system_pwsid_and_identifier(
        self, client_in, mapped_system
    ):
        facility = SystemFacility.objects.get(facility_id="DST")
        html = _detail(client_in, facility)
        split = html.split('<div class="record-split">', 1)[1]
        grid, inset = split.split('<div class="card-inset record-split-inset">', 1)
        for label in ("System", "PWSID"):
            assert f'<div class="field-label">{label}</div>' in inset, label
            assert f'<div class="field-label">{label}</div>' not in grid, label
        assert "Identifier" in inset
        assert "Identifier" not in grid
        # Map and Positions from lead the inset of an unlocated facility.
        assert (
            inset.index(">Map<")
            < inset.index(">Positions from<")
            < inset.index(">System<")
        )
        # The record's own fields stay at the left.
        for label in ("Facility ID", "Name on record", "Type", "Status"):
            assert f'<div class="field-label">{label}</div>' in grid, label
        # The inset spans the identifier with a class, not the unscoped one.
        assert "field-grid-2-span" not in inset
        assert re.search(
            r'class="field-group record-split-wide">\s*<div class="field-label field-row">\s*Identifier',
            inset,
        )

    def test_a_located_facility_has_no_map_rows_in_the_inset(
        self, client_in, mapped_system
    ):
        facility = SystemFacility.objects.get(facility_id="010")
        html = _detail(client_in, facility)
        inset = html.split('<div class="card-inset record-split-inset">', 1)[1]
        assert ">Positions from<" not in inset
        assert ">System<" in inset

    def test_a_well_facilitys_metered_well_is_in_the_inset(
        self, client_in, mapped_system
    ):
        facility = SystemFacility.objects.get(facility_id="010")
        html = _detail(client_in, facility)
        grid, inset = html.split('<div class="card-inset record-split-inset">', 1)
        assert ">Metered well<" in inset
        assert ">Metered well<" not in grid
        assert (
            inset.index(">PWSID<")
            < inset.index(">Metered well<")
            < inset.index("Identifier")
        )
        other = SystemFacility.objects.get(facility_id="DST")
        assert ">Metered well<" not in _detail(client_in, other)


# -- The add-a-system review ---------------------------------------------------


def _review():
    return render_to_string(
        "drinking/partials/_onboard_review.html",
        {
            "pwsid": "CA1010001",
            "name": "BAKMAN WATER COMPANY",
            "facilities": [],
            "facility_count": 3,
            "epa_facility_count": 3,
            "skipped": [],
            "warnings": [],
            "already_onboarded": False,
            "existing_facility_count": 0,
            "mailing": {"mailing_address_line1": "1 Main St"},
            "geography": {"county_served": "Testland"},
            "epa_population_served": 100,
            "epa_service_connections": 40,
            "enabled_modules": [],
        },
    )


class TestReview:
    def test_not_saved_yet_and_the_preview_tag_share_one_head_line(self):
        html = _review()
        head = html.split('<div class="onboard-head card-header-ruled">', 1)[1]
        head = head.split("Below is EPA", 1)[0]
        assert head.index("Not saved yet") < head.index("Preview")
        assert "onboard-status--tag" in head
        # Only the first card: the saved screen's box is a different template.
        assert html.count("onboard-status--preview") == 1

    def test_the_cases_table_has_a_colgroup_and_no_even_class(self):
        html = _review()
        assert "help-cases-table--even" not in html
        colgroup = html.split("<colgroup>", 1)[1].split("</colgroup>", 1)[0]
        assert re.findall(r"width:\s*(\d+)%", colgroup) == ["18", "26", "56"]
        assert "onboard-cases-table" in html

    def test_what_epa_holds_is_two_columns(self):
        html = _review()
        card = html.split("What EPA holds for this system", 1)[1]
        assert "onboard-holds-head" in html
        split = card.split('<div class="onboard-holds-split">', 1)[1]
        left, right = split.split("</div>\n  <div>\n", 1)
        assert "BAKMAN WATER COMPANY" in left
        assert 'class="field-grid-2"' in left
        for label in (
            "PWSID",
            "Status",
            "System type",
            "Owner type",
            "Primary source",
            "County served",
        ):
            assert f'<div class="field-label">{label}</div>' in left, label
        assert "Mailing address" in right
        assert "Population and service connections" in right
        assert "Population served (EPA total)" in right
        # Notes, the facilities table and the form stay full width below.
        assert "Facilities to be saved" not in right.split("</div>\n  </div>\n", 1)[0]
        assert "form-grid-2col" not in html
