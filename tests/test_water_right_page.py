# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water right page composed as a page: Face value minus Recorded equals
Remaining, a stable point-of-diversion order, every record grouped by water
year.

143-10 (R-121, R-122, R-055 right). Before this plan the page showed a face
value of 60000.00 and twelve records under "Recent diversion records", with
nothing summing them or setting the sum against the face value (R-121, and
R-055: no figure on the page was larger than any other); and inside one
month the two points of diversion swapped order from row to row because the
query ordered by ``-month`` alone, with no secondary key (R-122).

Every assertion below is the fixture's own pasted literal -- face value
60,000.00, recorded 1,200.00 + 300.00 = 1,500.00, remaining
60,000.00 - 1,500.00 = 58,500.00 -- never a re-derivation of
``surface.views._water_right_detail_context``'s own arithmetic.
"""
import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
)

pytestmark = pytest.mark.django_db

CURRENT_NAME = "WY 2025-2026"


def _current_period():
    # A single period is enough here: current_period_id() falls back to the
    # most recent ReportingPeriod by start_date when nothing has reached the
    # ledger, and there is only ever one candidate in these fixtures.
    return ReportingPeriodFactory(
        name=CURRENT_NAME, start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )


def _login():
    from core.models import User

    user = User.objects.create(
        username="rightreader",
        email="rightreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _right_page(right):
    return _login().get(reverse("surface:detail", args=[right.pk])).content.decode()


def _result_segment_values(html):
    return re.findall(
        r'<div class="budget-seg budget-seg--result">.*?'
        r'<div class="budget-seg-value[^"]*">\s*([\d,]+\.\d{2})',
        html,
        re.DOTALL,
    )


class TestWaterRightLeadPanel:
    """R-121 and R-055 right: Remaining is the ONLY large figure on the page."""

    def test_face_value_minus_recorded_equals_remaining(self):
        right = WaterRightFactory(face_value_acre_feet=Decimal("60000.0000"))
        current = _current_period()
        pod_a = PointOfDiversionFactory(water_right=right, name="MER-POD-010-DEMO Merced Falls Hydroelectric Diversion")
        pod_b = PointOfDiversionFactory(water_right=right, name="MER-POD-011-DEMO Snelling Re-Diversion")
        DiversionRecordFactory(
            point_of_diversion=pod_a, reporting_period=current,
            month=date(2026, 2, 1), volume_acre_feet=Decimal("1200.0000"),
        )
        DiversionRecordFactory(
            point_of_diversion=pod_b, reporting_period=current,
            month=date(2026, 2, 1), volume_acre_feet=Decimal("300.0000"),
        )
        html = _right_page(right)

        assert _result_segment_values(html) == ["58,500.00"]
        assert "60,000.00" in html
        panel = html[html.index('page-grid-account-balance'):html.index('page-grid-account-balance') + 3000]
        assert "1,500.00" in panel

    def test_no_face_value_renders_no_operators_and_the_no_face_value_sentence(self):
        right = WaterRightFactory(face_value_acre_feet=None)
        html = _right_page(right)
        assert "No face value is on record for this right." in html
        assert html.count('class="budget-seg budget-seg--result"') == 1
        panel_start = html.index('page-grid-account-balance')
        panel = html[panel_start:panel_start + 3000]
        assert "budget-op" not in panel


class TestWaterRightRecordOrder:
    """R-122: a stable secondary sort so two PODs recording in the same month
    always read in the same order, across every month."""

    def test_merced_falls_sorts_before_snelling_in_every_month(self):
        right = WaterRightFactory(face_value_acre_feet=Decimal("60000.0000"))
        current = _current_period()
        snelling = PointOfDiversionFactory(water_right=right, name="MER-POD-011-DEMO Snelling Re-Diversion")
        merced_falls = PointOfDiversionFactory(water_right=right, name="MER-POD-010-DEMO Merced Falls Hydroelectric Diversion")
        for month in (date(2026, 2, 1), date(2026, 3, 1)):
            # Snelling created first each month, so an unordered (or month-only)
            # query would be the one place this could still swap.
            DiversionRecordFactory(
                point_of_diversion=snelling, reporting_period=current,
                month=month, volume_acre_feet=Decimal("300.0000"),
            )
            DiversionRecordFactory(
                point_of_diversion=merced_falls, reporting_period=current,
                month=month, volume_acre_feet=Decimal("1200.0000"),
            )
        html = _right_page(right)
        table = html[html.index('<table class="data-table text-sm data-table--grouped">'):]
        table = table[:table.index("</table>")]
        for month_label in ("Feb 2026", "Mar 2026"):
            month_pos = table.index(month_label)
            # The SAME month appears twice (once per POD); the first occurrence
            # in document order must be Merced Falls, in both months.
            row = table[month_pos:table.index("</tr>", month_pos)]
            assert "Merced Falls" in row, (
                f"expected Merced Falls's row before Snelling's for {month_label}"
            )
