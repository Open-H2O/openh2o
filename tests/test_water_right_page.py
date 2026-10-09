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


# ---------------------------------------------------------------------------
# 150-02 Task 5: the page by water year. Face value 100.00; WY 2023-2024 holds
# 70.00 typed (January) and 50.00 estimated (February), 120.00 in all, 20.00
# over its face value; WY 2024-2025 holds 80.00 typed, 20.00 remaining. The
# newer year is the current one (the most recent period, nothing on the
# ledger), so the equation row reads 100.00 - 80.00 = 20.00.
# ---------------------------------------------------------------------------
ESTIMATED_BADGE = (
    '<span class="badge badge-grey" title="At least one diversion record this '
    'month is estimated from use, not measured.">Estimated</span>'
)


def _two_year_right(face_value=Decimal("100.0000"), *, estimate_in_current=False):
    right = WaterRightFactory(face_value_acre_feet=face_value)
    pod = PointOfDiversionFactory(water_right=right, name="Alder Ditch Headgate")
    wy2024 = ReportingPeriodFactory(
        name="WY 2023-2024", start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
    )
    wy2025 = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2024, month=date(2024, 1, 1),
        volume_acre_feet=Decimal("70.0000"), method="methodology",
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2024, month=date(2024, 2, 1),
        volume_acre_feet=Decimal("50.0000"), method="estimated_from_use",
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2025, month=date(2025, 1, 1),
        volume_acre_feet=Decimal("80.0000"),
        method="estimated_from_use" if estimate_in_current else "",
    )
    return right


class TestWaterRightByWaterYear:
    """Every water year on record is set against the face value."""

    def test_the_year_past_its_face_value_is_flagged_once_by_the_amount_over(self):
        html = _right_page(_two_year_right())

        assert '<b class="text-deficit">20.00 AF</b> over its face value' in html
        assert html.count("over its face value") == 1
        assert '<span class="text-secondary">20.00 AF remaining</span>' in html
        assert "violation" not in html.lower()

    def test_the_head_line_says_every_year_is_compared_below(self):
        html = _right_page(_two_year_right())

        assert (
            "Remaining is the face value less the volume recorded. Every water "
            "year on record is compared below."
        ) in html

    def test_the_year_with_an_estimate_says_how_many_of_its_months_were_estimated(self):
        html = _right_page(_two_year_right())

        assert (
            '<td colspan="4">WY 2023-2024 &middot; 2 records &middot; '
            "1 of 2 months estimated</td>"
        ) in html
        assert '<td colspan="4">WY 2024-2025 &middot; 1 record</td>' in html
        assert html.count(ESTIMATED_BADGE) == 1
        assert '<div class="text-tertiary text-xs">1 of 2 months</div>' in html

    def test_the_equation_still_reads_the_current_year(self):
        html = _right_page(_two_year_right())

        assert _result_segment_values(html) == ["20.00"]
        assert "diverted at 1 point, WY 2024-2025" in html
        assert "recorded and estimated" not in html

    def test_the_recorded_caption_names_the_estimate_when_the_current_year_holds_one(self):
        html = _right_page(_two_year_right(estimate_in_current=True))

        assert "recorded and estimated, diverted at 1 point, WY 2024-2025" in html

    def test_a_right_with_no_face_value_lists_its_years_with_nothing_set_against_them(self):
        html = _right_page(_two_year_right(face_value=None))

        assert "No face value is on record for this right." in html
        assert "By water year" in html
        assert "120.00" in html
        assert "over its face value" not in html
        assert "AF remaining" not in html


class TestWaterRightCardsTakeTheirContentsHeight:
    """ISS-201 on this page: the face-value card and the curtailment card are
    each their content's height, by modifiers this page alone carries, so the
    account page's balance cell (the same grid) keeps its stretch."""

    def test_the_page_carries_both_modifiers_and_the_stylesheet_defines_them(self):
        from pathlib import Path

        from surface.models import CurtailmentOrder

        right = WaterRightFactory(
            face_value_acre_feet=Decimal("100.0000"),
            priority_date=date(1962, 5, 5),
            source_name="El Nido Canal",
        )
        CurtailmentOrder.objects.create(
            order_id="TEST-CURT-PAGE", title="Test order",
            effective_date=date(2020, 1, 1), watershed="El Nido Canal",
            priority_date_cutoff=date(1962, 5, 5),
        )
        html = _right_page(right)
        css = (Path(__file__).resolve().parent.parent / "static/css/app.css").read_text()

        assert (
            'class="card-raised page-grid-account-balance '
            'page-grid-account-balance--content-height"'
        ) in html
        assert 'class="page-grid-2col page-grid-2col--align-start page-grid-account-full"' in html
        assert re.search(
            r"\.page-grid-account-balance--content-height\s*\{\s*align-self:\s*start;\s*\}", css
        )
        assert re.search(r"\.page-grid-2col--align-start\s*\{\s*align-items:\s*start;\s*\}", css)
