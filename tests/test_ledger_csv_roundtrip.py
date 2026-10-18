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


# ---------------------------------------------------------------------------
# A demonstration site (2026-10-18): the export's first line says
# the file comes from the demonstration, the blank template carries no such
# line, and the import skips the line so the export still round-trips. Before
# this the line sat above the column names on both files and the import
# refused either one as downloaded ("Missing required columns").
# ---------------------------------------------------------------------------


@pytest.fixture
def demonstration_site():
    from core.models import SiteConfig

    return SiteConfig.objects.create(agency_name="Demo", demonstration_mode=True)


def _first_row(response):
    return next(csv.reader(io.StringIO(response.content.decode("utf-8"))))


def test_demonstration_export_starts_with_the_demonstration_line(
    auth_client, demonstration_site
):
    from accounting.ledger_words import DEMONSTRATION_FILE_LINE

    resp = auth_client.get(reverse("accounting:ledger_export"))
    assert _first_row(resp) == [DEMONSTRATION_FILE_LINE]
    assert DEMONSTRATION_FILE_LINE == (
        "This file comes from the OpenH2O demonstration. Its figures are sample data."
    )


def test_demonstration_template_starts_with_the_columns(auth_client, demonstration_site):
    resp = auth_client.get(reverse("accounting:csv_template"))
    assert _first_row(resp) == IMPORT_COLUMNS


def test_demonstration_export_reimports_with_zero_new_rows(
    auth_client, demonstration_site, tmp_path
):
    water_type = WaterTypeFactory(code="GW")
    ParcelLedgerFactory(
        parcel=ParcelFactory(),
        water_type=water_type,
        amount_acre_feet=Decimal("-4.5"),
        effective_date=date(2024, 7, 1),
        transaction_date=date(2024, 7, 1),
        source_type="manual_entry",
    )
    export = auth_client.get(reverse("accounting:ledger_export"))
    csv_path = tmp_path / "ledger_export.csv"
    csv_path.write_bytes(export.content)

    out = io.StringIO()
    call_command("import_ledger_csv", str(csv_path), "--dry-run", stdout=out)
    report = out.getvalue()
    assert "Would create 0" in report
    assert "1 skipped as duplicates" in report


def test_import_skips_the_demonstration_line_and_counts_lines_from_the_file():
    from accounting.ledger_import import import_ledger_rows
    from accounting.ledger_words import DEMONSTRATION_FILE_LINE as line

    text = (
        f"{line}\r\n"
        + ",".join(IMPORT_COLUMNS)
        + "\r\nNO-SUCH-PARCEL,2024-01-01,-1,manual_entry,,,\r\n"
    )
    result = import_ledger_rows(io.StringIO(text), dry_run=True)
    # The column names are read, so the one error is the row's own, on line 3
    # of the file as a spreadsheet numbers it.
    assert [e["line"] for e in result["errors"]] == [3]
    assert not any("Missing required columns" in m for e in result["errors"] for m in e["messages"])


def test_an_empty_file_still_reads_as_empty():
    from accounting.ledger_import import import_ledger_rows

    result = import_ledger_rows(io.StringIO(""), dry_run=True)
    assert "appears empty" in result["errors"][0]["messages"][0]
