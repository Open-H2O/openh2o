# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's groundwater budget is spent by groundwater use (136-01, ISS-151).

Three value-asserting tests, written RED against the gross-ET basis before the
view changed, in the shape DESIGN.md rule 12's three review questions demand:
every expected number is a literal worked out by hand from the fixture and
written beside its arithmetic, never ``> 0`` and never the view's own formula.

**The basis (option A, Brent 2026-09-05).** Remaining = groundwater allocation
minus groundwater use, where groundwater use is the metered or calculated
pumping the dashboard already shows in its Groundwater column. Until 136-01 the
column subtracted gross crop water use, a quantity that FALLS in a drought
(ISS-151), so no basin could go over budget because of one.

**Like with like.** An account's allocation counts groundwater plans only. Six
of the eleven demonstration accounts sit in a surface-water service area as
well as a groundwater agency's zone, and the old column added the two
allocations: MER-ACCT-001 showed 2,901.42 AF of groundwater allocation plus
16,200.00 AF of surface entitlement as one number. Subtracting groundwater use
from that sum would have printed a surface entitlement as spare groundwater.
A zone with no groundwater plan shows a dash in its three budget cells.

The fixture extends the one ``tests/test_dashboard_golden.py`` builds (one
period, one zone, one parcel, one account, a 100.0000 AF plan) rather than
inventing a second.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention: every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"basis{n}")
    email = factory.Sequence(lambda n: f"basis{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _basin(pumped="37.5000", gross_et="80.0000", net="60.0000"):
    """One GSA zone with a 100.0000 AF groundwater plan, one parcel, one account.

    The parcel carries one meter reading of ``pumped`` AF (stored negative, the
    ledger's convention for water leaving its source) and one calculation run
    with the given gross and net crop water use, all inside WY 2025-2026.
    """
    period = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    groundwater = WaterTypeFactory(name="Groundwater", code="GW")
    zone = ZoneFactory(name="Basis GSA Zone", zone_type="management_area")
    parcel = ParcelFactory()
    ParcelZoneFactory(parcel=parcel, zone=zone)
    account = WaterAccountFactory(account_number="BASIS-0001", name="Basis Account")
    WaterAccountParcelFactory(water_account=account, parcel=parcel)
    AllocationPlanFactory(
        zone=zone,
        water_type=groundwater,
        reporting_period=period,
        allocation_acre_feet=Decimal("100.0000"),
    )
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=period, source_type="meter_reading",
        water_type=groundwater, amount_acre_feet=-Decimal(pumped),
        transaction_date=date(2026, 1, 15), effective_date=date(2026, 1, 15),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal(gross_et),
        net_consumptive_use_af=Decimal(net),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal(net),
    )
    return period, zone, parcel, account


def _dashboard(period):
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard") + f"?period={period.pk}")
    assert response.status_code == 200
    return response


def _account_row(response, account):
    return next(r for r in response.context["account_summaries"] if r["account"] == account)


def _zone_row(response, zone):
    return next(r for r in response.context["zone_summaries"] if r["zone"] == zone)


def test_remaining_is_allocation_minus_groundwater_use():
    """100.0000 allocated, 37.5000 pumped, 80.0000 of gross ET.

    Remaining = 100.0000 - 37.5000 = 62.5000 on both tables. The old basis read
    100.0000 - 80.0000 = 20.0000, which is what this test was red against.
    """
    period, zone, _parcel, account = _basin()

    response = _dashboard(period)

    assert _account_row(response, account)["remaining"] == Decimal("62.5000")
    assert _zone_row(response, zone)["remaining"] == Decimal("62.5000")


def test_account_allocation_counts_groundwater_plans_only():
    """The same parcel also sits in a surface service area with a 1,000.0000 AF
    surface plan. The account's allocation is the groundwater plan alone,
    100.0000 (the old basis read 100.0000 + 1,000.0000 = 1,100.0000), and the
    surface zone's three budget cells are absent, not zero."""
    period, _gsa, parcel, account = _basin()
    surface = WaterTypeFactory(name="Surface Water", code="SW")
    service_area = ZoneFactory(name="Basis Surface Service Area", zone_type="custom")
    ParcelZoneFactory(parcel=parcel, zone=service_area)
    AllocationPlanFactory(
        zone=service_area,
        water_type=surface,
        reporting_period=period,
        allocation_acre_feet=Decimal("1000.0000"),
    )

    response = _dashboard(period)

    assert _account_row(response, account)["allocation"] == Decimal("100.0000")
    surface_row = _zone_row(response, service_area)
    assert surface_row["allocation"] is None
    assert surface_row["carryover"] is None
    assert surface_row["remaining"] is None


def test_the_strip_counts_groundwater_overdrafts():
    """Pumping raised to 120.0000 against the 100.0000 plan: remaining is
    100.0000 - 120.0000 = -20.0000, so exactly one account is over its
    groundwater budget and the strip says so. Gross ET stays at 80.0000, so the
    old basis (100.0000 - 80.0000 = 20.0000) counted zero, which is what this
    test was red against."""
    period, _zone, _parcel, account = _basin(pumped="120.0000")

    response = _dashboard(period)
    html = response.content.decode()

    assert _account_row(response, account)["remaining"] == Decimal("-20.0000")
    assert response.context["accounts_over_budget"] == 1
    assert "account over groundwater budget" in html


def test_the_budget_columns_say_groundwater():
    """The words beside the numbers: both tables head the two budget columns as
    the groundwater budget (136-01, DESIGN.md rule 12)."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert html.count("GW allocation (AF)") == 2
    assert html.count("GW remaining (AF)") == 2
    assert "Allocation minus estimated consumptive use" not in html
