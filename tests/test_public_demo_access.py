# SPDX-License-Identifier: AGPL-3.0-or-later
"""The open-demo access rule: ``core.access.public_in_open_demo``.

An anonymous prospect evaluating the platform on the live demo
(``ACCESS_CONTROL_ENFORCED=False``) may read the Help explainers, the
glossary, the map page and the GeoJSON layers that draw it. On an agency
deployment (the default, ``True``) every one of these routes requires login
exactly as it did before the decorator existed.

Both directions are asserted over the SAME url list, so a route can never be
opened for agencies by accident without this file going red.
"""

import pytest
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

#: Every route the open demo shows an anonymous visitor. Read-only surfaces
#: only — nothing here writes, and nothing here is per-user.
DEMO_PUBLIC_URL_NAMES = (
    "getting_started",
    "glossary",
    "budgets_allocations",
    "surface_deliveries",
    "water_balances",
    "methods",
    "settings_explained",
    "geography:map",
    "geography:boundaries_geojson",
    "geography:flowlines_geojson",
    "geography:zones_geojson",
    "geography:zone_labels_geojson",
    "geography:tie_lines_geojson",
    "parcels:geojson",
    "wells:geojson",
    "surface:pods_geojson",
    "recharge:sites_geojson",
    "datasync:stations_geojson",
    "drinking:facilities_geojson",
)


def _urls():
    return [reverse(name) for name in DEMO_PUBLIC_URL_NAMES]


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_open_demo_serves_anonymous_visitors():
    c = Client()
    for url in _urls():
        response = c.get(url)
        assert response.status_code == 200, (
            f"anonymous visitor blocked from {url} on the open demo"
        )


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_agency_deployment_still_requires_login():
    c = Client()
    for url in _urls():
        response = c.get(url)
        assert response.status_code == 302, (
            f"anonymous visitor reached {url} on an enforced deployment"
        )
        assert "/accounts/login/" in response["Location"], (
            f"{url} redirected somewhere other than login: {response['Location']}"
        )
