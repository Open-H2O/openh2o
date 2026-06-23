# SPDX-License-Identifier: AGPL-3.0-or-later
"""
E6 — actionable empty states. When a list screen has no records, what it shows
depends on *why* it's empty:

  * fresh instance (admin, no boundary) → defer to the Setup Wizard spine;
  * configured instance, list just empty → the screen's own Add + Import;
  * empty because of a search/filter → plain "no matches", not an onboarding CTA.

Exercised on the Wells list; all four list screens share the same partial.
"""

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import BoundaryFactory


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"emptyuser{n}")
    email = factory.Sequence(lambda n: f"emptyuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _client(**user_kwargs):
    c = Client()
    c.force_login(UserFactory(**user_kwargs))
    return c


@pytest.mark.django_db
def test_configured_empty_list_offers_add_and_import():
    """Non-admin (needs_setup never fires) with an empty list: the screen's own
    Add + Import actions, not the wizard."""
    resp = _client().get(reverse("wells:list"))
    body = resp.content.decode()
    assert "+ Add Well" in body
    assert reverse("infrastructure:add") + "?type=well" in body
    assert reverse("infrastructure:import") + "?type=well" in body
    assert "groundwater extraction points" in body  # the plain-English description
    assert "Set up your watershed" not in body


@pytest.mark.django_db
def test_fresh_instance_defers_to_setup_wizard():
    """Admin on an instance with no boundary: the empty list points at the
    Setup Wizard (the onboarding spine), not a per-screen add."""
    resp = _client(is_staff=True).get(reverse("wells:list"))
    body = resp.content.decode()
    assert "Set up your watershed" in body
    assert reverse("setup:wizard") in body
    assert "+ Add Well" not in body


@pytest.mark.django_db
def test_admin_with_boundary_is_not_fresh():
    """Once a boundary exists the instance isn't fresh, so even an admin sees the
    per-screen Add/Import rather than the wizard CTA."""
    BoundaryFactory()
    resp = _client(is_staff=True).get(reverse("wells:list"))
    body = resp.content.decode()
    assert "Set up your watershed" not in body
    assert "+ Add Well" in body


@pytest.mark.django_db
def test_search_miss_keeps_plain_no_match():
    """An empty result from a *search* is not an onboarding moment."""
    resp = _client().get(reverse("wells:list"), {"q": "zzznomatch"})
    body = resp.content.decode()
    assert "No wells found matching" in body
    assert "+ Add Well" not in body
    assert "Set up your watershed" not in body
