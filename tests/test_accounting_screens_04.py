# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounting screens: words, forms, the methodology page and the ledger upload."""
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from accounting.forms import AllocationPlanForm, ReportingPeriodForm
from accounting.ledger_import import import_ledger_rows
from accounting.models import AllocationPlan, CalculationPlan, ReportingPeriod
from core.models import User
from parcels.models import ParcelLedger
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


def _client(**flags):
    if not flags.get("read_only"):
        flags.setdefault("is_staff", True)
    user = User.objects.create_user(
        username=f"as-{User.objects.count()}", password="x", is_active=True, **flags
    )
    c = Client()
    c.force_login(user)
    return c


def _square():
    return MultiPolygon(Polygon(((0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0), (0, 0))), srid=4326)


# -- Allocation credit ----------------------------------------------------


def test_an_allocation_ledger_row_reads_allocation_credit():
    period = ReportingPeriodFactory()
    ParcelLedgerFactory(
        reporting_period=period, source_type="allocation", water_type=None,
        amount_acre_feet=Decimal("5.0000"), effective_date=period.start_date,
    )
    html = _client().get(reverse("accounting:ledger_list") + f"?period={period.pk}").content.decode()
    assert "Allocation credit" in html


def test_the_source_filter_offers_allocation_credit():
    html = _client().get(reverse("accounting:ledger_list")).content.decode()
    assert ">Allocation credit</option>" in html


# -- New allocation without a name ---------------------------------------


def test_new_allocation_posts_without_a_name_and_saves():
    zone, wt, period = ZoneFactory(name="North"), WaterTypeFactory(name="Surface"), ReportingPeriodFactory(name="WY 2025-2026")
    c = _client()
    page = c.get(reverse("accounting:allocation_create")).content.decode()
    assert 'id="id_name"' not in page
    r = c.post(
        reverse("accounting:allocation_create"),
        {"zone": zone.pk, "water_type": wt.pk, "reporting_period": period.pk, "allocation_acre_feet": "10"},
    )
    assert r.status_code == 302
    assert AllocationPlan.objects.get().name == "North surface, WY 2025-2026"


def test_allocation_form_has_no_name_field():
    assert "name" not in AllocationPlanForm().fields


# -- Upload results ------------------------------------------------------


def _upload(text, **extra):
    f = SimpleUploadedFile("l.csv", text.encode(), content_type="text/csv")
    return _client().post(reverse("accounting:csv_upload"), {"file": f, "dry_run": "on", **extra}).content.decode()


CSV_HEAD = "parcel_number,effective_date,amount_acre_feet,source_type\n"


def test_the_errors_card_counts_rows_with_errors_under_its_own_unit_word():
    ParcelFactory(parcel_number="U-1")
    html = _upload(CSV_HEAD + "U-1,2025-01-05,-2,meter_reading\nNOPE,2025-01-05,-2,meter_reading\n")
    assert "rows skipped" not in html
    assert "rows with errors" in html


def test_the_upload_preview_heads_the_column_use_area():
    ParcelFactory(parcel_number="U-2")
    html = _upload(CSV_HEAD + "U-2,2025-01-05,-2,meter_reading\n")
    assert "<th>Use area</th>" in html and "<th>Parcel</th>" not in html


def test_the_zone_page_heads_the_column_use_area():
    from geography.models import ParcelZone

    zone, parcel = ZoneFactory(), ParcelFactory()
    ParcelZone.objects.create(parcel=parcel, zone=zone)
    html = _client().get(reverse("geography:zone_detail", args=[zone.pk])).content.decode()
    assert "<th>Use area</th>" in html and "<th>Parcel</th>" not in html


# -- Methodology ---------------------------------------------------------


def _et(parcel, mm):
    from datasync.models import OpenETCache

    return OpenETCache.objects.create(
        parcel=parcel, geometry=_square(), start_date=dt.date(2024, 6, 1),
        end_date=dt.date(2024, 6, 28), variable="ET", model_name="Ensemble",
        et_data=[{"et": mm, "date": "2024-06", "unit": "mm"}],
    )


