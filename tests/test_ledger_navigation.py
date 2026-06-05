# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 63: view-layer tests for the at-scale ledger navigation tools —
sortable columns (whitelist + fallback), the Zone facet (with de-duplication),
and the page-size selector. These exercise ``accounting.views.ledger_list``
query handling directly; the sticky/HTMX UI is verified live in the checkpoint.
"""

from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"navuser{n}")
    email = factory.Sequence(lambda n: f"navuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


def _ledger_url(**params):
    """Ledger URL with an explicit period= so the ISS-022 bare-landing
    auto-default never narrows the rows out from under a navigation assertion."""
    from urllib.parse import urlencode

    base = reverse("accounting:ledger_list")
    params.setdefault("period", "")  # "All Periods" — bypass the auto-default
    return f"{base}?{urlencode(params)}"


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Sortable columns
# ---------------------------------------------------------------------------


class TestLedgerSort:
    def _three_amounts(self):
        period = ReportingPeriodFactory()
        for amt, day in ((Decimal("5.0000"), 5), (Decimal("30.0000"), 6), (Decimal("12.0000"), 7)):
            ParcelLedgerFactory(
                reporting_period=period,
                amount_acre_feet=amt,
                effective_date=date(2024, 6, day),
                source_type="manual_entry",
            )
        return period

    def test_sort_amount_ascending(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="amount", dir="asc"))
        assert resp.status_code == 200
        amounts = [r.amount_acre_feet for r in resp.context["page_obj"]]
        assert amounts == sorted(amounts)
        assert amounts[0] == Decimal("5.0000")

    def test_sort_amount_descending(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="amount", dir="desc"))
        assert resp.status_code == 200
        amounts = [r.amount_acre_feet for r in resp.context["page_obj"]]
        assert amounts == sorted(amounts, reverse=True)
        assert amounts[0] == Decimal("30.0000")

    def test_bogus_sort_falls_back_to_newest_first(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="bogus"))
        assert resp.status_code == 200  # fail closed, no 500
        rows = list(resp.context["page_obj"])
        # Default is newest effective_date first.
        assert rows[0].effective_date == date(2024, 6, 7)
        assert resp.context["sort"] == "bogus"  # echoed back; just not applied


# ---------------------------------------------------------------------------
# Page size
# ---------------------------------------------------------------------------


class TestLedgerPageSize:
    def test_page_size_500_is_honored(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="500"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 500
        assert resp.context["page_size"] == 500

    def test_invalid_page_size_falls_back_to_100(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="9999"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 100
        assert resp.context["page_size"] == 100

    def test_non_numeric_page_size_falls_back_to_100(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="lots"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 100


# ---------------------------------------------------------------------------
# Zone facet
# ---------------------------------------------------------------------------


class TestLedgerZoneFacet:
    def test_zone_filter_narrows_and_does_not_duplicate(self, auth_client):
        period = ReportingPeriodFactory()
        zone_a = ZoneFactory()
        zone_b = ZoneFactory()

        # A parcel living in TWO zones, with two ledger rows of its own.
        parcel_in_both = ParcelFactory()
        ParcelZoneFactory(parcel=parcel_in_both, zone=zone_a)
        ParcelZoneFactory(parcel=parcel_in_both, zone=zone_b)
        for day in (10, 11):
            ParcelLedgerFactory(
                parcel=parcel_in_both,
                reporting_period=period,
                effective_date=date(2024, 6, day),
                source_type="manual_entry",
            )

        # A parcel in neither filtered zone — must be excluded.
        other = ParcelFactory()
        ParcelLedgerFactory(
            parcel=other,
            reporting_period=period,
            effective_date=date(2024, 6, 12),
            source_type="manual_entry",
        )

        resp = auth_client.get(_ledger_url(zone=str(zone_a.pk)))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])

        # Two genuine ledger rows for the zoned parcel — no duplication from the
        # parcel also belonging to zone_b.
        assert resp.context["total_count"] == 2
        assert len(rows) == 2
        pks = [r.pk for r in rows]
        assert len(pks) == len(set(pks))  # count == distinct count
        assert all(r.parcel_id == parcel_in_both.pk for r in rows)

    def test_zone_composes_with_source_type(self, auth_client):
        period = ReportingPeriodFactory()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)

        ParcelLedgerFactory(
            parcel=parcel,
            reporting_period=period,
            source_type="calculated",
            effective_date=date(2024, 6, 1),
        )
        ParcelLedgerFactory(
            parcel=parcel,
            reporting_period=period,
            source_type="manual_entry",
            effective_date=date(2024, 6, 2),
        )

        resp = auth_client.get(_ledger_url(zone=str(zone.pk), source_type="calculated"))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])
        assert len(rows) == 1
        assert rows[0].source_type == "calculated"
