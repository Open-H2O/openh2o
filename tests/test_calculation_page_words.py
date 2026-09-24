# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation audit page names its inches and its
method by the same words the methodology editor uses (143-09, R-045, R-046,
R-047).

Each guard is a VALUE assertion against a fixture whose numbers are typed in
here, never a re-derivation of `_step_detail_summary`'s own arithmetic. The
parcel and period names are fictional so the session-scoped Merced seed
cannot collide with them.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from accounting.precip_math import METHOD_LABELS
from accounting.views import _step_detail_summary
from tests.factories import ParcelFactory

User = get_user_model()


def _user():
    return User.objects.create_user(
        username="r045-reader", email="r045-reader@example.com",
        password="x", is_active=True,
    )


def _auth_client():
    client = Client()
    client.force_login(_user())
    return client


def _run(parcel, period="2026-08", config_hash="abc123def456"):
    """A CalculationRun with the plan's own fixture numbers.

    et_gross: 127.0 mm of ET (= 5.0000 in) over 10.00 ac, ÷ 12 in/ft = 4.1667 AF.
    subtract_effective_precip: usda_scs, 25.4 mm rain (= 1.0000 in), 12.7 mm
    effective (= 0.5000 in), 1.0000 AF taken off.
    """
    breakdown = [
        {
            "step_type": "et_gross",
            "label": "Gross ET (OpenET ensemble)",
            "detail": {"et_mm": "127.0", "area_acres": "10.00"},
            "input_af": "0.0000",
            "output_af": "4.1667",
        },
        {
            "step_type": "subtract_effective_precip",
            "label": "Subtract effective precipitation (USDA-SCS)",
            "detail": {
                "method": "usda_scs",
                "precip_mm": "25.4",
                "effective_precip_mm": "12.7",
                "effective_precip_af": "1.0000",
            },
            "input_af": "4.1667",
            "output_af": "3.1667",
        },
    ]
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal("4.1667"),
        final_af=Decimal("3.1667"),
        breakdown=breakdown,
        config_hash=config_hash,
        methodology_plan_name="Default Methodology",
    )


