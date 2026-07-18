# SPDX-License-Identifier: AGPL-3.0-or-later
"""Period selection by DATE, not by lexical month string (math eval item 6).

CalculationRun.period is a "YYYY-MM" string, and period selection used to be a
lexical range over that text in three different places. This pins the single
canonical selector: the derived period_start date is always in lockstep with the
string, the whole-month membership rule is explicit, and a mid-month period is
reported rather than silently truncated.
"""
from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun, ReportingPeriod
from accounting.services import runs_in_period
from health.checks import check_period_month_alignment
from tests.factories import ParcelFactory

pytestmark = pytest.mark.django_db


def _run(parcel, period, net=10):
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(net)),
        net_consumptive_use_af=Decimal(str(net)),
        final_af=Decimal("0"),
    )


def _period(name, start, end, finalized=False):
    return ReportingPeriod.objects.create(
        name=name, start_date=start, end_date=end, is_finalized=finalized
    )


class TestPeriodStartDerivation:
    def test_period_start_is_derived_on_save(self):
        run = _run(ParcelFactory(), "2024-06")
        assert run.period_start == date(2024, 6, 1)
        run.refresh_from_db()
        assert run.period_start == date(2024, 6, 1)

    def test_changing_period_updates_period_start(self):
        run = _run(ParcelFactory(), "2024-06")
        run.period = "2024-09"
        run.save()
        run.refresh_from_db()
        assert run.period_start == date(2024, 9, 1)

    def test_update_fields_save_still_syncs_period_start(self):
        """A targeted save(update_fields=["period"]) must not strand the date."""
        run = _run(ParcelFactory(), "2024-06")
        run.period = "2024-11"
        run.save(update_fields=["period"])
        run.refresh_from_db()
        assert run.period_start == date(2024, 11, 1)

    def test_unparseable_period_yields_null_not_a_crash(self):
        run = _run(ParcelFactory(), "garbage")
        assert run.period_start is None


class TestRunsInPeriod:
    def test_selects_only_months_in_the_period(self):
        p = ParcelFactory()
        _run(p, "2024-01")
        june = _run(p, "2024-06")
        _run(p, "2024-12")
        period = _period("Q2ish", date(2024, 5, 1), date(2024, 7, 31))

        got = runs_in_period(CalculationRun.objects.all(), period)
        assert [r.pk for r in got] == [june.pk]

    def test_boundary_months_are_inclusive(self):
        p = ParcelFactory()
        may = _run(p, "2024-05")
        july = _run(p, "2024-07")
        period = _period("May-Jul", date(2024, 5, 1), date(2024, 7, 31))

        got = {r.pk for r in runs_in_period(CalculationRun.objects.all(), period)}
        assert got == {may.pk, july.pk}

    def test_none_period_is_a_no_op(self):
        p = ParcelFactory()
        _run(p, "2024-01")
        _run(p, "2024-06")
        assert runs_in_period(CalculationRun.objects.all(), None).count() == 2

    def test_mid_month_period_counts_partial_months_whole(self):
        """The documented limitation, pinned so it cannot change silently.

        A monthly run cannot be split without pro-rating, so a period running
        15 Mar - 15 Sep includes ALL of March and ALL of September.
        """
        p = ParcelFactory()
        march = _run(p, "2024-03")
        june = _run(p, "2024-06")
        september = _run(p, "2024-09")
        period = _period("Mid-month", date(2024, 3, 15), date(2024, 9, 15))

        got = {r.pk for r in runs_in_period(CalculationRun.objects.all(), period)}
        assert got == {march.pk, june.pk, september.pk}

    def test_period_ending_before_a_month_excludes_it(self):
        p = ParcelFactory()
        _run(p, "2024-10")
        period = _period("Through Sep", date(2024, 1, 1), date(2024, 9, 30))
        assert runs_in_period(CalculationRun.objects.all(), period).count() == 0


class TestPeriodAlignmentCheck:
    def test_month_aligned_periods_are_green(self):
        _period("WY 2024", date(2023, 10, 1), date(2024, 9, 30))
        result = check_period_month_alignment()
        assert result["status"] == "green"
        assert result["details"]["offenders"] == []

    def test_mid_month_period_is_flagged(self):
        _period("Odd season", date(2024, 3, 15), date(2024, 9, 15))
        result = check_period_month_alignment()
        assert result["status"] == "yellow"
        assert result["details"]["offenders"][0]["period"] == "Odd season"

    def test_period_ending_on_a_short_month_end_is_aligned(self):
        """Feb 29 in a leap year IS the month end — not a mid-month boundary."""
        _period("Leap Feb", date(2024, 2, 1), date(2024, 2, 29))
        assert check_period_month_alignment()["status"] == "green"
