# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a field is charged for groundwater, worked by hand.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A canal delivery OpenH2O estimated (the point has no record for the month)
  stays on the canal page and in the water budget, is labelled estimated on
  the field's page, and is never subtracted from the field's groundwater
  charge. A typed record still is.
* A field's crop water use is counted unless the field carries the fallow mark;
  a field with no crop on record is charged like any other. A calculation plan
  that still holds the old no-crop step no longer zeroes anything.
* Canal delivery is always multiplied by the field's irrigation efficiency, with
  or without the setting in the plan.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.http import urlencode

from accounting.models import CalculationPlan, CalculationRun, CalculationStep
from core.models import User
from parcels.models import IrrigationMethod, Parcel, ParcelIrrigationMethod
from surface.models import DiversionRecord

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

Z = D("0.0001")
M = {7: "2025-07", 8: "2025-08", 9: "2025-09"}


def run_of(parcel, period):
    return CalculationRun.objects.get(parcel=parcel, period=period)


def pumped(parcel, period):
    return run_of(parcel, period).gw_extracted_af


@pytest.fixture
def ref():
    ld.seed_reference()


def worked_example_field(typed_af=None):
    """A well field with no meter, 8.8567 AF of crop use in July 2025, efficiency 0.75, on an unmetered point.

    No losses on the point, so the estimate delivers exactly the crop use.
    """
    well = ld.make_well("WX", -120.55, 37.2)
    field = ld.add_field("X1", 100, "Alfalfa", None, [], -120.55, 37.2, [{"2025-07": "26.99522"}], well)
    point = ld.make_point("X headgate", -120.5, 37.15, None, "0", "0", "0", [(field, "1")])
    if typed_af is not None:
        ld.typed_record(point, dt.date(2025, 7, 1), typed_af)
    return field, point


# ------------------------------------------------------------------ F-04
def test_estimated_delivery_leaves_the_groundwater_charge_whole(ref):
    field, point = worked_example_field()
    ld.run_months(["2025-07"])
    # the estimate was made and divided: it stays on the canal page and in the budget
    assert DiversionRecord.objects.get(point_of_diversion=point).method == "estimated_from_use"
    assert ld.ParcelLedger.objects.filter(parcel=field, source_type="surface_diversion").count() == 1
    assert pumped(field, "2025-07") == D("11.8089")


def test_a_typed_delivery_still_comes_off_the_groundwater_charge(ref):
    # 4 AF typed x 0.75 = 3.0000 AF used; (8.8567 - 3.0000) / 0.75 = 7.8089
    field, _ = worked_example_field(typed_af="4.0000")
    ld.run_months(["2025-07"])
    assert pumped(field, "2025-07") == D("7.8089")


def test_d2_august_estimate_reduces_no_fields_groundwater_need(ref):
    d2 = ld.build_d2()
    for i, key in enumerate(("G1", "G2", "G3")):
        well = ld.make_well(f"GW{i}", -120.55 + 0.01 * i, 37.19)
        ld.WellIrrigatedParcel.objects.create(well=well, parcel=d2[key])
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])
    assert DiversionRecord.objects.get(point_of_diversion=d2["P2"], month=ld.AUG).method == "estimated_from_use"
    # August crop use 15 / 12 / 6 AF over 0.75 / 0.80 / 0.75
    assert pumped(d2["G1"], "2025-08") == D("20.0000")
    assert pumped(d2["G2"], "2025-08") == D("15.0000")
    assert pumped(d2["G3"], "2025-08") == D("8.0000")


def test_the_field_page_says_the_estimated_delivery_is_estimated(ref):
    field, _ = worked_example_field()
    ld.run_months(["2025-07"])
    page = Client()
    page.force_login(User.objects.create_user(username="reader", password="x", is_active=True))
    body = page.get(reverse("parcels:detail", args=[field.pk])).content.decode()
    assert "includes 11.81 AF estimated" in body


def test_the_field_page_adds_nothing_for_a_typed_delivery(ref):
    field, _ = worked_example_field(typed_af="4.0000")
    ld.run_months(["2025-07"])
    page = Client()
    page.force_login(User.objects.create_user(username="reader", password="x", is_active=True))
    body = page.get(reverse("parcels:detail", args=[field.pk])).content.decode()
    assert "AF estimated" not in body


# ------------------------------------------------------------------ F-06
def test_d1_a_field_with_no_crop_on_record_is_charged_its_crop_use(ref):
    d1 = ld.build_d1()
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])
    ld.run_months(["2025-09"])
    f3 = d1["F3"]
    assert pumped(f3, "2025-07") == D("26.6667")
    assert pumped(f3, "2025-08") == D("26.6667")
    assert pumped(f3, "2025-09") == D("13.3333")