@pytest.mark.django_db
class TestCalculationPageDoesNotPrintTheConfigHash:
    """R-045, as Brent ruled it at the 143-09 checkpoint (2026-09-16): the
    twelve-character config hash is a machine key no page lets a reader
    compare, so it is not printed at all. The head names the methodology and
    stops. (The plan's first answer, naming the code as a "fingerprint" with
    a sentence about a hash, was struck: "Nobody knows what that means.")"""

    def test_head_names_the_methodology_and_no_code(self):
        parcel = ParcelFactory(parcel_number="R045-APN-001")
        _run(parcel)
        client = _auth_client()
        resp = client.get(
            reverse(
                "accounting:calculation_run_detail",
                kwargs={"parcel_id": parcel.pk, "period": "2026-08"},
            )
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Methodology:" in body
        assert "abc123def456" not in body
        assert "fingerprint" not in body.lower()
        assert "hash" not in body.lower()

    def test_blank_config_hash_prints_nothing_about_it(self):
        parcel = ParcelFactory(parcel_number="R045-APN-002")
        _run(parcel, period="2026-07", config_hash="")
        client = _auth_client()
        resp = client.get(
            reverse(
                "accounting:calculation_run_detail",
                kwargs={"parcel_id": parcel.pk, "period": "2026-07"},
            )
        )
        body = resp.content.decode()
        assert "predates" not in body
        assert "fingerprint" not in body.lower()


@pytest.mark.django_db
class TestCalculationPageNamesItsInches:
    """R-046 / R-047: step 1 shows the inches an auditor can check by hand;
    step 2 names its method the same way the editor does, and the config
    key never reaches the page."""

    def test_step1_detail_shows_the_inches_and_the_division(self):
        parcel = ParcelFactory(parcel_number="R047-APN-001")
        _run(parcel, period="2026-08")
        client = _auth_client()
        resp = client.get(
            reverse(
                "accounting:calculation_run_detail",
                kwargs={"parcel_id": parcel.pk, "period": "2026-08"},
            )
        )
        body = resp.content.decode()
        assert "5.0000 in of ET (127.00 mm) × 10.00 ac ÷ 12 in/ft" in body

    def test_step2_detail_names_the_method_and_hides_the_config_key(self):
        parcel = ParcelFactory(parcel_number="R046-APN-001")
        _run(parcel, period="2026-08")
        client = _auth_client()
        resp = client.get(
            reverse(
                "accounting:calculation_run_detail",
                kwargs={"parcel_id": parcel.pk, "period": "2026-08"},
            )
        )
        body = resp.content.decode()
        assert "USDA-SCS (TR-21): 0.5000 in effective of 1.0000 in rain" in body
        assert "usda_scs" not in body

    def test_step_detail_summary_directly_on_the_same_dicts(self):
        """The unit underneath the page: `_step_detail_summary` on the exact
        detail dicts the fixture above stores, so a page-level regression and
        a formula-level regression cannot be confused for one another."""
        et_step = {
            "step_type": "et_gross",
            "detail": {"et_mm": "127.0", "area_acres": "10.00"},
        }
        assert (
            _step_detail_summary(et_step)
            == "5.0000 in of ET (127.00 mm) × 10.00 ac ÷ 12 in/ft"
        )
        precip_step = {
            "step_type": "subtract_effective_precip",
            "detail": {
                "method": "usda_scs",
                "precip_mm": "25.4",
                "effective_precip_mm": "12.7",
                "effective_precip_af": "1.0000",
            },
        }
        assert (
            _step_detail_summary(precip_step)
            == "USDA-SCS (TR-21): 0.5000 in effective of 1.0000 in rain, 1.0000 AF taken off"
        )


@pytest.mark.django_db
class TestOneListOfMethodNames:
    """R-046, rule 6: the editor's rendered `<option>` texts equal
    `METHOD_LABELS`'s own values. The audit page and the editor share the
    one list, they cannot each keep their own copy to drift apart."""

    def test_method_labels_has_the_three_keys(self):
        assert set(METHOD_LABELS) == {"raw", "fraction", "usda_scs"}
        assert METHOD_LABELS["usda_scs"] == "USDA-SCS (TR-21)"
        assert METHOD_LABELS["fraction"] == "Fraction of precipitation"
        assert METHOD_LABELS["raw"] == "Raw (all precipitation)"

    def test_editor_options_equal_method_labels_values(self):
        from django.core.management import call_command

        call_command("seed_calculation_plan")
        user = User.objects.create_user(
            username="editor-reader", email="editor-reader@example.com",
            password="x", is_active=True, is_staff=True,
        )
        client = Client()
        client.force_login(user)
        body = client.get(reverse("accounting:methodology_settings")).content.decode()
        for label in METHOD_LABELS.values():
            assert f">{label}<" in body


def test_surface_step_summary_names_delivered_and_what_the_crop_could_use():
    """148-02: the subtracted figure is the crop's part, so the line says both."""
    step = {
        "step_type": "subtract_surface_water",
        "detail": {
            "delivered_af": "123.1769",
            "efficiency": "0.750",
            "efficiency_source": "agency",
            "consumed_af": "92.3827",
            "surface_water_af": "92.3827",
        },
    }
    assert _step_detail_summary(step) == (
        "−92.3827 AF the crop could use, of 123.1769 AF delivered "
        "(efficiency 0.75, the agency-wide figure)"
    )
    old = {"step_type": "subtract_surface_water", "detail": {"surface_water_af": "5"}}
    assert _step_detail_summary(old) == "−5.0000 AF surface water delivered"


def test_floor_step_summary_says_banked_only_on_an_old_banking_run():
    """148-02: a new run's below-floor figure is information, not a credit."""
    new = {"step_type": "clamp_floor", "detail": {"floor": "0", "surplus_af": "1.5"}}
    assert _step_detail_summary(new) == (
        "floor 0.00; 1.5000 AF below the floor, not carried forward"
    )
    old = {
        "step_type": "clamp_floor",
        "detail": {"floor": "0", "surplus_af": "1.5", "bank": True},
    }
    assert _step_detail_summary(old) == "floor 0.00; 1.5000 AF surplus banked"
