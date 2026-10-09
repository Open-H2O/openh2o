# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account's map (ISS-175, 150-02).

Brent, 2026-09-16 18:49: "The map of the features owned by the account seems
very useful." The standalone account page draws the 143-07 overview map card
with only that account's use areas: the shared card head, then the map host,
and the shared ``parcels/partials/_parcels_overview_map.html`` fetching
``parcels:geojson?account=<pk>``. The accounts workspace swaps the same pane
fragment in over HTMX and loads no map library, so there the card is left out.

Rendered with rows (the 89-03 lesson): an account that holds use areas. Every
expected string is the fixture's own literal.
"""
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

MAP_HOST = 'id="account-use-areas-map"'
SWATCH = '<span class="swatch-fill" style="color: var(--color-entity-blue);"></span>Use area'


def _login():
    from core.models import User

    user = User.objects.create(
        username="accountmapreader",
        email="accountmapreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def account_with_two_use_areas():
    account = WaterAccountFactory(account_number="MAP-ACCT-1", name="Map Account")
    WaterAccountParcelFactory(
        water_account=account, parcel=ParcelFactory(parcel_number="MAP-APN-1")
    )
    WaterAccountParcelFactory(
        water_account=account, parcel=ParcelFactory(parcel_number="MAP-APN-2")
    )
    # Another account's use area: never part of this page's counts.
    WaterAccountParcelFactory(
        water_account=WaterAccountFactory(account_number="MAP-ACCT-2"),
        parcel=ParcelFactory(parcel_number="MAP-APN-OTHER"),
    )
    return account


def _page(client, account, **headers):
    return client.get(
        reverse("accounting:account_detail", args=[account.pk]), **headers
    ).content.decode()


def test_the_page_draws_the_use_area_card_for_the_account(account_with_two_use_areas):
    account = account_with_two_use_areas
    body = _page(_login(), account)

    assert '<h2 class="section-header-flush">Use areas</h2>' in body
    assert "<span>2 use areas, all on the map</span>" in body
    assert SWATCH in body
    assert MAP_HOST in body
    assert f"fetch('/parcels/geojson/?account={account.pk}')" in body


def test_the_page_loads_the_map_library_and_frames_every_feature(
    account_with_two_use_areas,
):
    body = _page(_login(), account_with_two_use_areas)

    assert "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js" in body
    assert "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" in body
    assert "map-core" in body
    # No list on this page to follow: the map frames what it loaded.
    assert "OH2O.followResults(" not in body
    assert "OH2O._geojsonBounds(data)" in body


def test_the_count_line_says_how_many_are_on_the_map(account_with_two_use_areas):
    account = account_with_two_use_areas
    WaterAccountParcelFactory(
        water_account=account,
        parcel=ParcelFactory(parcel_number="MAP-APN-NO-SHAPE", geometry=None),
    )
    body = _page(_login(), account)

    assert "<span>3 use areas, 2 of them on the map</span>" in body
    assert MAP_HOST in body


def test_the_workspace_pane_fragment_carries_no_map(account_with_two_use_areas):
    """The HTMX request to the same URL is the accounts workspace's pane, a
    page with no map library loaded: the card is left out entirely."""
    body = _page(_login(), account_with_two_use_areas, HTTP_HX_REQUEST="true")

    assert "Account information" in body, "the pane fragment did not render"
    assert MAP_HOST not in body
    assert "account-use-areas-map-head" not in body
    assert "geojson" not in body


def test_an_account_with_no_use_area_shows_no_map_card():
    account = WaterAccountFactory(account_number="MAP-ACCT-EMPTY", name="Empty Account")
    body = _page(_login(), account)

    assert "Account information" in body
    assert "account-use-areas-map-head" not in body
    assert "maplibre-gl.js" not in body
