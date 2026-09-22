# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 4 (D4): diversion volumes in bulk against a point of diversion.

Two fixtures, copied verbatim from
``~/Documents/Vadose/Products/openh2o/six-shapes-2026-09/datasets/shape-1-surface-diverter/``
(never read from disk here -- the harness and the real world stay apart):
``monthly-diversion-2024.csv`` (the state's Water Use Reported layout, one
right with three points, no ``APPL_POD`` column -- the whole-file point is
required) and ``ditch-tenders-book-2024.csv`` (the operator's book layout,
two headgates resolved by ``local_name``). Everything else here is a small
synthetic CSV built for one specific rule (the USE rule, the COMBINED row,
the water-year mapping, the within-file combine), named as such.

The two corrections from the main session that this file proves:

1. The state's MONTH column is the calendar month number (1 = January,
   10 = October); under water_year, MONTH 10-12 belong to the PRIOR
   calendar year. A file's own ``calendar_month`` column, when present, is
   trusted outright -- even when it disagrees with the computed rule.
2. Rows landing on the same (point, month, type) within one file are summed
   into one record ("N rows combined into one month"); dedup against the
   database is skip-and-count, never overwrite.
"""
import csv
import io
import json
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig
from surface import diversion_import
from surface.models import DiversionRecord
from tests.factories import PointOfDiversionFactory, WaterRightFactory

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# The two real fixtures, copied verbatim (PROVENANCE.md, shape-1 dataset).
# ---------------------------------------------------------------------------

STATE_CSV_TEXT = (
    "APPL_ID,WATER_RIGHT_ID,YEAR,MONTH,MONTH NAME,MONTH FORMATTED,DIVERSION_TYPE,AMOUNT,calendar_month\n"
    "A001885,283,2024,1,January,1/1/2024,DIRECT,0,2024-01\n"
    "A001885,283,2024,2,February,2/1/2024,DIRECT,0,2024-02\n"
    "A001885,283,2024,3,March,3/1/2024,DIRECT,33,2024-03\n"
    "A001885,283,2024,4,April,4/1/2024,DIRECT,51,2024-04\n"
    "A001885,283,2024,5,May,5/1/2024,DIRECT,156,2024-05\n"
    "A001885,283,2024,6,June,6/1/2024,DIRECT,393,2024-06\n"
    "A001885,283,2024,7,July,7/1/2024,DIRECT,490,2024-07\n"
    "A001885,283,2024,8,August,8/1/2024,DIRECT,473,2024-08\n"
    "A001885,283,2024,9,September,9/1/2024,DIRECT,449,2024-09\n"
    "A001885,283,2024,10,October,10/1/2024,DIRECT,0,2023-10\n"
    "A001885,283,2024,11,November,11/1/2024,DIRECT,0,2023-11\n"
    "A001885,283,2024,12,December,12/1/2024,DIRECT,0,2023-12\n"
)

BOOK_CSV_TEXT = (
    "date,run,headgate,turnout,order_no,start,stop,flow_cfs,miners_inches,hours,acre_feet,event\n"
    "2024-03-01,2 Run,Headgate No. 1,Turnout 14,2024-101,2024-03-01 06:00,2024-03-16 06:00,0.55,22,360,16.50,irrigation\n"
    "2024-03-16,4 Run,Headgate No. 2,Turnout 22,2024-102,2024-03-16 06:00,2024-04-01 06:00,0.52,21,384,16.50,irrigation\n"
    "2024-04-01,2 Run,Headgate No. 1,Turnout 14,2024-103,2024-04-01 06:00,2024-04-16 06:00,0.86,34,360,25.50,irrigation\n"
    "2024-04-16,4 Run,Headgate No. 2,Turnout 22,2024-104,2024-04-16 06:00,2024-05-01 06:00,0.86,34,360,25.50,irrigation\n"
    "2024-05-01,2 Run,Headgate No. 1,Turnout 14,2024-105,2024-05-01 06:00,2024-05-16 06:00,2.62,105,360,78.00,irrigation\n"
    "2024-05-16,4 Run,Headgate No. 2,Turnout 22,2024-106,2024-05-16 06:00,2024-06-01 06:00,2.46,98,384,78.00,irrigation\n"
    "2024-06-01,2 Run,Headgate No. 1,Turnout 14,2024-107,2024-06-01 06:00,2024-06-16 06:00,6.60,264,360,196.50,irrigation\n"
    "2024-06-16,4 Run,Headgate No. 2,Turnout 22,2024-108,2024-06-16 06:00,2024-07-01 06:00,6.60,264,360,196.50,irrigation\n"
    "2024-07-01,2 Run,Headgate No. 1,Turnout 14,2024-109,2024-07-01 06:00,2024-07-16 06:00,8.23,329,360,245.00,irrigation\n"
    "2024-07-16,4 Run,Headgate No. 2,Turnout 22,2024-110,2024-07-16 06:00,2024-08-01 06:00,7.72,309,384,245.00,irrigation\n"
    "2024-08-01,2 Run,Headgate No. 1,Turnout 14,2024-111,2024-08-01 06:00,2024-08-16 06:00,7.95,318,360,236.50,irrigation\n"
    "2024-08-16,4 Run,Headgate No. 2,Turnout 22,2024-112,2024-08-16 06:00,2024-09-01 06:00,7.45,298,384,236.50,irrigation\n"
    "2024-09-01,2 Run,Headgate No. 1,Turnout 14,2024-113,2024-09-01 06:00,2024-09-16 06:00,7.55,302,360,224.50,irrigation\n"
    "2024-09-16,4 Run,Headgate No. 2,Turnout 22,2024-114,2024-09-16 06:00,2024-10-01 06:00,7.55,302,360,224.50,irrigation\n"
)


def _with_appl_pod(csv_text, value):
    """Return csv_text with one extra APPL_POD column, filled with value.

    A synthetic variant of the real fixture (test 2), not a second fixture.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames) + ["APPL_POD"]
    rows = list(reader)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        row["APPL_POD"] = value
        writer.writerow(row)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shape1_points(db):
    """WaterRight A001885 with its three real points of diversion."""
    right = WaterRightFactory(right_id="A001885")
    p1 = PointOfDiversionFactory(water_right=right, name="A001885_01", status="active")
    p2 = PointOfDiversionFactory(water_right=right, name="A001885_02", status="active")
    p3 = PointOfDiversionFactory(water_right=right, name="A001885_03", status="active")
    return right, p1, p2, p3


