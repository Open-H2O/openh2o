# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 Task 3 (Q5): the zone's jurisdiction attribute.

Proven here, each RED against the unfixed tree (quotes in 146-05-EVIDENCE.md):

  1. The flag without a stated legal basis is refused, at the model
     (``Zone.clean()``) and through the edit form (``ZoneForm``).
  2. The zone page shows the flag and its basis when set, and nothing at all
     when not (the plan's own words: "nothing when not", never "Not recorded").
  3. A zone edit route exists (``/map/zones/<pk>/edit/``) where none did
     before -- only ``zone_recovery_horizon``, a single-field HTMX control,
     not a general edit form.

Both new fields are plain columns on ``Zone``; neither crosses into another
module, so the composition rule does not apply here (unlike Q8's account
fields, covered in ``tests/test_account_unit_kind.py``).
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from geography.models import Zone
from tests.factories import ZoneFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"zonejurisdictionuser{n}")
    email = factory.Sequence(lambda n: f"zonejurisdictionuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. The flag requires a stated basis
# ---------------------------------------------------------------------------


def test_model_clean_refuses_the_flag_with_no_basis():
    zone = ZoneFactory(subsurface_supply_is_diversion=True, legal_basis="")
    with pytest.raises(ValidationError):
        zone.clean()


def test_model_clean_refuses_whitespace_only_basis():
    zone = ZoneFactory(subsurface_supply_is_diversion=True, legal_basis="   ")
    with pytest.raises(ValidationError):
        zone.clean()


def test_model_clean_accepts_the_flag_with_a_basis():
    zone = ZoneFactory(
        subsurface_supply_is_diversion=True,
        legal_basis="The Delta case, cited on the record.",
    )
    zone.clean()  # does not raise


def test_model_clean_accepts_the_flag_unset_with_no_basis():
    zone = ZoneFactory(subsurface_supply_is_diversion=False, legal_basis="")
    zone.clean()  # does not raise


def test_zone_edit_form_refuses_the_flag_with_no_basis(auth_client):
    zone = ZoneFactory()
    resp = auth_client.post(
        reverse("geography:zone_edit", args=[zone.pk]),
        {
            "name": zone.name,
            "zone_type": zone.zone_type,
            "description": "",
            "subsurface_supply_is_diversion": "on",
            "legal_basis": "",
        },
    )
    assert resp.status_code == 200  # re-rendered with the error, not redirected
    assert "legal basis" in resp.content.decode().lower()
    zone.refresh_from_db()
    assert zone.subsurface_supply_is_diversion is False


def test_zone_edit_form_saves_the_flag_with_a_basis(auth_client):
    zone = ZoneFactory()
    resp = auth_client.post(
        reverse("geography:zone_edit", args=[zone.pk]),
        {
            "name": zone.name,
            "zone_type": zone.zone_type,
            "description": "",
            "subsurface_supply_is_diversion": "on",
            "legal_basis": "The Delta case, cited on the record.",
        },
    )
    assert resp.status_code == 302
    zone.refresh_from_db()
    assert zone.subsurface_supply_is_diversion is True
    assert zone.legal_basis == "The Delta case, cited on the record."


def test_zone_edit_form_clears_the_flag(auth_client):
    zone = ZoneFactory(
        subsurface_supply_is_diversion=True, legal_basis="The Delta case."
    )
    resp = auth_client.post(
        reverse("geography:zone_edit", args=[zone.pk]),
        {
            "name": zone.name,
            "zone_type": zone.zone_type,
            "description": "",
            # No `subsurface_supply_is_diversion` key: an unchecked checkbox
            # posts nothing.
            "legal_basis": "",
        },
    )
    assert resp.status_code == 302
    zone.refresh_from_db()
    assert zone.subsurface_supply_is_diversion is False


# ---------------------------------------------------------------------------
# 2. The zone page: the flag and basis when set, nothing when not
# ---------------------------------------------------------------------------


def test_zone_page_shows_nothing_when_the_flag_is_not_set(auth_client):
    zone = ZoneFactory()
    body = auth_client.get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert "Subsurface supply" not in body


def test_zone_page_shows_the_flag_and_basis_when_set(auth_client):
    zone = ZoneFactory(
        subsurface_supply_is_diversion=True,
        legal_basis="The Delta case, cited on the record.",
    )
    body = auth_client.get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert "Subsurface supply" in body
    assert "The Delta case, cited on the record." in body


# ---------------------------------------------------------------------------
# 3. The edit route
# ---------------------------------------------------------------------------


def test_zone_edit_route_exists_and_renders_the_form(auth_client):
    zone = ZoneFactory()
    resp = auth_client.get(reverse("geography:zone_edit", args=[zone.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="subsurface_supply_is_diversion"' in body
    assert 'name="legal_basis"' in body


def test_zone_detail_page_links_to_the_edit_route(auth_client):
    zone = ZoneFactory()
    body = auth_client.get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert reverse("geography:zone_edit", args=[zone.pk]) in body
