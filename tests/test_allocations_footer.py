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

**143-06 extends this file along the period axis.** ISS-156 closed the water-type
axis; ISS-164 was filed the same day against the axis it left open, "All periods"
adding the SAME entitlement across two water years into a quantity nobody
manages (304,200.00 AF from one 108,000.00 AF plan seen twice). The classes below
add that axis, plus the row shape that made the old footer's mistake easy to miss
in the first place: the Name column repeating the zone, the water type and the
water year a row already states in its own columns (R-032), and the zone's own
name carrying no link to the record the row is about (R-033).
"""

import re
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


#: ISS-164's own shape: one zone, one surface plan of 108,000.00 AF, entered
#: identically in two different water years. The register's read is
#: 304,200.00 AF (148,500 + 155,700) on the demonstration data; this fixture
#: is the minimal case that isolates the SAME entitlement recurring rather
#: than two different figures, since a test that used two different amounts
#: could pass by accident if the view merely failed to add correctly.
ENTITLEMENT = Decimal("108000.0000")


@pytest.fixture
def two_periods_same_entitlement():
    """One zone, one surface plan of 108,000.00 AF in each of two water years."""
    zone = ZoneFactory(name="Halvern Irrigation District")
    surface = WaterTypeFactory(name="Surface Water", code="SW")
    period_a = ReportingPeriodFactory(
        name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    period_b = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    for period in (period_a, period_b):
        AllocationPlanFactory(
            zone=zone,
            water_type=surface,
            reporting_period=period,
            allocation_acre_feet=ENTITLEMENT,
        )
    return {"zone": zone, "period_a": period_a, "period_b": period_b}


class TestAllocationsAcrossWaterYears:
    """ISS-164: nothing on this page adds the same entitlement across two years."""

    def test_all_periods_never_prints_the_cross_year_sum(
        self, auth_client, two_periods_same_entitlement
    ):
        """Candidate A closes each water year with its own subtotal (rulings.md):
        with one plan per year, 108,000.00 prints twice per year (the row, then
        that year's own subtotal echoing its one row), four times on the whole
        page, never once combined into 216,000.00. Measured, not assumed: a
        fixture with more than one plan per year would not show the echo and
        would wrongly suggest "twice" is the invariant to pin."""
        period_a = two_periods_same_entitlement["period_a"]
        period_b = two_periods_same_entitlement["period_b"]
        response = auth_client.get(f"{reverse('accounting:allocations_list')}?period=")
        assert response.status_code == 200
        html = response.content.decode()

        assert html.count("108,000.00") == 4
        assert "216,000.00" not in html
        assert "216000" not in html
        assert f"All 1 surface-water allocation, {period_a.name}" in html
        assert f"All 1 surface-water allocation, {period_b.name}" in html

    def test_one_period_tfoot_names_the_entitlement_once_with_the_period_and_the_count(
        self, auth_client, two_periods_same_entitlement
    ):
        """'The footer' is the <tfoot>, not the whole page: the row above it
        prints the same 108,000.00 a second time, which is correct (it is the
        same allocation, read twice, in two different roles) and not what this
        guard is pinning. Scoped to the tfoot, the label names the period and
        the count exactly once, in the ruled wording."""
        period_a = two_periods_same_entitlement["period_a"]
        response = auth_client.get(
            f"{reverse('accounting:allocations_list')}?period={period_a.pk}"
        )
        assert response.status_code == 200
        html = response.content.decode()

        tfoot_match = re.search(r"<tfoot>(.*?)</tfoot>", html, re.DOTALL)
        assert tfoot_match, "no <tfoot> found on a single-period view"
        tfoot_html = tfoot_match.group(1)

        assert tfoot_html.count("108,000.00") == 1
        assert f"All 1 surface-water allocation, {period_a.name}" in tfoot_html
        assert "216,000.00" not in html


#: One row, one zone, named as the demonstration's own zone is named, so the
#: "reads the zone name three times" fault (R-032) and the "leads away from
#: the record" fault (R-033) are each checked against a name that would
#: actually collide with itself if the old Name column were still built from
#: zone + water type + water year joined with dashes.
@pytest.fixture
def one_allocation_row():
    zone = ZoneFactory(name="Halvern Irrigation-Urban GSA")
    water_type = WaterTypeFactory(name="Groundwater", code="GW")
    period = ReportingPeriodFactory(
        name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    plan = AllocationPlanFactory(
        zone=zone,
        water_type=water_type,
        reporting_period=period,
        allocation_acre_feet=Decimal("500.0000"),
    )
    return {"zone": zone, "water_type": water_type, "period": period, "plan": plan}


class TestAllocationsRowShape:
    """R-032 (the Name column repeats the row) and R-033 (nothing links)."""

    def test_the_zone_name_appears_once_and_no_th_reads_name(
        self, auth_client, one_allocation_row
    ):
        period = one_allocation_row["period"]
        response = auth_client.get(
            f"{reverse('accounting:allocations_list')}?period={period.pk}"
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert html.count(one_allocation_row["zone"].name) == 1
        assert "<th>Name</th>" not in html

    def test_the_zone_cell_is_a_link_to_the_zone_page(self, auth_client, one_allocation_row):
        period = one_allocation_row["period"]
        zone = one_allocation_row["zone"]
        response = auth_client.get(
            f"{reverse('accounting:allocations_list')}?period={period.pk}"
        )
        assert response.status_code == 200
        html = response.content.decode()

        expected_href = reverse("geography:zone_detail", args=[zone.pk])
        assert re.search(
            rf'<a href="{re.escape(expected_href)}"[^>]*>\s*{re.escape(zone.name)}',
            html,
        ), f"no <a href={expected_href!r}> wrapping the zone name found"


class TestAllocationsLandingDefault:
    """A bare GET lands on the current period; an explicit empty is 'All periods'."""

    def test_bare_get_lands_on_the_current_period_and_names_it(
        self, auth_client, one_allocation_row
    ):
        period = one_allocation_row["period"]
        response = auth_client.get(reverse("accounting:allocations_list"))
        assert response.status_code == 200
        assert response.context["period_id"] == str(period.pk)
        assert period.name in response.content.decode()

    def test_explicit_empty_period_renders_all_periods(self, auth_client, one_allocation_row):
        response = auth_client.get(f"{reverse('accounting:allocations_list')}?period=")
        assert response.status_code == 200
        assert "All periods" in response.content.decode()
