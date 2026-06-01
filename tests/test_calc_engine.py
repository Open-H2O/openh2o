# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the 38-02 calculation-engine spine.

Covers the four simple primitives, the evaluator's enabled-step walk and
loud-failure behavior, the seed command's idempotency, and run_calculations'
one-row-per-parcel-month idempotency with the correct (negative) sign.

OpenETCache fixtures mirror the live shape: et_data is a LIST of
{"et", "date", "unit"} dicts, with variable="ET" / model_name="Ensemble".
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.calculation import evaluate_chain
from accounting.models import CalculationPlan, CalculationStep
from accounting.services import et_mm_to_acre_feet
from accounting.steps import STEP_REGISTRY, clamp_floor, facility_only_zero
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation


def _square(x=0.0):
    """A tiny valid MultiPolygon for OpenETCache.geometry (required field)."""
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))


def _et_cache(parcel, period="2024-06", et_mm=100.0, variable="ET", model="Ensemble"):
    """Create an OpenETCache row with the live list-of-dicts et_data shape."""
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable=variable,
        model_name=model,
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )


def _irrigate(parcel):
    """Give a parcel a UsageLocation with a crop_type (so it's not facility-only)."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_has_exactly_the_four_simple_primitives():
    assert set(STEP_REGISTRY) == {
        "et_gross",
        "subtract_surface_water",
        "facility_only_zero",
        "clamp_floor",
    }
    # subtract_effective_precip is 38-03's job — must not be present yet.
    assert "subtract_effective_precip" not in STEP_REGISTRY


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_et_gross_returns_positive_magnitude_matching_conversion():
    parcel = _parcel("ET-1", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    fn = STEP_REGISTRY["et_gross"]
    af, record = fn(
        Decimal("0"), parcel, "2024-06", {}, {"model": "Ensemble", "variable": "ET"}
    )
    expected = abs(et_mm_to_acre_feet(Decimal("100"), Decimal("10")))
    assert af == expected
    assert af > 0
    assert record["step_type"] == "et_gross"
    assert record["detail"]["rows"] == 1
    assert record["detail"]["months_matched"] == 1


@pytest.mark.django_db
def test_et_gross_picks_only_the_requested_month_from_multimonth_row():
    """A single cache row spanning Jun–Aug must yield only June's mm for 2024-06."""
    from datasync.models import OpenETCache

    parcel = _parcel("ET-MULTI", acres="10")
    OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(2024, 6, 1),
        end_date=dt.date(2024, 8, 31),
        variable="ET",
        model_name="Ensemble",
        et_data=[
            {"et": 170.0, "date": "2024-06", "unit": "mm"},
            {"et": 174.0, "date": "2024-07", "unit": "mm"},
            {"et": 134.0, "date": "2024-08", "unit": "mm"},
        ],
    )
    fn = STEP_REGISTRY["et_gross"]
    af, record = fn(Decimal("0"), parcel, "2024-07", {}, {})
    assert record["detail"]["et_mm"] == "174.0"
    assert af == abs(et_mm_to_acre_feet(Decimal("174.0"), Decimal("10")))


@pytest.mark.django_db
def test_et_gross_no_data_returns_zero_and_rows_zero():
    parcel = _parcel("ET-0")
    fn = STEP_REGISTRY["et_gross"]
    af, record = fn(Decimal("0"), parcel, "2024-06", {}, {})
    assert af == Decimal("0")
    assert record["detail"]["rows"] == 0


@pytest.mark.django_db
def test_subtract_surface_water_subtracts_absolute_and_can_go_negative():
    parcel = _parcel("SW-1")
    # surface_diversion rows are stored NEGATIVE
    ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=dt.date(2024, 6, 1),
        effective_date=dt.date(2024, 6, 1),
        amount_acre_feet=Decimal("-3"),
        source_type="surface_diversion",
    )
    fn = STEP_REGISTRY["subtract_surface_water"]
    new, record = fn(Decimal("2"), parcel, "2024-06", {}, {})
    # 2 - abs(-3) = -1; this step does NOT floor (clamp_floor owns that)
    assert new == Decimal("-1")
    assert record["detail"]["surface_water_af"] == "3"


@pytest.mark.django_db
def test_facility_only_zero_zeros_parcel_without_crop():
    parcel = _parcel("FAC-1")  # no UsageLocation -> facility-only
    new, record = facility_only_zero(Decimal("5"), parcel, "2024-06", {}, {})
    assert new == Decimal("0")
    assert record["detail"]["facility_only"] is True


