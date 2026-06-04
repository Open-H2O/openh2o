# SPDX-License-Identifier: AGPL-3.0-or-later
"""DB-bound tests for the CalculationRun audit trail (38-05).

run_calculations writes one CalculationRun per calculated ledger row, in the same
transaction, so every derived bill is reconstructable. These tests prove the
defensibility invariants the blueprint demands:

  - 1:1 — exactly one run per calculated row; a no-ET (skipped) parcel gets neither.
  - Reconstruct — the run's stored figures add up to the billable number, and the
    persisted breakdown is an internally consistent gross->net waterfall.
  - Idempotency — re-running a period leaves exactly one run with identical values.
  - Banking captured — a deposit month records banked_af; a later draw month
    records drawn_af.

A run that merely EXISTS but doesn't reconstruct is worse than none (it looks
defensible and isn't), so the reconstruct test walks the math, it doesn't just
count rows. Runs in the Butler web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError

from accounting.models import (
    CalculationPlan,
    CalculationRun,
    CalculationStep,
    ReportingPeriod,
)
from accounting.services import et_mm_to_acre_feet
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation

Q = Decimal("0.0001")


def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))


def _irrigate(parcel):
    """Give the parcel a crop so facility_only_zero does NOT zero it out."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _et_cache(parcel, period="2024-06", et_mm=100.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )


def _precip_cache(parcel, period="2024-02", precip_mm=150.0):
    """A GRIDMET precip cache row in the live shape (value keyed "precip")."""
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="precip",
        model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}],
    )


def _surface_row(parcel, period, af):
    """A surface_diversion ledger row (stored NEGATIVE, like the live data)."""
    year, month = int(period[:4]), int(period[5:7])
    return ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=dt.date(year, month, 1),
        effective_date=dt.date(year, month, 1),
        amount_acre_feet=Decimal(str(-abs(af))),
        source_type="surface_diversion",
    )


def _gross_af(et_mm="100", acres="10"):
    """The positive gross-ET magnitude the et_gross step produces."""
    return abs(et_mm_to_acre_feet(Decimal(et_mm), Decimal(acres)))


def _calc_row(parcel, period):
    year, month = int(period[:4]), int(period[5:7])
    return ParcelLedger.objects.get(
        parcel=parcel,
        effective_date=dt.date(year, month, 1),
        source_type="calculated",
    )


def _run(parcel, period):
    return CalculationRun.objects.get(parcel=parcel, period=period)


def _finalized_period(period="2024-06", name="WY2024 June"):
    """A ReportingPeriod covering `period`, marked finalized (a filed number)."""
    year, month = int(period[:4]), int(period[5:7])
    last_day = 28  # safe for any month; the lookup only needs to span the 1st
    return ReportingPeriod.objects.create(
        name=name,
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, last_day),
        is_finalized=True,
    )


def _seed_finalized_parcel(number, period="2024-06"):
    """Parcel + ET + crop + active plan + a finalized ReportingPeriod for `period`."""
    parcel = _parcel(number, acres="10")
    _et_cache(parcel, period=period, et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")
    _finalized_period(period)
    return parcel


# --------------------------------------------------------------------------
# Finalized-period write guard (ISS-020 #1) — no silent overwrite of a filed
# number; --force overrides loudly; --dry-run is never blocked.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_finalized_period_refuses_recompute():
    parcel = _seed_finalized_parcel("RUN-FINAL")

    with pytest.raises(CommandError, match="finalized"):
        call_command("run_calculations", "--period", "2024-06")

    # The guard fired before the loop: nothing was written.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated"
    ).exists()
    assert not CalculationRun.objects.filter(parcel=parcel).exists()


@pytest.mark.django_db
def test_force_overrides_finalized_lock():
    parcel = _seed_finalized_parcel("RUN-FORCE")

    call_command("run_calculations", "--period", "2024-06", "--force")

    assert ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated"
    ).count() == 1
    assert CalculationRun.objects.filter(parcel=parcel, period="2024-06").count() == 1


