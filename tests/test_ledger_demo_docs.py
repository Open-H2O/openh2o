# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demonstration's surface allocations, the methodology page's written
rules, and the recharge site page's water-type label.

Each district's surface allocation is sized from what its canals deliver that
year, plus a stated margin; the methodology page states the constants and the
rounding a district needs to reproduce its own figures; and the recharge site
page uses "Credited to" for the water account only.
"""
import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.db.models import Sum
from django.test import Client
from django.urls import reverse

from accounting.models import AllocationPlan, ReportingPeriod, WaterType
from geography.models import ParcelZone, Zone
from parcels.models import ParcelLedger
from tests.factories import RechargeEventFactory, RechargeSiteFactory, ReportingPeriodFactory
from tests.test_merced_ledgers import (
    EL_NIDO_RIGHT,
    OPEN_WY,
    PRIOR_WY,
    _build_physical_merced,
)

MARGIN = Decimal("0.10")


def _delivered(zone, period):
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list("parcel_id", flat=True)
    total = ParcelLedger.objects.filter(
        parcel_id__in=parcel_ids, source_type="surface_diversion", reporting_period=period
    ).aggregate(s=Sum("amount_acre_feet"))["s"]
    return abs(total or Decimal("0"))


@pytest.mark.django_db
def test_each_surface_allocation_is_its_years_deliveries_plus_the_margin():
    _build_physical_merced()
    call_command("seed_merced_ledgers")
    sw = WaterType.objects.get(code="SW")
    zones = Zone.objects.filter(zone_type="custom", name__startswith="MER Surface Service Area")
    assert zones.count() == 2
    checked = 0
    for zone in zones:
        for period in ReportingPeriod.objects.filter(name__in=[PRIOR_WY, OPEN_WY]):
            plan = AllocationPlan.objects.get(zone=zone, water_type=sw, reporting_period=period)
            delivered = _delivered(zone, period)
            if EL_NIDO_RIGHT in zone.name and period.name == OPEN_WY:
                # The dry year: the canal delivers nothing, the allocation was cut.
                assert delivered == 0
                prior = AllocationPlan.objects.get(
                    zone=zone, water_type=sw, reporting_period__name=PRIOR_WY
                )
                assert 0 < plan.allocation_acre_feet <= prior.allocation_acre_feet
                continue
            assert delivered > 0, zone.name
            assert plan.allocation_acre_feet >= delivered, (zone.name, period.name)
            assert plan.allocation_acre_feet <= (delivered * (1 + MARGIN)).quantize(
                Decimal("0.0001")
            ) + Decimal("0.0001"), (zone.name, period.name)
            checked += 1
    assert checked == 3


# --- methodology page ---------------------------------------------------

def _login():
    from core.models import User

    user = User.objects.create(
        username="docsreader", email="docsreader@example.com",
        password=make_password("testpass123"), is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _methods_text():
    html = _login().get(reverse("methods")).content.decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.mark.django_db
class TestMethodologyStatesTheRules:
    def test_names_the_effective_rain_constants(self):
        text = _methods_text()
        for constant in ("0.531747", "0.295164", "0.057697", "0.003804",
                         "1.25", "0.824", "2.93", "0.000955"):
            assert constant in text, constant

    def test_names_half_to_even_rounding(self):
        assert "half to even" in _methods_text()

    def test_states_the_order_of_rounding_and_the_empty_delivery(self):
        text = _methods_text()
        assert "rounded once" in text
        assert "stored as 0" in text

    def test_states_how_a_headgates_water_is_divided_and_dated(self):
        text = _methods_text()
        assert "by the shares entered" in text
        assert "by acreage" in text
        assert "date of the diversion record" in text


def test_architecture_states_the_same_rules():
    from pathlib import Path

    text = Path(__file__).resolve().parent.parent.joinpath("ARCHITECTURE.md").read_text()
    for needle in ("0.531747", "0.824", "half to even", "stored as 0", "by acreage"):
        assert needle in text, needle


# --- recharge site page -------------------------------------------------

@pytest.mark.django_db
def test_recharge_site_page_says_credited_to_once_and_water_type_for_the_water():
    ReportingPeriodFactory(
        name=OPEN_WY, start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    site = RechargeSiteFactory()
    RechargeEventFactory(recharge_site=site, start_date=date(2026, 2, 1))
    html = _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "Log recharge event" in text, "the page should show the event form"
    assert text.count("Credited to") == 1
    assert re.search(r"<th[^>]*>\s*Water type\s*</th>", html)
    assert re.search(r"<label[^>]*>\s*Water type\s*</label>", html)


# --- a point that serves no field ---------------------------------------------


@pytest.mark.django_db
def test_the_demonstration_books_the_water_of_a_point_that_serves_no_field():
    """The seed divides the re-diversion that serves no field, so its water
    reaches the canal page as delivered to no field and a later engine run has
    nothing left to add."""
    from core.management.commands.seed_merced_operations import (
        JOURNEY_DOWNSTREAM_POD,
        JOURNEY_UPSTREAM_POD,
    )
    from surface.models import CanalMonthLoss, WaterRight
    from tests.factories import PointOfDiversionFactory
    from tests.test_merced_ledgers import NORMAL_RIGHT

    _build_physical_merced()
    right = WaterRight.objects.get(right_id=NORMAL_RIGHT)
    upstream = PointOfDiversionFactory(water_right=right, name=JOURNEY_UPSTREAM_POD)
    downstream = PointOfDiversionFactory(
        water_right=right,
        name=JOURNEY_DOWNSTREAM_POD,
        rediverted_from=upstream,
        evaporation_fraction=Decimal("0.0100"),
        seepage_fraction=Decimal("0"),
        spill_fraction=Decimal("0"),
    )
    call_command("seed_merced_ledgers")
    june = CanalMonthLoss.objects.get(
        point_of_diversion=downstream, month__year=2025, month__month=6
    )
    assert june.evaporation_af == Decimal("3.0000")
    assert june.unserved_af == Decimal("297.0000")
    assert CanalMonthLoss.objects.filter(point_of_diversion=downstream).count() == 8
