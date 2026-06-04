# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consumptive-use balance read (Phase 57-01, the corrected v1.10 lens).

`consumptive_use_balance(parcel_ids, reporting_period)` frames a parcel/account/
zone as **measured consumptive use vs. the supplies that met it** (surface,
groundwater, precipitation) — replacing the old "surface = supply / groundwater
= usage" framing. It is a NEW read over the SAME ledger + CalculationRun rows the
billable primitive and the mass balance already use, so the dashboard, the
per-parcel summary, and the mass-balance audit can never drift apart.

These tests build parcel-periods with EXPLICIT CalculationRun terms (gross ET,
net consumptive use, effective precip) so they prove correctness independent of
the stale Butler demo, where every persisted ``net_consumptive_use_af`` is still
0 (the field landed in Phase 54 after the 52.5 runs were written; Phase 58
re-runs the engine). The load-bearing invariants:

  * a surface-only no-well parcel shows ZERO groundwater supply (no phantom);
  * the groundwater supply equals the existing ``_balance_dict`` usage term
    (reconciliation #4) so the new lens agrees with the billable primitive;
  * account/zone roll-ups equal the sum of their member parcels (additivity #5).
"""
from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun
from accounting.services import (
    account_consumptive_balance,
    consumptive_use_balance,
    parcel_balance_breakdown,
    parcel_consumptive_balance,
    zone_consumptive_balance,
)
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    UsageLocationFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


def _run(parcel, period, *, gross_et, net_cu, precip):
    """One CalculationRun (a parcel-month) with EXPLICIT consumptive-use terms.

    net_cu is set independently of gross_et/precip so the test does not depend on
    the engine's gross−precip computation — it proves the reader sums the
    persisted field verbatim.
    """
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(gross_et)),
        net_consumptive_use_af=Decimal(str(net_cu)),
        effective_precip_af=Decimal(str(precip)),
        final_af=Decimal("0"),  # non-null; not read by the consumptive lens.
    )


def _surface_row(parcel, rp, eff_date, magnitude):
    """A surface_diversion ledger row, stored NEGATIVE (production convention)."""
    return ParcelLedgerFactory(
        parcel=parcel,
        reporting_period=rp,
        effective_date=eff_date,
        amount_acre_feet=Decimal(str(-abs(magnitude))),
        source_type="surface_diversion",
    )


def _calculated_row(parcel, rp, eff_date, magnitude):
    """A netted `calculated` groundwater row, stored NEGATIVE (usage)."""
    return ParcelLedgerFactory(
        parcel=parcel,
        reporting_period=rp,
        effective_date=eff_date,
        amount_acre_feet=Decimal(str(-abs(magnitude))),
        source_type="calculated",
    )


def test_conjunctive_parcel_all_supplies_populated():
    """Case 1: a has-well parcel — surface, groundwater, precip all > 0.

    gross ET 20 met by 10 surface + 3 precip + 7 pumped groundwater; net CU 17.
    All three supplies populate and gross == net + precip (within 4dp).
    """
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)  # -> CONJUNCTIVE

    _run(parcel, "2024-01", gross_et=20, net_cu=17, precip=3)
    _surface_row(parcel, rp, date(2024, 1, 1), 10)
    _calculated_row(parcel, rp, date(2024, 1, 1), 7)

    result = consumptive_use_balance([parcel.id], rp)

    assert result["consumptive_use_gross"] == Decimal("20")
    assert result["consumptive_use_net"] == Decimal("17")
    assert result["supplies"]["surface"] == Decimal("10")
    assert result["supplies"]["groundwater"] == Decimal("7")
    assert result["supplies"]["precip"] == Decimal("3")
    assert result["supply_total"] == Decimal("20")
    assert result["net_vs_supply"] == Decimal("0")
    # gross actual ET reconciles with net CU + the precip that offset it.
    gross = result["consumptive_use_gross"]
    net = result["consumptive_use_net"]
    precip = result["supplies"]["precip"]
    assert abs(gross - (net + precip)) <= Decimal("0.0001")


def test_surface_only_no_well_has_zero_groundwater_supply():
    """Case 2: the MER-APN-031 shape — surface-only, no well, no phantom GW.

    Groundwater supply is exactly 0 (no calculated row exists), surface and gross
    ET are both positive, net CU is positive. The lens must NOT invent a
    groundwater supply for a parcel that has no well to pump.
    """
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory(parcel_number="MER-APN-031")
    UsageLocationFactory(parcel=parcel)  # a crop + surface, but NO well

    _run(parcel, "2024-03", gross_et=10, net_cu=9, precip=1)
    _surface_row(parcel, rp, date(2024, 3, 1), 8)

    result = consumptive_use_balance([parcel.id], rp)

    assert result["supplies"]["groundwater"] == Decimal("0")
    assert result["supplies"]["surface"] == Decimal("8")
    assert result["consumptive_use_gross"] == Decimal("10")
    assert result["consumptive_use_net"] == Decimal("9")
    # supply_total = 8 surface + 0 gw + 1 precip = 9; under-supplied vs 10 ET.
    assert result["supply_total"] == Decimal("9")
    assert result["net_vs_supply"] == Decimal("-1")


def test_empty_parcel_is_all_zero_no_divide():
    """Case 3: a parcel with no runs and no ledger — every figure Decimal('0')."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()

    result = consumptive_use_balance([parcel.id], rp)

    assert result["consumptive_use_gross"] == Decimal("0")
    assert result["consumptive_use_net"] == Decimal("0")
    assert result["supplies"]["surface"] == Decimal("0")
    assert result["supplies"]["groundwater"] == Decimal("0")
    assert result["supplies"]["precip"] == Decimal("0")
    assert result["supply_total"] == Decimal("0")
    assert result["net_vs_supply"] == Decimal("0")


def test_groundwater_supply_reconciles_with_balance_dict_usage():
    """Case 4: groundwater supply == parcel_balance_breakdown usage (same period).

    The new lens and the billable primitive must agree on the GW number. The
    et_estimate twin is suppressed by billable_ledger (its calculated row bills),
    so usage counts the calculated magnitude only — and so must the lens.
    """
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    _run(parcel, "2024-04", gross_et=12, net_cu=12, precip=0)
    # calculated -7 (the netted bill) suppresses its gross et_estimate -9 twin.
    _calculated_row(parcel, rp, date(2024, 4, 1), 7)
    ParcelLedgerFactory(
        parcel=parcel,
        reporting_period=rp,
        effective_date=date(2024, 4, 1),
        amount_acre_feet=Decimal("-9"),
        source_type="et_estimate",
    )

    result = consumptive_use_balance([parcel.id], rp)
    breakdown = parcel_balance_breakdown(parcel, rp)

    assert result["supplies"]["groundwater"] == breakdown["usage"]
    assert result["supplies"]["groundwater"] == Decimal("7")


def test_parcel_wrapper_matches_direct_call():
    """parcel_consumptive_balance(p) == consumptive_use_balance([p.id])."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)
    _run(parcel, "2024-05", gross_et=15, net_cu=13, precip=2)
    _surface_row(parcel, rp, date(2024, 5, 1), 6)
    _calculated_row(parcel, rp, date(2024, 5, 1), 7)

    assert parcel_consumptive_balance(parcel, rp) == consumptive_use_balance(
        [parcel.id], rp
    )


def test_account_rollup_is_additive_over_member_parcels():
    """Case 5a: account consumptive balance == sum of its member parcels."""
    rp = ReportingPeriodFactory()
    account = WaterAccountFactory()

    p1 = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=p1)
    WaterAccountParcelFactory(water_account=account, parcel=p1)
    _run(p1, "2024-01", gross_et=20, net_cu=17, precip=3)
    _surface_row(p1, rp, date(2024, 1, 1), 10)
    _calculated_row(p1, rp, date(2024, 1, 1), 7)

    p2 = ParcelFactory()
    UsageLocationFactory(parcel=p2)
    WaterAccountParcelFactory(water_account=account, parcel=p2)
    _run(p2, "2024-02", gross_et=10, net_cu=9, precip=1)
    _surface_row(p2, rp, date(2024, 2, 1), 8)

    rolled = account_consumptive_balance(account, rp)
    b1 = parcel_consumptive_balance(p1, rp)
    b2 = parcel_consumptive_balance(p2, rp)

    assert rolled["consumptive_use_gross"] == (
        b1["consumptive_use_gross"] + b2["consumptive_use_gross"]
    )
    assert rolled["consumptive_use_net"] == (
        b1["consumptive_use_net"] + b2["consumptive_use_net"]
    )
    for key in ("surface", "groundwater", "precip"):
        assert rolled["supplies"][key] == (
            b1["supplies"][key] + b2["supplies"][key]
        )
    assert rolled["supply_total"] == b1["supply_total"] + b2["supply_total"]
    # An excluded (removed) assignment must not contribute.
    assert rolled["supplies"]["groundwater"] == Decimal("7")


def test_zone_rollup_is_additive_over_member_parcels():
    """Case 5b: zone consumptive balance == sum of its member parcels."""
    rp = ReportingPeriodFactory()
    zone = ZoneFactory()

    p1 = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=p1)
    ParcelZoneFactory(parcel=p1, zone=zone)
    _run(p1, "2024-01", gross_et=18, net_cu=15, precip=3)
    _surface_row(p1, rp, date(2024, 1, 1), 9)
    _calculated_row(p1, rp, date(2024, 1, 1), 6)

    p2 = ParcelFactory()
    UsageLocationFactory(parcel=p2)
    ParcelZoneFactory(parcel=p2, zone=zone)
    _run(p2, "2024-02", gross_et=12, net_cu=11, precip=1)
    _surface_row(p2, rp, date(2024, 2, 1), 10)

    rolled = zone_consumptive_balance(zone, rp)
    b1 = parcel_consumptive_balance(p1, rp)
    b2 = parcel_consumptive_balance(p2, rp)

    assert rolled["consumptive_use_gross"] == (
        b1["consumptive_use_gross"] + b2["consumptive_use_gross"]
    )
    for key in ("surface", "groundwater", "precip"):
        assert rolled["supplies"][key] == (
            b1["supplies"][key] + b2["supplies"][key]
        )
    assert rolled["supply_total"] == b1["supply_total"] + b2["supply_total"]


def test_none_period_aggregates_union_across_periods():
    """Case 6: reporting_period=None sums every run/ledger across all periods."""
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    rp1 = ReportingPeriodFactory(
        start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
    )
    _run(parcel, "2024-01", gross_et=20, net_cu=17, precip=3)
    _surface_row(parcel, rp1, date(2024, 1, 1), 10)

    rp2 = ReportingPeriodFactory(
        start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    _run(parcel, "2025-01", gross_et=14, net_cu=12, precip=2)
    _surface_row(parcel, rp2, date(2025, 1, 1), 5)

    only_rp1 = consumptive_use_balance([parcel.id], rp1)
    assert only_rp1["consumptive_use_gross"] == Decimal("20")
    assert only_rp1["supplies"]["surface"] == Decimal("10")

    union = consumptive_use_balance([parcel.id], None)
    assert union["consumptive_use_gross"] == Decimal("34")  # 20 + 14
    assert union["consumptive_use_net"] == Decimal("29")  # 17 + 12
    assert union["supplies"]["surface"] == Decimal("15")  # 10 + 5
    assert union["supplies"]["precip"] == Decimal("5")  # 3 + 2
