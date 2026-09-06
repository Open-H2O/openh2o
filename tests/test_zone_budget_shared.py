# SPDX-License-Identifier: AGPL-3.0-or-later
"""One function computes a zone's groundwater budget, and both screens call it.

ISS-154 was one screen counting canal water as pumping. Fixing only that would
have left a second, quieter defect standing: the dashboard's zone row and the
district page's Allocation vs. use table would then have printed two different
"remaining" figures for the same zone and the same period, because the dashboard
adds the prior year's carry-over and the district page never did. That is
ISS-155's class — correct arithmetic under a label that names a different
quantity — and DESIGN.md rule 12 exists to end it.

So the fix is a shared function, and these tests are what makes "shared" mean
something. The zone below is deliberately MIXED: one parcel pumps, the other
takes canal water, and only the pumping may be spent against the groundwater
allocation.

Every expected figure is a pasted literal. None is re-derived from the inputs in
the assertion — an assertion that recomputes the formula agrees with any formula.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client

from accounting.models import AllocationCarryover
from accounting.services import zone_groundwater_budget
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

PERIOD_START = date(2025, 10, 1)
PERIOD_END = date(2026, 9, 30)
# The period ends in September 2026, so carry-over rolling INTO it is labelled by
# the calendar year it ends in (carryover_math.water_year_of).
WATER_YEAR = 2026

# The fixture's inputs, stated once.
GW_ALLOCATION = Decimal("500.0000")
GW_CARRYOVER = Decimal("30.0000")
METERED_PUMPING = Decimal("100.0000")
CANAL_DELIVERY = Decimal("1000.0000")
SW_ALLOCATION = Decimal("2000.0000")

# The answers, hand-computed once and pasted. 500 + 30 = 530 available; 530 − 100
# pumped = 430 remaining. The canal's 1,000 AF is a SUPPLY to parcel B and never
# touches the groundwater budget — under ISS-154 it did, and remaining read −570.
EXPECTED_REMAINING = Decimal("430.0000")
EXPECTED_SURFACE_REMAINING = Decimal("1000.0000")
DEFECTIVE_REMAINING = Decimal("-570.0000")


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"zonebudgetuser{n}")
    email = factory.Sequence(lambda n: f"zonebudgetuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def mixed_zone():
    """One zone, one period, two parcels: one pumps, one takes canal water."""
    period = ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=PERIOD_START,
        end_date=PERIOD_END,
    )
    gw_type = WaterTypeFactory(name="Groundwater", code="GW")
    sw_type = WaterTypeFactory(name="Surface Water", code="SW")
    zone = ZoneFactory(name="Mixed Supply GSA")

    parcel_a = ParcelFactory(parcel_number="ISS154-A")
    parcel_b = ParcelFactory(parcel_number="ISS154-B")
    ParcelZoneFactory(parcel=parcel_a, zone=zone)
    ParcelZoneFactory(parcel=parcel_b, zone=zone)

    # A pumps 100 AF through a meter; B takes 1,000 AF of canal water. Both are
    # stored NEGATIVE — that shared sign convention is the whole reason canal
    # water could land inside a column headed "pumped".
    ParcelLedgerFactory(
        parcel=parcel_a,
        reporting_period=period,
        source_type="meter_reading",
        effective_date=date(2026, 6, 15),
        amount_acre_feet=-METERED_PUMPING,
    )
    ParcelLedgerFactory(
        parcel=parcel_b,
        reporting_period=period,
        source_type="surface_diversion",
        effective_date=date(2026, 6, 1),
        amount_acre_feet=-CANAL_DELIVERY,
    )

    AllocationPlanFactory(
        zone=zone,
        water_type=gw_type,
        reporting_period=period,
        allocation_acre_feet=GW_ALLOCATION,
    )
    AllocationPlanFactory(
        zone=zone,
        water_type=sw_type,
        reporting_period=period,
        allocation_acre_feet=SW_ALLOCATION,
    )
    AllocationCarryover.objects.create(
        zone=zone,
        water_type=gw_type,
        water_year=WATER_YEAR,
        amount_af=GW_CARRYOVER,
    )
    return {"zone": zone, "period": period, "parcel_a": parcel_a, "parcel_b": parcel_b}


@pytest.fixture
def viewer():
    user = UserFactory()
    client = Client()
    client.force_login(user)
    return client


def test_the_helper_counts_groundwater_only(mixed_zone):
    budget = zone_groundwater_budget(mixed_zone["zone"], mixed_zone["period"])
    assert budget["allocation"] == GW_ALLOCATION
    assert budget["carryover"] == GW_CARRYOVER
    assert budget["used"] == METERED_PUMPING
    assert budget["remaining"] == EXPECTED_REMAINING
    assert budget["remaining"] != DEFECTIVE_REMAINING


def test_a_zone_with_no_groundwater_plan_has_no_groundwater_budget(mixed_zone):
    """136-01's dash rule: absent, not zero.

    A surface service area carries surface plans only. Its groundwater
    allocation, carry-over and remaining are three cells the agency does not
    have, and a zero there would read as a budget fully spent.
    """
    bare = ZoneFactory(name="Surface Service Area Only")
    budget = zone_groundwater_budget(bare, mixed_zone["period"])
    assert budget["allocation"] is None
    assert budget["carryover"] is None
    assert budget["remaining"] is None
    assert budget["used"] == Decimal("0")


def test_the_district_page_reads_the_helpers_numbers(mixed_zone, viewer):
    zone = mixed_zone["zone"]
    resp = viewer.get(f"/map/zones/{zone.pk}/")
    assert resp.status_code == 200
    budgets = resp.context["budgets"]

    gw = [b for b in budgets if (b["water_type"].code or "").upper() == "GW"]
    assert len(gw) == 1
    row = gw[0]
    assert row["used_label"] == "pumped"
    assert row["budget"] == GW_ALLOCATION
    assert row["carryover"] == GW_CARRYOVER
    assert row["used"] == METERED_PUMPING
    assert row["remaining"] == EXPECTED_REMAINING

    sw = [b for b in budgets if (b["water_type"].code or "").upper() == "SW"]
    assert len(sw) == 1
    surface = sw[0]
    assert surface["used_label"] == "delivered"
    assert surface["used"] == CANAL_DELIVERY
    assert surface["remaining"] == EXPECTED_SURFACE_REMAINING
    # A surface allocation has no groundwater carry-over. Absent, so the template
    # dashes it rather than printing a zero that would read as "none left over".
    assert surface["carryover"] is None

    body = resp.content.decode()
    assert "430.00" in body, "the remaining figure never reaches the rendered table"
    assert "-570.00" not in body and "−570.00" not in body


def test_the_dashboard_zone_row_reads_the_same_remaining(mixed_zone, viewer):
    """The point of the helper: the two screens cannot drift apart."""
    period = mixed_zone["period"]
    resp = viewer.get(f"/accounting/dashboard/?period={period.pk}")
    assert resp.status_code == 200
    rows = [
        r for r in resp.context["zone_summaries"]
        if r["zone"].pk == mixed_zone["zone"].pk
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["allocation"] == GW_ALLOCATION
    assert row["carryover"] == GW_CARRYOVER
    assert row["groundwater"] == METERED_PUMPING
    assert row["remaining"] == EXPECTED_REMAINING
