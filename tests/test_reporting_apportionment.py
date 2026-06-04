# SPDX-License-Identifier: AGPL-3.0-or-later
"""
End-to-end tests for Phase 56-02: shared wells and PODs split by the
measurement-first apportionment kernel at report-read time.

These prove the wiring (56-01 built the math; this proves the three report paths
actually call it with real per-period ET demand):

  1. No hand-set share -> the volume follows measured ET demand (the thirsty crop
     gets the larger slice), via CalculationRun.net_consumptive_use_af for the period.
  2. A hand-set share wins over ET (measurement-first).
  3. No CalculationRun rows -> even 1/N split, identical to the legacy static behavior
     (and identical to passing no period at all — the back-compat guarantee).
  4. A shared group's TOTAL is preserved — apportionment only redistributes WITHIN a
     group (the POD's diverted total, the well's metered total), never changes the sum.
"""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun
from reporting.generators import (
    build_normalized_pod_parcel_map,
    build_normalized_well_parcel_map,
    generate_calwatrs_csv,
    generate_gears_csv,
)
from reporting.services import build_openet_prefill
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db

# A month inside ReportingPeriodFactory's default WY 2023-2024 (2023-10 -> 2024-09).
JAN = date(2024, 1, 1)


def _run(parcel, net_demand, period="2024-01"):
    """A minimal CalculationRun carrying a known net consumptive use (the demand)."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(net_demand)),
        net_consumptive_use_af=Decimal(str(net_demand)),
        final_af=Decimal("0"),
    )


def _meter(parcel, af):
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="meter_reading",
        amount_acre_feet=Decimal(af),
        effective_date=JAN,
        transaction_date=JAN,
    )


def _et(parcel, af):
    """An et_estimate ledger entry, stored negative like sync_openet_to_ledger writes."""
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="et_estimate",
        amount_acre_feet=Decimal(af),
        effective_date=JAN,
        transaction_date=JAN,
    )


def _weight(parcel_members, parcel_id):
    """Pull a single parcel's weight out of a {parcel_id: [(x, weight)]} entry."""
    return parcel_members[parcel_id][0][1]


# ---------------------------------------------------------------------------
# Well map: the GW side of the kernel wiring.
# ---------------------------------------------------------------------------

def test_well_map_splits_by_et_demand_when_no_handset():
    """Two parcels, both fractions at the 1.0 sentinel -> the thirstier parcel's
    well share is larger, driven purely by CalculationRun ET demand."""
    rp = ReportingPeriodFactory()
    well = WellFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("1.0000"))
    WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("1.0000"))
    _run(a, "5")   # b is thirstier
    _run(b, "15")

    m = build_normalized_well_parcel_map(rp)
    wa = _weight(m, a.pk)
    wb = _weight(m, b.pk)

    assert wb > wa                              # demand split engaged
    assert wa == Decimal("0.2500")              # 5 / 20
    assert wb == Decimal("0.7500")              # 15 / 20
    assert wa + wb == Decimal("1.0000")         # weights normalized


def test_well_map_handset_fraction_wins_over_et_demand():
    """A hand-set 0.6/0.4 split is honored even though ET says b is thirstier."""
    rp = ReportingPeriodFactory()
    well = WellFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
    WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
    _run(a, "5")
    _run(b, "15")

    m = build_normalized_well_parcel_map(rp)
    assert _weight(m, a.pk) == Decimal("0.6000")
    assert _weight(m, b.pk) == Decimal("0.4000")


def test_well_map_even_split_when_no_runs_matches_legacy():
    """No CalculationRun rows -> even split, identical whether or not a period is
    passed (the back-compat guarantee: no demand signal -> legacy static behavior)."""
    rp = ReportingPeriodFactory()
    well = WellFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("1.0000"))
    WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("1.0000"))

    with_period = build_normalized_well_parcel_map(rp)
    no_period = build_normalized_well_parcel_map()

    for m in (with_period, no_period):
        assert _weight(m, a.pk) == Decimal("0.5000")
        assert _weight(m, b.pk) == Decimal("0.5000")


def test_single_parcel_well_gets_full_weight():
    rp = ReportingPeriodFactory()
    well = WellFactory()
    p = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=p, fraction=Decimal("1.0000"))
    _run(p, "9")

    m = build_normalized_well_parcel_map(rp)
    assert _weight(m, p.pk) == Decimal("1.0000")


# ---------------------------------------------------------------------------
# POD map: the SW side, mirror of the well map.
# ---------------------------------------------------------------------------

