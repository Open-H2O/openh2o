# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field page shows water use recorded with no supply reported (ISS-157).

The capability was already built and already principled: where a field has no
well, the engine records the leftover as ``unmet_demand_af`` with
``residual_disposition="unmet_demand"`` rather than inventing pumping, and the
help pages already say so in as many words ("It is never phantom pumping").
**Nothing displayed it.** In the dry year 47 fields carry the disposition and six
carry an amount.

⛔ The words are the risk and they are settled (Brent, 2026-09-06): *water use
recorded, no supply reported*. Never unauthorized, unpermitted, unlawful, illegal
or stolen, and never implying them. The screen states the arithmetic and stops.
The words themselves are held by ``tests/test_water_vocabulary.py`` against the
DESIGN.md rule-12 row; this file holds the figure and its zero case.

A zero renders NOTHING — not "0.00" and not "none". A zero printed here would
read as a clearance, which is a finding, and the screen does not make findings.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

pytestmark = pytest.mark.django_db

PHRASE = "Water use recorded, no supply reported"


def _user():
    import factory
    from django.contrib.auth.hashers import make_password

    class _User(factory.django.DjangoModelFactory):
        class Meta:
            model = "core.User"

        username = factory.Sequence(lambda n: f"unmetuser{n}")
        email = factory.Sequence(lambda n: f"unmetuser{n}@example.com")
        password = factory.LazyFunction(lambda: make_password("testpass123"))
        is_active = True

    return _User()


def _periods():
    older = ReportingPeriodFactory(
        name="WY 2024-2025",
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
    )
    newer = ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    return older, newer


def _field_with_unmet_demand():
    """A no-well field: 363.26 AF consumed, 330.37 AF of it unexplained."""
    older, newer = _periods()
    parcel = ParcelFactory()
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=older, source_type="surface_diversion",
        amount_acre_feet=Decimal("-80.0000"),
        transaction_date=dt.date(2025, 1, 15), effective_date=dt.date(2025, 1, 15),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2025-01",
        gross_et_af=Decimal("90.0000"),
        net_consumptive_use_af=Decimal("90.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("10.0000"),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("363.2600"),
        net_consumptive_use_af=Decimal("363.2600"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("0.0000"),
        residual_disposition="unmet_demand",
        unmet_demand_af=Decimal("330.3700"),
    )
    return parcel, older, newer


def _client():
    client = Client()
    client.force_login(_user())
    return client


def test_the_helper_sums_the_unmet_demand_for_the_period():
    """One run, 330.3700 AF. The literal is the fixture's, hand-carried."""
    from accounting.services import parcel_unmet_demand

    parcel, older, newer = _field_with_unmet_demand()

    assert parcel_unmet_demand(parcel, newer) == Decimal("330.3700")


def test_the_helper_ignores_a_period_with_no_unmet_disposition():
    """The older year's run resolved to groundwater, so it contributes nothing."""
    from accounting.services import parcel_unmet_demand

    parcel, older, newer = _field_with_unmet_demand()

    assert parcel_unmet_demand(parcel, older) == Decimal("0")


def test_the_field_page_states_the_figure_under_the_settled_words():
    parcel, older, newer = _field_with_unmet_demand()

    response = _client().get(
        reverse("parcels:detail", args=[parcel.pk]) + f"?period={newer.pk}",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    html = response.content.decode()

    assert PHRASE in html, (
        "the field consumed 363.26 AF with 330.37 AF of it unexplained, and the "
        "page says nothing about it (ISS-157)"
    )
    assert '<span class="td-num">330.37</span>' in html


def test_the_wet_year_says_nothing():
    """The same field, the year its supplies were on record."""
    parcel, older, newer = _field_with_unmet_demand()

    response = _client().get(
        reverse("parcels:detail", args=[parcel.pk]) + f"?period={older.pk}",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200

    assert PHRASE not in response.content.decode(), (
        "a zero renders nothing at all; printing the line on a year with no "
        "unmet demand would read as a clearance"
    )


def test_a_field_whose_runs_carry_zero_says_nothing():
    """The disposition is set but the amount is zero — 41 of the 47 dry-year fields."""
    from accounting.services import parcel_unmet_demand

    older, newer = _periods()
    parcel = ParcelFactory()
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("120.0000"),
        net_consumptive_use_af=Decimal("120.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("0.0000"),
        residual_disposition="unmet_demand",
        unmet_demand_af=Decimal("0.0000"),
    )

    response = _client().get(
        reverse("parcels:detail", args=[parcel.pk]) + f"?period={newer.pk}",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    html = response.content.decode()

    assert PHRASE not in html
    assert parcel_unmet_demand(parcel, newer) == Decimal("0")