@pytest.fixture
def book_points(db):
    """Two points the ditch tender's book names by local_name."""
    right = WaterRightFactory(right_id="STEVINSON-01")
    p1 = PointOfDiversionFactory(
        water_right=right, name="Headgate 1 POD", local_name="Headgate No. 1", status="active",
    )
    p2 = PointOfDiversionFactory(
        water_right=right, name="Headgate 2 POD", local_name="Headgate No. 2", status="active",
    )
    return p1, p2


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"diversionimportuser{n}")
    email = factory.Sequence(lambda n: f"diversionimportuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _import(columns, rows, **kwargs):
    return diversion_import.import_diversion_rows(columns, rows, **kwargs)


def _parse(text):
    return diversion_import.parse_csv(io.StringIO(text))


# ---------------------------------------------------------------------------
# 1. State layout, whole-file point
# ---------------------------------------------------------------------------


def test_state_layout_with_whole_file_point_creates_twelve_records(shape1_points):
    right, p1, p2, p3 = shape1_points
    columns, rows = _parse(STATE_CSV_TEXT)

    result = _import(columns, rows, whole_file_point=p1, dry_run=False)

    assert result["layout"] == "state"
    assert result["created"] == 12
    assert result["errors"] == []
    assert result["unresolved_rows"] == []

    records = list(DiversionRecord.objects.filter(point_of_diversion=p1))
    assert len(records) == 12
    non_zero = [r for r in records if r.volume_acre_feet > 0]
    zero = [r for r in records if r.volume_acre_feet == 0]
    assert len(non_zero) == 7
    assert len(zero) == 5
    total = sum((r.volume_acre_feet for r in records), Decimal("0"))
    assert total == Decimal("2045.0000")
    assert all(r.data_state == "provisional" for r in records)
    assert all(r.method == "" for r in records)


# ---------------------------------------------------------------------------
# 2. State layout, APPL_POD column present -- no whole-file point needed
# ---------------------------------------------------------------------------


def test_state_layout_with_appl_pod_column_resolves_without_whole_file_point(shape1_points):
    right, p1, p2, p3 = shape1_points
    text = _with_appl_pod(STATE_CSV_TEXT, "A001885_01")
    columns, rows = _parse(text)

    result = _import(columns, rows, whole_file_point=None, dry_run=False)

    assert result["created"] == 12
    assert result["unresolved_rows"] == []
    assert DiversionRecord.objects.filter(point_of_diversion=p1).count() == 12
    assert DiversionRecord.objects.exclude(point_of_diversion=p1).count() == 0


# ---------------------------------------------------------------------------
# 3. State layout, no APPL_POD, no whole-file point, right has 3 points
# ---------------------------------------------------------------------------


def test_state_layout_without_point_or_whole_file_point_is_unresolved(shape1_points):
    right, p1, p2, p3 = shape1_points
    columns, rows = _parse(STATE_CSV_TEXT)

    result = _import(columns, rows, whole_file_point=None, dry_run=False)

    assert result["created"] == 0
    assert len(result["unresolved_rows"]) == 12
    assert DiversionRecord.objects.count() == 0
    assert "3 points" in result["unresolved_rows"][0]["reason"]


# ---------------------------------------------------------------------------
# 4. Book layout, two headgates by local_name
# ---------------------------------------------------------------------------


def test_book_layout_two_headgates_creates_fourteen_records(book_points):
    p1, p2 = book_points
    columns, rows = _parse(BOOK_CSV_TEXT)

    result = _import(columns, rows, dry_run=False)

    assert result["layout"] == "book"
    assert result["created"] == 14
    assert result["errors"] == []
    assert result["unresolved_rows"] == []

    records = DiversionRecord.objects.filter(point_of_diversion__in=[p1, p2])
    assert records.count() == 14
    total = sum((r.volume_acre_feet for r in records), Decimal("0"))
    assert total == Decimal("2045.0000")


# ---------------------------------------------------------------------------
# 5. A book row with flow_cfs and hours only
# ---------------------------------------------------------------------------


def test_book_row_with_flow_cfs_and_hours_converts_and_names_factor(book_points):
    p1, p2 = book_points
    text = (
        "date,headgate,flow_cfs,hours\n"
        "2024-03-01,Headgate No. 1,0.55,360\n"
    )
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    assert len(result["conversions"]) == 1
    conv = result["conversions"][0]
    assert "1.9835" in conv["factor"]
    assert "0.55 cfs" in conv["from"]

    record = DiversionRecord.objects.get()
    expected = (Decimal("0.55") * Decimal("360") / Decimal("24")) * Decimal("1.9835")
    assert record.volume_acre_feet == expected.quantize(Decimal("0.0001"))


# ---------------------------------------------------------------------------
# 6. Re-import creates nothing and counts the skips
# ---------------------------------------------------------------------------


def test_reimport_creates_nothing_and_counts_skips(shape1_points):
    right, p1, p2, p3 = shape1_points
    columns, rows = _parse(STATE_CSV_TEXT)

    first = _import(columns, rows, whole_file_point=p1, dry_run=False)
    assert first["created"] == 12

    columns2, rows2 = _parse(STATE_CSV_TEXT)
    second = _import(columns2, rows2, whole_file_point=p1, dry_run=False)

    assert second["created"] == 0
    assert second["skipped_duplicates"] == 12
    assert DiversionRecord.objects.count() == 12


# ---------------------------------------------------------------------------
# 7-9. USE rows under each of the three rules
# ---------------------------------------------------------------------------


def _use_rule_fixture():
    right = WaterRightFactory(right_id="A100001")
    point = PointOfDiversionFactory(water_right=right, status="active")
    text = (
        "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT,calendar_month\n"
        "A100001,2024,6,DIRECT,100,2024-06\n"
        "A100001,2024,6,USE,130,2024-06\n"
    )
    return point, text


def test_use_rule_drop_drops_and_counts(db):
    point, text = _use_rule_fixture()
    SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="drop")
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    assert result["use_rows_dropped"] == 1
    record = DiversionRecord.objects.get()
    assert record.volume_acre_feet == Decimal("100.0000")
    assert record.returned_af == Decimal("0.0000")


