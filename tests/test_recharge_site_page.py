# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recharge list and recharge site page: capacity named the same way on
every screen, readings grouped by what they measure, one lead figure for
the water recharged.

143-10 (R-125, R-126, R-055 recharge). Before this plan the recharge list's
Capacity column said "637 AF" with nothing saying what it was the capacity
of (R-125); the site page's Recent measurements table put mg/L, ft, cfs and
in/hr in one Value column ordered only by date (R-126); and its Event
history table gave Volume no more weight than Start (R-055).

Every assertion below is the fixture's own pasted literal -- 100.00 + 50.00
= 150.00 recharged this water year, 70.00 the prior year's own total --
never a re-derivation of ``recharge.views._group_recharge_events``'s own
arithmetic, and the combined 220.00 across both years must appear nowhere
(rule: nothing adds across water years, ISS-155/156).
"""
import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tests.factories import (
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

CURRENT_NAME = "WY 2025-2026"
PRIOR_NAME = "WY 2024-2025"


def _periods():
    prior = ReportingPeriodFactory(
        name=PRIOR_NAME, start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    current = ReportingPeriodFactory(
        name=CURRENT_NAME, start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    return prior, current


_login_count = 0


def _login():
    from core.models import User

    global _login_count
    _login_count += 1
    user = User.objects.create(
        username=f"basinreader{_login_count}",
        email=f"basinreader{_login_count}@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _site_page(site):
    return _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()


def _reading(site, day, mtype, value, unit, notes=""):
    from recharge.models import RechargeMeasurement

    return RechargeMeasurement.objects.create(
        recharge_site=site,
        measurement_date=timezone.make_aware(datetime(2026, 2, day, 9, 0)),
        measurement_type=mtype,
        value=Decimal(value),
        unit=unit,
        notes=notes,
    )


def _result_segment_values(html):
    return re.findall(
        r'<div class="budget-seg budget-seg--result">.*?'
        r'<div class="budget-seg-value[^"]*">\s*([\d,]+\.\d{2})',
        html,
        re.DOTALL,
    )


class TestRechargeCapacityNamedTheSameWayEverywhere:
    """R-125: "Capacity per fill" on the list, the site page and the add form."""

    def test_the_list_header_names_capacity_per_fill(self):
        RechargeSiteFactory(capacity_acre_feet=Decimal("637.1000"))
        html = _login().get(reverse("recharge:list")).content.decode()
        assert "Capacity per fill (AF)" in html

    def test_the_site_page_labels_it_the_same_way(self):
        site = RechargeSiteFactory(capacity_acre_feet=Decimal("637.1000"))
        html = _site_page(site)
        assert "Capacity per fill (AF)" in html
        assert "637.10" in html

    def test_the_add_form_labels_it_capacity_per_fill_on_both_cards(self):
        html = (
            _login()
            .get(reverse("infrastructure:add") + "?type=recharge_site")
            .content.decode()
        )
        assert "Capacity per fill (acre-feet)" in html
        html = (
            _login()
            .get(reverse("infrastructure:add") + "?type=storage")
            .content.decode()
        )
        assert "Capacity per fill (acre-feet)" in html


class TestRechargeMeasurementsGroupedByType:
    """R-126: one row-group per measurement type present, naming its unit."""

    def test_two_types_render_as_two_named_groups_in_choice_order(self):
        site = RechargeSiteFactory()
        _reading(site, 17, "water_level", "2.5900", "ft")
        _reading(site, 10, "water_level", "3.2300", "ft")
        _reading(site, 16, "flow_rate", "52.3700", "cfs")

        html = _site_page(site)
        card = html[html.index("Recent measurements"):]
        card = card[: card.index("</table>")]

        assert "Water level, ft" in card
        assert "Flow rate, cfs" in card
        assert card.index("Water level, ft") < card.index("Flow rate, cfs")
        assert "<th>Unit</th>" not in card

    def test_a_note_sits_in_a_td_on_its_own_reading_row(self):
        site = RechargeSiteFactory()
        _reading(site, 17, "water_level", "2.5900", "ft", notes="Turbid after the storm.")
        _reading(site, 10, "water_level", "3.2300", "ft")

        html = _site_page(site)
        card = html[html.index("Recent measurements"):]
        card = card[: card.index("</table>")]
        assert "Turbid after the storm." in card
        assert "&mdash;" in card  # the un-noted reading's empty cell


class TestRechargeLeadPanel:
    """R-055 recharge: one current-year result; nothing sums across years."""

    def test_current_year_events_sum_to_one_result_figure(self):
        site = RechargeSiteFactory()
        _periods()
        RechargeEventFactory(recharge_site=site, start_date=date(2025, 11, 1), volume_acre_feet=Decimal("100.0000"))
        RechargeEventFactory(recharge_site=site, start_date=date(2025, 12, 1), volume_acre_feet=Decimal("50.0000"))
        RechargeEventFactory(recharge_site=site, start_date=date(2025, 1, 1), volume_acre_feet=Decimal("70.0000"))

        html = _site_page(site)

        assert html.count('class="budget-seg budget-seg--result"') == 1
        assert _result_segment_values(html) == ["150.00"]

        subtotals = re.findall(r'<tr class="row-subtotal">.*?</tr>', html, re.S)
        (prior_row,) = [b for b in subtotals if PRIOR_NAME in b]
        assert "70.00" in prior_row

        assert "220.00" not in html
