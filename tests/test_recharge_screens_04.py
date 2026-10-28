# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recharge screens: a screen sets a site's zone, a site takes a typed location,
the "Water recharged" panel follows the event table, and capacity and well type
are defined where they print.

Every figure below is this file's own fixture value, typed out; none is read
back from the code under test.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from recharge.models import RechargeSite
from tests.factories import (
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

POLYGON = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [
            [[-120.0, 37.0], [-120.0, 37.2], [-119.8, 37.2], [-119.8, 37.0], [-120.0, 37.0]]
        ],
    }
)


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
    return _client("rc-writer")


@pytest.fixture
def viewer():
    return _client("rc-viewer", read_only=True)


def _add(client, **fields):
    data = {"infra_type": "recharge_site", "name": "Rc basin", "status": "active"}
    data.update(fields)
    return client.post(reverse("infrastructure:add"), data)


# -- a screen sets a recharge site's zone -------------------------------------


class TestAScreenSetsTheZone:
    def test_the_add_form_offers_the_zones_and_saves_the_choice(self, writer):
        zone = ZoneFactory(name="Rc north subbasin")
        html = writer.get(reverse("infrastructure:add") + "?type=recharge_site").content.decode()
        assert 'name="zone"' in html
        assert "Rc north subbasin" in html
        resp = _add(writer, geometry_json=POLYGON, zone=str(zone.pk))
        assert resp.status_code == 302
        assert RechargeSite.objects.get(name="Rc basin").zone == zone

    def test_the_add_form_saves_no_zone_when_none_is_chosen(self, writer):
        _add(writer, geometry_json=POLYGON, zone="")
        assert RechargeSite.objects.get(name="Rc basin").zone is None

    def test_a_zone_that_does_not_exist_is_refused_with_a_message(self, writer):
        resp = _add(writer, geometry_json=POLYGON, zone="999999")
        assert resp.status_code == 200
        assert RechargeSite.objects.count() == 0
        assert "Choose a zone from the list." in resp.content.decode()

    def test_a_writer_changes_the_zone_on_the_site_page(self, writer):
        old, new = ZoneFactory(name="Rc old zone"), ZoneFactory(name="Rc new zone")
        site = RechargeSiteFactory(zone=old)
        page = writer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert f'action="{reverse("recharge:site_zone", args=[site.pk])}"' in page
        assert "Rc new zone" in page
        resp = writer.post(reverse("recharge:site_zone", args=[site.pk]), {"zone": str(new.pk)})
        assert resp.status_code == 302
        site.refresh_from_db()
        assert site.zone == new

    def test_a_writer_clears_the_zone(self, writer):
        site = RechargeSiteFactory(zone=ZoneFactory())
        writer.post(reverse("recharge:site_zone", args=[site.pk]), {"zone": ""})
        site.refresh_from_db()
        assert site.zone is None

    def test_a_viewer_cannot_change_it_and_sees_no_control(self, viewer):
        zone = ZoneFactory()
        site = RechargeSiteFactory(zone=None)
        resp = viewer.post(reverse("recharge:site_zone", args=[site.pk]), {"zone": str(zone.pk)})
        assert resp.status_code == 403
        site.refresh_from_db()
        assert site.zone is None
        page = viewer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert reverse("recharge:site_zone", args=[site.pk]) not in page

    def test_the_flash_links_to_the_control_instead_of_saying_no_screen_does(self, writer):
        site = RechargeSiteFactory(zone=None)
        body = writer.post(
            reverse("recharge:event_create", args=[site.pk]),
            {"start_date": "2024-02-01", "volume_acre_feet": "12.5"},
        ).content.decode()
        assert "No page sets" not in body
        assert 'href="#site-zone"' in body
        page = writer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert 'id="site-zone"' in page

    def test_a_site_with_a_zone_gets_no_zone_link_in_the_flash(self, writer):
        site = RechargeSiteFactory(zone=ZoneFactory())
        body = writer.post(
            reverse("recharge:event_create", args=[site.pk]),
            {"start_date": "2024-02-01", "volume_acre_feet": "12.5"},
        ).content.decode()
        assert 'href="#site-zone"' not in body


# -- the add form takes a typed location --------------------------------------


class TestATypedLocation:
    def test_typed_coordinates_with_no_polygon_save_that_point(self, writer):
        resp = _add(writer, latitude="36.9876", longitude="-119.7654")
        assert resp.status_code == 302
        site = RechargeSite.objects.get(name="Rc basin")
        assert (round(site.location.x, 4), round(site.location.y, 4)) == (-119.7654, 36.9876)
        assert site.geometry is None

    def test_a_drawn_polygon_wins_over_typed_coordinates(self, writer):
        _add(writer, geometry_json=POLYGON, latitude="36.0", longitude="-119.0")
        site = RechargeSite.objects.get(name="Rc basin")
        assert site.geometry is not None
        assert (round(site.location.x, 6), round(site.location.y, 6)) == (-119.9, 37.1)

    def test_neither_way_is_refused_with_a_sentence_naming_both(self, writer):
        resp = _add(writer)
        assert resp.status_code == 200
        assert RechargeSite.objects.count() == 0
        assert (
            "Draw the outline on the map, or type a latitude and longitude."
            in resp.content.decode()
        )

    def test_the_inputs_are_not_hidden_for_a_recharge_site(self, writer):
        html = writer.get(reverse("infrastructure:add") + "?type=recharge_site").content.decode()
        assert 'id="latitude"' in html and 'id="longitude"' in html
        assert "or type a latitude and longitude" in html
        # The script that once hid the pair outside point mode is gone.
        assert "mode === 'point' ? '' : 'none'" not in html


