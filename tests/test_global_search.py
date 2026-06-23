# SPDX-License-Identifier: AGPL-3.0-or-later
"""
E2 — global search. Exercises ``config.views.global_search``: the min-length
gate, per-entity matching across the six primary record types, the grouped
result shape, and that each hit routes to its own detail screen.
"""

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    ParcelFactory,
    PointOfDiversionFactory,
    WaterAccountFactory,
    WellFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"searchuser{n}")
    email = factory.Sequence(lambda n: f"searchuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(UserFactory())
    return c


def _search(client, q):
    return client.get(reverse("global_search"), {"q": q})


def _group(resp, key):
    """Return the result group with the given entity key, or None."""
    for g in resp.context["groups"]:
        if g["key"] == key:
            return g
    return None


@pytest.mark.django_db
def test_requires_login():
    """Search is behind login, like every other record view."""
    resp = Client().get(reverse("global_search"), {"q": "anything"})
    assert resp.status_code == 302
    assert "/accounts/login" in resp.url


@pytest.mark.django_db
def test_short_query_returns_nothing(auth_client):
    """A one-character query stays below the gate, so the dropdown is empty."""
    ParcelFactory(parcel_number="MER-APN-014")
    resp = _search(auth_client, "M")
    assert resp.status_code == 200
    assert resp.context["groups"] == []
    assert resp.context["total"] == 0


@pytest.mark.django_db
def test_parcel_match_by_number_routes_to_detail(auth_client):
    parcel = ParcelFactory(parcel_number="MER-APN-014", owner_name="Rivera")
    resp = _search(auth_client, "apn-014")  # case-insensitive
    group = _group(resp, "parcels")
    assert group is not None
    result = group["results"][0]
    assert result["label"] == "MER-APN-014"
    assert result["url"] == reverse("parcels:detail", args=[parcel.pk])
    # The detail link is rendered into the dropdown markup.
    assert result["url"].encode() in resp.content


@pytest.mark.django_db
def test_parcel_match_by_owner_name(auth_client):
    ParcelFactory(parcel_number="MER-APN-099", owner_name="Singh Family Trust")
    resp = _search(auth_client, "singh")
    group = _group(resp, "parcels")
    assert group is not None
    assert group["results"][0]["sublabel"] == "Singh Family Trust"


@pytest.mark.django_db
def test_spans_multiple_entities(auth_client):
    """One shared token surfaces every entity type that matched, each its own group."""
    WellFactory(name="Zebra Well")
    WaterAccountFactory(name="Zebra Farms", account_number="ACCT-ZEB")
    ZoneFactory(name="Zebra Zone")
    PointOfDiversionFactory(name="Zebra Diversion")

    resp = _search(auth_client, "zebra")
    keys = {g["key"] for g in resp.context["groups"]}
    assert keys == {"wells", "accounts", "zones", "surface"}
    assert resp.context["total"] == 4


@pytest.mark.django_db
def test_no_match_renders_empty_state(auth_client):
    ParcelFactory(parcel_number="MER-APN-014")
    resp = _search(auth_client, "qqzzxx")
    assert resp.context["groups"] == []
    assert b"No matches" in resp.content


@pytest.mark.django_db
def test_per_group_cap(auth_client):
    """A flood of matches is capped per group so the dropdown stays scannable."""
    for i in range(10):
        ParcelFactory(parcel_number=f"FLOOD-{i:03d}")
    resp = _search(auth_client, "flood")
    group = _group(resp, "parcels")
    assert len(group["results"]) == 6  # SEARCH_GROUP_LIMIT
