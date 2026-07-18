# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for check_et_meter_agreement — the satellite-ET-versus-meter cross-check.

Math eval 2026-07-18, item 9. The mass-balance closure metric cannot detect a
multiplicative error in OpenET's ET, because the residual method inflates both
sides of the identity together (doubling gross ET moved closure 0.07%). A meter
is the only instrument in the database independent of OpenET, so these tests
exist mainly to pin ONE behaviour: doubled ET must turn this check red.
"""

from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun
from health.checks import check_et_meter_agreement
from parcels.models import ParcelLedger
from tests.factories import ParcelFactory, ReportingPeriodFactory


pytestmark = pytest.mark.django_db


def _metered_parcel(period_month, *, consumptive_use, metered, surface="0"):
    """One metered parcel-month: an ET-derived run plus the meter that rebuts it."""
    parcel = ParcelFactory()
    consumptive_use = Decimal(consumptive_use)
    surface = Decimal(surface)
    CalculationRun.objects.create(
        parcel=parcel,
        period=period_month,
        # gross ET is the chain's starting magnitude; net consumptive use is what
        # survives the effective-precip subtraction and is what we compare.
        gross_et_af=consumptive_use,
        net_consumptive_use_af=consumptive_use,
        surface_water_af=surface,
        residual_disposition="metered",
    )
    if Decimal(metered) > 0:
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=date(int(period_month[:4]), int(period_month[5:]), 15),
            effective_date=date(int(period_month[:4]), int(period_month[5:]), 15),
            source_type="meter_reading",
            # Usage rows debit: stored negative, as production writes them.
            amount_acre_feet=-Decimal(metered),
        )
    return parcel


class TestAgreement:
    def test_returns_the_check_contract(self):
        result = check_et_meter_agreement()
        assert set(result) == {"category", "status", "message", "details"}
        assert result["category"] == "et_meter_agreement"
        assert result["status"] in {"green", "yellow", "red"}

    def test_no_metered_parcels_is_green_and_says_so(self):
        """A district with no meters cannot run this test. That is not a fault."""
        ReportingPeriodFactory()
        result = check_et_meter_agreement()
        assert result["status"] == "green"
        assert "nothing independent" in result["message"]
        assert result["details"]["comparable_parcel_periods"] == 0

    def test_plausible_efficiency_is_green(self):
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(month, consumptive_use="93", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "green"
        assert result["details"]["aggregate_ratio"] == "0.9300"
        assert result["details"]["comparable_parcel_periods"] == 3

    def test_doubled_et_turns_the_check_red(self):
        """THE point of this check — the failure closure is structurally blind to.

        Same meters, ET twice as large. Closure would barely move; this must not.
        """
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(month, consumptive_use="186", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "red"
        assert result["details"]["aggregate_ratio"] == "1.8600"
        assert "check ET magnitude" in result["message"]

    def test_implausibly_low_et_is_also_red(self):
        """Symmetry matters: understated ET hides pumping just as badly."""
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(month, consumptive_use="30", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "red"

    def test_mildly_out_of_band_aggregate_is_yellow_not_red(self):
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(month, consumptive_use="107", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "yellow"

    def test_one_odd_parcel_does_not_red_a_healthy_aggregate(self):
        """A single outlier is a data-quality signal, not a system failure."""
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(month, consumptive_use="900", metered="1000")
        _metered_parcel("2024-04", consumptive_use="20", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "yellow"
        assert len(result["details"]["out_of_band"]) == 1
        assert result["details"]["out_of_band"][0]["ratio"] == "0.200"
        # The aggregate stays healthy — the outlier is small next to the rest.
        assert Decimal(result["details"]["aggregate_ratio"]) > Decimal("0.60")

    def test_small_sample_never_judges(self):
        """Two parcels is anecdote. Report the number, refuse the verdict."""
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02"):
            _metered_parcel(month, consumptive_use="186", metered="100")
        result = check_et_meter_agreement()
        assert result["status"] == "green"
        assert "too small to judge" in result["message"]
        assert result["details"]["sufficient_sample"] is False

    def test_surface_water_counts_as_applied_water(self):
        """A conjunctive parcel is supplied by ditch AND well; both are applied.

        Ignoring the surface half would understate supply and fake an overshoot.
        """
        ReportingPeriodFactory()
        for month in ("2024-01", "2024-02", "2024-03"):
            _metered_parcel(
                month, consumptive_use="93", metered="50", surface="50"
            )
        result = check_et_meter_agreement()
        assert result["status"] == "green"
        assert result["details"]["aggregate_ratio"] == "0.9300"
        assert result["details"]["total_applied_water_af"] == "300.0000"

    def test_unmetered_parcels_are_ignored(self):
        """Only runs the engine marked `metered` have an independent witness."""
        ReportingPeriodFactory()
        parcel = ParcelFactory()
        CalculationRun.objects.create(
            parcel=parcel,
            period="2024-01",
            gross_et_af=Decimal("500"),
            net_consumptive_use_af=Decimal("500"),
            residual_disposition="groundwater",
        )
        result = check_et_meter_agreement()
        assert result["details"]["comparable_parcel_periods"] == 0
        assert result["status"] == "green"

    def test_meter_outside_the_period_months_is_not_counted(self):
        """Period membership has exactly one definition (item 6). Honour it."""
        ReportingPeriodFactory()
        parcel = _metered_parcel("2024-01", consumptive_use="93", metered="100")
        # A reading a year later must not be pulled into this period's supply.
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=date(2029, 1, 15),
            effective_date=date(2029, 1, 15),
            source_type="meter_reading",
            amount_acre_feet=Decimal("-9999"),
        )
        result = check_et_meter_agreement()
        assert result["details"]["by_period"][0]["applied_water_af"] == "100.0000"
