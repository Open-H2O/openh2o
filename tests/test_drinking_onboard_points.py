# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 80-03 — the per-facility sampling-point builder.

This is the surface that makes the drinking module usable end to end. Onboarding
creates a system and its facilities, which looks finished and is not: the lab
importer matches every row on PS Code, and a PS Code lives on a SamplingPoint.
Until this screen has been used, a real lab file imports zero rows.

Three things here are load-bearing.

**The distribution system is not a special case.** ``CA1010001_DST_LCR`` is the
Lead & Copper tap, and it is an ordinary point on an ordinary facility whose
state key happens to be ``DST`` rather than ``010``. The test for it exists
because the tempting shortcut — a numeric point-number field, an ``int()``, a
``\\d+`` pattern — passes every well test and drops every program point.

**A duplicate is an ordinary event.** An operator re-walking a system they had
partly finished is the common case, not an error, so adding an existing PS Code
reports and skips instead of raising IntegrityError into a 500.

**The route is guarded.** A system that was never onboarded has no facilities to
hang points on; rendering an empty page would say "this system has no
facilities" when the truth is "you have not onboarded this system".
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking.models import SamplingPoint, SystemFacility, WaterSystem

PWSID = "CA1010001"


@pytest.fixture
def client_logged_in(db, django_user_model):
    user = django_user_model.objects.create(
        username="operator",
        email="operator@example.gov",
        password=make_password("pw"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def system(db):
    """Bakman, with the two facility shapes the real export carries."""
    system = WaterSystem.objects.create(pwsid=PWSID, name="BAKMAN WATER COMPANY")
    SystemFacility.objects.create(
        system=system,
        facility_id="010",
        epa_facility_id="14042",
        name="WELL 10",
        facility_type="WL",
        is_source=True,
    )
    SystemFacility.objects.create(
        system=system,
        facility_id="DST",
        epa_facility_id="25984",
        name="DISTRIBUTION SYSTEM",
        facility_type="DS",
    )
    return system


def _add(client, pwsid, facility, **fields):
    return client.post(
        reverse("drinking:onboard_points_add", args=[pwsid]),
        {"facility": facility.pk, **fields},
    )


class TestComposedCodes:
    def test_program_point_on_the_distribution_system(self, client_logged_in, system):
        """The case the whole plan turns on: LCR on DST."""
        dst = system.facilities.get(facility_id="DST")
        response = _add(
            client_logged_in, PWSID, dst,
            point_number="LCR", name="LCR Tap Sample", point_type="tap",
        )
        assert response.status_code == 200

        point = SamplingPoint.objects.get(name="LCR Tap Sample")
        assert point.ps_code == "CA1010001_DST_LCR"
        assert point.facility == dst

    def test_well_point(self, client_logged_in, system):
        well = system.facilities.get(facility_id="010")
        _add(client_logged_in, PWSID, well, point_number="010", name="WELL 10 - RAW")

        point = SamplingPoint.objects.get(name="WELL 10 - RAW")
        assert point.ps_code == "CA1010001_010_010"
        assert point.facility == well

    def test_point_is_attached_to_the_facility_it_was_added_under(
        self, client_logged_in, system
    ):
        """Two facilities, two points, no crossing over."""
        well = system.facilities.get(facility_id="010")
        dst = system.facilities.get(facility_id="DST")
        _add(client_logged_in, PWSID, well, point_number="010")
        _add(client_logged_in, PWSID, dst, point_number="900")

        assert SamplingPoint.objects.get(
            ps_code="CA1010001_010_010"
        ).facility == well
        assert SamplingPoint.objects.get(
            ps_code="CA1010001_DST_900"
        ).facility == dst

    def test_composition_uses_the_state_key_not_epas(self, client_logged_in, system):
        """Composing from epa_facility_id would build CA1010001_14042_010."""
        well = system.facilities.get(facility_id="010")
        _add(client_logged_in, PWSID, well, point_number="010")

        codes = list(SamplingPoint.objects.values_list("ps_code", flat=True))
        assert codes == ["CA1010001_010_010"]
        assert "14042" not in codes[0]


class TestDuplicates:
    def test_adding_an_existing_code_reports_and_does_not_raise(
        self, client_logged_in, system
    ):
        dst = system.facilities.get(facility_id="DST")
        _add(client_logged_in, PWSID, dst, point_number="LCR", name="LCR Tap Sample")

        # No IntegrityError, no 500 — a plain 200 carrying an explanation.
        response = _add(
            client_logged_in, PWSID, dst, point_number="LCR", name="Typed again"
        )
        assert response.status_code == 200
        assert b"already here" in response.content

        assert SamplingPoint.objects.filter(ps_code="CA1010001_DST_LCR").count() == 1
        # The skip is a skip: the first point's name is not overwritten.
        assert SamplingPoint.objects.get(
            ps_code="CA1010001_DST_LCR"
        ).name == "LCR Tap Sample"


class TestRejection:
    def test_blank_point_number_is_refused(self, client_logged_in, system):
        dst = system.facilities.get(facility_id="DST")
        response = _add(client_logged_in, PWSID, dst, point_number="   ")
        assert response.status_code == 200
        assert not SamplingPoint.objects.exists()

    def test_underscore_in_point_number_is_refused(self, client_logged_in, system):
        dst = system.facilities.get(facility_id="DST")
        response = _add(client_logged_in, PWSID, dst, point_number="9_00")
        assert response.status_code == 200
        assert not SamplingPoint.objects.exists()

    def test_facility_from_another_system_is_refused(self, client_logged_in, system):
        other = WaterSystem.objects.create(pwsid="CA9999999", name="ELSEWHERE")
        foreign = SystemFacility.objects.create(
            system=other, facility_id="001", name="NOT OURS"
        )
        response = _add(client_logged_in, PWSID, foreign, point_number="001")
        assert response.status_code == 200
        assert not SamplingPoint.objects.exists()


class TestRouteGuard:
    def test_non_onboarded_pwsid_redirects_to_the_wizard(self, client_logged_in, db):
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=["CA0000000"])
        )
        assert response.status_code == 302
        assert response.url == reverse("drinking:onboard")

    def test_system_with_no_facilities_redirects(self, client_logged_in, db):
        WaterSystem.objects.create(pwsid="CA5555555", name="BARE")
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=["CA5555555"])
        )
        assert response.status_code == 302
        assert response.url == reverse("drinking:onboard")

    def test_onboarded_system_renders_its_facilities(self, client_logged_in, system):
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        )
        assert response.status_code == 200
        # The facility id is shown because it is the middle segment of every code.
        assert b"DST" in response.content
        assert b"CA1010001_DST_" in response.content

    def test_requires_login(self, db, system):
        response = Client().get(reverse("drinking:onboard_points", args=[PWSID]))
        assert response.status_code == 302
        # Bounced to the login page, carrying the builder as `next` — not
        # served, and not silently dropped either.
        assert response.url.startswith("/accounts/login/")
        assert "next=" in response.url
