# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-04 Task 3 (D9): a facility the operator adds by hand, with its local name.

Until this plan a ``SystemFacility`` was written only by Envirofacts onboarding,
so a source the district engineer had just assigned an id to did not exist in
the product until EPA published it. Shape 2's walk (Le Grand CSD) needed the
operator's own name for a source beside the state's padded one (the memo's J8:
"Cedar Well 02", the state's "WL 002 CEDAR WELL 02").

What is pinned here:

* the add form renders and saves on the shape-2 module set (no ``wells``, no
  ``parcels``, no ``accounting``) with no well field in it, and on the full set
  with the well field present and saved;
* a hand-added facility says so wherever the federal record's label would
  otherwise claim it;
* the local name shows beside the state's name in the list and on the
  facility's own page;
* editing a facility the federal record wrote changes only what the operator
  owns (the local name, and the well link where ``wells`` is on); the state's
  fields stay the state's.
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core import modules as mod
from drinking import provenance
from drinking.models import SystemFacility, WaterSystem
from tests.factories import (
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

# Shape 2's module list, as the six-shapes study stood it up (146-01's recipe).
SHAPE_2 = [
    "core", "geography", "measurements", "standards", "drinking", "setup",
    "infrastructure", "health", "feedback",
]


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"facdoor{n}")
    email = factory.Sequence(lambda n: f"facdoor{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def system(db):
    """Le Grand, and only Le Grand.

    The views read the deployment's one system (lowest PWSID), and
    ``tests/test_merced_drinking_seed.py`` seeds City of Merced (CA2410009)
    outside any test transaction, where it outlives its module. Cleared here
    the way ``tests/test_production_import.py`` clears it.
    """
    WaterSystem.objects.all().delete()
    return WaterSystemFactory(pwsid="CA2410011", name="LE GRAND CSD")


@pytest.fixture
def shape_2(settings):
    compose_urlconf_under_the_full_module_set()
    settings.OPENH2O_MODULES = SHAPE_2


def _cedar_post(**overrides):
    data = {
        "facility_id": "007",
        "name": "WL 007 CEDAR WELL 02",
        "local_name": "Cedar Well 02",
        "facility_type": "WL",
        "activity_status": "A",
        "is_source": "on",
        "water_type": "GW",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# The door on the shape-2 module set
# ---------------------------------------------------------------------------


class TestAddOnShape2:
    def test_the_module_set_really_leaves_wells_out(self, shape_2):
        assert not mod.is_enabled("wells")
        assert not mod.is_enabled("parcels")
        assert mod.is_enabled("drinking")

    def test_the_form_renders_with_a_local_name_and_no_well_field(
        self, shape_2, client_in, system
    ):
        response = client_in.get(reverse("drinking:facility_add"))
        assert response.status_code == 200
        html = response.content.decode()
        assert 'name="local_name"' in html
        assert 'name="facility_id"' in html
        assert 'name="well"' not in html

    def test_a_facility_added_by_hand_is_saved_with_its_local_name(
        self, shape_2, client_in, system
    ):
        response = client_in.post(reverse("drinking:facility_add"), _cedar_post())
        facility = SystemFacility.objects.get(system=system, facility_id="007")
        assert response.status_code == 302
        assert response.url == reverse("drinking:facility_detail", args=[facility.pk])
        assert facility.local_name == "Cedar Well 02"
        assert facility.name == "WL 007 CEDAR WELL 02"
        assert facility.added_by_hand is True
        assert facility.well is None

    def test_the_list_shows_the_local_name_beside_the_states(
        self, shape_2, client_in, system
    ):
        client_in.post(reverse("drinking:facility_add"), _cedar_post())
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        assert "Cedar Well 02" in html
        assert "the state&#x27;s WL 007 CEDAR WELL 02" in html or (
            "the state's WL 007 CEDAR WELL 02" in html
        )

    def test_the_facility_page_shows_the_local_name_and_who_entered_it(
        self, shape_2, client_in, system
    ):
        client_in.post(reverse("drinking:facility_add"), _cedar_post())
        facility = SystemFacility.objects.get(facility_id="007")
        html = client_in.get(
            reverse("drinking:facility_detail", args=[facility.pk])
        ).content.decode()
        assert "Local name" in html
        assert "Cedar Well 02" in html
        # The identity card's publisher is the operator, not EPA: a
        # hand-typed row labelled "EPA Envirofacts (SDWIS)" would be a
        # provenance claim nobody made.
        assert provenance.OPERATOR_ENTERED in html
        assert provenance.EPA_SDWIS not in html

    def test_the_list_offers_the_door(self, shape_2, client_in, system):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        assert reverse("drinking:facility_add") in html
        assert "+ Add facility" in html


# ---------------------------------------------------------------------------
# The door on the full module set
# ---------------------------------------------------------------------------


class TestAddOnTheFullSet:
    def test_the_form_carries_the_well_field(self, client_in, system):
        assert mod.is_enabled("wells")
        html = client_in.get(reverse("drinking:facility_add")).content.decode()
        assert 'name="well"' in html

    def test_the_well_link_is_saved(self, client_in, system):
        well = WellFactory(name="MER-PWS-099")
        client_in.post(
            reverse("drinking:facility_add"), _cedar_post(well=str(well.pk))
        )
        assert SystemFacility.objects.get(facility_id="007").well == well


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    def test_the_facility_id_is_required(self, client_in, system):
        response = client_in.post(
            reverse("drinking:facility_add"), _cedar_post(facility_id="")
        )
        assert response.status_code == 200
        assert not SystemFacility.objects.exists()

    def test_an_id_the_system_already_carries_is_refused_by_name(
        self, client_in, system
    ):
        SystemFacilityFactory(system=system, facility_id="007")
        response = client_in.post(reverse("drinking:facility_add"), _cedar_post())
        assert response.status_code == 200
        assert SystemFacility.objects.filter(facility_id="007").count() == 1
        assert "007" in response.content.decode()
        assert "already" in response.content.decode()

    def test_no_system_yet_says_onboard_first(self, client_in, db):
        WaterSystem.objects.all().delete()  # see the `system` fixture
        response = client_in.get(reverse("drinking:facility_add"))
        assert response.status_code == 200
        html = response.content.decode()
        assert reverse("drinking:onboard") in html
        assert 'name="facility_id"' not in html

    def test_anonymous_users_are_turned_away(self, db, system):
        response = Client().get(reverse("drinking:facility_add"))
        assert response.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


class TestEdit:
    def test_a_federal_facility_edits_only_what_the_operator_owns(
        self, client_in, system
    ):
        facility = SystemFacilityFactory(
            system=system, facility_id="002", name="WELL 01A",
            facility_type="WL", activity_status="A",
        )
        url = reverse("drinking:facility_edit", args=[facility.pk])
        html = client_in.get(url).content.decode()
        assert 'name="local_name"' in html
        # By id, not by name: the page's feedback widget carries its own
        # name="name" input.
        assert 'id="id_facility_id"' not in html
        assert 'id="id_name"' not in html

        response = client_in.post(url, {
            "local_name": "Well 1A by the tank",
            "name": "SOMETHING ELSE",
            "facility_id": "999",
        })
        assert response.status_code == 302
        facility.refresh_from_db()
        assert facility.local_name == "Well 1A by the tank"
        assert facility.name == "WELL 01A"
        assert facility.facility_id == "002"
        assert facility.added_by_hand is False

    def test_a_hand_added_facility_edits_every_field(
        self, shape_2, client_in, system
    ):
        client_in.post(reverse("drinking:facility_add"), _cedar_post())
        facility = SystemFacility.objects.get(facility_id="007")
        url = reverse("drinking:facility_edit", args=[facility.pk])
        client_in.post(url, _cedar_post(name="WL 007 CEDAR WELL 2", activity_status="I"))
        facility.refresh_from_db()
        assert facility.name == "WL 007 CEDAR WELL 2"
        assert facility.activity_status == "I"
        assert facility.added_by_hand is True

    def test_the_facility_page_links_its_edit(self, client_in, system):
        facility = SystemFacilityFactory(system=system, facility_id="002")
        html = client_in.get(
            reverse("drinking:facility_detail", args=[facility.pk])
        ).content.decode()
        assert reverse("drinking:facility_edit", args=[facility.pk]) in html
