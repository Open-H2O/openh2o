# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for Phase 39-02: carry-over storage, the rollover command,
and the dashboard fold-in.

39-01 proved the pure math (tests/test_carryover_math.py). This file proves the
DB-bound wiring: that the rollover_allocations command stores the right SIGNED
row at the right (zone, water_type, water_year) grain, that it is idempotent and
never touches finalized ledger rows (ISS-020), and that the dashboard's
"remaining" now reflects carried-forward surplus or debt.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounting.models import AllocationCarryover
from accounting.services import (
    water_year_periods,
    water_year_usage_by_type,
    zone_carryover,
)
from parcels.models import ParcelLedger
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"co_user{n}")
    email = factory.Sequence(lambda n: f"co_user{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def gw_type():
    return WaterTypeFactory(name="Groundwater", code="GW")


def wy_period(name, start, end, finalized=True):
    return ReportingPeriodFactory(
        name=name, start_date=start, end_date=end, is_finalized=finalized
    )


def usage_row(
    parcel,
    eff_date,
    af,
    *,
    source_type="et_estimate",
    water_type=None,
    reporting_period=None,
):
    """A negative (usage) ledger row dated to eff_date.

    ``reporting_period`` defaults to None (matching real et_estimate rows, which
    the rollover catches via effective_date). The dashboard, however, filters
    usage by the reporting_period FK, so dashboard fixtures set it explicitly.
    """
    return ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=date.today(),
        effective_date=eff_date,
        amount_acre_feet=Decimal(str(-abs(af))),
        source_type=source_type,
        water_type=water_type,
        reporting_period=reporting_period,
    )


# ---------------------------------------------------------------------------
# water_year_periods — labelled by end_date
# ---------------------------------------------------------------------------


class TestWaterYearPeriods:
    def test_annual_period_labelled_by_end_year(self):
        wy_period("WY 2023-2024", date(2023, 10, 1), date(2024, 9, 30))
        wy_period("WY 2024-2025", date(2024, 10, 1), date(2025, 9, 30))

        got = water_year_periods(2024)
        assert [p.name for p in got] == ["WY 2023-2024"]
        got2025 = water_year_periods(2025)
        assert [p.name for p in got2025] == ["WY 2024-2025"]

    def test_october_month_rolls_into_next_water_year(self):
        # A monthly period ending in October belongs to the NEXT water year
        # (anchor month 10), exactly like carryover_math.water_year_of.
        wy_period("Oct 2024", date(2024, 10, 1), date(2024, 10, 31))
        assert [p.name for p in water_year_periods(2025)] == ["Oct 2024"]
        assert water_year_periods(2024) == []

    def test_empty_when_no_period(self):
        assert water_year_periods(1999) == []


# ---------------------------------------------------------------------------
# water_year_usage_by_type — engine rows -> GW, billable_ledger applied
# ---------------------------------------------------------------------------


class TestUsageByType:
    def test_engine_rows_bucket_to_groundwater(self):
        gw = gw_type()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)

        # et_estimate carries NULL water_type but is groundwater extraction.
        usage_row(parcel, date(2024, 6, 1), 30, source_type="et_estimate")
        # a metered groundwater pull, typed GW.
        usage_row(
            parcel, date(2024, 7, 1), 12, source_type="meter_reading", water_type=gw
        )

        buckets = water_year_usage_by_type(zone, date(2024, 1, 1), date(2024, 12, 31))
        assert buckets["GW"] == Decimal("42.0000")

    def test_calculated_row_suppresses_its_et_estimate_twin(self):
        gw = gw_type()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)

        # Gross ET 30 and a netted calculated 18 for the SAME parcel-month: only
        # the calculated row should bill (no ET double-count), both -> GW.
        usage_row(parcel, date(2024, 6, 1), 30, source_type="et_estimate")
        usage_row(parcel, date(2024, 6, 1), 18, source_type="calculated")

        buckets = water_year_usage_by_type(zone, date(2024, 1, 1), date(2024, 12, 31))
        assert buckets["GW"] == Decimal("18.0000")

    def test_date_range_excludes_outside_months(self):
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        usage_row(parcel, date(2024, 6, 1), 30, source_type="et_estimate")
        usage_row(parcel, date(2025, 6, 1), 99, source_type="et_estimate")

        buckets = water_year_usage_by_type(zone, date(2024, 1, 1), date(2024, 12, 31))
        assert buckets["GW"] == Decimal("30.0000")