# -- the Water recharged panel follows the table ------------------------------


class TestThePanelRefreshes:
    def test_the_event_post_carries_the_panel_with_the_new_total(self, writer):
        ReportingPeriodFactory(
            name="Rc WY", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        site = RechargeSiteFactory(zone=ZoneFactory())
        RechargeEventFactory(
            recharge_site=site, start_date=date(2025, 11, 1), volume_acre_feet=Decimal("30.0000")
        )
        before = writer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert "30.00" in before
        body = writer.post(
            reverse("recharge:event_create", args=[site.pk]),
            {"start_date": "2025-12-01", "volume_acre_feet": "12.5"},
        ).content.decode()
        panel = re.search(r'<div[^>]*id="water-recharged"[^>]*>', body)
        assert panel and 'hx-swap-oob="true"' in panel.group(0)
        assert re.search(r"budget-seg-value[^>]*>\s*42\.50", body)
        assert "2 events, Rc WY" in body

    def test_deleting_an_event_refreshes_the_panel_too(self, writer):
        ReportingPeriodFactory(
            name="Rc WY", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        site = RechargeSiteFactory(zone=ZoneFactory())
        RechargeEventFactory(
            recharge_site=site, start_date=date(2025, 11, 1), volume_acre_feet=Decimal("30.0000")
        )
        event = RechargeEventFactory(
            recharge_site=site, start_date=date(2025, 12, 1), volume_acre_feet=Decimal("8.0000")
        )
        body = writer.post(
            reverse("recharge:event_delete", args=[site.pk, event.pk])
        ).content.decode()
        assert 'id="water-recharged"' in body
        assert re.search(r"budget-seg-value[^>]*>\s*30\.00", body)

    def test_the_full_page_carries_the_panel_once_and_not_out_of_band(self, writer):
        ReportingPeriodFactory(
            name="Rc WY", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        site = RechargeSiteFactory()
        page = writer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert page.count('id="water-recharged"') == 1
        assert "hx-swap-oob" not in page


# -- one name for capacity, and the values of well type -----------------------


CAPACITY_DEFINITION = "The volume the site holds per fill, as entered."


class TestCapacityHasOneNameAndADefinition:
    def test_the_model_and_the_admin_use_the_screens_name(self):
        field = RechargeSite._meta.get_field("capacity_acre_feet")
        assert str(field.verbose_name) == "Capacity per fill (AF)"

    def test_the_list_the_page_and_the_form_define_it(self, writer):
        site = RechargeSiteFactory(capacity_acre_feet=Decimal("250.0000"))
        for url in (
            reverse("recharge:list"),
            reverse("recharge:detail", args=[site.pk]),
            reverse("infrastructure:add") + "?type=recharge_site",
            reverse("infrastructure:add") + "?type=storage",
        ):
            html = writer.get(url).content.decode()
            assert CAPACITY_DEFINITION in html, url

    def test_no_screen_still_calls_it_capacity_acre_feet(self, writer):
        site = RechargeSiteFactory(capacity_acre_feet=Decimal("250.0000"))
        html = writer.get(reverse("recharge:detail", args=[site.pk])).content.decode()
        assert "Capacity acre feet" not in html

    def test_the_glossary_defines_it(self, writer):
        html = writer.get(reverse("glossary")).content.decode()
        assert "Capacity per fill" in html
        assert CAPACITY_DEFINITION in html


class TestWellTypeValuesAreDefined:
    def test_the_well_page_lists_the_types_on_record_and_says_what_not_recorded_means(
        self, writer
    ):
        WellTypeFactory(name="Rc alpha")
        WellTypeFactory(name="Rc beta")
        well = WellFactory(well_type=None)
        html = writer.get(reverse("wells:detail", args=[well.pk])).content.decode()
        # Other tests' well types may be on record too; ours are listed among them.
        listed = re.search(r"Well types on record: ([^<]*?)\. Not recorded", html)
        assert listed is not None
        assert {"Rc alpha", "Rc beta"} <= set(listed.group(1).split(", "))
        assert "Not recorded means no well type was entered." in html
        assert "irrigation, domestic" not in html

    def test_a_type_that_is_set_prints_its_name(self, writer):
        wt = WellTypeFactory(name="Rc gamma")
        well = WellFactory(well_type=wt)
        html = writer.get(reverse("wells:detail", args=[well.pk])).content.decode()
        assert "Rc gamma" in html

    def test_the_glossary_defines_well_type(self, writer):
        html = writer.get(reverse("glossary")).content.decode()
        assert "Well Type" in html
        assert "Not recorded means no well type was entered." in html
