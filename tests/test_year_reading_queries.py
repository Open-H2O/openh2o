# SPDX-License-Identifier: AGPL-3.0-or-later
"""The year's pages ask the database the same number of questions however many use areas a site has.

At 8,906 use areas the dashboard asked 202,785 questions and took three and a
half minutes: it added up the year one account and one use area at a time. Each
page now reads the year once. These tests build a site of 4 use areas, accounts
and links, count the questions each page asks, grow the site to 12 and count
again: the two counts must be equal.

Questions are counted with ``connection.execute_wrapper``, which has no ceiling.
"""
from contextlib import contextmanager

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse

from accounting.statements import collect_figures
from tests import year_reading_world as world

pytestmark = pytest.mark.django_db

SMALL, LARGE = 4, 12


@contextmanager
def counted():
    found = {"queries": 0}

    def count(execute, sql, params, many, context):
        found["queries"] += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count):
        yield found


def _counts(client, period, zones):
    pages = {
        "dashboard": (reverse("accounting:dashboard"), {"period": period.pk}),
        "accounts list": (reverse("accounting:accounts_list"), {"period": period.pk}),
        "groundwater zone page": (reverse("geography:zone_detail", args=[zones["east"].pk]), {}),
        "surface zone page": (reverse("geography:zone_detail", args=[zones["west"].pk]), {}),
    }
    found = {}
    for name, (url, params) in pages.items():
        with counted() as c:
            response = client.get(url, params)
        assert response.status_code == 200, name
        found[name] = c["queries"]
    with counted() as c:
        figures = collect_figures(period)
    assert figures
    found["the year's figures"] = c["queries"]
    return found


def test_each_page_asks_the_same_number_of_questions_at_three_times_the_use_areas():
    zones = world.build_scaled_zones()
    period = world.add_scaled(zones, 0, SMALL)
    client = Client()
    client.force_login(
        get_user_model().objects.create_user(
            username="counter", email="counter@example.org", password="a-good-passw0rd", agency_admin=True
        )
    )
    _counts(client, period, zones)  # first reads fill caches that stay full
    small = _counts(client, period, zones)
    world.add_scaled(zones, SMALL, LARGE - SMALL)
    large = _counts(client, period, zones)
    grew = {name: (small[name], large[name]) for name in small if large[name] != small[name]}
    assert grew == {}, f"questions at {SMALL} and at {LARGE} use areas: {grew}"