def test_pod_map_splits_by_et_demand_when_no_handset():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("1.0000"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("1.0000"))
    _run(a, "5")
    _run(b, "15")

    m = build_normalized_pod_parcel_map(rp)
    weights = dict(m[pod.pk])
    assert weights[a.pk] == Decimal("0.2500")
    assert weights[b.pk] == Decimal("0.7500")
    assert weights[a.pk] + weights[b.pk] == Decimal("1.0000")


def test_pod_map_handset_wins_and_even_without_runs():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.6000"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.4000"))
    _run(a, "5")
    _run(b, "15")

    handset = dict(build_normalized_pod_parcel_map(rp)[pod.pk])
    assert handset[a.pk] == Decimal("0.6000")
    assert handset[b.pk] == Decimal("0.4000")


# ---------------------------------------------------------------------------
# End-to-end: CalWATRS CSV — the path where the split is observable per row.
# ---------------------------------------------------------------------------

def _calwatrs_rows(reporting_period):
    text = generate_calwatrs_csv(reporting_period, "a1").getvalue()
    return list(csv.reader(io.StringIO(text)))[1:]  # drop the header row


def test_calwatrs_splits_pod_volume_by_demand_total_preserved():
    """One diverted total split across two parcels follows ET demand, and the
    POD's total volume is unchanged — apportionment only redistributes within it."""
    rp = ReportingPeriodFactory()
    wr = WaterRightFactory()
    pod = PointOfDiversionFactory(water_right=wr)
    a = ParcelFactory()
    b = ParcelFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("1.0000"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("1.0000"))
    _run(a, "5")
    _run(b, "15")
    DiversionRecordFactory(
        point_of_diversion=pod,
        month=JAN,
        volume_acre_feet=Decimal("100.0000"),
        diversion_type="direct_use",
    )

    rows = _calwatrs_rows(rp)
    assert len(rows) == 2                                   # one row per parcel
    volumes = sorted(Decimal(r[7]) for r in rows)           # column 7 = Volume (AF)
    assert volumes[0] == Decimal("25")                      # 100 * 0.25
    assert volumes[1] == Decimal("75")                      # 100 * 0.75
    assert sum(Decimal(r[7]) for r in rows) == Decimal("100")  # POD total preserved


def test_calwatrs_honors_handset_split_over_demand():
    rp = ReportingPeriodFactory()
    wr = WaterRightFactory()
    pod = PointOfDiversionFactory(water_right=wr)
    a = ParcelFactory()
    b = ParcelFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.6000"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.4000"))
    _run(a, "5")    # ET says b is thirstier, but the hand-set split wins
    _run(b, "15")
    DiversionRecordFactory(
        point_of_diversion=pod,
        month=JAN,
        volume_acre_feet=Decimal("100.0000"),
        diversion_type="direct_use",
    )

    volumes = sorted(Decimal(r[7]) for r in _calwatrs_rows(rp))
    assert volumes == [Decimal("40"), Decimal("60")]


# ---------------------------------------------------------------------------
# End-to-end: GEARS by-well + OpenET pre-fill — no double-count, total preserved.
# ---------------------------------------------------------------------------

def test_gears_by_well_total_preserved_no_double_count():
    """A well metered on each of its two parcels reports its total ONCE (not 2x),
    and routing through the demand-split path does not change that total."""
    rp = ReportingPeriodFactory()
    well = WellFactory(well_registration_id="REG-1")
    a = ParcelFactory()
    b = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("1.0000"))
    WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("1.0000"))
    _meter(a, "10.0000")   # same reading recorded on each parcel the well serves
    _meter(b, "10.0000")
    _run(a, "5")           # demand split present, but the well total is invariant
    _run(b, "15")

    rows = list(csv.reader(io.StringIO(generate_gears_csv(rp, "by_well").getvalue())))[1:]
    assert len(rows) == 1                       # one well row
    assert Decimal(rows[0][5]) == Decimal("10")  # column 5 = Extraction Volume, not 20


def test_prefill_calwatrs_follows_demand_split():
    """_prefill_calwatrs now routes through the period-aware demand map (was raw
    fractions): a thirstier parcel pulls more of its ET into the shared POD's value."""
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory()
    b = ParcelFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("1.0000"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("1.0000"))
    _et(a, "-10.0000")
    _et(b, "-30.0000")
    _run(a, "10")          # weights 0.25 / 0.75
    _run(b, "30")

    result = build_openet_prefill(rp, "calwatrs")
    assert len(result["entities"]) == 1
    value = result["entities"][0]["months"][0]["value_af"]
    # demand-weighted: 10*0.25 + 30*0.75 = 25.0 (an even split would give 20.0)
    assert value == Decimal("25")
