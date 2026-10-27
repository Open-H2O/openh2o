# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entering ledger rows: which water year a row counts in, which periods can
exist, and what the Download CSV link carries.

* A typed or uploaded row counts in the water year its date falls in, never in
  one picked on the form. A date no water year covers is kept with no water
  year (``attach_orphans_to_period`` attaches it when one is created).
* A water year starts on the first of a month and ends on a month's last day.
* The Use Ledger download carries every filter on the screen.
"""
import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounting.forms import ReportingPeriodForm
from accounting.models import ReportingPeriod
from accounting.services import (
    attach_orphans_to_period,
    parcel_balance,
    parse_ledger_csv,
)
from core.models import User
from geography.models import ParcelZone
from parcels.models import ParcelLedger
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    user = User.objects.create(
        username="le-user", email="le@example.com",
        password=make_password("x"), is_active=True,
    )
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def wy_2025():
    return ReportingPeriodFactory(
        name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )


def _entry_post(parcel, effective, amount, picked=None):
    data = {
        "parcel": parcel.pk,
        "transaction_date": effective,
        "effective_date": effective,
        "amount_acre_feet": amount,
        "source_type": "meter_reading",
        "description": "",
    }
    if picked is not None:
        data["reporting_period"] = picked.pk
    return data


# -- F-13: the row counts in the water year its date falls in -------------------


def test_typed_2023_reading_adds_nothing_to_wy_2025_even_when_that_year_is_picked(
    client, wy_2025
):
    parcel = ParcelFactory()
    resp = client.post(
        reverse("accounting:ledger_create"),
        _entry_post(parcel, "2023-05-01", "-12.5", picked=wy_2025),
    )
    assert resp.status_code == 302
    assert parcel_balance(parcel, reporting_period=wy_2025) == Decimal("0")
    assert ParcelLedger.objects.filter(reporting_period=wy_2025).count() == 0
    row = ParcelLedger.objects.get()
    assert row.reporting_period_id is None


def test_typed_reading_counts_in_the_year_its_date_falls_in(client, wy_2025):
    parcel = ParcelFactory()
    client.post(
        reverse("accounting:ledger_create"),
        _entry_post(parcel, "2025-11-15", "-12.5"),
    )
    assert ParcelLedger.objects.get().reporting_period_id == wy_2025.pk


def test_entry_form_has_no_water_year_picker(client, wy_2025):
    page = client.get(reverse("accounting:ledger_create")).content.decode()
    assert 'name="reporting_period"' not in page


def test_uploaded_2023_reading_adds_nothing_to_wy_2025(client, wy_2025):
    parcel = ParcelFactory(parcel_number="LE-UP-1")
    text = (
        "parcel_number,effective_date,amount_acre_feet,source_type\n"
        "LE-UP-1,2023-05-01,-12.5,meter_reading\n"
        "LE-UP-1,2025-11-15,-3,meter_reading\n"
    )
    resp = client.post(
        reverse("accounting:csv_upload"),
        {
            "file": SimpleUploadedFile("f.csv", text.encode()),
            # A stale form that still posts a picked year must not decide anything.
            "reporting_period": wy_2025.pk,
        },
    )
    assert resp.status_code == 200
    assert parcel_balance(parcel, reporting_period=wy_2025) == Decimal("-3.0000")
    old = ParcelLedger.objects.get(effective_date=date(2023, 5, 1))
    assert old.reporting_period_id is None


def test_an_orphan_attaches_when_a_year_covering_it_is_created(wy_2025):
    parcel = ParcelFactory(parcel_number="LE-ORPH")
    parse_ledger_csv(
        io.BytesIO(
            b"parcel_number,effective_date,amount_acre_feet,source_type\n"
            b"LE-ORPH,2023-05-01,-12.5,meter_reading\n"
        )
    )
    wy_2023 = ReportingPeriodFactory(
        name="WY 2022-2023", start_date=date(2022, 10, 1), end_date=date(2023, 9, 30)
    )
    attach_orphans_to_period(wy_2023)
    assert parcel_balance(parcel, reporting_period=wy_2023) == Decimal("-12.5000")


# -- F-22: periods run first of a month to last of a month ------------------------


def _period_form(start, end):
    return ReportingPeriodForm(data={"name": "WY test", "start_date": start, "end_date": end})


def test_a_period_ending_15_march_is_refused_beside_the_end_date():
    form = _period_form("2025-10-01", "2026-03-15")
    assert not form.is_valid()
    assert "end_date" in form.errors
    assert "start_date" not in form.errors


def test_a_period_starting_16_march_is_refused_beside_the_start_date():
    form = _period_form("2026-03-16", "2026-09-30")
    assert not form.is_valid()
    assert "start_date" in form.errors


def test_1_october_to_30_september_saves():
    form = _period_form("2025-10-01", "2026-09-30")
    assert form.is_valid(), form.errors
    form.save()
    assert ReportingPeriod.objects.count() == 1


def test_a_period_ending_on_a_february_last_day_saves():
    assert _period_form("2027-02-01", "2028-02-29").is_valid()


# -- F-26: the download carries the screen's filters -----------------------------


def _rows(response):
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    header = next(i for i, r in enumerate(rows) if "parcel_number" in r)
    return rows[header + 1:]


def _total(response):
    return sum(Decimal(r[2]) for r in _rows(response))


@pytest.fixture
def zoned_rows():
    """150 AF of rows in all; 100 AF of them on fields in the zone."""
    zone = ZoneFactory(name="Le Zone")
    inside = ParcelFactory(parcel_number="LE-IN")
    outside = ParcelFactory(parcel_number="LE-OUT")
    ParcelZone.objects.create(parcel=inside, zone=zone)
    for amount in ("-60", "-40"):
        ParcelLedgerFactory(
            parcel=inside, effective_date=date(2025, 11, 1),
            amount_acre_feet=Decimal(amount), source_type="meter_reading",
        )
    ParcelLedgerFactory(
        parcel=outside, effective_date=date(2025, 11, 1),
        amount_acre_feet=Decimal("-50"), source_type="meter_reading",
        description="elsewhere",
    )
    return zone


def test_download_under_a_zone_filter_totals_100(client, zoned_rows):
    url = reverse("accounting:ledger_export")
    assert _total(client.get(url)) == Decimal("-150.0000")
    assert _total(client.get(url, {"zone": zoned_rows.pk})) == Decimal("-100.0000")


def test_download_under_a_search_filter_carries_the_search(client, zoned_rows):
    url = reverse("accounting:ledger_export")
    assert _total(client.get(url, {"q": "LE-IN"})) == Decimal("-100.0000")
    assert _total(client.get(url, {"q": "elsewhere"})) == Decimal("-50.0000")


def test_the_results_fragment_carries_a_download_link_with_the_new_filters(
    client, zoned_rows
):
    resp = client.get(
        reverse("accounting:ledger_list"),
        {"period": "", "zone": zoned_rows.pk, "q": "LE-IN"},
        HTTP_HX_REQUEST="true",
    )
    html = resp.content.decode()
    assert 'id="ledger-download"' in html
    assert 'hx-swap-oob="true"' in html
    assert f"zone={zoned_rows.pk}" in html
    assert "q=LE-IN" in html


def test_the_full_page_download_link_carries_zone_and_search(client, zoned_rows):
    html = client.get(
        reverse("accounting:ledger_list"), {"period": "", "zone": zoned_rows.pk, "q": "LE-IN"}
    ).content.decode()
    assert html.count('id="ledger-download"') == 1
    assert f"zone={zoned_rows.pk}" in html
    assert "hx-swap-oob" not in html.split('id="ledger-download"')[1].split(">")[0]