def test_use_rule_returned_computes_returned_af(db):
    point, text = _use_rule_fixture()
    SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="returned")
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    record = DiversionRecord.objects.get()
    assert record.volume_acre_feet == Decimal("100.0000")
    assert record.returned_af == Decimal("30.0000")


def test_use_rule_as_direct_merges_into_direct(db):
    point, text = _use_rule_fixture()
    SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="as_direct")
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    record = DiversionRecord.objects.get()
    assert record.volume_acre_feet == Decimal("230.0000")
    assert record.returned_af == Decimal("0.0000")
    assert any(c["row_count"] == 2 for c in result["combined_rows"])


# ---------------------------------------------------------------------------
# 7a-7d. 146-03 Task 6: the USE-row question moves to the import screen.
# ---------------------------------------------------------------------------


def test_explicit_use_rule_overrides_site_config_default(db):
    """An explicit ``use_rule`` kwarg (the import screen's own question)

    wins over the deployment's remembered SiteConfig default.
    """
    point, text = _use_rule_fixture()
    SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="drop")
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False, use_rule="as_direct")

    assert result["created"] == 1
    record = DiversionRecord.objects.get()
    assert record.volume_acre_feet == Decimal("230.0000")
    assert result["settings"]["diversion_use_type_rule"] == "as_direct"


