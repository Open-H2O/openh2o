# SPDX-License-Identifier: AGPL-3.0-or-later
"""The monitoring dashboard's satellite-allowance card (ISS-128).

The card used to read "380 of 400 monthly budget used" on a demonstration that
had spent nothing, against an allowance that was really 100. Both numbers are
now real. This file holds the third thing the fix needs, which is not a number
at all: the reader must be able to see WHICH of two sources the figure came
from, because a figure whose provenance is invisible is one nobody can act on.

Every provider read is mocked. No test here touches the network.
"""

from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from datasync.models import OpenETCache

PROVIDER_ANSWERED = {
    "source": "provider",
    "limit": 100,
    "used": 12,
    "tier": 1,
    "reason": "",
}
PROVIDER_UNREACHABLE = {
    "source": "fallback",
    "limit": 100,
    "used": None,
    "tier": None,
    "reason": "OpenET could not be reached",
}


@pytest.fixture
def client_logged_in(db):
    from core.models import User

    user = User.objects.create(
        username="iss128-reader", email="iss128-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


def _dashboard(client, status):
    with patch(
        "datasync.adapters.openet.OpenETAdapter.account_status", return_value=status
    ):
        return client.get(reverse("datasync:monitoring_dashboard"))


@pytest.mark.django_db
class TestTheCardSaysWhereTheNumberCameFrom:
    def test_provider_sourced_says_openet_counted_it(self, client_logged_in):
        body = _dashboard(client_logged_in, PROVIDER_ANSWERED).content.decode()
        assert "Counted by OpenET" in body
        assert "tier 1" in body
        assert "Counted here" not in body

    def test_fallback_sourced_says_it_was_counted_here_and_why(self, client_logged_in):
        body = _dashboard(client_logged_in, PROVIDER_UNREACHABLE).content.decode()
        assert "Counted here" in body
        assert "could not be reached" in body
        assert "Counted by OpenET" not in body

    def test_the_two_states_are_distinguishable(self, client_logged_in):
        provider = _dashboard(client_logged_in, PROVIDER_ANSWERED).content.decode()
        fallback = _dashboard(client_logged_in, PROVIDER_UNREACHABLE).content.decode()
        assert provider != fallback

    def test_it_says_when_the_allowance_resets(self, client_logged_in):
        body = _dashboard(client_logged_in, PROVIDER_ANSWERED).content.decode()
        assert "resets on the 1st" in body


@pytest.mark.django_db
class TestTheFiguresAreTheRightOnes:
    def test_the_provider_figures_win_when_the_provider_answers(
        self, client_logged_in
    ):
        resp = _dashboard(client_logged_in, PROVIDER_ANSWERED)
        assert resp.context["openet_used"] == 12
        assert resp.context["openet_limit"] == 100
        assert resp.context["openet_remaining"] == 88

    def test_the_local_count_is_used_when_the_provider_is_silent(
        self, client_logged_in, settings
    ):
        settings.OPENET_MONTHLY_BUDGET = 100
        resp = _dashboard(client_logged_in, PROVIDER_UNREACHABLE)
        assert resp.context["openet_used"] == OpenETCache.monthly_query_count()
        assert resp.context["openet_limit"] == 100

    def test_a_fixture_seeded_demonstration_reports_nothing_spent(
        self, client_logged_in, settings
    ):
        """The whole defect, at the screen. 380 rows loaded, zero spent."""
        from django.contrib.gis.geos import MultiPolygon, Polygon
        from datetime import date

        from parcels.models import Parcel

        settings.OPENET_MONTHLY_BUDGET = 100
        geometry = MultiPolygon(
            Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326
        )
        parcel = Parcel.objects.create(
            parcel_number="MER-8001", geometry=geometry, status="active"
        )
        for day in range(1, 21):
            OpenETCache.objects.create(
                parcel=parcel,
                geometry=geometry,
                start_date=date(2024, 1, day),
                end_date=date(2024, 12, 31),
                variable="ET",
                model_name=f"Ensemble-{day}",
                et_data=[],
                origin="fixture",
            )

        resp = _dashboard(client_logged_in, PROVIDER_UNREACHABLE)
        assert OpenETCache.objects.count() == 20
        assert resp.context["openet_used"] == 0


@pytest.mark.django_db
class TestARunningLowAllowanceIsBurntOrangeNotRed:
    def test_plenty_left_is_not_flagged(self, client_logged_in):
        resp = _dashboard(client_logged_in, PROVIDER_ANSWERED)
        assert resp.context["openet_low"] is False
        assert "text-deficit" not in resp.content.decode()

    def test_four_fifths_spent_is_flagged(self, client_logged_in):
        status = dict(PROVIDER_ANSWERED, used=80)
        resp = _dashboard(client_logged_in, status)
        assert resp.context["openet_low"] is True
        body = resp.content.decode()
        assert "text-deficit" in body
        assert "var(--color-deficit)" in body

    def test_it_never_reaches_for_the_error_colour(self, client_logged_in):
        """A spent allowance is a budget state, not a hard error."""
        status = dict(PROVIDER_ANSWERED, used=100)
        body = _dashboard(client_logged_in, status).content.decode()
        assert "--color-error" not in body
        assert "#f87171" not in body

    def test_an_exhausted_allowance_never_reports_negative_remaining(
        self, client_logged_in
    ):
        status = dict(PROVIDER_ANSWERED, used=140)
        resp = _dashboard(client_logged_in, status)
        assert resp.context["openet_remaining"] == 0


@pytest.mark.django_db
class TestTheDashboardMakesNoOutboundCall:
    def test_rendering_the_page_reads_the_cache_not_the_network(
        self, client_logged_in
    ):
        """account_status() is called, but its HTTP layer must never be."""
        from datasync.adapters.openet import ACCOUNT_STATUS_CACHE_KEY
        from django.core.cache import cache

        cache.set(ACCOUNT_STATUS_CACHE_KEY, PROVIDER_ANSWERED, 60)
        try:
            with patch(
                "datasync.adapters.openet.OpenETAdapter._request"
            ) as mock_request:
                resp = client_logged_in.get(
                    reverse("datasync:monitoring_dashboard")
                )
            mock_request.assert_not_called()
            assert resp.context["openet_used"] == 12
        finally:
            cache.delete(ACCOUNT_STATUS_CACHE_KEY)
