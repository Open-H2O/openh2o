# SPDX-License-Identifier: AGPL-3.0-or-later
"""The surface water imports' messages and the code changes Brent approved
with them (150.1-02 screen 18, messages A to E, 2026-10-14 17:51 to 18:47).

Each test pins a behaviour the old code got wrong, not only a wording:
a 25.5 MB file read "25 MB" against a 25 MB cap; a blank unit was read as
acre-feet; dates written M/D/YYYY were refused; a book with no point column
was refused although the preview offers a whole-file point; a water right
not on file blocked that point; the state's "Combined (Direct + Storage)"
missed the combined check; only "Appropriative" water right types imported;
a face value in another unit refused the whole right.
"""
import io
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from core.forms import DeliverySettingsForm
from core.models import SiteConfig
from surface import diversion_import, importer
from surface.models import WaterRight, WaterRightType
from tests.factories import PointOfDiversionFactory, WaterRightFactory


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"surfacemsguser{n}")
    email = factory.Sequence(lambda n: f"surfacemsguser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture
def one_point(db):
    right = WaterRightFactory(right_id="BOOK-ONE")
    return PointOfDiversionFactory(
        water_right=right, name="Headgate 1 POD", local_name="Headgate No. 1",
        status="active",
    )


def _parse(text):
    return diversion_import.parse_csv(io.StringIO(text))


def _build(text, **kwargs):
    columns, rows = _parse(text)
    layout = diversion_import.recognise_layout(columns)
    return diversion_import.import_diversion_rows(
        columns, rows, layout=layout, dry_run=True, **kwargs
    )


# --- message A: whole-file messages -----------------------------------------


def test_too_large_rounds_the_size_up():
    cap = 25 * 1024 * 1024
    assert importer.too_large_message(int(25.5 * 1024 * 1024), cap) == (
        "This file is 26 MB. OpenH2O imports files of up to 25 MB."
    )


def test_rights_import_tells_an_empty_file_from_a_header_only_file():
    with pytest.raises(ImportError, match="no column names on its first line"):
        importer.parse_upload(io.BytesIO(b""), "r.csv")
    with pytest.raises(ImportError, match="column names but no rows below them"):
        importer.parse_upload(io.BytesIO(b"APPLICATION_NUMBER\n"), "r.csv")


def test_diversion_row_cap_says_split_by_point_or_year():
    assert diversion_import.row_cap_message(2001) == (
        "This file has 2,001 rows, and OpenH2O imports up to 2,000 rows from one "
        "file. Split the file by point or by year and import each part."
    )


def test_a_book_with_no_point_column_takes_the_whole_file_point(one_point):
    text = "date,acre_feet\n2025-01-01,3\n"
    columns, _rows = _parse(text)
    assert diversion_import.recognise_layout(columns) == "book"
    result = _build(text, whole_file_point=one_point)
    assert result["created"] == 1 and not result["errors"]


def test_unrecognised_columns_on_the_page_point_to_the_tables(auth_client):
    upload = SimpleUploadedFile("x.csv", b"foo,bar\n1,2\n", content_type="text/csv")
    body = auth_client.post(
        reverse("surface:diversion_import_preview"), {"file": upload}
    ).content.decode()
    assert (
        "OpenH2O does not recognize the columns in this file: foo, bar. "
        "The tables below list the columns OpenH2O imports."
    ) in body


# --- message B: Water Use Reported rows ---------------------------------------


def test_season_with_no_starting_month_is_refused_on_delivery_settings(db):
    config = SiteConfig.objects.create(agency_name="OpenH2O")
    form = DeliverySettingsForm(
        data={
            "recovery_horizon": "carry_forward",
            "efficiency_percent": 75,
            "over_delivery_treatment": "not_credited",
            "diversion_report_year_rule": "season",
            "season_start_month": "",
        },
        instance=config,
    )
    assert not form.is_valid()
    assert form.errors["season_start_month"] == ["Enter the season's starting month."]


def test_the_year_sentence_names_how_a_season_is_read(db):
    config = SiteConfig(diversion_report_year_rule="season", season_start_month=4)
    assert diversion_import.rule_sentence(config) == (
        "OpenH2O reads YEAR as a season starting in April and ending the next "
        "March, so MONTH 4 through 12 fall in the calendar year before YEAR."
    )


def test_the_year_sentence_is_not_shown_over_a_book(auth_client, one_point):
    upload = SimpleUploadedFile(
        "b.csv", b"local_name,date,acre_feet\nHeadgate No. 1,2025-01-01,3\n",
        content_type="text/csv",
    )
    body = auth_client.post(
        reverse("surface:diversion_import_preview"), {"file": upload}
    ).content.decode()
    assert "1 row from a book of deliveries" in body
    assert "OpenH2O reads YEAR" not in body


def test_a_type_is_echoed_as_the_file_writes_it(db):
    result = _build("APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT\nA1,2024,1,Divert,5\n")
    assert result["errors"][0]["message"] == (
        "OpenH2O does not recognize the diversion type 'Divert'. "
        "Use DIRECT, STORAGE or USE."
    )


# --- message C: book rows -----------------------------------------------------


def test_a_book_date_written_m_d_yyyy_is_read(one_point):
    result = _build("local_name,date,acre_feet\nHeadgate No. 1,3/4/2025,2\n")
    assert not result["errors"]
    assert result["created"] == 1


def test_a_blank_unit_is_refused_not_read_as_acre_feet(one_point):
    result = _build("local_name,date,volume,unit\nHeadgate No. 1,2025-03-01,1000,\n")
    assert result["created"] == 0
    assert result["errors"][0]["message"] == (
        "The unit is blank. Enter af, gallons, ccf, mg or cfs_hours."
    )


@pytest.mark.parametrize("unit", ["acre-ft", "ac-ft", "acre feet"])
def test_common_acre_foot_spellings_are_acre_feet(one_point, unit):
    result = _build(f"local_name,date,volume,unit\nHeadgate No. 1,2025-03-01,12,{unit}\n")
    assert not result["errors"]
    assert result["total_af"] == Decimal("12.0000")


def test_the_af_column_is_named_as_written(one_point):
    result = _build("local_name,date,af\nHeadgate No. 1,2025-03-01,2 AF\n")
    assert result["errors"][0]["message"] == "The af value '2 AF' is not a number."


def test_flow_and_hours_are_checked_apart(one_point):
    result = _build("local_name,date,flow_cfs,hours\nHeadgate No. 1,2025-03-01,2.5,ten\n")
    assert result["errors"][0]["message"] == "The hours value 'ten' is not a number."


# --- message D: unresolved rows -----------------------------------------------


def test_a_right_not_on_file_falls_through_to_the_whole_file_point(one_point):
    text = "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT\nNOT-ON-FILE,2024,1,DIRECT,5\n"
    unresolved = _build(text)["unresolved_rows"]
    assert unresolved[0]["reason"] == (
        "No water right on file has the application number NOT-ON-FILE. Import "
        "the water right, or choose one point of diversion for the whole file on the preview."
    )
    result = _build(text, whole_file_point=one_point)
    assert not result["unresolved_rows"] and result["created"] == 1


# --- message E: water rights rows ---------------------------------------------


MAPPING = {
    "right_id": "APPLICATION_NUMBER",
    "right_type_name": "WATER_RIGHT_TYPE",
    "holder_name": "PRIMARY_OWNER_NAME",
    "face_value_acre_feet": "FACE_VALUE_AMOUNT",
    "face_value_units": "FACE_VALUE_UNITS",
}


def _right_row(number, rtype="Appropriative", units="Acre-feet per Year"):
    return {
        "APPLICATION_NUMBER": number, "WATER_RIGHT_TYPE": rtype,
        "PRIMARY_OWNER_NAME": "Holder", "FACE_VALUE_AMOUNT": "12",
        "FACE_VALUE_UNITS": units,
    }


def test_a_repeat_in_one_file_is_named_as_such(db):
    results = importer.validate_rows(
        [_right_row("S1"), _right_row("S1")], MAPPING, set()
    )
    assert results[1]["errors"] == ["Water right S1 appears earlier in this file."]


def test_a_face_value_in_another_unit_imports_the_right_without_it(db):
    results = importer.validate_rows(
        [_right_row("S2", rtype="Statement of Div and Use", units="Cubic Feet per Second")],
        MAPPING, set(),
    )
    assert results[0]["errors"] == []
    assert importer.commit_rows(results) == 1
    right = WaterRight.objects.get(right_id="S2")
    assert right.face_value_acre_feet is None
    assert right.right_type.name == "Statement of Div and Use"
    assert results[0]["warnings"] == [
        "OpenH2O imported this right without its face value, which the file gives "
        "in Cubic Feet per Second. OpenH2O records a face value in acre-feet per year."
    ]
    assert WaterRightType.objects.filter(name="Statement of Div and Use").count() == 1


# --- message F: the leftovers -------------------------------------------------


def test_the_rights_result_says_records_and_counts_the_notes(db):
    from django.template.loader import render_to_string

    html = render_to_string(
        "surface/partials/_right_import_result.html",
        {"created": 3, "skipped": [], "total": 3,
         "noted": [{"index": 0, "warnings": ["A note."]}]},
    )
    text = " ".join(html.split())
    assert "OpenH2O created 3 water right records. 1 of them has a note below." in text
    assert "Every row was valid." not in text


def test_the_import_preview_labels_the_data_status(auth_client, one_point):
    upload = SimpleUploadedFile(
        "b.csv", b"local_name,date,acre_feet\nHeadgate No. 1,2025-01-01,3\n",
        content_type="text/csv",
    )
    body = auth_client.post(
        reverse("surface:diversion_import_preview"), {"file": upload}
    ).content.decode()
    assert ">Data status</label>" in body
    assert "Data state" not in body


# --- message G: the two import pages, read whole ------------------------------


def test_the_rights_page_describes_what_the_import_now_does(auth_client):
    body = " ".join(auth_client.get(reverse("surface:water_right_import")).content.decode().split())
    assert "skips the row" not in body
    assert "OpenH2O adds any right type not yet on file, spelled as the file spells it." in body
    assert (
        "OpenH2O keeps the face value only when this column reads Acre-feet per Year. "
        "Otherwise OpenH2O imports the right without its face value."
    ) in body


def test_the_diversion_page_says_what_it_imports(auth_client):
    body = " ".join(auth_client.get(reverse("surface:diversion_import")).content.decode().split())
    assert (
        "This page imports monthly diversion volumes from a CSV file: California's "
        "Water Use Reported export or your own book of deliveries."
    ) in body.replace("&#x27;", "'").replace("&#39;", "'")
    assert "OpenH2O saves nothing until you press Import on the preview." in body


def test_the_rights_matching_step_says_records_not_rights(auth_client):
    upload = SimpleUploadedFile(
        "r.csv", b"APPLICATION_NUMBER,WATER_RIGHT_TYPE,PRIMARY_OWNER_NAME\nA1,Riparian,H\n",
        content_type="text/csv",
    )
    body = " ".join(auth_client.post(
        reverse("surface:water_right_import_preview"), {"file": upload}
    ).content.decode().split())
    assert "Match the file&#x27;s columns" in body or "Match the file's columns" in body
    assert (
        "OpenH2O found <strong>1</strong> row and <strong>3</strong> columns, and matched "
        "each field below to an eWRIMS column. Change any match that is wrong, then press Create."
    ) in body
    assert "create the rights" not in body
