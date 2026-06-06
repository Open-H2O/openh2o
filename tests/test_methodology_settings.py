# SPDX-License-Identifier: AGPL-3.0-or-later
"""View-level tests for the Methodology Settings UI (38-07).

This page is glue over already-TDD'd math, so these are standard view tests, not
a TDD plan. They lock the behavior that actually matters for a self-serve agency:

  - Staff gate — anonymous and logged-in-non-staff users are bounced from the
    page AND from every mutation/preview endpoint; only staff get in.
  - Config save MERGES, never replaces — editing one step's knobs must not drop
    another step's plumbing keys (the 38-02 silent-zero trap: a lost et_gross
    model/variable silently zeroes every parcel).
  - Reorder integrity — moving steps renumbers a contiguous 1..N permutation and
    never trips unique_together(plan, order) (no IntegrityError).
  - Toggle persists the enabled flag.
  - Preview persists NOTHING — evaluate_chain is side-effect-free (38-04); a
    preview must write zero ledger/run/credit rows.
  - Empty-plan path renders a 200 empty state, not a 500.

Pinned to config.settings.local (prod settings 301/400 list views). Runs in the
web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from accounting.models import (
    CalculationPlan,
    CalculationRun,
    CalculationStep,
    WaterCredit,
)
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation

User = get_user_model()


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _staff_client():
    user = User.objects.create_user(
        username="staffer", password="x", is_active=True, is_staff=True
    )
    c = Client()
    c.force_login(user)
    return c


def _nonstaff_client():
    user = User.objects.create_user(
        username="plainuser", password="x", is_active=True, is_staff=False
    )
    c = Client()
    c.force_login(user)
    return c


def _parcel(number="MTH-1", acres="10"):
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


def _step(step_type):
    plan = CalculationPlan.active()
    return plan.steps.get(step_type=step_type)


# --------------------------------------------------------------------------
# 1. Staff gate
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_is_redirected_from_every_methodology_url():
    call_command("seed_calculation_plan")
    step_id = _step("clamp_floor").id
    anon = Client()

    assert anon.get(reverse("accounting:methodology_settings")).status_code == 302
    assert anon.post(
        reverse("accounting:methodology_step_toggle", args=[step_id])
    ).status_code == 302
    assert anon.post(
        reverse("accounting:methodology_step_move", args=[step_id, "down"])
    ).status_code == 302
    assert anon.post(
        reverse("accounting:methodology_step_config", args=[step_id])
    ).status_code == 302
    assert anon.post(reverse("accounting:methodology_preview")).status_code == 302


@pytest.mark.django_db
@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_logged_in_nonstaff_is_redirected_from_every_methodology_url():
    # Phase 41-01 made the methodology gate switch-aware (admin_required): a
    # non-admin is blocked only when ACCESS_CONTROL_ENFORCED is ON. With the
    # switch OFF (default, demo) any logged-in user passes through by design.
    call_command("seed_calculation_plan")
    step_id = _step("clamp_floor").id
    c = _nonstaff_client()

    assert c.get(reverse("accounting:methodology_settings")).status_code == 302
    assert c.post(
        reverse("accounting:methodology_step_toggle", args=[step_id])
    ).status_code == 302
    assert c.post(
        reverse("accounting:methodology_step_move", args=[step_id, "down"])
    ).status_code == 302
    assert c.post(
        reverse("accounting:methodology_step_config", args=[step_id])
    ).status_code == 302
    assert c.post(reverse("accounting:methodology_preview")).status_code == 302


@pytest.mark.django_db
def test_staff_reaches_the_page_and_every_mutation_and_preview():
    call_command("seed_calculation_plan")
    step_id = _step("clamp_floor").id
    c = _staff_client()

    assert c.get(reverse("accounting:methodology_settings")).status_code == 200
    assert c.post(
        reverse("accounting:methodology_step_toggle", args=[step_id])
    ).status_code == 200
    assert c.post(
        reverse("accounting:methodology_step_move", args=[step_id, "up"])
    ).status_code == 200
    assert c.post(
        reverse("accounting:methodology_step_config", args=[step_id]),
        {"floor": "0"},
    ).status_code == 200
    # Preview with no parcel still 200 (friendly message), proving the gate passed.
    assert c.post(reverse("accounting:methodology_preview")).status_code == 200


# --------------------------------------------------------------------------
# 2. Config save MERGES, never drops
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_editing_one_step_config_never_drops_another_steps_plumbing():
    call_command("seed_calculation_plan")
    c = _staff_client()

    et_step = _step("et_gross")
    precip_step = _step("subtract_effective_precip")
    # Seeded plumbing the silent-zero trap depends on.
    assert et_step.config.get("model") == "Ensemble"
    assert et_step.config.get("variable") == "ET"
    assert precip_step.config.get("soil_storage_in") is not None

    resp = c.post(
        reverse("accounting:methodology_step_config", args=[precip_step.id]),
        {"method": "fraction", "fraction": "0.5", "soil_storage_in": "3.0",
         "label": precip_step.label},
    )
    assert resp.status_code == 200

    # et_gross is a DIFFERENT step — must be entirely untouched.
    et_step.refresh_from_db()
    assert et_step.config.get("model") == "Ensemble"
    assert et_step.config.get("variable") == "ET"

    # The precip step gained the new keys AND kept its existing one (merge).
    precip_step.refresh_from_db()
    assert precip_step.config.get("method") == "fraction"
    assert Decimal(str(precip_step.config.get("fraction"))) == Decimal("0.5")
    assert precip_step.config.get("soil_storage_in") is not None


@pytest.mark.django_db
def test_clamp_floor_save_exposes_the_banking_levers():
    call_command("seed_calculation_plan")
    c = _staff_client()
    clamp = _step("clamp_floor")

    resp = c.post(
        reverse("accounting:methodology_step_config", args=[clamp.id]),
        {"floor": "0", "bank": "on", "depreciation_rate": "0.10", "expiry_months": "12"},
    )
    assert resp.status_code == 200

    clamp.refresh_from_db()
    assert clamp.config.get("bank") is True
    assert Decimal(str(clamp.config.get("depreciation_rate"))) == Decimal("0.10")
    assert clamp.config.get("expiry_months") == 12

    # Blank expiry must persist as None (never), not "" — banking_math needs None.
    resp = c.post(
        reverse("accounting:methodology_step_config", args=[clamp.id]),
        {"floor": "0", "expiry_months": ""},
    )
    assert resp.status_code == 200
    clamp.refresh_from_db()
    assert clamp.config.get("expiry_months") is None
    # bank checkbox absent from the second POST -> unchecked.
    assert clamp.config.get("bank") is False


# --------------------------------------------------------------------------
# 3. Reorder integrity
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_reorder_keeps_orders_contiguous_and_restores_after_up_then_down():
    call_command("seed_calculation_plan")
    c = _staff_client()
    plan = CalculationPlan.active()

    original = {s.step_type: s.order for s in plan.steps.all()}
    middle = plan.steps.get(order=3)

    up = c.post(reverse("accounting:methodology_step_move", args=[middle.id, "up"]))
    assert up.status_code == 200
    orders = sorted(s.order for s in plan.steps.all())
    assert orders == [1, 2, 3, 4, 5]  # still a contiguous permutation, no gaps/dupes
    middle.refresh_from_db()
    assert middle.order == 2  # moved up one slot

    down = c.post(reverse("accounting:methodology_step_move", args=[middle.id, "down"]))
    assert down.status_code == 200
    restored = {s.step_type: s.order for s in plan.steps.all()}
    assert restored == original  # up then down is a perfect round-trip


@pytest.mark.django_db
def test_repeated_reorders_never_raise_integrity_error():
    call_command("seed_calculation_plan")
    c = _staff_client()
    plan = CalculationPlan.active()
    first = plan.steps.get(order=1)

    # Hammer the same step down repeatedly; the two-pass renumber must never trip
    # unique_together(plan, order). A 500 here would mean an IntegrityError leaked.
    for _ in range(6):
        resp = c.post(
            reverse("accounting:methodology_step_move", args=[first.id, "down"])
        )
        assert resp.status_code == 200
        assert sorted(s.order for s in plan.steps.all()) == [1, 2, 3, 4, 5]


# --------------------------------------------------------------------------
# 4. Toggle persists
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_toggle_persists_the_enabled_flag():
    call_command("seed_calculation_plan")
    c = _staff_client()
    step = _step("subtract_surface_water")
    assert step.enabled is True

    c.post(reverse("accounting:methodology_step_toggle", args=[step.id]))
    step.refresh_from_db()
    assert step.enabled is False

    c.post(reverse("accounting:methodology_step_toggle", args=[step.id]))
    step.refresh_from_db()
    assert step.enabled is True


# --------------------------------------------------------------------------
# 5. Preview persists nothing
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_writes_zero_rows_but_renders_the_final_number():
    call_command("seed_calculation_plan")
    parcel = _parcel("MTH-PREVIEW", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    c = _staff_client()

    runs_before = CalculationRun.objects.count()
    calc_before = ParcelLedger.objects.filter(source_type="calculated").count()
    credits_before = WaterCredit.objects.count()

    resp = c.post(
        reverse("accounting:methodology_preview"),
        {"parcel_id": str(parcel.id), "period": "2024-06"},
    )
    assert resp.status_code == 200
    # The success path (not the error message) rendered the waterfall + final AF.
    assert b"Billable groundwater" in resp.content

    # The whole point of evaluate_chain being side-effect-free: nothing persisted.
    assert CalculationRun.objects.count() == runs_before
    assert (
        ParcelLedger.objects.filter(source_type="calculated").count() == calc_before
    )
    assert WaterCredit.objects.count() == credits_before


@pytest.mark.django_db
def test_preview_degrades_gracefully_on_a_no_et_parcel():
    call_command("seed_calculation_plan")
    parcel = _parcel("MTH-NOET", acres="10")  # no ET cache
    _irrigate(parcel)
    c = _staff_client()

    resp = c.post(
        reverse("accounting:methodology_preview"),
        {"parcel_id": str(parcel.id), "period": "2024-06"},
    )
    assert resp.status_code == 200  # 0 AF, not a 500
    assert CalculationRun.objects.count() == 0


# --------------------------------------------------------------------------
# 6. Empty-plan path
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_settings_page_is_200_empty_state_when_no_active_plan():
    # No seed_calculation_plan -> CalculationPlan.active() is None.
    assert CalculationPlan.active() is None
    c = _staff_client()

    resp = c.get(reverse("accounting:methodology_settings"))
    assert resp.status_code == 200  # friendly empty state, never a 500
    assert b"No active methodology" in resp.content
