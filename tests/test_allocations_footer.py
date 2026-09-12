# SPDX-License-Identifier: AGPL-3.0-or-later
"""The allocations footer subtotals by water type and adds nothing across them.

**ISS-156.** Until 2026-09-06 this page's footer printed one figure. On the
demonstration data, WY 2025-2026 read **159,671.46 AF** — a surface-water
district's diversion entitlement (148,500.00 AF) added to a groundwater
sustainability agency's pumping allowance (11,171.46 AF), in one number, in
acre-feet, with nothing on the screen saying it was a mixture. Different
agencies, different law. Nobody manages the sum, so nobody could act on it.

The arithmetic was never wrong. The label was, and shared units are not what
makes two rows addable — that is STATE.md's third standing review question, and
it is the same defect class as ISS-154 (the ledger footer adding allocation
paper to delivered water) and ISS-155.

**How this test is built, and the two traps it is written around.** They are
STATE.md's other two review questions, and ISS-154 survived a green suite by
falling into the second:

1. *A numeric test asserts a VALUE, not a direction.* Every assertion below
   names the figure the fixture puts on the page, so changing a subtotal by hand
   fails here rather than sliding through as "still positive, still a sum".
2. *A test may not re-derive the formula it tests.* There is deliberately no
   ``surface + groundwater == total`` assertion anywhere in this file. Such an
   assertion cannot disagree with the view, because it computes what the view
   computes; it measures the test author's arithmetic, not the screen.

The fixture reproduces the demonstration's shape at demonstration scale rather
than inventing round numbers, so a failure here reads against the issue.
"""

from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    AllocationPlanFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"allocuser{n}")
    email = factory.Sequence(lambda n: f"allocuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    client = Client()
    client.force_login(user)
    return client


pytestmark = pytest.mark.django_db


#: One water year of the demonstration's shape: five surface plans summing to
#: 148,500.00 AF and three groundwater plans summing to 11,171.46 AF. The split
#: across plans is the demonstration's, not a convenience — a single plan per
#: type would not exercise the grouping at all.
SURFACE_PLANS = (
    Decimal("60000.0000"),
    Decimal("40000.0000"),
    Decimal("28000.0000"),
    Decimal("16200.0000"),
    Decimal("4300.0000"),
)
GROUNDWATER_PLANS = (
    Decimal("5320.4600"),
    Decimal("3950.0000"),
    Decimal("1901.0000"),
)


@pytest.fixture
def two_water_types():
    """A period holding both kinds of allocation, named as the platform names them."""
    period = ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    surface = WaterTypeFactory(name="Surface Water", code="SW")
    groundwater = WaterTypeFactory(name="Groundwater", code="GW")

    for index, amount in enumerate(SURFACE_PLANS):
        AllocationPlanFactory(
            name=f"Surface plan {index}",
            zone=ZoneFactory(),
            water_type=surface,
            reporting_period=period,
            allocation_acre_feet=amount,
        )
    for index, amount in enumerate(GROUNDWATER_PLANS):
        AllocationPlanFactory(
            name=f"Groundwater plan {index}",
            zone=ZoneFactory(),
            water_type=groundwater,
            reporting_period=period,
            allocation_acre_feet=amount,
        )
    return period


def _allocations(client, period):
    return client.get(
        f"{reverse('accounting:allocations_list')}?period={period.pk}"
    )


class TestAllocationsFooter:
    def test_each_water_type_carries_its_own_subtotal(self, auth_client, two_water_types):
        """The two figures, by name, on the screen.

        148,500.00 AF of surface-water allocation and 11,171.46 AF of
        groundwater allocation — the same two numbers ISS-156 measured on the
        demonstration, each under the name of the water type it belongs to.
        """
        response = _allocations(auth_client, two_water_types)
        assert response.status_code == 200
        html = response.content.decode()

        subtotals = {
            row["water_type__name"]: row for row in response.context["allocation_subtotals"]
        }
        assert set(subtotals) == {"Groundwater", "Surface Water"}
        assert subtotals["Surface Water"]["total"] == Decimal("148500.0000")
        assert subtotals["Surface Water"]["plans"] == 5
        assert subtotals["Groundwater"]["total"] == Decimal("11171.4600")
        assert subtotals["Groundwater"]["plans"] == 3

        assert "Surface Water" in html
        # 143-06: the unit left the per-figure cell for the card head (rule 4,
        # "a unit is stated once per single-unit table"), so the footer figure
        # itself no longer carries " AF" -- the value's presence is still the
        # thing this test pins.
        assert "148,500.00" in html
        assert "Groundwater" in html
        assert "11,171.46" in html

    def test_the_screen_never_prints_the_mixed_sum(self, auth_client, two_water_types):
        """159,671.46 AF is the figure ISS-156 was filed against.

        Written as the literal the issue names rather than as
        ``surface + groundwater``, so this assertion cannot be satisfied by the
        view and the test agreeing on a formula.
        """
        response = _allocations(auth_client, two_water_types)
        html = response.content.decode()

        assert "159,671.46" not in html
        assert "159671" not in html
        assert "allocation_total" not in response.context

    def test_one_water_type_still_gets_a_subtotal(self, auth_client, two_water_types):
        """Filtering to groundwater leaves one subtotal, still named.

        A single-type view is where a grouped footer is most tempting to
        collapse back into an unlabelled total.
        """
        response = auth_client.get(
            f"{reverse('accounting:allocations_list')}"
            f"?period={two_water_types.pk}&q=Groundwater"
        )
        assert response.status_code == 200
        subtotals = response.context["allocation_subtotals"]
        assert len(subtotals) == 1
        assert subtotals[0]["water_type__name"] == "Groundwater"
        assert subtotals[0]["total"] == Decimal("11171.4600")
        # 143-06: no " AF" suffix on the figure itself (rule 4; see the note
        # in test_each_water_type_carries_its_own_subtotal above).
        assert "11,171.46" in response.content.decode()

    def test_a_period_with_no_allocations_prints_no_footer(self, auth_client):
        """An empty state states the fact and stops (DESIGN.md copy rule 8)."""
        period = ReportingPeriodFactory(
            name="WY 2026-2027",
            start_date=date(2026, 10, 1),
            end_date=date(2027, 9, 30),
        )
        response = _allocations(auth_client, period)
        assert response.status_code == 200
        assert response.context["allocation_subtotals"] == []
        html = response.content.decode()
        assert "<tfoot>" not in html
        assert "No allocations found" in html
