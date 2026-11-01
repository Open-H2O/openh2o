# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger file's calculation_method column (Phase 151.6, plan 02, ruling 44).

A calculated row of the downloaded ledger file names the plan and the settings
code of the run that produced it: "<plan name>, settings <config_hash>". Every
other row leaves the cell blank, and so does a calculated row whose run is gone.
The ledger import ignores the column, so export, import, export gives the same
file, and the blank template does not gain it. The "How was this calculated?"
page prints the same code beside the method name.

The district is ``tests.ledger_districts.build_d1`` run for July to September
2025: F3 and F4 have calculated rows in each month, F1 and F2 have meter readings.
The tests then set each run's plan name and settings code to stated literals.
"""
import csv
import io

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounting.models import CalculationRun
from core.models import User

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

IMPORT_COLUMNS = [
    "parcel_number", "effective_date", "amount_acre_feet", "source_type",
    "water_type_code", "description", "transaction_date",
]
DEFAULT = "Default Methodology, settings a582bd80c59b"
SECOND = "Second Plan, settings 0123456789ab"


@pytest.fixture
def d1():
    ld.seed_reference()
    d1 = ld.build_d1()
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    CalculationRun.objects.update(methodology_plan_name="Default Methodology", config_hash="a582bd80c59b")
    CalculationRun.objects.filter(parcel=d1["F4"], period="2025-08").update(
        methodology_plan_name="Second Plan", config_hash="0123456789ab")
    # F3's September run is gone; its calculated row stays.
    CalculationRun.objects.filter(parcel=d1["F3"], period="2025-09").delete()
    return d1


@pytest.fixture
def client():
    c = Client()
    c.force_login(User.objects.create_user(username="reader-method", password="x", is_active=True))
    return c


def _export(client):
    response = client.get(reverse("accounting:ledger_export"))
    assert response.status_code == 200
    lines = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    start = next(i for i, r in enumerate(lines) if "parcel_number" in r)
    header = lines[start]
    return response.content, header, [dict(zip(header, r)) for r in lines[start + 1:]]


# ---------------------------------------------------------------- (e) the column's values
def test_the_export_ends_with_a_calculation_method_column(d1, client):
    _, header, _ = _export(client)
    assert header == IMPORT_COLUMNS + ["calculation_method"]


def test_a_calculated_row_names_its_plan_and_settings_code(d1, client):
    _, _, rows = _export(client)
    found = {(r["parcel_number"], r["effective_date"]): r["calculation_method"]
             for r in rows if r["source_type"] == "calculated" and r["parcel_number"] in ("F3", "F4")}
    assert found[("F3", "2025-07-01")] == DEFAULT
    assert found[("F3", "2025-08-01")] == DEFAULT
    assert found[("F4", "2025-07-01")] == DEFAULT
    assert found[("F4", "2025-08-01")] == SECOND
    assert found[("F4", "2025-09-01")] == DEFAULT


def test_a_calculated_row_whose_run_is_gone_has_a_blank_method(d1, client):
    _, _, rows = _export(client)
    sep = [r for r in rows if r["parcel_number"] == "F3" and r["effective_date"] == "2025-09-01"
           and r["source_type"] == "calculated"]
    assert [r["calculation_method"] for r in sep] == [""]


def test_a_row_that_is_not_calculated_has_a_blank_method_even_beside_a_run(d1, client):
    # F1 has a July run and a July meter reading; the reading is not the run's output.
    _, _, rows = _export(client)
    meter = [r for r in rows if r["source_type"] == "meter_reading"]
    assert len(meter) == 6
    assert {r["calculation_method"] for r in meter} == {""}
    assert CalculationRun.objects.filter(parcel=d1["F1"], period="2025-07").count() == 1


# ---------------------------------------------------------------- (f) one query, not one per row
def test_the_export_reads_the_runs_in_one_query_however_many_rows(d1, client):
    _, header, _ = _export(client)  # warm-up request
    assert header[-1] == "calculation_method"
    with CaptureQueriesContext(connection) as small:
        client.get(reverse("accounting:ledger_export"))
    months = [(2024, 10), (2024, 11), (2024, 12)] + [(2025, m) for m in range(1, 7)] + [(2025, 10), (2025, 11), (2025, 12)]
    for year, month in months:  # twelve more calculated rows on F4, with no run behind them
        ld.ledger(d1["F4"], ld.dt.date(year, month, 1), "-1.0000", "calculated", "GW", "calculated test input")
    with CaptureQueriesContext(connection) as large:
        client.get(reverse("accounting:ledger_export"))
    assert len(large) == len(small)
    run_queries = [q for q in large.captured_queries if "accounting_calculationrun" in q["sql"]]
    assert len(run_queries) == 1


# ---------------------------------------------------------------- (g) export, import, export
def test_export_then_import_then_export_gives_the_same_file(d1, client, tmp_path):
    first, header, _ = _export(client)
    assert header[-1] == "calculation_method"
    path = tmp_path / "ledger_export.csv"
    path.write_bytes(first)

    out = io.StringIO()
    call_command("import_ledger_csv", str(path), "--dry-run", stdout=out)
    assert "Would create 0" in out.getvalue()

    ld.ParcelLedger.objects.all().delete()
    call_command("import_ledger_csv", str(path), stdout=io.StringIO())
    second, _, _ = _export(client)

    def lines(content):
        return sorted(content.decode("utf-8").splitlines())

    # Rows made on the same day come back in creation order, so compare the lines as a set.
    assert lines(second) == lines(first)
    assert any(DEFAULT in line for line in lines(second))


# ---------------------------------------------------------------- (h) the blank template
def test_the_blank_template_does_not_gain_the_column(client):
    response = client.get(reverse("accounting:csv_template"))
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    header = next(r for r in rows if "parcel_number" in r)
    assert header == IMPORT_COLUMNS
    assert "calculation_method" not in response.content.decode("utf-8")


# ---------------------------------------------------------------- (i) the run page
def test_the_calculation_page_prints_the_code_beside_the_method_name(d1, client):
    body = client.get(reverse("accounting:calculation_run_detail", args=[d1["F3"].pk, "2025-07"])).content.decode()
    assert "Methodology: Default Methodology, settings a582bd80c59b" in body


def test_a_second_plan_prints_its_own_name_and_code(d1, client):
    body = client.get(reverse("accounting:calculation_run_detail", args=[d1["F4"].pk, "2025-08"])).content.decode()
    assert "Methodology: Second Plan, settings 0123456789ab" in body


def test_the_short_page_for_a_metered_month_prints_the_code_too(d1, client):
    body = client.get(reverse("accounting:calculation_run_detail", args=[d1["F1"].pk, "2025-07"])).content.decode()
    assert "Methodology: Default Methodology, settings a582bd80c59b" in body
