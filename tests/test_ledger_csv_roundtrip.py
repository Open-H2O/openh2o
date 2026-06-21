# SPDX-License-Identifier: AGPL-3.0-or-later
"""Round-trip guarantee for the ledger CSV export/import pair.

The exporter must emit exactly the columns the importer reads, so a file
downloaded from "Export" feeds straight back into "Import" without loss. The
view used to write a ``water_type`` *name* and a ``reporting_period`` the
importer ignores (and omitted ``transaction_date``), so its own export could not
be re-imported — these tests pin the fix shut.
"""
import csv
import io
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from tests.factories import ParcelFactory, ParcelLedgerFactory, WaterTypeFactory

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"csvuser{n}")
    email = factory.Sequence(lambda n: f"csvuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(UserFactory())
    return c


# The columns import_ledger_csv / parse_ledger_csv read, in order.
IMPORT_COLUMNS = [
    "parcel_number",
    "effective_date",
    "amount_acre_feet",
    "source_type",
    "water_type_code",
    "description",
    "transaction_date",
]


def _header_row(response):
    """The export's column-header row (skipping a demonstration-mode banner line)."""
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    return next(r for r in rows if "parcel_number" in r)


def test_export_header_matches_importer_columns(auth_client):
    resp = auth_client.get(reverse("accounting:ledger_export"))
    assert resp.status_code == 200
    assert _header_row(resp) == IMPORT_COLUMNS


def test_template_header_matches_importer_columns(auth_client):
    resp = auth_client.get(reverse("accounting:csv_template"))
    assert resp.status_code == 200
    assert _header_row(resp) == IMPORT_COLUMNS


def test_export_reimports_with_zero_new_rows(auth_client, tmp_path):
    """Export the ledger, feed the file back to the importer: every row already
    exists, so a dry-run creates nothing and reports them all as duplicates."""
    water_type = WaterTypeFactory(code="GW")
    parcel = ParcelFactory()
    # A comma in the description and a negative amount exercise quoting + the
    # numeric-passthrough of the formula-injection guard.
    ParcelLedgerFactory(
        parcel=parcel,
        water_type=water_type,
        amount_acre_feet=Decimal("-12.3456"),
        effective_date=date(2024, 6, 15),
        transaction_date=date(2024, 6, 15),
        source_type="manual_entry",
        description="delivery, north canal",
    )

    export = auth_client.get(reverse("accounting:ledger_export"))
    csv_path = tmp_path / "ledger_export.csv"
    csv_path.write_bytes(export.content)

    out = io.StringIO()
    call_command("import_ledger_csv", str(csv_path), "--dry-run", stdout=out)
    report = out.getvalue()

    assert "Would create 0" in report
    assert "1 skipped as duplicates" in report
