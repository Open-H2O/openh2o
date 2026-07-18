# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for 38-06 billing reconciliation.

The engine (38-02→38-05) writes a netted ``calculated`` ledger row per
parcel-month alongside the pre-existing gross ``et_estimate`` row. Both are
stored negative, so summing every row double-counts ET. ``billable_ledger``
implements the settled prefer-calculated-else-et_estimate rule: where a
``calculated`` row exists for a (parcel_id, effective_date), the matching
``et_estimate`` row is suppressed from billing; where it does not, the raw
``et_estimate`` row stands in so no parcel-month silently drops to zero.

These tests build ledger rows directly (no GEE/cache) — pure ledger arithmetic,
fast and deterministic. They exercise the helper itself, the three balance
surfaces (parcel/account/zone), and the GEARS by-ET CSV generator.
"""
import csv as csv_mod
from datetime import date
from decimal import Decimal

import pytest

from accounting.services import (
    account_balance,
    billable_ledger,
    parcel_balance,
    zone_balance,
)
from parcels.models import ParcelLedger
from reporting.generators import generate_gears_csv
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    ZoneFactory,
)

JUNE = date(2024, 6, 1)
JULY = date(2024, 7, 1)


def _et(parcel, amount, effective_date=JUNE):
    """A gross OpenET estimate row (stored negative, reporting_period=None)."""
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="et_estimate",
        effective_date=effective_date,
        amount_acre_feet=Decimal(amount),
    )


def _calc(parcel, amount, effective_date=JUNE):
    """A netted calculation-engine row (stored negative)."""
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="calculated",
        effective_date=effective_date,
        amount_acre_feet=Decimal(amount),
    )


# ---------------------------------------------------------------------------
# billable_ledger() — the helper in isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBillableLedger:
    def test_suppresses_et_when_calculated_exists(self):
        """et_estimate is dropped when a calculated row shares its parcel-month."""
        parcel = ParcelFactory()
        _et(parcel, "-11")
        _calc(parcel, "-11")

        result = billable_ledger(ParcelLedger.objects.all())
        source_types = sorted(r.source_type for r in result)
        assert source_types == ["calculated"]

    def test_keeps_et_when_no_calculated(self):
        """et_estimate stands in as the fallback when the engine hasn't run."""
        parcel = ParcelFactory()
        _et(parcel, "-14")

        result = billable_ledger(ParcelLedger.objects.all())
        assert [r.source_type for r in result] == ["et_estimate"]

    def test_keeps_calculated_alone(self):
        parcel = ParcelFactory()
        _calc(parcel, "-11")

        result = billable_ledger(ParcelLedger.objects.all())
        assert [r.source_type for r in result] == ["calculated"]

    def test_only_et_is_suppressed_other_sources_survive(self):
        """meter_reading / surface_diversion / recharge are never suppressed."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, source_type="meter_reading",
            effective_date=JUNE, amount_acre_feet=Decimal("-5"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="surface_diversion",
            effective_date=JUNE, amount_acre_feet=Decimal("-3"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="recharge",
            effective_date=JUNE, amount_acre_feet=Decimal("8"),
        )
        _et(parcel, "-11")
        _calc(parcel, "-11")

        result = billable_ledger(ParcelLedger.objects.all())
        survivors = sorted(r.source_type for r in result)
        assert survivors == ["calculated", "meter_reading", "recharge", "surface_diversion"]

    def test_empty_queryset_returns_empty(self):
        result = billable_ledger(ParcelLedger.objects.none())
        assert list(result) == []

    def test_meter_only_queryset_unchanged(self):
        """No suppression keys → nothing excluded (regression)."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, source_type="meter_reading",
            effective_date=JUNE, amount_acre_feet=Decimal("-7"),
        )
        result = billable_ledger(ParcelLedger.objects.all())
        assert [r.source_type for r in result] == ["meter_reading"]

    def test_meter_suppresses_matching_et_without_calculated(self):
        """Metered parcel-month with a synced et_estimate bills the METER only.

        58-03 makes the meter authoritative (the engine writes no calculated
        row), but sync_openet_to_ledger still writes the et_estimate row —
        before the meter joined the suppression keys, that month billed
        meter + estimate (~2x actual). The meter row carries its real
        mid-month reading date; the key normalizes to the first of the month.
        """
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, source_type="meter_reading",
            effective_date=date(2024, 6, 17), amount_acre_feet=Decimal("-12"),
        )
        _et(parcel, "-10")  # dated JUNE (first of month)

        result = billable_ledger(ParcelLedger.objects.all())
        assert [r.source_type for r in result] == ["meter_reading"]

    def test_meter_does_not_suppress_other_month_et(self):
        """A June meter reading must NOT suppress a July et_estimate."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, source_type="meter_reading",
            effective_date=date(2024, 6, 17), amount_acre_feet=Decimal("-12"),
        )
        _et(parcel, "-10", effective_date=JULY)

        result = billable_ledger(ParcelLedger.objects.all())
        survivors = sorted(r.source_type for r in result)
        assert survivors == ["et_estimate", "meter_reading"]

    def test_does_not_suppress_across_months(self):
        """A calculated June row must NOT suppress a July et_estimate (exact pair)."""
        parcel = ParcelFactory()
        _calc(parcel, "-11", effective_date=JUNE)
        _et(parcel, "-9", effective_date=JULY)

        result = billable_ledger(ParcelLedger.objects.all())
        kept = {(r.source_type, r.effective_date) for r in result}
        assert ("et_estimate", JULY) in kept
        assert ("calculated", JUNE) in kept

    def test_does_not_suppress_across_parcels(self):
        """A calculated row on parcel A must NOT suppress et_estimate on parcel B."""
        parcel_a = ParcelFactory()
        parcel_b = ParcelFactory()
        _calc(parcel_a, "-11")
        _et(parcel_b, "-9")

        result = billable_ledger(ParcelLedger.objects.all())
        kept = {(r.parcel_id, r.source_type) for r in result}
        assert (parcel_b.id, "et_estimate") in kept
        assert (parcel_a.id, "calculated") in kept


# ---------------------------------------------------------------------------
# Balance surfaces — the double-count kill
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBalancesReconcile:
    def test_parcel_balance_counts_et_once(self):
        """et(-11)+calc(-11) on one parcel-month bills 11, NOT 22."""
        parcel = ParcelFactory()
        _et(parcel, "-11")
        _calc(parcel, "-11")
        assert parcel_balance(parcel) == Decimal("-11")

    def test_parcel_balance_fallback_to_et(self):
        parcel = ParcelFactory()
        _et(parcel, "-14")
        assert parcel_balance(parcel) == Decimal("-14")

    def test_parcel_balance_calculated_alone(self):
        parcel = ParcelFactory()
        _calc(parcel, "-11")
        assert parcel_balance(parcel) == Decimal("-11")

    def test_parcel_balance_keeps_non_et_rows(self):
        """Suppressing et must not drop meter/surface/recharge rows."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, source_type="meter_reading",
            effective_date=JUNE, amount_acre_feet=Decimal("-5"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="surface_diversion",
            effective_date=JUNE, amount_acre_feet=Decimal("-3"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="recharge",
            effective_date=JUNE, amount_acre_feet=Decimal("8"),
        )
        _et(parcel, "-11")
        _calc(parcel, "-11")
        # -5 - 3 + 8 - 11 (calc; et suppressed) = -11
        assert parcel_balance(parcel) == Decimal("-11")

    def test_account_balance_no_double_count(self):
        """Two parcels — one engine-run, one fallback — net the sum of each."""
        account = WaterAccountFactory()
        p_calc = ParcelFactory()
        p_fallback = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=p_calc)
        WaterAccountParcelFactory(water_account=account, parcel=p_fallback)
        _et(p_calc, "-11")
        _calc(p_calc, "-11")
        _et(p_fallback, "-14")

        result = account_balance(account)
        assert result["usage"] == Decimal("25")  # 11 + 14, not 36
        assert result["net"] == Decimal("-25")

    def test_zone_balance_no_double_count(self):
        zone = ZoneFactory()
        p_calc = ParcelFactory()
        p_fallback = ParcelFactory()
        ParcelZoneFactory(parcel=p_calc, zone=zone)
        ParcelZoneFactory(parcel=p_fallback, zone=zone)
        _et(p_calc, "-11")
        _calc(p_calc, "-11")
        _et(p_fallback, "-14")

        result = zone_balance(zone)
        assert result["usage"] == Decimal("25")
        assert result["net"] == Decimal("-25")


