# SPDX-License-Identifier: AGPL-3.0-or-later
"""Five kinds of old data are gone: no choice, model, column, step or helper can make or read them.

The kinds are ET estimate ledger entries, canal estimates from crop need, the credited over-delivery,
the rain bank and the facility-only calculation step.
"""

import io

import pytest
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse

from accounting import services, steps
from accounting.models import AllocationCarryover, CalculationRun, CalculationStep
from core.models import SiteConfig
from parcels.models import ParcelLedger
from surface import diversion_import
from surface.models import DiversionRecord

from .factories import PointOfDiversionFactory, WaterRightFactory
from .import_flow import token_of

STATE_CSV = (
    "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT,calendar_month\n"
    "A100001,2024,6,DIRECT,100,2024-06\n"
)


def _values(choices):
    return {value for value, _label in choices}


# ---------------------------------------------------------------- ET estimate entries


@pytest.mark.parametrize("model_name", ["ParcelLedger", "ParcelLedgerEvent"])
def test_et_estimate_is_not_a_source_type_choice(model_name):
    model = apps.get_model("parcels", model_name)
    assert "et_estimate" not in _values(model._meta.get_field("source_type").choices)
    assert "et_estimate" not in _values(ParcelLedger.SOURCE_TYPE_CHOICES)


@pytest.mark.django_db
def test_the_usage_row_constraint_does_not_name_et_estimate():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'parcelledger_usage_rows_non_positive'"
        )
        (definition,) = cursor.fetchone()
    assert "et_estimate" not in definition
    assert "meter_reading" in definition


# ---------------------------------------------------------------- canal estimates from crop need


def test_estimated_from_use_is_not_a_diversion_method_choice():
    assert "estimated_from_use" not in _values(DiversionRecord.METHOD_CHOICES)
    assert "estimated_from_use" not in _values(
        DiversionRecord._meta.get_field("method").choices
    )


@pytest.mark.django_db
def test_the_import_command_refuses_the_retired_method(tmp_path):
    path = tmp_path / "state.csv"
    path.write_text(STATE_CSV)
    with pytest.raises(CommandError, match="invalid choice"):
        call_command(
            "import_diversion_records", str(path),
            "--method", "estimated_from_use", "--dry-run", stdout=io.StringIO(),
        )


@pytest.mark.django_db
def test_the_import_page_answers_400_to_a_method_outside_the_choices_and_stores_nothing(
    admin_client,
):
    right = WaterRightFactory(right_id="A100001")
    PointOfDiversionFactory(water_right=right, status="active")
    upload = SimpleUploadedFile("state.csv", STATE_CSV.encode(), content_type="text/csv")
    preview = admin_client.post(reverse("surface:diversion_import_preview"), {"file": upload})
    response = admin_client.post(
        reverse("surface:diversion_import_commit"),
        {"token": token_of(preview), "method": "xyz", "data_state": "provisional"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 400
    assert DiversionRecord.objects.count() == 0


@pytest.mark.django_db
def test_commit_rows_raises_value_error_for_a_method_outside_the_choices():
    with pytest.raises(ValueError):
        diversion_import.commit_rows({"errors": [], "candidates": []}, method="xyz")


# ---------------------------------------------------------------- the credited over-delivery


@pytest.mark.parametrize(
    "choices",
    [
        SiteConfig.OVER_DELIVERY_TREATMENT_CHOICES,
        CalculationRun._meta.get_field("over_delivery_treatment").choices,
    ],
    ids=["SiteConfig", "CalculationRun"],
)
def test_credited_is_not_an_over_delivery_treatment_choice(choices):
    assert _values(choices) == {"not_credited", "named_line"}


def test_incidental_recharge_pool_is_not_a_carryover_origin():
    assert "incidental_recharge_pool" not in _values(
        AllocationCarryover._meta.get_field("origin").choices
    )


# ---------------------------------------------------------------- the rain bank


@pytest.mark.parametrize("model_name", ["WaterCredit", "WaterCreditDraw"])
def test_the_rain_bank_models_are_not_installed(model_name):
    with pytest.raises(LookupError):
        apps.get_model("accounting", model_name)


@pytest.mark.parametrize(
    "field",
    [
        "banked_af",
        "drawn_af",
        "over_delivery_leave_behind",
        "over_delivery_credited_af",
        "over_delivery_credit_pooled",
    ],
)
def test_the_calculation_run_has_no_field_for_the_old_kinds(field):
    with pytest.raises(FieldDoesNotExist):
        CalculationRun._meta.get_field(field)


# ---------------------------------------------------------------- the facility-only step


def test_facility_only_zero_is_not_a_step_type_or_a_registered_step():
    assert "facility_only_zero" not in _values(CalculationStep.STEP_TYPE_CHOICES)
    assert "facility_only_zero" not in steps.STEP_REGISTRY


# ---------------------------------------------------------------- the ledger helper


def test_accounting_services_has_no_billable_ledger():
    assert not hasattr(services, "billable_ledger")
