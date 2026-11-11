# SPDX-License-Identifier: AGPL-3.0-or-later
"""A change of irrigation method counts from the month it is given; a corrected area reaches back.

A field's method is read when a month is calculated, and the nightly job calculates every open
month again. A change of method made from August is a change from August on: July was irrigated
the old way, so July's efficiency and deep percolation must not move when July is run again.
An area correction is the other kind of change: it counts in every month not finalized.
"""

from decimal import Decimal as D
from urllib.parse import urlencode

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun, ReportingPeriod
from parcels.models import IrrigationMethod, ParcelIrrigationMethod
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

JULY = "2025-07"
AUGUST = "2025-08"


def _run(parcel, period):
    run = CalculationRun.objects.filter(parcel=parcel, period=period).order_by("-pk").first()
    return {
        "efficiency": run.groundwater_application_efficiency,
        "deep_percolation": run.deep_percolation_gw_af,
        "groundwater": run.gw_extracted_af,
        "gross_et": run.gross_et_af,
    }


def _july(parcel):
    return _run(parcel, JULY)


@pytest.fixture
def d1():
    ld.seed_reference()
    built = ld.build_d1()
    ld.run_months([JULY])
    return built


@pytest.fixture
def drip():
    return IrrigationMethod.objects.create(
        name="Drip (invented)", assigned_efficiency=D("0.900"), range_low=D("0.850"),
        range_high=D("0.950"), source="test input", sort_order=98,
    )


def _client():
    user, _ = get_user_model().objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    return client


def _save_method(parcel, method, start_month=""):
    """Save a method the way the use area page's edit form does."""
    body = urlencode({
        "field": "irrigation_method", "value": method.pk if method else "",
        "start_month": start_month, "reason": "Changed over to drip.",
    })
    return _client().patch(
        reverse("parcels:edit_field", args=[parcel.pk]),
        data=body, content_type="application/x-www-form-urlencoded",
    )


def test_a_method_changed_from_august_leaves_july_as_it_was(d1, drip):
    before = _july(d1["F4"])

    response = _save_method(d1["F4"], drip, "2025-08-17")
    assert response.status_code == 200
    ld.run_months([JULY])

    assert _july(d1["F4"]) == before


def test_august_is_run_with_the_new_method(d1, drip):
    _save_method(d1["F4"], drip, "2025-08-01")

    ld.run_months([JULY, AUGUST])

    assert _run(d1["F4"], AUGUST)["efficiency"] == D("0.900")
    assert _july(d1["F4"])["efficiency"] == D("0.800")


def test_a_method_saved_with_no_month_on_a_use_area_with_none_applies_to_every_month(d1, drip):
    f3 = d1["F3"]
    assert not ParcelIrrigationMethod.objects.filter(parcel=f3).exists()

    response = _save_method(f3, drip)
    assert response.status_code == 200
    ld.run_months([JULY, AUGUST])

    row = ParcelIrrigationMethod.objects.get(parcel=f3)
    assert row.start_month is None
    assert _run(f3, JULY)["efficiency"] == D("0.900")
    assert _run(f3, AUGUST)["efficiency"] == D("0.900")


def test_a_use_area_with_a_method_must_say_from_which_month(d1, drip):
    response = _save_method(d1["F4"], drip)

    assert "Choose a day in the starting month." in response.content.decode()
    assert ParcelIrrigationMethod.objects.filter(parcel=d1["F4"]).count() == 1


def test_a_start_month_inside_a_finalized_year_is_refused(d1, drip):
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)

    response = _save_method(d1["F4"], drip, "2025-08-01")

    assert "WY 2024-2025 is finalized. An administrator can reopen it on the water year page." in response.content.decode()
    assert ParcelIrrigationMethod.objects.filter(parcel=d1["F4"]).count() == 1


def test_saving_a_method_for_a_month_that_has_one_replaces_it(d1, drip):
    _save_method(d1["F4"], drip, "2025-08-01")
    sprinkler = IrrigationMethod.objects.get(name="Sprinkler")

    _save_method(d1["F4"], sprinkler, "2025-08-20")

    august = ParcelIrrigationMethod.objects.get(parcel=d1["F4"], start_month="2025-08-01")
    assert august.method == sprinkler
    assert ParcelIrrigationMethod.objects.filter(parcel=d1["F4"]).count() == 2


def test_not_set_from_a_month_gives_the_default_from_then(d1):
    _save_method(d1["F4"], None, "2025-08-01")

    ld.run_months([JULY, AUGUST])

    assert _july(d1["F4"])["efficiency"] == D("0.800")
    assert _run(d1["F4"], AUGUST)["efficiency"] != D("0.800")
    body = _client().get(reverse("parcels:detail", args=[d1["F4"].pk])).content.decode()
    assert "Not set from August 2025" in body
    assert "Earlier: Sprinkler, 80%, until July 2025" in body


def test_the_page_shows_the_month_and_the_earlier_method(d1, drip):
    _save_method(d1["F4"], drip, "2025-08-01")

    body = _client().get(reverse("parcels:detail", args=[d1["F4"].pk])).content.decode()

    assert "Drip (invented), 90%, from August 2025" in body
    assert "Earlier: Sprinkler, 80%, until July 2025" in body


def test_a_method_from_before_the_upgrade_reads_the_same_in_every_month(d1):
    row = ParcelIrrigationMethod.objects.get(parcel=d1["F4"])
    assert row.start_month is None
    before = _july(d1["F4"])

    ld.run_months([JULY])

    assert _july(d1["F4"]) == before
    assert before["efficiency"] == D("0.800")
    body = _client().get(reverse("parcels:detail", args=[d1["F4"].pk])).content.decode()
    assert "Sprinkler, 80%" in body
    assert "Earlier:" not in body


def test_an_area_correction_reaches_back_into_july(d1):
    assert _july(d1["F4"])["groundwater"] == D("37.5000")
    d1["F4"].area_acres = D("120")
    d1["F4"].save()

    ld.run_months([JULY])

    assert _july(d1["F4"])["groundwater"] == D("45.0000")