# ---------------------------------------------------------------------------
# GEARS by-ET CSV — switches to calculated, falls back to et_estimate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGearsByEtReconcile:
    def _period(self):
        return ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

    def _rows(self, content):
        reader = csv_mod.reader(content.splitlines())
        header = next(reader)
        return header, [r for r in reader if r]

    def test_by_et_uses_calculated_and_falls_back(self):
        """Calculated parcel reports its NET volume; fallback parcel reports
        gross; no duplicate row. (Both carry the state method label
        'Unmetered/Estimated' since ISS-047a — the net-vs-gross distinction is
        proven by the volume column, not the method string.)"""
        period = self._period()
        p_calc = ParcelFactory()
        p_fallback = ParcelFactory()
        # gross 11, net 9 — distinct so we can prove the netted number is used
        _et(p_calc, "-11")
        _calc(p_calc, "-9")
        _et(p_fallback, "-14")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)

        # Columns: Parcel Number, Area, Month, ET Volume (AF), Measurement Method
        by_parcel = {r[0]: r for r in rows}
        assert len(rows) == 2  # exactly one row per parcel — no duplicate

        calc_row = by_parcel[p_calc.parcel_number]
        assert calc_row[4] == "Unmetered/Estimated"
        assert Decimal(calc_row[3]) == Decimal("9")  # net, not gross 11

        fb_row = by_parcel[p_fallback.parcel_number]
        assert fb_row[4] == "Unmetered/Estimated"
        assert Decimal(fb_row[3]) == Decimal("14")

    def test_by_et_calculated_gross_not_duplicated(self):
        """The calculated parcel's suppressed gross et_estimate must not appear."""
        period = self._period()
        p_calc = ParcelFactory()
        _et(p_calc, "-11")
        _calc(p_calc, "-9")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)
        assert len(rows) == 1
        assert rows[0][4] == "Unmetered/Estimated"
        assert Decimal(rows[0][3]) == Decimal("9")
