# SPDX-License-Identifier: AGPL-3.0-or-later
"""The diversion (point of diversion) page composed as a page: a lead figure,
a structured equation, a water-year-grouped records table.

143-10 (R-115, R-055 diversion, R-112 POD). Before this plan the diversion
page printed Diverted, Return flow and Retained as one flat row of like
figures with the return-flow badge wrapped inside the Retained cell and the
water year repeated on every row (R-115); Diverted, the figure the page
exists for, was one cell like any other, the same size as everything else
(R-055); and the left column ran to the bottom of the page while the right
column ended well short of it (R-112).

Every assertion below names the fixture's own literal value -- diverted
100.00 + 200.00 = 300.00, returned 25.00 + 0.00 = 25.00, retained
300.00 - 25.00 = 275.00 -- and none re-derives the arithmetic
``surface.views._group_diversion_records`` already computes (the three
standing review questions: a numeric test asserts a VALUE not a direction; a
test may not re-derive the formula it tests; a figure that adds rows says
what makes them addable).
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
)

pytestmark = pytest.mark.django_db

CURRENT_NAME = "WY 2025-2026"
PRIOR_NAME = "WY 2024-2025"


def _periods():
    """The prior water year, then the current one (latest start_date).

    ``accounting.services.current_period_id`` falls back to the most recent
    ``ReportingPeriod`` by ``start_date`` when nothing has been through the
    ledger yet (its third fallback) -- exactly the case here, since these
    fixtures write ``DiversionRecord`` rows directly and never touch
    ``ParcelLedger``.
    """
    prior = ReportingPeriodFactory(
        name=PRIOR_NAME, start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    current = ReportingPeriodFactory(
        name=CURRENT_NAME, start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    return prior, current


def _login():
    from core.models import User

    user = User.objects.create(
        username="podreader",
        email="podreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _pod_page(pod):
    return _login().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()


def _row_subtotal_blocks(html):
    return re.findall(r'<tr class="row-subtotal">.*?</tr>', html, re.S)


def _th_col_sep(html):
    return re.findall(r'<th[^>]*\bcol-sep\b[^>]*>([^<]*)</th>', html)


def _thead(html):
    marker = 'id="diversion-records-section"'
    section = html[html.index(marker):]
    return section[section.index("<thead>"):section.index("</thead>")]


class TestPodRecordsGroupedByWaterYear:
    """R-115: the equation reads by structure, one water year per group."""

    def _two_year_pod(self):
        pod = PointOfDiversionFactory()
        prior, current = _periods()
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=current,
            month=date(2025, 11, 1), volume_acre_feet=Decimal("100.0000"),
            returned_af=Decimal("25.0000"),
        )
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=current,
            month=date(2025, 12, 1), volume_acre_feet=Decimal("200.0000"),
            returned_af=Decimal("0"),
        )
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=prior,
            month=date(2025, 3, 1), volume_acre_feet=Decimal("50.0000"),
            returned_af=Decimal("0"),
        )
        return pod

    def test_current_year_subtotal_row_carries_the_three_summed_figures(self):
        html = _pod_page(self._two_year_pod())
        subtotals = _row_subtotal_blocks(html)
        (current_row,) = [b for b in subtotals if CURRENT_NAME in b]
        assert "300.00" in current_row
        assert "25.00" in current_row
        assert "275.00" in current_row

    def test_exactly_one_col_sep_header_reading_retained(self):
        html = _pod_page(self._two_year_pod())
        headers = _th_col_sep(html)
        assert len(headers) == 1
        assert headers[0].strip() == "Retained"

    def test_no_header_reads_period(self):
        html = _pod_page(self._two_year_pod())
        assert "Period" not in _thead(html)

    def test_prior_year_gets_its_own_group_and_subtotal(self):
        html = _pod_page(self._two_year_pod())
        assert re.search(
            r'<tr class="row-group">\s*<td colspan="5">' + re.escape(PRIOR_NAME), html
        )
        subtotals = _row_subtotal_blocks(html)
        (prior_row,) = [b for b in subtotals if PRIOR_NAME in b]
        assert "50.00" in prior_row


class TestPodLeadPanel:
    """R-055 diversion: Retained is the ONLY large figure, Diverted a plain segment."""

    def test_one_result_segment_reading_the_retained_figure(self):
        pod = PointOfDiversionFactory()
        prior, current = _periods()
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=current,
            month=date(2025, 11, 1), volume_acre_feet=Decimal("100.0000"),
            returned_af=Decimal("25.0000"),
        )
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=current,
            month=date(2025, 12, 1), volume_acre_feet=Decimal("200.0000"),
            returned_af=Decimal("0"),
        )
        html = _pod_page(pod)
        assert html.count('class="budget-seg budget-seg--result"') == 1
        panel = html[html.index('class="budget-panel"'):html.index('class="budget-panel"') + 2000]
        assert "300.00" in panel
        assert "275.00" in panel

    def test_no_records_in_the_current_period_shows_no_figure(self):
        pod = PointOfDiversionFactory()
        _periods()  # current period exists, but nothing is recorded in it
        html = _pod_page(pod)
        assert f"No records in {CURRENT_NAME}." in html
        panel = html[html.index('class="budget-panel"'):html.index('class="budget-panel"') + 2000]
        assert panel.count("&mdash;") == 3
        assert "300.00" not in panel


class TestPodPageGrid:
    """R-112: the account grid, not the old two-column layout that let the
    right-hand column end a third of the way down the page."""

    def test_page_grid_account_present_and_records_card_is_full_width(self):
        pod = PointOfDiversionFactory()
        html = _pod_page(pod)
        assert "page-grid-account" in html
        assert (
            'page-grid-account-full" style="padding: 0;" id="diversion-records-section"'
            in html
        )