def test_d1_gsa_used_and_remaining_count_the_field_with_no_crop(ref):
    d1 = ld.build_d1()
    for m in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([m])
    row = ld.zone_budget(d1["gsa"], "WY 2024-2025")
    assert row["used"] == D("221.6667")
    assert row["remaining"] == D("-121.6667")


def test_a_field_marked_fallow_is_charged_nothing(ref):
    d1 = ld.build_d1()
    Parcel.objects.filter(pk=d1["F3"].pk).update(fallow=True)
    ld.run_months(["2025-07"])
    run = run_of(d1["F3"], "2025-07")
    assert (run.gw_extracted_af or D("0")) == D("0")
    assert run.net_consumptive_use_af == D("0.0000")


def test_a_plan_still_holding_the_no_crop_step_does_not_zero(ref):
    plan = CalculationPlan.active()
    CalculationStep.objects.filter(plan=plan, step_type="clamp_floor").update(order=6)
    CalculationStep.objects.create(
        plan=plan, order=5, step_type="facility_only_zero", enabled=True, config={}, label="Zero out facility-only parcels")
    d1 = ld.build_d1()
    ld.run_months(["2025-07"])
    assert pumped(d1["F3"], "2025-07") == D("26.6667")


def test_the_seeded_plan_has_no_no_crop_step(ref):
    types = list(CalculationPlan.active().steps.order_by("order").values_list("step_type", flat=True))
    assert types == ["et_gross", "subtract_effective_precip", "subtract_surface_water", "clamp_floor"]


def test_seeding_again_takes_the_old_step_out_of_an_existing_plan(ref):
    from django.core.management import call_command

    plan = CalculationPlan.active()
    CalculationStep.objects.filter(plan=plan, step_type="clamp_floor").update(order=6)
    CalculationStep.objects.create(
        plan=plan, order=4, step_type="facility_only_zero", enabled=True, config={}, label="Zero out facility-only parcels")
    CalculationStep.objects.filter(plan=plan, order=6).update(order=5)
    assert plan.steps.count() == 5
    call_command("seed_calculation_plan", stdout=ld.io.StringIO())
    types = list(plan.steps.order_by("order").values_list("step_type", flat=True))
    assert types == ["et_gross", "subtract_effective_precip", "subtract_surface_water", "clamp_floor"]


def test_the_fallow_mark_is_set_from_the_field_page(ref):
    field, _ = worked_example_field()
    user = User.objects.create_user(username="operator", password="x", is_active=True)
    page = Client()
    page.force_login(user)
    url = reverse("parcels:edit_field", args=[field.pk])
    resp = page.patch(url, data=urlencode({"field": "fallow", "value": "yes"}),
                      content_type="application/x-www-form-urlencoded")
    assert resp.status_code == 200
    field.refresh_from_db()
    assert field.fallow is True
    assert "Fallow" in resp.content.decode()
    resp = page.patch(url, data=urlencode({"field": "fallow", "value": "no"}),
                      content_type="application/x-www-form-urlencoded")
    field.refresh_from_db()
    assert field.fallow is False


# ------------------------------------------------------------------ F-18
def efficiency_field():
    """100 acres, efficiency 0.870, 15.0182 AF of crop use in September 2026, 13.7974 AF delivered."""
    IrrigationMethod.objects.create(
        name="Test method", assigned_efficiency=D("0.870"), range_low=D("0.800"), range_high=D("0.900"),
        source="test input", sort_order=98)
    well = ld.make_well("WE", -120.55, 37.2)
    field = ld.add_field("E1", 100, "Alfalfa", None, [], -120.55, 37.2, [{"2026-09": "45.7754"}], well)
    ParcelIrrigationMethod.objects.create(parcel=field, method=IrrigationMethod.objects.get(name="Test method"))
    ld.ledger(field, dt.date(2026, 9, 1), "-13.7974", "surface_diversion", "SW", "own delivery typed on the field ledger")
    return field


def test_a_plan_without_the_efficiency_setting_multiplies_by_efficiency(ref):
    step = CalculationStep.objects.get(plan=CalculationPlan.active(), step_type="subtract_surface_water")
    step.config = {}
    step.save()
    field = efficiency_field()
    ld.run_months(["2026-09"])
    # 13.7974 x 0.870 = 12.0037 used; 15.0182 - 12.0037 = 3.0145; 3.0145 / 0.870 = 3.4649
    assert pumped(field, "2026-09") == D("3.4649")


def test_a_plan_with_the_setting_off_still_multiplies_by_efficiency(ref):
    step = CalculationStep.objects.get(plan=CalculationPlan.active(), step_type="subtract_surface_water")
    step.config = {"apply_efficiency": False}
    step.save()
    field = efficiency_field()
    ld.run_months(["2026-09"])
    assert pumped(field, "2026-09") == D("3.4649")
