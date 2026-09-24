# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-parcel closing water mass balance (Phase 52.6-03, ISS-053).

`parcel_mass_balance(parcel, reporting_period)` gathers every input and output
term for a parcel-period from the ledger, the CalculationRun audit, and the
Phase-39 banking machinery, and reports whether the books close:

    surface + precip + gw_recovered = et + recharge + runoff + delta_storage
                                       + deep_percolation_surface_af

These tests build parcel-periods with KNOWN terms (seeded CalculationRun +
ledger rows) so each balance closes by construction, and prove the function
gathers and nets them correctly. The load-bearing invariant is ISS-053: a
no-well parcel carries ZERO personal recharge credit it could never pump.

148-02 Task 3 (Q1, an over-delivery is nobody's credit): `recharge` above is
now real `recharge` ledger rows ONLY (managed recharge) — an over-delivery
never becomes one, personal or pooled, so a month with a real over-delivery
and no managed recharge does NOT close any more; its residual states the
over-delivery plainly instead (`test_no_well_flood_mar_closes_with_zero_personal_recharge`,
`test_mer_apn_031_shape_no_personal_recharge_pooled`).
"""
from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun
from accounting.services import parcel_balance_breakdown, parcel_mass_balance
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
    UsageLocationFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db


def _clamp_floor_breakdown(incidental_af):
    """A minimal CalculationRun.breakdown carrying a deep-percolation magnitude.

    Mirrors the shape the calculation engine writes: the clamp_floor step's
    detail records ``incidental_recharge_af`` (ISS-052) — kept here so an old
    run's stored breakdown still has the shape a reader expects, but 148-02
    Task 3's `parcel_mass_balance` no longer reads it back; `_run` below sets
    `over_delivery_af` on the CalculationRun directly instead.
    """
    return [
        {
            "step_type": "clamp_floor",
            "detail": {"incidental_recharge_af": str(incidental_af)},
        }
    ]


def _run(parcel, period, *, gross_et, precip, surface, banked, drawn, final,
         incidental):
    """Create one CalculationRun (a parcel-month audit row) with known terms.

    148-02 Task 3: `over_delivery_af` is set to the same `incidental` figure
    the breakdown carries (mirroring what `run_calculations` actually does,
    steps.py::clamp_floor) — it is the run's OWN column now, not something
    `parcel_mass_balance` re-derives from the breakdown any more.
    """
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(gross_et)),
        effective_precip_af=Decimal(str(precip)),
        surface_water_af=Decimal(str(surface)),
        banked_af=Decimal(str(banked)),
        drawn_af=Decimal(str(drawn)),
        final_af=Decimal(str(final)),
        over_delivery_af=Decimal(str(incidental)),
        breakdown=_clamp_floor_breakdown(incidental),
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


def test_conjunctive_parcel_balance_closes():
    """A conjunctive (has-well) deficit month: surface + precip + gw = et."""
    rp = ReportingPeriodFactory()  # WY 2023-10-01 .. 2024-09-30
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)  # -> CONJUNCTIVE

    # gross ET 20 met by 10 surface + 3 precip + 7 pumped groundwater.
    _run(parcel, "2024-01", gross_et=20, precip=3, surface=10,
         banked=0, drawn=0, final=7, incidental=0)
    _surface_row(parcel, rp, date(2024, 1, 1), 10)
    _calculated_row(parcel, rp, date(2024, 1, 1), 7)

    result = parcel_mass_balance(parcel, rp)

    assert result["inputs"]["surface"] == Decimal("10")
    assert result["inputs"]["precip"] == Decimal("3")
    assert result["inputs"]["gw_recovered"] == Decimal("7")
    assert result["outputs"]["et"] == Decimal("20")
    assert result["outputs"]["recharge"] == Decimal("0")
    assert result["outputs"]["runoff"] == Decimal("0")
    assert result["outputs"]["delta_storage"] == Decimal("0")
    assert abs(result["residual_af"]) <= Decimal("0.01")
    assert result["closes"] is True


def test_no_well_flood_mar_closes_with_zero_personal_recharge():
    """148-02 Task 3 (Q1, an over-delivery is nobody's credit) RETARGET: a
    FLOOD_MAR (crop, no well) over-delivery month no longer closes via a
    `recharge` output term — that term is real recharge ledger rows only, and
    an over-delivery is never one. The 4 AF the crop could not use shows up
    only as `over_delivery_af` on the run, and the RESIDUAL equals it exactly
    (the identity states the over-delivery plainly rather than absorbing it
    into a manufactured recharge figure, ISS-158). No personal groundwater is
    pumped and no personal recharge credit is left on the parcel."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    UsageLocationFactory(parcel=parcel)  # crop, no well -> FLOOD_MAR

    # 12 surface + 2 precip vs 10 ET => 4 AF over-delivery.
    run = _run(parcel, "2024-02", gross_et=10, precip=2, surface=12,
               banked=0, drawn=0, final=0, incidental=4)
    _surface_row(parcel, rp, date(2024, 2, 1), 12)

    result = parcel_mass_balance(parcel, rp)

    assert result["inputs"]["gw_recovered"] == Decimal("0")
    # No real recharge ledger row exists, so the output term is 0 — the
    # over-delivery is NOT a recharge output any more.
    assert result["outputs"]["recharge"] == Decimal("0")
    assert result["outputs"]["delta_storage"] == Decimal("0")
    assert result["closes"] is False
    assert result["residual_af"] == run.over_delivery_af == Decimal("4")
    # ISS-053: no positive personal recharge ledger credit on a no-well parcel.
    from parcels.models import ParcelLedger
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge", amount_acre_feet__gt=0
    ).exists()


def test_mer_apn_031_shape_no_personal_recharge_pooled():
    """148-02 Task 3 (Q1) RETARGET: MER-APN-031 shape (surface-only, no well).

    The ISS-053 worked case, updated: gw_recovered == 0, no personal recharge
    row, and — Q1 — no pooled deposit either, since an over-delivery is
    nobody's credit at all any more. The 3 AF the crop could not use is the
    run's `over_delivery_af`, and the residual equals it exactly (the books
    do not close, and are not made to)."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory(parcel_number="MER-APN-031")
    UsageLocationFactory(parcel=parcel)  # a crop + (below) surface, but no well

    # 9 surface + 1 precip vs 7 ET => 3 AF over-delivery.
    run = _run(parcel, "2024-03", gross_et=7, precip=1, surface=9,
               banked=0, drawn=0, final=0, incidental=3)
    _surface_row(parcel, rp, date(2024, 3, 1), 9)

    result = parcel_mass_balance(parcel, rp)

    assert result["inputs"]["gw_recovered"] == Decimal("0")
    assert result["outputs"]["recharge"] == Decimal("0")
    assert result["closes"] is False
    assert result["residual_af"] == run.over_delivery_af == Decimal("3")

    from parcels.models import ParcelLedger
    personal_recharge = ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge", amount_acre_feet__gt=0
    )
    assert not personal_recharge.exists(), "no phantom personal recharge credit"


def test_banked_then_drawn_across_months_closes():
    """delta_storage absorbs banking timing so a full period still closes.

    Month 1 banks a surface surplus; month 2 draws it back to cover a deficit.
    Over the period the net storage change is zero and the books close.
    """
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)  # conjunctive: banks and pumps

    # Month 1: 8 surface vs 5 ET => 3 AF surplus banked.
    _run(parcel, "2024-01", gross_et=5, precip=0, surface=8,
         banked=3, drawn=0, final=0, incidental=0)
    _surface_row(parcel, rp, date(2024, 1, 1), 8)

    # Month 2: 5 ET, no surface; draw the 3 banked, pump the remaining 2.
    _run(parcel, "2024-02", gross_et=5, precip=0, surface=0,
         banked=0, drawn=3, final=5, incidental=0)
    _calculated_row(parcel, rp, date(2024, 2, 1), 2)

    result = parcel_mass_balance(parcel, rp)

    # Period totals: surface 8, precip 0, gw 2 in; et 10, delta_storage net 0 out.
    assert result["inputs"]["surface"] == Decimal("8")
    assert result["inputs"]["gw_recovered"] == Decimal("2")
    assert result["outputs"]["et"] == Decimal("10")
    assert result["outputs"]["delta_storage"] == Decimal("0")
    assert result["closes"] is True


def test_gw_recovered_reconciles_with_balance_dict_usage():
    """gw_recovered MUST equal the existing _balance_dict usage term.

    Cross-check against parcel_balance_breakdown so the mass balance never
    drifts from the billable ledger. The et_estimate row is suppressed by
    billable_ledger (its calculated twin bills), so usage counts the calculated
    magnitude only -- and gw_recovered must agree.
    """
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    _run(parcel, "2024-04", gross_et=12, precip=0, surface=0,
         banked=0, drawn=0, final=7, incidental=0)
    # calculated -7 (the netted bill) suppresses its gross et_estimate -9 twin.
    _calculated_row(parcel, rp, date(2024, 4, 1), 7)
    ParcelLedgerFactory(
        parcel=parcel,
        reporting_period=rp,
        effective_date=date(2024, 4, 1),
        amount_acre_feet=Decimal("-9"),
        source_type="et_estimate",
    )

    result = parcel_mass_balance(parcel, rp)
    breakdown = parcel_balance_breakdown(parcel, rp)

    assert result["inputs"]["gw_recovered"] == breakdown["usage"]
    assert result["inputs"]["gw_recovered"] == Decimal("7")


def test_deep_percolation_surface_af_is_delivered_minus_consumed():
    """148-02: a run carrying surface_delivered_af (the apply_efficiency knob
    was on) names the part of the delivery the crop could not use as its OWN
    output term -- separate from recharge, and it subtracts from the residual
    like every other output, so the books still close."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    UsageLocationFactory(parcel=parcel)

    # 12 AF delivered, only 9 AF of it consumed (the field's own efficiency) ==
    # 9 AF gross ET, so the books close with the 3 AF difference named as
    # deep_percolation_surface_af rather than left to look like a phantom gain.
    run = _run(parcel, "2024-05", gross_et=9, precip=0, surface=9,
               banked=0, drawn=0, final=0, incidental=0)
    run.surface_delivered_af = Decimal("12")
    run.save()
    _surface_row(parcel, rp, date(2024, 5, 1), 12)

    result = parcel_mass_balance(parcel, rp)

    assert result["inputs"]["surface"] == Decimal("12")  # delivered, unchanged
    assert result["outputs"]["deep_percolation_surface_af"] == Decimal("3")
    assert result["closes"] is True


def test_deep_percolation_surface_af_is_zero_when_run_predates_the_knob():
    """A run with no surface_delivered_af (an old run, or the knob off)
    contributes 0 -- the new term never invents a number an old run never
    recorded."""
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    _run(parcel, "2024-01", gross_et=20, precip=3, surface=10,
         banked=0, drawn=0, final=7, incidental=0)
    _surface_row(parcel, rp, date(2024, 1, 1), 10)
    _calculated_row(parcel, rp, date(2024, 1, 1), 7)

    result = parcel_mass_balance(parcel, rp)

    assert result["outputs"]["deep_percolation_surface_af"] == Decimal("0")
    assert result["closes"] is True