@pytest.mark.django_db
def test_dry_run_allowed_on_finalized_period():
    parcel = _seed_finalized_parcel("RUN-DRYFINAL")

    # Must not raise — a preview of a finalized recompute writes nothing.
    call_command("run_calculations", "--period", "2024-06", "--dry-run")

    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated"
    ).exists()
    assert not CalculationRun.objects.filter(parcel=parcel).exists()


# --------------------------------------------------------------------------
# 1:1 invariant — one run per calculated row; none for a skipped parcel
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_calculated_parcel_gets_exactly_one_run():
    parcel = _parcel("RUN-ONE", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    assert CalculationRun.objects.filter(parcel=parcel, period="2024-06").count() == 1
    assert (
        ParcelLedger.objects.filter(parcel=parcel, source_type="calculated").count()
        == 1
    )


@pytest.mark.django_db
def test_no_et_parcel_gets_zero_runs_and_zero_calculated_rows():
    """A parcel skipped for no ET produces NEITHER a calculated row NOR a run."""
    parcel = _parcel("RUN-NOET", acres="10")
    _irrigate(parcel)  # has a crop, but no ET cache -> skipped_no_et
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    assert CalculationRun.objects.filter(parcel=parcel).count() == 0
    assert (
        ParcelLedger.objects.filter(parcel=parcel, source_type="calculated").count()
        == 0
    )


# --------------------------------------------------------------------------
# Reconstruct invariant — the run's stored figures add up to the bill
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_reconstructs_the_billable_value():
    parcel = _parcel("RUN-RECON", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)  # ~3.28 AF gross
    _irrigate(parcel)
    _surface_row(parcel, "2024-06", af=1)  # partial offset -> positive bill remains
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    run = _run(parcel, "2024-06")
    calc = _calc_row(parcel, "2024-06")

    # (1) final_af equals the magnitude of the calculated ledger row.
    assert run.final_af == -calc.amount_acre_feet

    # (2) gross_et_af matches the et_gross step's output (at the ledger's 4dp).
    et_step = next(s for s in run.breakdown if s["step_type"] == "et_gross")
    assert run.gross_et_af == Decimal(et_step["output_af"]).quantize(Q)
    assert run.gross_et_af == _gross_af().quantize(Q)

    # (3) the breakdown is an internally consistent waterfall: every step's
    #     input equals the prior step's output (no hidden jumps in the math).
    for prev, nxt in zip(run.breakdown, run.breakdown[1:]):
        assert nxt["input_af"] == prev["output_af"]

    # (4) last enabled step's output, minus any credit drawn, IS the final bill.
    last = run.breakdown[-1]
    assert last["step_type"] == "clamp_floor"
    assert (Decimal(last["output_af"]) - run.drawn_af).quantize(Q) == run.final_af

    # The surface-water subtraction is captured; the precip step ran (Pe = 0
    # with no precip data) so its column is 0.0000, NOT null.
    assert run.surface_water_af == Decimal("1.0000")
    assert run.effective_precip_af == Decimal("0.0000")


# --------------------------------------------------------------------------
# Idempotency — re-running leaves exactly one run, identical values
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_rerunning_a_period_leaves_one_identical_run():
    parcel = _parcel("RUN-IDEM", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    _surface_row(parcel, "2024-06", af=1)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    run1 = _run(parcel, "2024-06")
    snap1 = (
        run1.gross_et_af,
        run1.effective_precip_af,
        run1.surface_water_af,
        run1.banked_af,
        run1.drawn_af,
        run1.final_af,
        run1.breakdown,
    )

    call_command("run_calculations", "--period", "2024-06")  # second run
    runs = CalculationRun.objects.filter(parcel=parcel, period="2024-06")
    assert runs.count() == 1
    run2 = runs.first()
    snap2 = (
        run2.gross_et_af,
        run2.effective_precip_af,
        run2.surface_water_af,
        run2.banked_af,
        run2.drawn_af,
        run2.final_af,
        run2.breakdown,
    )
    assert snap1 == snap2


# --------------------------------------------------------------------------
# Banking captured — deposit month records banked_af, draw month drawn_af
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Methodology provenance (ISS-020 #2) — every run carries a durable fingerprint
# of the recipe that made it; the fingerprint is stable across re-runs and moves
# when the enabled config moves, but not when a cosmetic label changes.
# --------------------------------------------------------------------------


def _active_step(step_type):
    return CalculationStep.objects.get(
        plan=CalculationPlan.active(), step_type=step_type
    )


@pytest.mark.django_db
def test_run_carries_methodology_provenance():
    parcel = _parcel("RUN-PROV", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    run = _run(parcel, "2024-06")
    assert run.config_hash  # non-empty
    assert len(run.config_hash) == 12
    assert run.methodology_plan_name == CalculationPlan.active().name
    assert run.methodology_plan_id == CalculationPlan.active().id


@pytest.mark.django_db
def test_config_hash_stable_across_reruns():
    parcel = _parcel("RUN-HASHIDEM", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    hash1 = _run(parcel, "2024-06").config_hash
    call_command("run_calculations", "--period", "2024-06")  # unchanged plan
    hash2 = _run(parcel, "2024-06").config_hash

    assert hash1 and hash1 == hash2


@pytest.mark.django_db
def test_config_hash_changes_when_step_config_changes():
    parcel = _parcel("RUN-HASHCFG", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    hash1 = _run(parcel, "2024-06").config_hash

    # Bump an enabled step's config — the methodology changed, so must the hash.
    step = _active_step("clamp_floor")
    step.config = {**step.config, "floor": 0.5}
    step.save()
    call_command("run_calculations", "--period", "2024-06")
    hash2 = _run(parcel, "2024-06").config_hash

    assert hash1 and hash2 and hash1 != hash2


@pytest.mark.django_db
def test_config_hash_ignores_labels_but_tracks_enabled_set():
    parcel = _parcel("RUN-HASHLBL", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    hash1 = _run(parcel, "2024-06").config_hash

    # Renaming a step is cosmetic — the fingerprint must NOT move.
    step = _active_step("clamp_floor")
    step.label = "Renamed clamp (cosmetic)"
    step.save()
    call_command("run_calculations", "--period", "2024-06")
    assert _run(parcel, "2024-06").config_hash == hash1

    # Disabling a step changes the enabled set — the fingerprint MUST move,
    # even when (as here, no surface data) the number itself is unchanged.
    surf = _active_step("subtract_surface_water")
    surf.enabled = False
    surf.save()
    call_command("run_calculations", "--period", "2024-06")
    assert _run(parcel, "2024-06").config_hash != hash1


@pytest.mark.django_db
def test_surface_overdelivery_becomes_incidental_recharge_not_a_credit():
    """ISS-052: surface delivered beyond crop ET is deep-percolation recharge
    credited to groundwater — NOT a precip credit banked and drawn down later
    (which masked real summer pumping). Under the production usda_scs plan, Pe is
    capped at ET, so the whole over-delivery routes to recharge and banking is 0."""
    parcel = _parcel("RUN-RECHARGE", acres="10")
    _irrigate(parcel)
    # "Wet" month: surface (5 AF) exceeds gross ET (~3.28 AF) by ~1.72 AF.
    _et_cache(parcel, period="2024-02", et_mm=100.0)
    _surface_row(parcel, "2024-02", af=5)
    # Following month: ET only, no surface.
    _et_cache(parcel, period="2024-03", et_mm=100.0)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02")
    call_command("run_calculations", "--period", "2024-03")

    over_delivery = (Decimal("5") - _gross_af()).quantize(Q)  # ~1.72 AF

    deposit_run = _run(parcel, "2024-02")
    # Nothing banked (no genuine rain surplus); surface covered all ET, bill 0.
    assert deposit_run.banked_af == Decimal("0.0000")
    assert deposit_run.final_af == Decimal("0.0000")
    clamp = next(
        s for s in deposit_run.breakdown if s["step_type"] == "clamp_floor"
    )
    assert (
        Decimal(clamp["detail"]["incidental_recharge_af"]).quantize(Q)
        == over_delivery
    )

    # A positive GW recharge ledger row was written for the over-delivery.
    recharge = ParcelLedger.objects.get(
        parcel=parcel,
        effective_date=dt.date(2024, 2, 1),
        source_type="recharge",
    )
    assert recharge.amount_acre_feet > 0
    assert recharge.amount_acre_feet.quantize(Q) == over_delivery
    assert recharge.water_type.code == "GW"
    assert recharge.description.startswith("Incidental recharge")

    # The next month draws NOTHING (no phantom credit) -> real pumping is billed.
    draw_run = _run(parcel, "2024-03")
    assert draw_run.drawn_af == Decimal("0.0000")
    assert draw_run.final_af == _gross_af().quantize(Q)
    assert draw_run.final_af == -_calc_row(parcel, "2024-03").amount_acre_feet


@pytest.mark.django_db
def test_incidental_recharge_row_is_idempotent_across_reruns():
    """Re-running a period replaces only the engine's own incidental recharge row
    (delete-then-insert by description prefix) — no duplication, no drift."""
    parcel = _parcel("RUN-RECHARGE-IDEM", acres="10")
    _irrigate(parcel)
    _et_cache(parcel, period="2024-02", et_mm=100.0)
    _surface_row(parcel, "2024-02", af=5)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02")
    call_command("run_calculations", "--period", "2024-02")  # re-run

    rows = ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge", effective_date=dt.date(2024, 2, 1)
    )
    assert rows.count() == 1
    assert rows.first().water_type.code == "GW"


@pytest.mark.django_db
def test_genuine_rain_surplus_still_banks_under_raw_precip():
    """Banking still works for REAL rain surplus: under method="raw" effective
    precip can exceed ET, so a wet month banks a credit a dry month draws. No
    surface here -> no incidental recharge row, banking only."""
    parcel = _parcel("RUN-RAINBANK", acres="10")
    _irrigate(parcel)
    _et_cache(parcel, period="2024-02", et_mm=100.0)          # ~3.28 AF ET
    _precip_cache(parcel, period="2024-02", precip_mm=250.0)  # ~8.2 AF rain >> ET
    _et_cache(parcel, period="2024-03", et_mm=100.0)          # dry: ET only
    plan = CalculationPlan.objects.create(name="Raw-precip", is_active=True)
    CalculationStep.objects.create(
        plan=plan, order=1, step_type="et_gross", enabled=True,
        config={"model": "Ensemble", "variable": "ET"}, label="gross",
    )
    CalculationStep.objects.create(
        plan=plan, order=2, step_type="subtract_effective_precip", enabled=True,
        config={"method": "raw"}, label="precip raw",
    )
    CalculationStep.objects.create(
        plan=plan, order=3, step_type="clamp_floor", enabled=True,
        config={"floor": 0, "bank": True, "depreciation_rate": 0,
                "expiry_months": None},
        label="floor",
    )

    call_command("run_calculations", "--period", "2024-02")
    call_command("run_calculations", "--period", "2024-03")

    deposit_run = _run(parcel, "2024-02")
    draw_run = _run(parcel, "2024-03")

    # Genuine rain surplus banked; no surface -> NO incidental recharge row.
    assert deposit_run.banked_af > 0
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge"
    ).exists()
    # Dry month draws the banked credit down, reducing the bill below gross ET.
    assert draw_run.drawn_af > 0
    assert draw_run.final_af < _gross_af().quantize(Q)