def test_use_rows_present_counts_use_rows_in_the_file(db):
    point, text = _use_rule_fixture()
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=True)

    assert result["use_rows_present"] == 1


def test_use_rows_present_is_zero_for_a_file_with_no_use_rows(db):
    right = WaterRightFactory(right_id="A100005")
    PointOfDiversionFactory(water_right=right, status="active")
    text = "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT\nA100005,2024,6,DIRECT,50\n"
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=True)

    assert result["use_rows_present"] == 0


def test_preview_shows_use_question_when_file_has_use_rows(auth_client, db):
    point, text = _use_rule_fixture()
    upload = SimpleUploadedFile("use-rows.csv", text.encode(), content_type="text/csv")

    resp = auth_client.post(reverse("surface:diversion_import_preview"), {"file": upload})

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Some rows in this file are typed USE" in body


def test_preview_hides_use_question_for_the_direct_only_shape1_fixture(auth_client, shape1_points):
    right, p1, p2, p3 = shape1_points
    upload = SimpleUploadedFile(
        "monthly-diversion-2024.csv", STATE_CSV_TEXT.encode(), content_type="text/csv",
    )

    resp = auth_client.post(reverse("surface:diversion_import_preview"), {"file": upload})

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Some rows in this file are typed USE" not in body


def test_commit_with_a_different_use_rule_saves_it_back_to_site_config(auth_client, db):
    point, text = _use_rule_fixture()
    config = SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="drop")
    columns, rows = _parse(text)

    resp = auth_client.post(reverse("surface:diversion_import_commit"), {
        "rows_json": json.dumps(rows),
        "method": "",
        "data_state": "provisional",
        "use_rule": "as_direct",
    })

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Saved as this deployment's answer for next time." in body
    config.refresh_from_db()
    assert config.diversion_use_type_rule == "as_direct"


def test_commit_with_the_same_use_rule_as_stored_does_not_say_it_saved(auth_client, db):
    point, text = _use_rule_fixture()
    config = SiteConfig.objects.create(agency_name="Test Agency", diversion_use_type_rule="as_direct")
    columns, rows = _parse(text)

    resp = auth_client.post(reverse("surface:diversion_import_commit"), {
        "rows_json": json.dumps(rows),
        "method": "",
        "data_state": "provisional",
        "use_rule": "as_direct",
    })

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Saved as this deployment's answer for next time." not in body
    config.refresh_from_db()
    assert config.diversion_use_type_rule == "as_direct"


# ---------------------------------------------------------------------------
# 10. A COMBINED row errors, naming the year
# ---------------------------------------------------------------------------


def test_combined_type_errors_naming_the_year(db):
    text = "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT\nA100002,2013,3,COMBINED,50\n"
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert "2013" in result["errors"][0]["message"]
    assert "COMBINED" in result["errors"][0]["message"]


# ---------------------------------------------------------------------------
# 11. Water-year mapping: MONTH 10 of report year 2024 -> 2023-10
# ---------------------------------------------------------------------------


def test_water_year_mapping_puts_month_ten_in_prior_calendar_year(db):
    right = WaterRightFactory(right_id="A100003")
    PointOfDiversionFactory(water_right=right, status="active")
    SiteConfig.objects.create(agency_name="Test Agency", diversion_report_year_rule="water_year")
    text = "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT\nA100003,2024,10,DIRECT,5\n"
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    record = DiversionRecord.objects.get()
    assert record.month == date(2023, 10, 1)


