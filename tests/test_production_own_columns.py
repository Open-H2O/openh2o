# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.3 (ISS-375): a production log with its own column headings.

The command takes ``--column`` (one name per type of water) and
``--operator-unit``; the screen's preview asks which column holds the month, what
each other column holds, and the unit. Both doors save the same rows.

Every file here is invented test data: PWSID XX0000001, a twelve-month log for 2024
with made-up gallons. Nothing is read from disk but the temporary file each test
writes. The wording asserted is the Fixed column of rows 63 to 83 and 101 of
``.planning/phases/152-proven-by-strangers/152-03.3-ROWS.md``.
"""
import io
from html import unescape

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from drinking.models import SystemProduction, WaterSystem
from tests.import_flow import import_and_read, token_of

pytestmark = pytest.mark.django_db

# Invented test data: twelve months of one groundwater figure under a heading the
# importer has never seen.
FIGURES = [1000000 + 10000 * n for n in range(12)]
OWN_HEADINGS_CSV = "Month,All wells (gallons)\n" + "".join(
    f"2024-{n + 1:02d},{figure}\n" for n, figure in enumerate(FIGURES)
)
COLUMN_ARGS = ["--column", "month=Month", "--column", "groundwater=All wells (gallons)"]

# Invented test data: a Section 5 log, one month, no unit option given.
SECTION_5_CSV = (
    "Date/Month,Water Produced from Groundwater (Wells),Water Produced from Surface Water,"
    "Finished Water Purchased or Received from another PWS,Total Amount of Potable Water,"
    "Water Sold to Another PWS,Non-potable (exclude recycled),Recycled\n"
    "January,4000000,0,0,4000000,0,0,0\n"
)
# Invented test data: an eAR export, one row.
EAR_CSV = (
    "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,"
    "Quantity as in Units Reported\n"
    "XX0000001,2024,January,1/1/2024,GW,G,4000000\n"
)

ROW_67 = "12 rows from a log with its own column headings"
ROW_68 = (
    "OpenH2O does not know these column headings. Choose what each column holds. "
    "Then press Update preview."
)
ROW_69 = "Which column holds the month"
ROW_73 = "Choose the unit of the figures in this file."
ROW_74 = "Choose the column that holds the month."
ROW_75 = "Choose the type of water in at least one column."
ROW_76 = (
    "Well A and Well B are both set to Groundwater. OpenH2O keeps one groundwater "
    "figure a month. Add the two columns together in the file first."
)
ROW_77_CELL = "OpenH2O cannot read a month from Month 'Smarch 2024'."
ROW_81_HEAD = "OpenH2O does not know the columns in this file: "
ROW_81_TAIL = (
    "Name the month column and at least one other column with --column."
)
ROW_82 = "A log with its own column headings needs --operator-unit."
ROW_83 = "The month column does not give a year. Pass --operator-year."
ROW_101 = "OpenH2O does not recognize the unit 'litres'. Use G, MG, AF or CCF."

UPLOAD_PAGE = {
    63: (
        "This page imports monthly production figures from a CSV file. It reads "
        "California's Electronic Annual Report (eAR) export or a monthly log kept on "
        "Section 5 of the eAR template. For a log with its own column headings, you "
        "choose on the preview what each column holds."
    ),
    64: "A log with its own column headings",
    65: (
        "On the preview, choose the column that holds the month. For each other "
        "column, choose the type of water it holds. Then choose one unit for the "
        "whole file. This kind of log has no default unit."
    ),
    66: (
        "The import takes one column for each type of water. When the log has a "
        "column for each well, add the wells together into one column first."
    ),
}


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"ownhead{n}")
    email = factory.Sequence(lambda n: f"ownhead{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def system():
    WaterSystem.objects.all().delete()
    # Invented test data: a made-up system.
    return WaterSystem.objects.create(
        pwsid="XX0000001",
        name="INVENTED TEST WATER SYSTEM",
        activity_status="A",
        pws_type="CWS",
        state_classification="C",
        primary_source_code="GW",
    )


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


def _flat(text):
    return " ".join(unescape(text).split())


def _file(tmp_path, text, name="log.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _run(*args):
    out, err = io.StringIO(), io.StringIO()
    call_command("import_production", *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def _fields():
    """Every saved production row, as the fields the two doors must agree on."""
    return sorted(
        (
            row.year,
            row.month,
            row.type_code,
            row.facility_id,
            row.provenance,
            row.unit_as_reported,
            str(row.volume_as_reported),
        )
        for row in SystemProduction.objects.all()
    )


def _upload(client, text=OWN_HEADINGS_CSV):
    return client.post(
        reverse("drinking:production_import_preview"),
        {"file": SimpleUploadedFile("log.csv", text.encode(), content_type="text/csv")},
    )


def _step(client, token, **fields):
    return client.post(
        reverse("drinking:production_import_preview"), {"token": token, **fields}
    )


COMPLETE_STEP = {
    "month_column": "Month",
    "column_type:All wells (gallons)": "GW",
    "operator_unit": "G",
    "operator_year": "",
}


# -- the command: a log with its own headings ------------------------------------


def test_command_saves_twelve_rows_for_a_log_with_its_own_headings(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), "--pwsid", "XX0000001", *COLUMN_ARGS,
         "--operator-unit", "G")
    assert SystemProduction.objects.count() == 12


def test_command_saves_groundwater_with_no_facility(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "G")
    rows = SystemProduction.objects.all()
    assert {row.type_code for row in rows} == {"GW"}
    assert {row.facility_id for row in rows} == {None}


def test_command_records_the_log_as_operator_log_in_the_unit_given(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "G")
    rows = SystemProduction.objects.all()
    assert {row.provenance for row in rows} == {"operator_log"}
    assert {row.unit_as_reported for row in rows} == {"G"}


def test_command_keeps_the_figure_of_each_month_as_the_file_gives_it(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "G")
    saved = {
        (row.year, row.month): int(row.volume_as_reported)
        for row in SystemProduction.objects.all()
    }
    assert saved == {(2024, n + 1): figure for n, figure in enumerate(FIGURES)}


def test_command_dry_run_saves_nothing_for_a_log_with_its_own_headings(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "G",
         "--dry-run")
    assert SystemProduction.objects.count() == 0


@pytest.mark.parametrize(
    "name,type_code",
    [
        ("groundwater", "GW"),
        ("surface_water", "SW"),
        ("purchased", "PU"),
        ("sold", "SO"),
        ("non_potable", "NP"),
        ("recycled", "RC"),
        ("non_potable_sold", "NS"),
    ],
)
def test_each_column_name_maps_to_its_type_of_water(tmp_path, system, name, type_code):
    path = _file(tmp_path, "Month,Figure\n2024-01,500\n")
    _run(path, "--column", "month=Month", "--column", f"{name}=Figure",
         "--operator-unit", "G")
    assert [row.type_code for row in SystemProduction.objects.all()] == [type_code]


# -- the command: month cells ----------------------------------------------------


@pytest.mark.parametrize(
    "cells",
    [
        ["1/2024", "2/2024"],
        ["January 2024", "February 2024"],
        ["2024-01", "2024-02"],
    ],
    ids=["m-yyyy", "month-name-and-year", "yyyy-mm"],
)
def test_command_reads_each_month_cell_form(tmp_path, system, cells):
    path = _file(tmp_path, f"Month,Figure\n{cells[0]},100\n{cells[1]},200\n")
    _run(path, "--column", "month=Month", "--column", "groundwater=Figure",
         "--operator-unit", "G")
    saved = sorted((row.year, row.month) for row in SystemProduction.objects.all())
    assert saved == [(2024, 1), (2024, 2)]


def test_command_reads_month_names_with_no_year_when_given_the_year(tmp_path, system):
    path = _file(tmp_path, "Month,Figure\nJanuary,100\nFebruary,200\n")
    _run(path, "--column", "month=Month", "--column", "groundwater=Figure",
         "--operator-unit", "G", "--operator-year", "2024")
    saved = sorted((row.year, row.month) for row in SystemProduction.objects.all())
    assert saved == [(2024, 1), (2024, 2)]


def test_command_refuses_month_names_with_no_year_and_no_operator_year(tmp_path, system):
    path = _file(tmp_path, "Month,Figure\nJanuary,100\n")
    with pytest.raises(CommandError) as raised:
        _run(path, "--column", "month=Month", "--column", "groundwater=Figure",
             "--operator-unit", "G")
    assert str(raised.value) == ROW_83
    assert SystemProduction.objects.count() == 0


def test_command_reports_a_month_it_cannot_read_and_saves_nothing_for_that_row(
    tmp_path, system
):
    path = _file(tmp_path, "Month,Figure\n2024-01,100\nSmarch 2024,200\n")
    output = _run(path, "--column", "month=Month", "--column", "groundwater=Figure",
                  "--operator-unit", "G")
    assert ROW_77_CELL in output
    assert [(row.year, row.month) for row in SystemProduction.objects.all()] == [(2024, 1)]


# -- the command: refusals -------------------------------------------------------


def test_command_refuses_column_without_operator_unit(tmp_path, system):
    with pytest.raises(CommandError) as raised:
        _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS)
    assert str(raised.value) == ROW_82
    assert SystemProduction.objects.count() == 0


def test_command_refuses_unknown_headings_with_no_column(tmp_path, system):
    with pytest.raises(CommandError) as raised:
        _run(_file(tmp_path, OWN_HEADINGS_CSV), "--operator-unit", "G")
    message = str(raised.value)
    assert message == f"{ROW_81_HEAD}Month, All wells (gallons). {ROW_81_TAIL}"
    assert SystemProduction.objects.count() == 0


def test_command_reads_a_lower_case_operator_unit_as_g(tmp_path, system):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "g")
    assert {row.unit_as_reported for row in SystemProduction.objects.all()} == {"G"}
    assert SystemProduction.objects.count() == 12


def test_command_refuses_a_unit_it_does_not_recognize_in_operator_unit(tmp_path, system):
    with pytest.raises(CommandError) as raised:
        _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "litres")
    assert str(raised.value) == ROW_101
    assert SystemProduction.objects.count() == 0


def test_command_refuses_a_unit_it_does_not_recognize_in_unit_for_blank(tmp_path, system):
    with pytest.raises(CommandError) as raised:
        _run(_file(tmp_path, EAR_CSV), "--unit-for-blank", "litres")
    assert str(raised.value) == ROW_101
    assert SystemProduction.objects.count() == 0


# -- regression guards (these pass before the feature is built) ------------------


def test_guard_a_section_5_log_with_no_operator_unit_still_saves_in_gallons(
    tmp_path, system
):
    _run(_file(tmp_path, SECTION_5_CSV), "--operator-year", "2024")
    rows = SystemProduction.objects.all()
    assert {row.unit_as_reported for row in rows} == {"G"}
    assert ("GW", 4000000) in {
        (row.type_code, int(row.volume_as_reported)) for row in rows
    }


def test_guard_the_ear_export_still_imports_as_before(tmp_path, system):
    _run(_file(tmp_path, EAR_CSV))
    rows = SystemProduction.objects.all()
    assert [(row.year, row.month, row.type_code, row.unit_as_reported)
            for row in rows] == [(2024, 1, "GW", "G")]


# -- the screen: upload page -----------------------------------------------------


@pytest.mark.parametrize("row", sorted(UPLOAD_PAGE))
def test_upload_page_shows_its_new_sentence(client_in, system, row):
    page = client_in.get(reverse("drinking:production_import"))
    assert UPLOAD_PAGE[row] in _flat(page.content.decode()), f"row {row}"


# -- the screen: the preview step ------------------------------------------------


def test_preview_of_a_log_with_its_own_headings_says_row_67(client_in, system):
    body = _flat(_upload(client_in).content.decode())
    assert ROW_67 in body


def test_preview_of_a_log_with_its_own_headings_says_row_68(client_in, system):
    body = _flat(_upload(client_in).content.decode())
    assert ROW_68 in body


def test_preview_labels_the_month_column_select(client_in, system):
    body = _flat(_upload(client_in).content.decode())
    assert ROW_69 in body


def test_preview_unit_select_starts_at_not_chosen_with_nothing_selected(client_in, system):
    html = unescape(_upload(client_in).content.decode())
    import re

    select = re.search(
        r'<select[^>]*name="operator_unit"[^>]*>(.*?)</select>', html, re.S
    )
    assert select is not None, "the preview has no operator_unit select"
    options = re.findall(r"<option([^>]*)>(.*?)</option>", select.group(1), re.S)
    first_attrs, first_label = options[0]
    assert 'value=""' in first_attrs
    assert first_label.strip() == "Not chosen"
    assert all("selected" not in attrs for attrs, _label in options)


def test_preview_offers_not_imported_and_every_type_for_the_other_column(client_in, system):
    html = unescape(_upload(client_in).content.decode())
    import re

    select = re.search(
        r'<select[^>]*name="column_type:All wells \(gallons\)"[^>]*>(.*?)</select>',
        html, re.S,
    )
    assert select is not None, "the preview has no select for the other column"
    labels = [
        _flat(label)
        for _attrs, label in re.findall(r"<option([^>]*)>(.*?)</option>", select.group(1), re.S)
    ]
    assert labels == [
        "Not imported", "Groundwater", "Surface water", "Purchased", "Sold",
        "Non-potable", "Recycled", "Non-potable sold",
    ]


def test_step_with_no_unit_says_row_73_and_saves_nothing(client_in, system):
    token = token_of(_upload(client_in))
    response = _step(client_in, token, **{**COMPLETE_STEP, "operator_unit": ""})
    assert ROW_73 in _flat(response.content.decode())
    assert SystemProduction.objects.count() == 0


def test_step_with_no_month_column_says_row_74_and_saves_nothing(client_in, system):
    token = token_of(_upload(client_in))
    response = _step(client_in, token, **{**COMPLETE_STEP, "month_column": ""})
    assert ROW_74 in _flat(response.content.decode())
    assert SystemProduction.objects.count() == 0


def test_step_with_no_column_typed_says_row_75_and_saves_nothing(client_in, system):
    token = token_of(_upload(client_in))
    response = _step(
        client_in, token, **{**COMPLETE_STEP, "column_type:All wells (gallons)": ""}
    )
    assert ROW_75 in _flat(response.content.decode())
    assert SystemProduction.objects.count() == 0


def test_step_with_two_columns_on_groundwater_says_row_76_and_saves_nothing(
    client_in, system
):
    token = token_of(_upload(client_in, "Month,Well A,Well B\n2024-01,100,200\n"))
    response = _step(
        client_in, token, month_column="Month", operator_unit="G", operator_year="",
        **{"column_type:Well A": "GW", "column_type:Well B": "GW"},
    )
    assert ROW_76 in _flat(response.content.decode())
    assert SystemProduction.objects.count() == 0


def test_commit_with_no_unit_saves_nothing(client_in, system):
    token = token_of(_upload(client_in))
    client_in.post(
        reverse("drinking:production_import_commit"),
        {"token": token, **COMPLETE_STEP, "operator_unit": ""},
        HTTP_HX_REQUEST="true",
    )
    assert SystemProduction.objects.count() == 0


# -- one code path: the screen and the command save the same rows ----------------


def test_screen_import_saves_twelve_rows(client_in, system):
    token = token_of(_upload(client_in))
    import_and_read(
        client_in, reverse("drinking:production_import_commit"), token, COMPLETE_STEP
    )
    assert SystemProduction.objects.count() == 12


def test_screen_and_command_save_the_same_rows(client_in, system, tmp_path):
    _run(_file(tmp_path, OWN_HEADINGS_CSV), *COLUMN_ARGS, "--operator-unit", "G")
    from_command = _fields()
    SystemProduction.objects.all().delete()

    token = token_of(_upload(client_in))
    import_and_read(
        client_in, reverse("drinking:production_import_commit"), token, COMPLETE_STEP
    )

    assert len(from_command) == 12
    assert _fields() == from_command


def test_a_log_with_its_own_headings_holding_only_january_is_january(tmp_path, system):
    # Invented test data. Only the state's layouts put a whole year in the
    # January row; an office's own log that holds only January means January.
    text = "Month,All wells (gallons)\n2024-01,1000\n"
    _run(_file(tmp_path, text), *COLUMN_ARGS, "--operator-unit", "G")
    row = SystemProduction.objects.get()
    assert (row.month, row.annual_in_january) == (1, False)
