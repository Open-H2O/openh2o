# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The facility pages and the Add a water system page, four defects.

**A site keeps one water system's records.** Add a water system turns down a
PWSID that is not the site's existing system, before it asks EPA anything, and
says which system the site keeps. The same PWSID again is a refresh and still
reaches the review. Every fetch is patched to raise, so a refusal that reaches
the network fails here by name.

**The count line counts what is a source.** A storage tank or a clear well is a
facility, not a source; it is counted as "other".

**The facility form prints every field's errors.**

**Add facility says what it is on a site with no water system.**
"""

import re

import factory
import pytest
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import envirofacts
from drinking.models import SystemFacility, WaterSystem
from drinking.views import onboard
from tests.factories import SystemFacilityFactory, WaterSystemFactory


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"facilities05{n}")
    email = factory.Sequence(lambda n: f"facilities05{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _text(response):
    html = response.content.decode()
    html = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture
def no_federal_call(monkeypatch):
    """Any call to EPA fails the test; a refusal must happen before one."""

    def boom(*args, **kwargs):
        raise AssertionError("the view asked EPA before it refused")

    for name in ("fetch_water_system", "fetch_facilities", "fetch_geographic_area"):
        monkeypatch.setattr(envirofacts, name, boom)


@pytest.fixture
def site_system(db):
    return WaterSystemFactory(pwsid="CA5500001", name="Alder Water Company")


# -- Add a water system: one system per site ---------------------------------


class TestOneWaterSystemPerSite:
    def test_lookup_of_a_second_pwsid_is_turned_down_before_any_call(
        self, client_in, site_system, no_federal_call
    ):
        response = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": "ca5500002"}
        )
        assert response.status_code == 200
        text = _text(response)
        assert "Alder Water Company" in text
        assert "CA5500001" in text
        assert "keeps the records of one water system" in text
        assert WaterSystem.objects.count() == 1
        assert onboard.SESSION_KEY_ONBOARD_PWSID not in client_in.session

    def test_commit_of_a_second_pwsid_is_turned_down_before_any_call(
        self, client_in, site_system, no_federal_call
    ):
        # A review opened in another tab before the site had a system.
        session = client_in.session
        session[onboard.SESSION_KEY_ONBOARD_PWSID] = "CA5500002"
        session.save()
        client_in.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        response = client_in.post(reverse("drinking:onboard_commit"))
        assert response.status_code == 200
        text = _text(response)
        assert "Alder Water Company" in text
        assert "keeps the records of one water system" in text
        assert WaterSystem.objects.count() == 1
        assert WaterSystem.objects.filter(pwsid="CA5500002").count() == 0

    def test_the_same_pwsid_again_still_reaches_the_review(
        self, client_in, site_system, monkeypatch
    ):
        calls = []

        def fetch_system(pwsid, refresh=False):
            calls.append(pwsid)
            return {
                "pwsid": pwsid,
                "pws_name": "ALDER WATER COMPANY",
                "pws_activity_code": "A",
                "pws_type_code": "CWS",
                "primary_source_code": "GW",
            }

        monkeypatch.setattr(envirofacts, "fetch_water_system", fetch_system)
        monkeypatch.setattr(envirofacts, "fetch_facilities", lambda p, refresh=False: [])
        monkeypatch.setattr(envirofacts, "fetch_geographic_area", lambda p, refresh=False: {})
        response = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": "ca5500001"}
        )
        assert response.status_code == 200
        assert calls == ["CA5500001"]
        assert "keeps the records of one water system" not in _text(response)
        assert client_in.session[onboard.SESSION_KEY_ONBOARD_PWSID] == "CA5500001"

    def test_a_site_with_no_system_takes_any_pwsid_to_the_lookup(
        self, client_in, monkeypatch
    ):
        asked = []

        def fetch_system(pwsid, refresh=False):
            asked.append(pwsid)
            raise envirofacts.PwsidNotFound("none")

        monkeypatch.setattr(envirofacts, "fetch_water_system", fetch_system)
        client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "CA5500009"})
        assert asked == ["CA5500009"]

    def test_the_page_says_which_system_the_site_keeps(self, client_in, site_system):
        text = _text(client_in.get(reverse("drinking:onboard")))
        assert "Alder Water Company" in text
        assert "keeps the records of one water system" in text

    def test_the_page_is_unchanged_on_a_site_with_no_system(self, client_in):
        text = _text(client_in.get(reverse("drinking:onboard")))
        assert "keeps the records of one water system" not in text

    def test_add_facility_keeps_adding_to_that_one_system(self, client_in, site_system):
        response = client_in.post(
            reverse("drinking:facility_add"),
            {
                "facility_id": "901",
                "name": "",
                "local_name": "Back well",
                "facility_type": "WL",
                "activity_status": "A",
                "water_type": "GW",
                "is_source": "on",
            },
        )
        assert response.status_code == 302
        assert SystemFacility.objects.get(facility_id="901").system == site_system


# -- the count line ----------------------------------------------------------


class TestTheCountLine:
    def _mix(self):
        system = WaterSystemFactory()
        for facility_id, facility_type, is_source in (
            ("001", "WL", True),
            ("002", "ST", False),
            ("003", "CW", False),
            ("004", "TP", False),
            ("005", "DS", False),
        ):
            SystemFacilityFactory(
                system=system, facility_id=facility_id,
                facility_type=facility_type, is_source=is_source,
            )

    def test_storage_and_clear_well_are_other_not_sources(self, client_in):
        self._mix()
        text = _text(client_in.get(reverse("drinking:facilities")))
        assert (
            "5 facilities: 1 source, 1 treatment plant, 1 distribution system, 2 other"
        ) in re.sub(r"\s+,", ",", text)

    def test_other_is_left_off_when_there_are_none(self, client_in):
        system = WaterSystemFactory()
        SystemFacilityFactory(system=system, facility_type="WL", is_source=True)
        SystemFacilityFactory(system=system, facility_type="TP", is_source=False)
        text = re.sub(r"\s+,", ",", _text(client_in.get(reverse("drinking:facilities"))))
        assert "2 facilities: 1 source, 1 treatment plant, 0 distribution systems" in text
        assert " other" not in text.split("2 facilities:")[1][:120]

    def test_the_count_is_one_query(self, client_in, django_assert_num_queries):
        from drinking.views.facilities import _facility_population_counts

        self._mix()
        with django_assert_num_queries(1):
            counts = _facility_population_counts(SystemFacility.objects.all())
        assert tuple(counts) == (1, 1, 1, 2)


# -- the form prints every field's errors ------------------------------------


class TestTheFormPrintsEveryError:
    def _post(self, client, **over):
        data = {
            "facility_id": "777",
            "name": "",
            "local_name": "",
            "facility_type": "WL",
            "activity_status": "A",
            "water_type": "GW",
            "is_source": "on",
        }
        data.update(over)
        return client.post(reverse("drinking:facility_add"), data)

    @pytest.mark.parametrize(
        "field", ["facility_type", "water_type", "activity_status"]
    )
    def test_an_invalid_choice_prints_next_to_its_field(
        self, client_in, site_system, field
    ):
        response = self._post(client_in, **{field: "ZZ"})
        assert response.status_code == 200
        form = response.context["form"]
        assert form.errors[field]
        html = response.content.decode()
        group = re.search(
            rf'id="{form[field].id_for_label}".*?(?=<div class="form-group|<div class="form-footer)',
            html,
            re.S,
        )
        assert group is not None
        assert "form-error-text" in group.group(0)
        assert "Select a valid choice" in group.group(0)

    def test_the_invalid_well_prints_next_to_the_well(self, client_in, site_system):
        response = self._post(client_in, well="999999")
        form = response.context.get("form")
        if form is None or "well" not in form.fields:
            pytest.skip("this module set offers no well link")
        assert form.errors["well"]
        html = response.content.decode()
        tail = html.split(f'id="{form["well"].id_for_label}"')[1]
        assert "form-error-text" in tail.split('class="form-footer"')[0]

    def test_the_edit_form_of_an_epa_facility_prints_its_errors(
        self, client_in, site_system
    ):
        facility = SystemFacilityFactory(
            system=site_system, facility_id="321", added_by_hand=False
        )
        response = client_in.post(
            reverse("drinking:facility_edit", args=[facility.pk]),
            {"local_name": "x" * 400},
        )
        assert response.status_code == 200
        assert "form-error-text" in response.content.decode()


# -- Add facility on a site with no system -----------------------------------


class TestAddFacilityWithNoSystem:
    def test_the_page_carries_a_description(self, client_in):
        assert WaterSystem.objects.count() == 0
        html = client_in.get(reverse("drinking:facility_add")).content.decode()
        found = re.findall(r'<p class="page-description">(.*?)</p>', html, re.S)
        assert found and found[0].strip()