# ---------------------------------------------------------------------------
# 12. A file with calendar_month is trusted, even over the computed rule
# ---------------------------------------------------------------------------


def test_calendar_month_column_is_trusted_over_the_computed_rule(db):
    right = WaterRightFactory(right_id="A100004")
    PointOfDiversionFactory(water_right=right, status="active")
    SiteConfig.objects.create(agency_name="Test Agency", diversion_report_year_rule="water_year")
    # water_year would compute 2023-10 for MONTH 10 of report year 2024;
    # calendar_month says otherwise, and it must win.
    text = (
        "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT,calendar_month\n"
        "A100004,2024,10,DIRECT,7,2099-01\n"
    )
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    record = DiversionRecord.objects.get()
    assert record.month == date(2099, 1, 1)
    assert any("calendar_month column trusted" in n["note"] for n in result["notes"])


# ---------------------------------------------------------------------------
# 13. Within-file combine: two rows, same point/month/type -> one record
# ---------------------------------------------------------------------------


def test_rows_combined_into_one_month(book_points):
    p1, p2 = book_points
    text = (
        "date,headgate,acre_feet\n"
        "2024-03-01,Headgate No. 1,10.00\n"
        "2024-03-15,Headgate No. 1,5.00\n"
    )
    columns, rows = _parse(text)

    result = _import(columns, rows, dry_run=False)

    assert result["created"] == 1
    assert len(result["combined_rows"]) == 1
    combined = result["combined_rows"][0]
    assert combined["row_count"] == 2
    record = DiversionRecord.objects.get()
    assert record.volume_acre_feet == Decimal("15.0000")


# ---------------------------------------------------------------------------
# Layout recognition
# ---------------------------------------------------------------------------


def test_unrecognised_layout_raises_naming_headers():
    with pytest.raises(ImportError) as exc_info:
        diversion_import.recognise_layout(["foo", "bar"])
    assert "foo" in str(exc_info.value)
    assert "bar" in str(exc_info.value)


# ---------------------------------------------------------------------------
# The screens: upload page, preview, commit
# ---------------------------------------------------------------------------


def test_diversion_import_upload_page_reachable(auth_client):
    resp = auth_client.get(reverse("surface:diversion_import"))
    assert resp.status_code == 200


def test_diversion_import_preview_shows_mapping_and_totals(auth_client, shape1_points):
    right, p1, p2, p3 = shape1_points
    upload = SimpleUploadedFile(
        "monthly-diversion-2024.csv", STATE_CSV_TEXT.encode(), content_type="text/csv",
    )
    resp = auth_client.post(reverse("surface:diversion_import_preview"), {"file": upload})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "state layout" in body
    assert "rows_json" in body


def test_diversion_import_commit_creates_records_through_the_view(auth_client, shape1_points):
    right, p1, p2, p3 = shape1_points
    columns, rows = _parse(STATE_CSV_TEXT)

    resp = auth_client.post(reverse("surface:diversion_import_commit"), {
        "rows_json": json.dumps(rows),
        "point": str(p1.pk),
        "method": "",
        "data_state": "provisional",
    })

    assert resp.status_code == 200
    assert DiversionRecord.objects.filter(point_of_diversion=p1).count() == 12


# ---------------------------------------------------------------------------
# The management command
# ---------------------------------------------------------------------------


def test_management_command_dry_run_writes_nothing(tmp_path, shape1_points):
    right, p1, p2, p3 = shape1_points
    path = tmp_path / "state.csv"
    path.write_text(STATE_CSV_TEXT)
    out = io.StringIO()

    call_command(
        "import_diversion_records", str(path),
        "--point", str(p1.pk), "--dry-run", stdout=out,
    )

    assert "12" in out.getvalue()
    assert DiversionRecord.objects.count() == 0


def test_management_command_creates_records(tmp_path, shape1_points):
    right, p1, p2, p3 = shape1_points
    path = tmp_path / "state.csv"
    path.write_text(STATE_CSV_TEXT)
    out = io.StringIO()

    call_command("import_diversion_records", str(path), "--point", str(p1.pk), stdout=out)

    assert DiversionRecord.objects.filter(point_of_diversion=p1).count() == 12


def test_management_command_file_not_found_names_the_container_path(db):
    with pytest.raises(CommandError) as exc_info:
        call_command("import_diversion_records", "/no/such/file.csv")
    message = str(exc_info.value)
    assert "web:/tmp/" in message
