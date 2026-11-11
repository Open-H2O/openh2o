# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changing a field's irrigation method in August leaves July's figures as they were.

A field's method is read when a month is calculated, and the nightly job calculates every open
month again. A change of method made in August is a change from August on: July was irrigated
the old way, so July's efficiency and deep percolation must not move when July is run again.

Whether an area correction should reach back is a separate question with no answer yet: the
second test records what July does and asserts nothing about it.
"""

from decimal import Decimal as D

import pytest

from accounting.models import CalculationRun
from parcels.models import IrrigationMethod, ParcelIrrigationMethod
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

JULY = "2025-07"


def _july(parcel):
    run = CalculationRun.objects.filter(parcel=parcel, period=JULY).order_by("-pk").first()
    return {
        "efficiency": run.groundwater_application_efficiency,
        "deep_percolation": run.deep_percolation_gw_af,
        "groundwater": run.gw_extracted_af,
        "gross_et": run.gross_et_af,
    }


@pytest.fixture
def d1():
    ld.seed_reference()
    built = ld.build_d1()
    ld.run_months([JULY])
    return built


@pytest.mark.xfail(
    strict=True,
    reason="Whether a change of irrigation method takes effect from a month, as a fallow mark "
    "does, is a question for the maintainer before it is built.",
)
def test_a_method_changed_in_august_leaves_july_as_it_was(d1):
    before = _july(d1["F4"])
    drip = IrrigationMethod.objects.create(
        name="Drip (invented)", assigned_efficiency=D("0.900"), range_low=D("0.850"),
        range_high=D("0.950"), source="test input", sort_order=98,
    )
    ParcelIrrigationMethod.objects.filter(parcel=d1["F4"]).update(method=drip)

    ld.run_months([JULY])

    assert _july(d1["F4"]) == before


def test_an_area_correction_and_july_is_recorded_not_judged(d1, capsys):
    before = _july(d1["F4"])
    d1["F4"].area_acres = D("120")
    d1["F4"].save()

    ld.run_months([JULY])

    after = _july(d1["F4"])
    print(f"July before the area correction: {before}; after: {after}")