def test_the_preview_prints_two_places_and_keeps_the_exact_figure_in_the_title():
    call_command("seed_calculation_plan")
    parcel = ParcelFactory(area_acres=Decimal("10"))
    _et(parcel, 123.456)
    html = _client().post(
        reverse("accounting:methodology_preview"), {"parcel_id": parcel.pk, "period": "2024-06"}
    ).content.decode()
    import re

    shown = re.findall(r'title="(\d+\.\d{3,}) acre-feet">(\d+\.\d+)', html)
    assert shown
    for exact, text in shown:
        assert len(text.split(".")[1]) == 2
        assert round(Decimal(exact), 2) == Decimal(text)


def test_the_preview_says_why_a_field_with_no_et_is_zero():
    call_command("seed_calculation_plan")
    parcel = ParcelFactory()
    html = _client().post(
        reverse("accounting:methodology_preview"), {"parcel_id": parcel.pk, "period": "2024-06"}
    ).content.decode()
    assert "No ET is stored for this use area and month" in html


def test_the_button_loads_one_active_plan_and_the_page_shows_it():
    c = _client()
    page = c.get(reverse("accounting:methodology_settings")).content.decode()
    assert reverse("accounting:methodology_load_default") in page
    assert "seed_calculation_plan" not in page
    assert c.post(reverse("accounting:methodology_load_default")).status_code == 302
    assert CalculationPlan.objects.filter(is_active=True).count() == 1
    assert "Default Methodology" in c.get(reverse("accounting:methodology_settings")).content.decode()
    c.post(reverse("accounting:methodology_load_default"))
    assert CalculationPlan.objects.count() == 1


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_a_viewer_is_refused_and_sees_a_sentence_not_a_button():
    v = _client(read_only=True)
    assert v.post(reverse("accounting:methodology_load_default")).status_code == 403
    assert CalculationPlan.objects.count() == 0
    page = v.get(reverse("accounting:methodology_settings")).content.decode()
    assert "An administrator can load the default plan" in page
    assert reverse("accounting:methodology_load_default") not in page


def test_saving_the_rain_step_writes_only_the_chosen_methods_setting():
    call_command("seed_calculation_plan")
    step = CalculationPlan.active().steps.get(step_type="subtract_effective_precip")
    assert "fraction" not in step.config
    r = _client().post(
        reverse("accounting:methodology_step_config", args=[step.pk]),
        {"method": "usda_scs", "soil_storage_in": "3.5", "fraction": "0.7"},
    )
    assert r.status_code == 200
    step.refresh_from_db()
    assert step.config["soil_storage_in"] == 3.5
    assert "fraction" not in step.config


# -- Water years ---------------------------------------------------------


def test_an_overlapping_water_year_is_refused_naming_the_year():
    ReportingPeriod.objects.create(name="WY 2025-2026", start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30))
    form = ReportingPeriodForm(
        {"name": "Next", "start_date": "2026-09-01", "end_date": "2027-08-31"}
    )
    assert not form.is_valid()
    text = " ".join(m for errs in form.errors.values() for m in errs)
    assert "WY 2025-2026" in text
    assert "reporting_period_no_overlap" not in text and "Constraint" not in text


# -- Ledger import zero --------------------------------------------------


def test_a_zero_allocation_row_is_a_row_error_and_the_rest_imports():
    ParcelFactory(parcel_number="Z-1")
    text = (
        CSV_HEAD
        + "Z-1,2025-01-05,4,allocation\n"
        + "Z-1,2025-01-06,0,allocation\n"
        + "Z-1,2025-01-07,3,recharge\n"
    )
    res = import_ledger_rows(io.StringIO(text))
    assert res["created_count"] == 2
    assert [e["line"] for e in res["errors"]] == [3]
    assert "more than zero" in res["errors"][0]["messages"][0]
    assert ParcelLedger.objects.count() == 2