@pytest.mark.django_db
def test_facility_only_zero_passes_through_irrigated_parcel():
    parcel = _parcel("FAC-2")
    _irrigate(parcel)
    new, record = facility_only_zero(Decimal("5"), parcel, "2024-06", {}, {})
    assert new == Decimal("5")
    assert record["detail"]["facility_only"] is False


@pytest.mark.django_db
def test_clamp_floor_floors_negative_at_zero():
    parcel = _parcel("CL-1")
    new, record = clamp_floor(
        Decimal("-2"), parcel, "2024-06", {}, {"floor": 0, "bank": True}
    )
    assert new == Decimal("0")
    # bank is recorded but a no-op in 38-02
    assert record["detail"]["bank"] is True


@pytest.mark.django_db
def test_clamp_floor_passes_value_above_floor():
    parcel = _parcel("CL-2")
    new, _ = clamp_floor(Decimal("4"), parcel, "2024-06", {}, {})
    assert new == Decimal("4")


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_chain_raises_without_active_plan():
    parcel = _parcel("EV-0")
    with pytest.raises(ValueError, match="no active CalculationPlan"):
        evaluate_chain(parcel, "2024-06")


@pytest.mark.django_db
def test_evaluate_chain_skips_disabled_steps():
    """The disabled (unregistered) effective-precip step must be skipped, not resolved."""
    parcel = _parcel("EV-1", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    call_command("seed_calculation_plan")

    final_af, breakdown = evaluate_chain(parcel, "2024-06")
    step_types = [s["step_type"] for s in breakdown]
    assert "subtract_effective_precip" not in step_types  # disabled -> skipped
    assert step_types == [
        "et_gross",
        "subtract_surface_water",
        "facility_only_zero",
        "clamp_floor",
    ]
    # No surface water, irrigated -> net == gross
    assert final_af == abs(et_mm_to_acre_feet(Decimal("100"), Decimal("10")))


@pytest.mark.django_db
def test_evaluate_chain_raises_on_enabled_unregistered_step():
    parcel = _parcel("EV-2")
    plan = CalculationPlan.objects.create(name="Broken", is_active=True)
    CalculationStep.objects.create(
        plan=plan,
        order=1,
        step_type="subtract_effective_precip",
        enabled=True,
        config={},
        label="enabled-but-unregistered",
    )
    with pytest.raises(ValueError, match="not registered"):
        evaluate_chain(parcel, "2024-06")


# --------------------------------------------------------------------------
# seed_calculation_plan idempotency
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_is_idempotent_and_precip_disabled():
    call_command("seed_calculation_plan")
    call_command("seed_calculation_plan")  # second run must not duplicate

    plans = CalculationPlan.objects.filter(is_active=True)
    assert plans.count() == 1
    plan = plans.first()
    assert plan.steps.count() == 5

    precip = plan.steps.get(step_type="subtract_effective_precip")
    assert precip.enabled is False
    assert plan.steps.filter(enabled=True).count() == 4


# --------------------------------------------------------------------------
# run_calculations idempotency + sign
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_calculations_writes_one_negative_row_and_is_idempotent():
    p1 = _parcel("RUN-1", acres="10")
    p2 = _parcel("RUN-2", acres="20")
    for p in (p1, p2):
        _et_cache(p, period="2024-06", et_mm=100.0)
        _irrigate(p)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    rows = ParcelLedger.objects.filter(source_type="calculated")
    assert rows.count() == 2
    for p, acres in ((p1, "10"), (p2, "20")):
        row = rows.get(parcel=p)
        assert row.effective_date == dt.date(2024, 6, 1)
        assert row.amount_acre_feet < 0  # consumption stored negative
        # The command stores -abs(et) quantized to 4 places; compare like-for-like.
        expected = (-abs(et_mm_to_acre_feet(Decimal("100"), Decimal(acres)))).quantize(
            Decimal("0.0001")
        )
        assert row.amount_acre_feet == expected
        assert "Derived extraction estimate" in row.description

    # Idempotent: second run leaves identical count + amounts (no double-count).
    before = {r.parcel_id: r.amount_acre_feet for r in rows}
    call_command("run_calculations", "--period", "2024-06")
    rows2 = ParcelLedger.objects.filter(source_type="calculated")
    assert rows2.count() == 2
    after = {r.parcel_id: r.amount_acre_feet for r in rows2}
    assert before == after


@pytest.mark.django_db
def test_run_calculations_skips_parcels_without_et():
    p_with = _parcel("HAS-ET", acres="10")
    _et_cache(p_with, period="2024-06", et_mm=100.0)
    _irrigate(p_with)
    _parcel("NO-ET", acres="10")  # no ET cache -> should be skipped
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")
    rows = ParcelLedger.objects.filter(source_type="calculated")
    assert rows.count() == 1
    assert rows.first().parcel_id == p_with.id
