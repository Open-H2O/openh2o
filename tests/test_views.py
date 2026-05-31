# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Smoke tests verifying every page returns HTTP 200 for appropriate users.

Uses Django's test Client with force_login for authenticated routes.
Health endpoints are public (no login required per Phase 7 design decision).
"""

import pytest
import factory
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    WellFactory,
    RechargeSiteFactory,
    WaterRightFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------------------
# Public pages (no login required)
# ---------------------------------------------------------------------------


class TestPublicPages:
    def test_index_unauthenticated(self, client):
        """Index returns 200 for unauthenticated users."""
        response = client.get(reverse("index"))
        assert response.status_code == 200

    def test_health_dashboard_public(self, client):
        """Health dashboard is public (no login required)."""
        response = client.get(reverse("health:dashboard"))
        assert response.status_code == 200

    def test_health_api_public(self, client):
        """Health API is public (no login required)."""
        response = client.get(reverse("health:api"))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Help pages (login required)
# ---------------------------------------------------------------------------


class TestHelpPages:
    def test_getting_started(self, auth_client):
        response = auth_client.get(reverse("getting_started"))
        assert response.status_code == 200

    def test_glossary(self, auth_client):
        response = auth_client.get(reverse("glossary"))
        assert response.status_code == 200

    def test_getting_started_redirects_anonymous(self, client):
        response = client.get(reverse("getting_started"))
        assert response.status_code == 302

    def test_glossary_redirects_anonymous(self, client):
        response = client.get(reverse("glossary"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Accounting pages (login required)
# ---------------------------------------------------------------------------


class TestDashboardAllocationProRating:
    def test_prorates_allocation_by_parcel_count(self, auth_client):
        """Zone with 4 parcels, account owns 1: allocation = 25% of zone total."""
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        zone = ZoneFactory()
        water_type = WaterTypeFactory()

        # Create 4 parcels in the zone
        parcels = [ParcelFactory() for _ in range(4)]
        for p in parcels:
            ParcelZoneFactory(parcel=p, zone=zone)

        # Account owns only 1 of the 4 parcels
        account = WaterAccountFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcels[0])

        # Zone allocation is 100 AF
        AllocationPlanFactory(
            zone=zone,
            water_type=water_type,
            reporting_period=period,
            allocation_acre_feet=Decimal("100.0000"),
        )

        response = auth_client.get(
            reverse("accounting:dashboard") + f"?period={period.pk}"
        )
        assert response.status_code == 200

        # Find the account summary in context
        account_summaries = response.context["account_summaries"]
        match = [s for s in account_summaries if s["account"] == account]
        assert len(match) == 1
        # Pro-rated: 100 AF * (1/4) = 25 AF
        assert match[0]["allocation"] == Decimal("25.0000")


class TestAccountingPages:
    def test_dashboard(self, auth_client):
        response = auth_client.get(reverse("accounting:dashboard"))
        assert response.status_code == 200

    def test_accounts_list(self, auth_client):
        response = auth_client.get(reverse("accounting:accounts_list"))
        assert response.status_code == 200

    def test_periods_list(self, auth_client):
        response = auth_client.get(reverse("accounting:periods_list"))
        assert response.status_code == 200

    def test_allocations_list(self, auth_client):
        response = auth_client.get(reverse("accounting:allocations_list"))
        assert response.status_code == 200

    def test_ledger_list(self, auth_client):
        response = auth_client.get(reverse("accounting:ledger_list"))
        assert response.status_code == 200

    def test_account_create_get(self, auth_client):
        response = auth_client.get(reverse("accounting:account_create"))
        assert response.status_code == 200

    def test_period_create_get(self, auth_client):
        response = auth_client.get(reverse("accounting:period_create"))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Parcels pages (login required)
# ---------------------------------------------------------------------------


class TestParcelsPages:
    def test_parcels_list(self, auth_client):
        response = auth_client.get(reverse("parcels:list"))
        assert response.status_code == 200

    def test_parcels_list_redirects_anonymous(self, client):
        response = client.get(reverse("parcels:list"))
        assert response.status_code == 302

    def test_parcel_detail(self, auth_client):
        parcel = ParcelFactory()
        response = auth_client.get(reverse("parcels:detail", kwargs={"pk": parcel.pk}))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Wells pages (login required)
# ---------------------------------------------------------------------------


class TestWellsPages:
    def test_wells_list(self, auth_client):
        response = auth_client.get(reverse("wells:list"))
        assert response.status_code == 200

    def test_wells_list_redirects_anonymous(self, client):
        response = client.get(reverse("wells:list"))
        assert response.status_code == 302

    def test_well_detail(self, auth_client):
        well = WellFactory()
        response = auth_client.get(reverse("wells:detail", kwargs={"pk": well.pk}))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Surface water pages (login required)
# ---------------------------------------------------------------------------


class TestSurfacePages:
    def test_water_rights_list(self, auth_client):
        response = auth_client.get(reverse("surface:water_rights_list"))
        assert response.status_code == 200

    def test_water_rights_list_redirects_anonymous(self, client):
        response = client.get(reverse("surface:water_rights_list"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Recharge pages (login required)
# ---------------------------------------------------------------------------


class TestRechargePages:
    def test_recharge_list(self, auth_client):
        response = auth_client.get(reverse("recharge:list"))
        assert response.status_code == 200

    def test_recharge_list_redirects_anonymous(self, client):
        response = client.get(reverse("recharge:list"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Datasync pages (login required)
# ---------------------------------------------------------------------------


class TestDatasyncPages:
    def test_station_list(self, auth_client):
        response = auth_client.get(reverse("datasync:station_list"))
        assert response.status_code == 200

    def test_station_list_redirects_anonymous(self, client):
        response = client.get(reverse("datasync:station_list"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Reporting pages (login required)
# ---------------------------------------------------------------------------


class TestReportingPages:
    def test_report_list(self, auth_client):
        response = auth_client.get(reverse("reporting:report_list"))
        assert response.status_code == 200

    def test_report_list_redirects_anonymous(self, client):
        response = client.get(reverse("reporting:report_list"))
        assert response.status_code == 302
