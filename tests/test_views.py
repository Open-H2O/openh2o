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
    ParcelLedgerFactory,
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


class TestLedgerDefaultPeriod:
    """ISS-022: the ledger should land on the period that surfaces the audit
    trail, not the empty calendar-current one."""

    def _two_periods_with_rows(self):
        from datetime import date

        # Older period carries the calculated (audit-linked) rows; a newer
        # period carries only a manual row, so by start_date it is the most
        # recent period but it would hide every "How was this calculated?" link.
        period_calc = ReportingPeriodFactory(
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )
        period_recent = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        ParcelLedgerFactory(
            reporting_period=period_calc,
            source_type="calculated",
            effective_date=date(2024, 6, 15),
        )
        ParcelLedgerFactory(
            reporting_period=period_recent,
            source_type="manual_entry",
            effective_date=date(2026, 1, 15),
        )
        return period_calc, period_recent

    def test_defaults_to_most_recent_calculated_bearing_period(self, auth_client):
        period_calc, _ = self._two_periods_with_rows()

        response = auth_client.get(reverse("accounting:ledger_list"))

        assert response.status_code == 200
        assert response.context["period_auto_defaulted"] is True
        # period_id is rendered as a string for the dropdown selected-state check
        assert response.context["period_id"] == str(period_calc.pk)
        rows = list(response.context["page_obj"])
        assert rows, "default period should not be empty"
        assert all(r.reporting_period_id == period_calc.pk for r in rows)
        assert all(r.source_type == "calculated" for r in rows)

    def test_explicit_all_periods_stays_unfiltered(self, auth_client):
        self._two_periods_with_rows()

        # An explicit empty period= (the "All Periods" choice) must be honored.
        response = auth_client.get(reverse("accounting:ledger_list") + "?period=")

        assert response.status_code == 200
        assert response.context["period_auto_defaulted"] is False
        assert response.context["total_count"] == 2


class TestAccountDetailBillableLedger:
    """ISS-026: the per-parcel breakdown on account_detail must route through
    billable_ledger so a netted `calculated` row suppresses its gross
    `et_estimate` twin. Otherwise the same parcel-month is counted twice and the
    per-parcel usage shows ~double the (correct) account total in the same table."""

    def test_per_parcel_usage_suppresses_et_estimate_twin(self, auth_client):
        from datetime import date
        from decimal import Decimal

        account = WaterAccountFactory()
        parcel = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)

        # The normal post-run state: a gross et_estimate row AND its netted
        # calculated twin for the SAME (parcel, month), both stored negative.
        eff = date(2024, 6, 1)
        ParcelLedgerFactory(
            parcel=parcel, source_type="et_estimate",
            effective_date=eff, amount_acre_feet=Decimal("-10.0000"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="calculated",
            effective_date=eff, amount_acre_feet=Decimal("-10.0000"),
        )

        # ?period= (empty value, non-empty querystring) yields selected_period=None
        # and NO period filter — the state where summing both rows double-counts
        # (et_estimate rows carry reporting_period=None, so a period filter would
        # hide the bug).
        response = auth_client.get(
            reverse("accounting:account_detail", kwargs={"pk": account.pk})
            + "?period="
        )
        assert response.status_code == 200

        pbs = response.context["parcel_balances"]
        match = [b for b in pbs if b["parcel"] == parcel]
        assert len(match) == 1
        # billable: the calculated row only -> usage 10, NOT 10 + 10 = 20.
        assert match[0]["usage"] == Decimal("10.0000")
        # And the per-parcel figure reconciles with the account-level total.
        assert response.context["balance"]["usage"] == Decimal("10.0000")


class TestDashboardActiveAccountScope:
    """ISS-032: the dashboard grand totals sum active accounts while the zone
    block covers all parcels. The account section is labeled so the two
    populations are not read as one."""

    def test_account_section_labeled_active(self, auth_client):
        from datetime import date

        ReportingPeriodFactory(
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )
        response = auth_client.get(reverse("accounting:dashboard"))
        assert response.status_code == 200
        assert b"Active Water Accounts" in response.content


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