# ---------------------------------------------------------------------------
# rollover_allocations command
# ---------------------------------------------------------------------------


class TestRolloverCommand:
    def _setup(self, alloc=100, usage=30, finalized=True):
        gw = gw_type()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        period = wy_period(
            "WY 2023-2024", date(2023, 10, 1), date(2024, 9, 30), finalized
        )
        AllocationPlanFactory(
            zone=zone,
            water_type=gw,
            reporting_period=period,
            allocation_acre_feet=Decimal(str(alloc)),
        )
        if usage:
            usage_row(parcel, date(2024, 6, 1), usage, source_type="et_estimate")
        return zone, gw

    def test_surplus_rolls_forward_signed(self):
        zone, gw = self._setup(alloc=100, usage=30)
        call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

        row = AllocationCarryover.objects.get(zone=zone, water_type=gw)
        assert row.water_year == 2025
        assert row.source_water_year == 2024
        assert row.amount_af == Decimal("70.0000")

    def test_overdraw_rolls_forward_as_debt(self):
        zone, gw = self._setup(alloc=100, usage=130)
        call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

        row = AllocationCarryover.objects.get(zone=zone, water_type=gw)
        assert row.amount_af == Decimal("-30.0000")

    def test_idempotent_double_run(self):
        self._setup(alloc=100, usage=30)
        call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())
        first = list(
            AllocationCarryover.objects.values_list("amount_af", flat=True)
        )
        call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())
        second = list(
            AllocationCarryover.objects.values_list("amount_af", flat=True)
        )
        assert AllocationCarryover.objects.count() == 1
        assert first == second == [Decimal("70.0000")]

    def test_dry_run_writes_nothing(self):
        self._setup(alloc=100, usage=30)
        call_command(
            "rollover_allocations",
            "--water-year",
            "2024",
            "--dry-run",
            stdout=StringIO(),
        )
        assert AllocationCarryover.objects.count() == 0

    def test_provisional_warning_when_not_finalized(self):
        self._setup(alloc=100, usage=30, finalized=False)
        out = StringIO()
        call_command("rollover_allocations", "--water-year", "2024", stdout=out)
        assert "PROVISIONAL" in out.getvalue()

    def test_no_warning_when_finalized(self):
        self._setup(alloc=100, usage=30, finalized=True)
        out = StringIO()
        call_command("rollover_allocations", "--water-year", "2024", stdout=out)
        assert "PROVISIONAL" not in out.getvalue()

    def test_does_not_mutate_ledger_rows(self):
        # ISS-020 guard: rollover only READS the prior year and WRITES new
        # carry-over rows — it must never touch a finalized period's ledger.
        self._setup(alloc=100, usage=30, finalized=True)
        before = list(
            ParcelLedger.objects.values_list("id", "amount_acre_feet").order_by("id")
        )
        call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())
        after = list(
            ParcelLedger.objects.values_list("id", "amount_acre_feet").order_by("id")
        )
        assert before == after

    def test_errors_when_no_period(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command(
                "rollover_allocations", "--water-year", "1990", stdout=StringIO()
            )


# ---------------------------------------------------------------------------
# zone_carryover helper
# ---------------------------------------------------------------------------


class TestZoneCarryover:
    def test_zero_when_none(self):
        zone = ZoneFactory()
        assert zone_carryover(zone, 2025) == Decimal("0")

    def test_signed_sum_across_types(self):
        gw = WaterTypeFactory(name="Groundwater", code="GW")
        sw = WaterTypeFactory(name="Surface Water", code="SW")
        zone = ZoneFactory()
        AllocationCarryover.objects.create(
            zone=zone, water_type=gw, water_year=2025, amount_af=Decimal("80")
        )
        AllocationCarryover.objects.create(
            zone=zone, water_type=sw, water_year=2025, amount_af=Decimal("-30")
        )
        assert zone_carryover(zone, 2025) == Decimal("50")


# ---------------------------------------------------------------------------
# Dashboard fold-in
# ---------------------------------------------------------------------------


class TestDashboardCarryover:
    def _setup_dashboard(self, carryover_af):
        gw = gw_type()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        # Selected period = WY ending 2026-09-30 -> water_year 2026.
        period = wy_period(
            "WY 2025-2026", date(2025, 10, 1), date(2026, 9, 30), finalized=False
        )
        AllocationPlanFactory(
            zone=zone,
            water_type=gw,
            reporting_period=period,
            allocation_acre_feet=Decimal("1000"),
        )
        # Usage of 200 inside the selected period. Set reporting_period so the
        # dashboard's period-filtered balance counts it (current-year usage).
        usage_row(
            parcel,
            date(2026, 1, 1),
            200,
            source_type="meter_reading",
            water_type=gw,
            reporting_period=period,
        )
        # 57-02 budget basis: the dashboard's zone "remaining" is now consumed by
        # measured CONSUMPTIVE USE (gross ET from CalculationRuns), not the pumped
        # row alone. Record 200 AF of ET in a month inside the period so remaining
        # = budget(+carryover) − 200, exactly as the assertions below expect.
        from accounting.models import CalculationRun

        CalculationRun.objects.create(
            parcel=parcel,
            period="2026-01",
            gross_et_af=Decimal("200"),
            net_consumptive_use_af=Decimal("200"),
            effective_precip_af=Decimal("0"),
            final_af=Decimal("0"),
        )
        if carryover_af is not None:
            AllocationCarryover.objects.create(
                zone=zone,
                water_type=gw,
                water_year=2026,
                source_water_year=2025,
                amount_af=Decimal(str(carryover_af)),
            )
        return zone, period

    def _zone_row(self, response, zone):
        return next(
            r for r in response.context["zone_summaries"] if r["zone"].id == zone.id
        )

    def test_surplus_carryover_raises_remaining(self):
        zone, period = self._setup_dashboard(carryover_af=300)
        client = Client()
        client.force_login(UserFactory())
        resp = client.get(reverse("accounting:dashboard"), {"period": period.id})
        row = self._zone_row(resp, zone)
        # remaining = allocation 1000 + carryover 300 - consumptive use 200 = 1100
        assert row["carryover"] == Decimal("300.0000")
        assert row["remaining"] == Decimal("1100.0000")

    def test_debt_carryover_reduces_remaining(self):
        # The live demo has no over-drawn zone; this proves the debt path renders.
        zone, period = self._setup_dashboard(carryover_af=-400)
        client = Client()
        client.force_login(UserFactory())
        resp = client.get(reverse("accounting:dashboard"), {"period": period.id})
        row = self._zone_row(resp, zone)
        # remaining = allocation 1000 + carryover (-400) - consumptive use 200 = 400
        assert row["carryover"] == Decimal("-400.0000")
        assert row["remaining"] == Decimal("400.0000")
        # The carried-forward column renders in the HTML with a minus sign.
        assert b"Carried fwd" in resp.content

    def test_no_carryover_row_is_zero(self):
        zone, period = self._setup_dashboard(carryover_af=None)
        client = Client()
        client.force_login(UserFactory())
        resp = client.get(reverse("accounting:dashboard"), {"period": period.id})
        row = self._zone_row(resp, zone)
        assert row["carryover"] == Decimal("0")
        # remaining = 1000 + 0 - 200 = 800
        assert row["remaining"] == Decimal("800.0000")
