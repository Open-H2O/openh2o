# SPDX-License-Identifier: AGPL-3.0-or-later
"""parcels:geojson and its ``account`` parameter (ISS-175, 150-02).

The account page draws the overview map card with only that account's use
areas, so the endpoint takes ``?account=<id>``: the parcels the account holds
now through its active ``accounting.WaterAccountParcel`` rows. An integer that
names no account gives the empty FeatureCollection (200); a value that is not
an integer gives 400 with a one-line body. With no parameter the response is
the one the Use Areas overview map has always fetched, pinned here by its
shape: the same property keys, ``pk`` in properties, application/json, and the
fixture's own feature count.

Every expected value is the fixture's literal (two accounts, three located use
areas, two of them on account A), never a re-run of the view's query.
"""
import json
from datetime import date

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    ParcelFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
)

pytestmark = pytest.mark.django_db


def _login():
    from core.models import User

    user = User.objects.create(
        username="geojsonreader",
        email="geojsonreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def two_accounts():
    account_a = WaterAccountFactory(account_number="GJ-ACCT-A", name="Account A")
    account_b = WaterAccountFactory(account_number="GJ-ACCT-B", name="Account B")
    a_one = ParcelFactory(parcel_number="GJ-A-1")
    a_two = ParcelFactory(parcel_number="GJ-A-2")
    b_one = ParcelFactory(parcel_number="GJ-B-1")
    WaterAccountParcelFactory(water_account=account_a, parcel=a_one)
    WaterAccountParcelFactory(water_account=account_a, parcel=a_two)
    WaterAccountParcelFactory(water_account=account_b, parcel=b_one)
    return account_a, account_b


def _get(client, **params):
    return client.get(reverse("parcels:geojson"), params)


def _numbers(response):
    return sorted(
        f["properties"]["parcel_number"] for f in json.loads(response.content)["features"]
    )


def test_the_account_filter_returns_only_that_accounts_use_areas(two_accounts):
    account_a, _ = two_accounts
    response = _get(_login(), account=account_a.pk)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    data = json.loads(response.content)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    assert _numbers(response) == ["GJ-A-1", "GJ-A-2"]


def test_the_other_account_gets_its_own_one_use_area(two_accounts):
    _, account_b = two_accounts
    assert _numbers(_get(_login(), account=account_b.pk)) == ["GJ-B-1"]


def test_a_removed_assignment_and_an_unlocated_use_area_are_not_drawn(two_accounts):
    """The map draws what the account holds NOW (``removed_date`` empty, the
    rows the account page counts) and only what has a geometry."""
    account_a, _ = two_accounts
    WaterAccountParcelFactory(
        water_account=account_a,
        parcel=ParcelFactory(parcel_number="GJ-A-REMOVED"),
        removed_date=date(2026, 1, 15),
    )
    WaterAccountParcelFactory(
        water_account=account_a,
        parcel=ParcelFactory(parcel_number="GJ-A-NO-SHAPE", geometry=None),
    )

    assert _numbers(_get(_login(), account=account_a.pk)) == ["GJ-A-1", "GJ-A-2"]


def test_an_unknown_account_gives_the_empty_collection(two_accounts):
    response = _get(_login(), account=987654)

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []


def test_a_non_integer_account_is_a_400_with_a_one_line_body(two_accounts):
    response = _get(_login(), account="abc")

    assert response.status_code == 400
    assert response.content == b"The account parameter must be an integer id."


def test_no_parameter_returns_every_located_use_area_in_the_same_shape(two_accounts):
    response = _get(_login())

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    data = json.loads(response.content)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 3
    assert _numbers(response) == ["GJ-A-1", "GJ-A-2", "GJ-B-1"]
    for feature in data["features"]:
        assert sorted(feature["properties"]) == [
            "area_acres", "owner_name", "parcel_number", "pk", "status",
        ]
        assert feature["properties"]["pk"] == feature["id"]
