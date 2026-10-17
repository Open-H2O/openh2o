# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The zone edit form (146-05 Task 3), without the Delta checkbox.

146-05 added a zone edit route with a jurisdiction checkbox ("water reaching a
crop from below is a diversion ... (the Delta case)") and a legal basis box.
No calculation ever read either, and no zone ever set the box; both were removed
on 2026-10-12, Phase 150.5-01. The edit route
stays.
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from geography.models import Zone
from tests.factories import ZoneFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"zoneedituser{n}")
    email = factory.Sequence(lambda n: f"zoneedituser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


def test_zone_has_no_subsurface_rule_columns():
    names = {f.name for f in Zone._meta.get_fields()}
    assert "subsurface_supply_is_diversion" not in names
    assert "legal_basis" not in names


def test_zone_edit_route_renders_the_form_without_the_checkbox(auth_client):
    zone = ZoneFactory()
    resp = auth_client.get(reverse("geography:zone_edit", args=[zone.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="name"' in body
    assert "subsurface_supply_is_diversion" not in body
    assert 'name="legal_basis"' not in body
    assert "Delta case" not in body


def test_zone_create_page_has_no_jurisdiction_card(auth_client):
    body = auth_client.get(reverse("geography:zone_create")).content.decode()
    assert "subsurface_supply_is_diversion" not in body
    assert "Delta case" not in body


def test_zone_edit_form_saves(auth_client):
    zone = ZoneFactory()
    resp = auth_client.post(
        reverse("geography:zone_edit", args=[zone.pk]),
        {"name": "Renamed zone", "zone_type": zone.zone_type, "description": ""},
    )
    assert resp.status_code == 302
    zone.refresh_from_db()
    assert zone.name == "Renamed zone"


def test_zone_page_has_no_subsurface_line(auth_client):
    zone = ZoneFactory()
    body = auth_client.get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert "Subsurface supply" not in body


def test_zone_detail_page_links_to_the_edit_route(auth_client):
    zone = ZoneFactory()
    body = auth_client.get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert reverse("geography:zone_edit", args=[zone.pk]) in body
