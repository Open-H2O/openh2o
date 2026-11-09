# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.3 (ISS-374): import the state's sampling schedule.

Written first, before the feature. The service is driven through its two doors,
the ``import_schedule`` command and the screen (upload, preview, commit), and
the two must write the same rows.

All data is INVENTED (invented test data): the water system XX0000001, its PS
Codes like ``XX0000001_001_001`` and the analytes "Test Analyte Alpha" and so on.
No file of the state's is read. Every sentence a person reads is the Fixed column
of ``.planning/phases/152-proven-by-strangers/152-03.3-ROWS.md``; the row number
is named beside each. Row numbers in errors are the spreadsheet's (header = row 1).
"""

import csv
import io
import re
from datetime import date
from html import unescape

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.forms.models import model_to_dict
from django.test import Client
from django.urls import reverse

from drinking.models import Analyte, SamplingSchedule, WaterSystem
from tests.factories import (
    AnalyteFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)
from tests.import_flow import import_and_read, token_of

PS_1 = "XX0000001_001_001"
PS_2 = "XX0000001_002_001"

HEADINGS = [
    "PSCODE", "SAMPLE POINT", "CLASS", "STATUS", "GC", "GROUP", "ANALYTE CODE",
    "ANALYTE", "LAST RESULT", "LESS THAN", "REPORTING LEVEL",
    "COUNTING ERROR (+/-)", "UOM", "MCL", "DLR", "LAST SAMPLE",
    "COUNT OF RESULTS", "FREQ MONTHS", "MOD", "NEXT SAMPLE DUE", "NOTES",
    "SAMPLE ID", "LAB ID", "LAB NAME", "METHOD",
]

# -- the rows (Fixed column) -------------------------------------------------
ROW_2_SENTENCE = (
    "Import the state's schedule file. You can also add a row for each item on "
    "your sampling checklist."
)
ROW_29 = "This file has no {columns} column."
ROW_29_SCREEN_TAIL = " The table below lists the columns OpenH2O imports."
ROW_30 = "{n} rows from the state's schedule file"
ROW_31 = "OpenH2O will add {n} rows to the schedule."
ROW_32 = "OpenH2O will change {n} rows already on the schedule. Each change is listed below."
ROW_33 = "{n} rows are already on the schedule with the same frequency and dates."
ROW_34 = "{n} rows have errors. OpenH2O skips them."
ROW_35 = (
    "{n} rows repeat the sampling point and analyte of an earlier row in the "
    "file. OpenH2O keeps the first row and skips the repeats."
)
ROW_36 = "Changes to rows already on the schedule"
ROW_40 = "Rows on the schedule that this file does not have"
ROW_41 = "OpenH2O leaves these rows as they are."
ROW_42 = "Rows with errors"
ROW_44 = "PSCODE is blank."
ROW_45 = (
    "No sampling point on file has the PS Code {code}. Add the sampling point "
    "first, or correct the code in the file."
)
ROW_46 = "ANALYTE is blank."
ROW_47 = "OpenH2O cannot read '{value}' in FREQ MONTHS as a number of months."
ROW_48 = (
    "OpenH2O cannot read the date '{value}' in LAST SAMPLE. OpenH2O reads a "
    "date in the form M/D/YYYY."
)
ROW_49 = (
    "OpenH2O cannot read the month '{value}' in NEXT SAMPLE DUE. OpenH2O reads "
    "a month in the form YYYY/MM."
)
ROW_51 = "OpenH2O added {n} rows to the schedule and changed {m} rows."
ROW_52 = "OpenH2O skipped {n} rows with errors."
ROW_58 = "OpenH2O would add {n} rows to the schedule and change {m} rows."
ROW_59 = "Row {n}: {label} at {point}. {field}: {old} to {new}."
ROW_60 = "Not in this file: {label} at {point}. OpenH2O leaves it as it is."
ROW_61 = "{n} rows are already on the schedule with the same frequency and dates."
ROW_62 = (
    "OpenH2O added {n} rows to the schedule, changed {m} rows and skipped {k} "
    "rows with errors."
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"schedimport{n}")
    email = factory.Sequence(lambda n: f"schedimport{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


@pytest.fixture
def system(db):
    """The invented water system XX0000001 and its two sampling points; nothing else."""
    WaterSystem.objects.all().delete()  # see tests/test_production_import.py::le_grand
    ws = WaterSystemFactory(pwsid="XX0000001", name="Invented Test Water District")
    one = SystemFacilityFactory(system=ws, facility_id="001", facility_type="WL")
    two = SystemFacilityFactory(system=ws, facility_id="002", facility_type="TP")
    SamplingPointFactory(ps_code=PS_1, facility=one, point_type="source")
    SamplingPointFactory(ps_code=PS_2, facility=two, point_type="entry_point")
    return ws


@pytest.fixture
def analytes(db):
    return {
        "alpha": AnalyteFactory(name="Test Analyte Alpha", ddw_code="9001"),
        "beta": AnalyteFactory(name="Test Analyte Beta", ddw_code="9002"),
        "gamma": AnalyteFactory(name="Test Analyte Gamma", ddw_code="9003"),
    }


def line(**kwargs):
    """One file row (a dict over every heading); defaults are a valid new row."""
    row = dict.fromkeys(HEADINGS, "")
    row.update({
        "PSCODE": PS_1, "ANALYTE CODE": "9001", "ANALYTE": "Test Analyte Alpha",
        "FREQ MONTHS": "12", "NEXT SAMPLE DUE": "2035/07",
    })
    row.update(kwargs)
    return row


def file_text(rows, headings=HEADINGS):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headings, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def write_file(tmp_path, rows, headings=HEADINGS, name="schedule.csv"):
    path = tmp_path / name
    path.write_text(file_text(rows, headings), encoding="utf-8")
    return path


def run(*args):
    out = io.StringIO()
    call_command("import_schedule", *args, stdout=out, stderr=io.StringIO())
    return [ln.rstrip() for ln in out.getvalue().splitlines() if ln.strip()]


def run_rows(tmp_path, rows, *args):
    return run(str(write_file(tmp_path, rows)), *args)


def screen_preview(client, text):
    return client.post(
        reverse("drinking:schedule_import_preview"),
        {"file": SimpleUploadedFile("schedule.csv", text.encode(), content_type="text/csv")},
    )


def screen_import(client, text):
    preview = screen_preview(client, text)
    return import_and_read(client, reverse("drinking:schedule_import_commit"), token_of(preview))


def words(response):
    """The page's visible text, tags dropped, entities read, whitespace collapsed."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", response.content.decode())).split())


def snapshot():
    """Every schedule row as comparable fields (ids and stamps left out)."""
    return sorted((
        (
            row.sampling_point.ps_code if row.sampling_point_id else None,
            row.analyte.name if row.analyte_id else None,
            row.group_label, row.frequency, row.last_done, row.next_due,
            row.next_due_is_month, row.notes,
        )
        for row in SamplingSchedule.objects.select_related("sampling_point", "analyte")
    ), key=repr)


def only_row():
    return SamplingSchedule.objects.get()


def existing(system, point_code, *, analyte=None, group="", **fields):
    fields.setdefault("frequency", "annual")
    return SamplingSchedule.objects.create(
        system=system,
        sampling_point=SamplingPointFactory._meta.model.objects.get(ps_code=point_code),
        analyte=analyte, group_label=group, **fields,
    )


# -- the model ---------------------------------------------------------------


def test_every_6_years_sits_between_every_3_and_every_9_years():
    from drinking.models import SCHEDULE_FREQUENCY_CHOICES

    keys = [key for key, _ in SCHEDULE_FREQUENCY_CHOICES]
    assert ("every_6_years", "Every 6 years") in SCHEDULE_FREQUENCY_CHOICES
    assert keys.index("every_3_years") + 1 == keys.index("every_6_years")
    assert keys.index("every_6_years") + 1 == keys.index("every_9_years")


def test_a_schedule_row_holds_next_due_is_month_and_it_defaults_to_false(system):
    row = SamplingSchedule.objects.create(system=system, group_label="Coliform", frequency="monthly")
    row.refresh_from_db()
    assert row.next_due_is_month is False


def test_the_upload_page_opens(auth_client, system):
    assert auth_client.get(reverse("drinking:schedule_import")).status_code == 200


# -- frequencies (FREQ MONTHS) ------------------------------------------------


@pytest.mark.parametrize("months, frequency", [
    ("1", "monthly"), ("3", "quarterly"), ("12", "annual"), ("36", "every_3_years"),
    ("72", "every_6_years"), ("108", "every_9_years"), ("120", "every_10_years"),
])
def test_a_frequency_in_months_becomes_its_choice(system, analytes, tmp_path, months, frequency):
    run_rows(tmp_path, [line(**{"FREQ MONTHS": months})])
    row = only_row()
    assert row.frequency == frequency
    assert "Every" not in row.notes or frequency.startswith("every_")
    assert "months" not in row.notes


def test_any_other_whole_number_is_other_and_the_months_go_in_the_notes(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"FREQ MONTHS": "45"})])
    row = only_row()
    assert row.frequency == "other"
    assert row.notes == "Every 45 months"


@pytest.mark.parametrize("value", ["", "often", "1.5", "12 months"])
def test_a_frequency_that_is_no_whole_number_is_a_row_error(system, analytes, tmp_path, value):
    lines = run_rows(tmp_path, [line(**{"FREQ MONTHS": value})])
    assert f"Row 2: {ROW_47.format(value=value)}" in lines
    assert not SamplingSchedule.objects.exists()


# -- PS Codes ------------------------------------------------------------------


def test_the_ps_code_finds_the_sampling_point(system, analytes, tmp_path):
    run_rows(tmp_path, [line(PSCODE=PS_2)])
    assert only_row().sampling_point.ps_code == PS_2
    assert only_row().system == system


def test_a_blank_ps_code_is_row_44(system, analytes, tmp_path):
    lines = run_rows(tmp_path, [line(PSCODE="")])
    assert f"Row 2: {ROW_44}" in lines
    assert not SamplingSchedule.objects.exists()


def test_an_unknown_ps_code_is_row_45(system, analytes, tmp_path):
    lines = run_rows(tmp_path, [line(PSCODE="XX0000001_999_001")])
    assert f"Row 2: {ROW_45.format(code='XX0000001_999_001')}" in lines
    assert not SamplingSchedule.objects.exists()


# -- analytes ------------------------------------------------------------------


def test_the_analyte_is_found_by_its_code_first(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"ANALYTE CODE": "9002", "ANALYTE": "Test Analyte Alpha"})])
    row = only_row()
    assert row.analyte == analytes["beta"]
    assert row.group_label == ""


def test_the_analyte_is_found_by_name_without_regard_to_case(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"ANALYTE CODE": "", "ANALYTE": "test ANALYTE gamma"})])
    row = only_row()
    assert row.analyte == analytes["gamma"]
    assert row.group_label == ""


def test_an_analyte_not_on_the_site_becomes_the_row_label_and_creates_no_analyte(system, analytes, tmp_path):
    before = Analyte.objects.count()
    run_rows(tmp_path, [line(**{"ANALYTE CODE": "9999", "ANALYTE": "Invented Unlisted Substance"})])
    row = only_row()
    assert row.analyte is None
    assert row.group_label == "Invented Unlisted Substance"
    assert Analyte.objects.count() == before


def test_a_blank_analyte_is_row_46(system, analytes, tmp_path):
    lines = run_rows(tmp_path, [line(**{"ANALYTE CODE": "", "ANALYTE": ""})])
    assert f"Row 2: {ROW_46}" in lines
    assert not SamplingSchedule.objects.exists()


# -- dates ---------------------------------------------------------------------


@pytest.mark.parametrize("text", ["8/21/2023", "2023-08-21"])
def test_a_last_sample_in_either_form_becomes_last_done(system, analytes, tmp_path, text):
    run_rows(tmp_path, [line(**{"LAST SAMPLE": text})])
    assert only_row().last_done == date(2023, 8, 21)


def test_a_blank_last_sample_leaves_last_done_empty(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"LAST SAMPLE": ""})])
    assert only_row().last_done is None


def test_an_unreadable_last_sample_is_row_48(system, analytes, tmp_path):
    lines = run_rows(tmp_path, [line(**{"LAST SAMPLE": "21 August"})])
    assert f"Row 2: {ROW_48.format(value='21 August')}" in lines
    assert not SamplingSchedule.objects.exists()


def test_a_next_sample_due_month_becomes_the_first_of_the_month_marked_as_a_month(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"NEXT SAMPLE DUE": "2035/07"})])
    row = only_row()
    assert row.next_due == date(2035, 7, 1)
    assert row.next_due_is_month is True


def test_a_next_sample_due_full_date_is_that_day_and_not_a_month(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{"NEXT SAMPLE DUE": "7/15/2035"})])
    row = only_row()
    assert row.next_due == date(2035, 7, 15)
    assert row.next_due_is_month is False


@pytest.mark.parametrize("value", ["", "July 2035", "2035/13", "soon"])
def test_an_unreadable_next_sample_due_is_row_49(system, analytes, tmp_path, value):
    lines = run_rows(tmp_path, [line(**{"NEXT SAMPLE DUE": value})])
    assert f"Row 2: {ROW_49.format(value=value)}" in lines
    assert not SamplingSchedule.objects.exists()


# -- notes and what is not stored ----------------------------------------------


def test_the_notes_of_a_new_row_run_months_then_group_then_the_notes_column(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{
        "FREQ MONTHS": "45", "GROUP": "Invented Group Q", "NOTES": "Invented note text.",
    })])
    assert only_row().notes == "Every 45 months\nGroup: Invented Group Q\nInvented note text."


def test_each_line_of_the_notes_is_there_only_when_present(system, analytes, tmp_path):
    run_rows(tmp_path, [
        line(**{"GROUP": "Invented Group Q"}),
        line(PSCODE=PS_2, **{"NOTES": "Only a note."}),
    ])
    by_point = {r.sampling_point.ps_code: r.notes for r in SamplingSchedule.objects.select_related("sampling_point")}
    assert by_point[PS_1] == "Group: Invented Group Q"
    assert by_point[PS_2] == "Only a note."


def test_no_other_column_is_stored_anywhere(system, analytes, tmp_path):
    run_rows(tmp_path, [line(**{
        "LAB NAME": "Invented Lab Name Zeta", "LAB ID": "INV-LAB-77", "METHOD": "Invented Method 5",
        "SAMPLE ID": "INV-SAMPLE-9", "LAST RESULT": "0.123456", "UOM": "invented-uom",
        "SAMPLE POINT": "Invented Point Label",
    })])
    for value in model_to_dict(only_row()).values():
        text = str(value)
        for stray in ("Invented Lab Name Zeta", "INV-LAB-77", "Invented Method 5",
                      "INV-SAMPLE-9", "0.123456", "invented-uom", "Invented Point Label"):
            assert stray not in text


# -- repeats -------------------------------------------------------------------


def test_a_row_repeating_the_point_and_analyte_is_skipped_and_the_first_is_kept(system, analytes, tmp_path):
    run_rows(tmp_path, [
        line(**{"FREQ MONTHS": "3"}),
        line(**{"FREQ MONTHS": "1"}),
        line(PSCODE=PS_2),
    ])
    assert SamplingSchedule.objects.count() == 2
    first = SamplingSchedule.objects.get(sampling_point__ps_code=PS_1)
    assert first.frequency == "quarterly"


def test_a_repeated_label_with_no_analyte_is_also_a_repeat(system, analytes, tmp_path):
    named = {"ANALYTE CODE": "", "ANALYTE": "Invented Group Label"}
    run_rows(tmp_path, [line(**{**named, "FREQ MONTHS": "3"}), line(**{**named, "FREQ MONTHS": "1"})])
    assert SamplingSchedule.objects.count() == 1
    assert only_row().frequency == "quarterly"


def test_the_preview_counts_the_repeats_row_35(auth_client, system, analytes):
    text = file_text([
        line(), line(), line(), line(PSCODE=PS_2),
    ])
    shown = words(screen_preview(auth_client, text))
    assert ROW_35.format(n=2) in shown
    assert ROW_30.format(n=4) in shown


# -- missing columns -----------------------------------------------------------


@pytest.mark.parametrize("missing", ["PSCODE", "ANALYTE", "FREQ MONTHS", "NEXT SAMPLE DUE"])
def test_the_command_refuses_a_file_missing_a_required_column(system, analytes, tmp_path, missing):
    kept = [h for h in HEADINGS if h != missing]
    path = write_file(tmp_path, [line()], headings=kept)
    with pytest.raises(CommandError) as raised:
        run(str(path))
    assert str(raised.value).startswith(ROW_29.format(columns=missing))
    assert not SamplingSchedule.objects.exists()


@pytest.mark.parametrize("missing", ["PSCODE", "ANALYTE", "FREQ MONTHS", "NEXT SAMPLE DUE"])
def test_the_screen_refuses_a_file_missing_a_required_column_with_row_29(auth_client, system, analytes, missing):
    kept = [h for h in HEADINGS if h != missing]
    shown = words(screen_preview(auth_client, file_text([line()], headings=kept)))
    assert ROW_29.format(columns=missing) + ROW_29_SCREEN_TAIL in shown
    assert not SamplingSchedule.objects.exists()


def test_several_missing_columns_are_joined_with_commas_and_or(auth_client, system, analytes, tmp_path):
    kept = [h for h in HEADINGS if h not in ("PSCODE", "ANALYTE", "NEXT SAMPLE DUE")]
    shown = words(screen_preview(auth_client, file_text([line()], headings=kept)))
    assert "This file has no PSCODE, ANALYTE or NEXT SAMPLE DUE column." in shown
    with pytest.raises(CommandError) as raised:
        run(str(write_file(tmp_path, [line()], headings=kept)))
    assert str(raised.value).startswith("This file has no PSCODE, ANALYTE or NEXT SAMPLE DUE column.")


# -- --pwsid -------------------------------------------------------------------


def test_with_two_water_systems_the_command_needs_pwsid(system, analytes, tmp_path):
    WaterSystemFactory(pwsid="XX0000002", name="Second Invented District")
    with pytest.raises(CommandError) as raised:
        run_rows(tmp_path, [line()])
    assert "--pwsid" in str(raised.value)
    assert not SamplingSchedule.objects.exists()


def test_pwsid_names_the_system_that_receives_the_rows(system, analytes, tmp_path):
    other = WaterSystemFactory(pwsid="XX0000002", name="Second Invented District")
    facility = SystemFacilityFactory(system=other, facility_id="001", facility_type="WL")
    SamplingPointFactory(ps_code="XX0000002_001_001", facility=facility)
    run_rows(tmp_path, [line(PSCODE="XX0000002_001_001")], "--pwsid", "XX0000002")
    assert only_row().system == other


# -- a second import (ruling 113) ----------------------------------------------


@pytest.fixture
def second_import(system, analytes):
    """An existing schedule and a file that touches it. Invented.

    A: changes frequency only (annual to quarterly).   B: same values, unchanged.
    D: next due changes from a day to a month.         E: same values, unchanged.
    C: not named in the file (left out).               Two new rows, two errors.
    """
    day_old = date(2024, 3, 5)
    seen = date(2023, 8, 21)
    rows = {
        "A": existing(system, PS_1, analyte=analytes["alpha"], frequency="annual",
                      last_done=seen, next_due=day_old, notes="keep me exactly"),
        "B": existing(system, PS_1, analyte=analytes["beta"], frequency="quarterly",
                      last_done=seen, next_due=day_old, notes="B notes"),
        "C": existing(system, PS_2, group="Left Out Group", frequency="monthly", notes="C notes"),
        "D": existing(system, PS_2, analyte=analytes["alpha"], frequency="monthly",
                      next_due=day_old, notes="D notes"),
        "E": existing(system, PS_2, analyte=analytes["beta"], frequency="annual",
                      last_done=seen, next_due=day_old, notes="E notes"),
    }
    text = file_text([
        line(**{"ANALYTE CODE": "9001", "FREQ MONTHS": "3", "LAST SAMPLE": "8/21/2023",
                "NEXT SAMPLE DUE": "3/5/2024", "NOTES": "a file note that must not land"}),
        line(**{"ANALYTE CODE": "9002", "ANALYTE": "Test Analyte Beta", "FREQ MONTHS": "3",
                "LAST SAMPLE": "8/21/2023", "NEXT SAMPLE DUE": "3/5/2024"}),
        line(PSCODE=PS_2, **{"ANALYTE CODE": "9001", "FREQ MONTHS": "1", "NEXT SAMPLE DUE": "2025/01"}),
        line(PSCODE=PS_2, **{"ANALYTE CODE": "9002", "ANALYTE": "Test Analyte Beta", "FREQ MONTHS": "12",
                             "LAST SAMPLE": "8/21/2023", "NEXT SAMPLE DUE": "3/5/2024"}),
        line(PSCODE=PS_2, **{"ANALYTE CODE": "", "ANALYTE": "Brand New Group", "NEXT SAMPLE DUE": "2035/07"}),
        line(**{"ANALYTE CODE": "9003", "ANALYTE": "Test Analyte Gamma", "FREQ MONTHS": "36",
                "NEXT SAMPLE DUE": "2036/01"}),
        line(PSCODE="XX0000001_999_001"),
        line(PSCODE=""),
    ])
    return rows, text


def test_a_second_import_changes_only_the_four_fields_and_keeps_the_notes(second_import, tmp_path):
    rows, text = second_import
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    run(str(tmp_path / "again.csv"))
    a = SamplingSchedule.objects.get(pk=rows["A"].pk)
    assert a.frequency == "quarterly"
    assert a.notes == "keep me exactly"
    d = SamplingSchedule.objects.get(pk=rows["D"].pk)
    assert (d.frequency, d.last_done, d.next_due, d.next_due_is_month) == (
        "monthly", None, date(2025, 1, 1), True)
    assert d.notes == "D notes"


def test_a_second_import_adds_only_the_new_rows(second_import, tmp_path):
    rows, text = second_import
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    run(str(tmp_path / "again.csv"))
    assert SamplingSchedule.objects.count() == len(rows) + 2
    labels = set(SamplingSchedule.objects.values_list("group_label", flat=True))
    assert "Brand New Group" in labels


def test_a_row_the_file_does_not_name_is_left_exactly_as_it_was(second_import, tmp_path):
    rows, text = second_import
    before = model_to_dict(rows["C"])
    stamp = SamplingSchedule.objects.get(pk=rows["C"].pk).updated_at
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    run(str(tmp_path / "again.csv"))
    after = SamplingSchedule.objects.get(pk=rows["C"].pk)
    assert model_to_dict(after) == before
    assert after.updated_at == stamp


def test_an_unchanged_row_is_not_rewritten(second_import, tmp_path):
    rows, text = second_import
    stamp = SamplingSchedule.objects.get(pk=rows["B"].pk).updated_at
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    run(str(tmp_path / "again.csv"))
    assert SamplingSchedule.objects.get(pk=rows["B"].pk).updated_at == stamp


def test_the_same_file_imported_twice_adds_nothing_the_second_time(system, analytes, tmp_path):
    path = write_file(tmp_path, [line(), line(PSCODE=PS_2)])
    run(str(path))
    first = snapshot()
    lines = run(str(path))
    assert snapshot() == first
    assert lines[-1] == ROW_62.format(n=0, m=0, k=0)


def test_the_command_dry_run_reports_and_saves_nothing(second_import, tmp_path):
    rows, text = second_import
    before = snapshot()
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    lines = run(str(tmp_path / "again.csv"), "--dry-run")
    assert snapshot() == before
    assert ROW_58.format(n=2, m=2) in lines
    assert ROW_59.format(n=2, label="Test Analyte Alpha", point=PS_1,
                         field="Frequency", old="Annual", new="Quarterly") in lines
    assert any(ln.startswith("Row 4: Test Analyte Alpha at " + PS_2 + ". Next due: Mar 5, 2024 to Jan 2025")
               for ln in lines)
    assert ROW_60.format(label="Left Out Group", point=PS_2) in lines
    assert ROW_61.format(n=2) in lines


def test_the_command_run_ends_with_row_62_and_lists_the_same_changes(second_import, tmp_path):
    rows, text = second_import
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    lines = run(str(tmp_path / "again.csv"))
    assert lines[-1] == ROW_62.format(n=2, m=2, k=2)
    assert ROW_59.format(n=2, label="Test Analyte Alpha", point=PS_1,
                         field="Frequency", old="Annual", new="Quarterly") in lines
    assert ROW_60.format(label="Left Out Group", point=PS_2) in lines
    assert ROW_61.format(n=2) in lines


def test_the_command_prints_row_errors_with_the_spreadsheet_row_number(second_import, tmp_path):
    rows, text = second_import
    (tmp_path / "again.csv").write_text(text, encoding="utf-8")
    lines = run(str(tmp_path / "again.csv"))
    assert f"Row 8: {ROW_45.format(code='XX0000001_999_001')}" in lines
    assert f"Row 9: {ROW_44}" in lines


# -- the screen -----------------------------------------------------------------


def test_the_preview_shows_every_count_and_saves_nothing(auth_client, second_import):
    rows, text = second_import
    before = snapshot()
    shown = words(screen_preview(auth_client, text))
    assert ROW_30.format(n=8) in shown
    assert ROW_31.format(n=2) in shown
    assert ROW_32.format(n=2) in shown
    assert ROW_33.format(n=2) in shown
    assert ROW_34.format(n=2) in shown
    assert snapshot() == before


def test_the_preview_lists_each_change_in_a_changes_table(auth_client, second_import):
    rows, text = second_import
    shown = words(screen_preview(auth_client, text))
    assert ROW_36 in shown
    for head in ("Sampling point", "What is sampled", "What changes"):
        assert head in shown
    assert "Frequency: Annual to Quarterly" in shown
    assert "Next due: Mar 5, 2024 to Jan 2025" in shown


def test_a_change_shows_a_day_like_aug_21_2023(auth_client, system, analytes):
    existing(system, PS_1, analyte=analytes["alpha"], frequency="annual",
             last_done=date(2023, 8, 21), next_due=date(2024, 3, 5))
    text = file_text([line(**{"FREQ MONTHS": "12", "LAST SAMPLE": "11/14/2024",
                              "NEXT SAMPLE DUE": "3/5/2024"})])
    assert "Last done: Aug 21, 2023 to Nov 14, 2024" in words(screen_preview(auth_client, text))


def test_the_preview_lists_the_rows_the_file_leaves_out(auth_client, second_import):
    rows, text = second_import
    shown = words(screen_preview(auth_client, text))
    assert ROW_40 in shown
    assert ROW_41 in shown
    assert "Left Out Group" in shown


def test_the_preview_lists_the_errors_under_rows_with_errors(auth_client, second_import):
    rows, text = second_import
    shown = words(screen_preview(auth_client, text))
    assert ROW_42 in shown
    assert ROW_45.format(code="XX0000001_999_001") in shown
    assert ROW_44 in shown


def test_pressing_import_writes_the_rows_and_says_row_51_and_row_52(auth_client, second_import):
    rows, text = second_import
    shown = words(screen_import(auth_client, text))
    assert ROW_51.format(n=2, m=2) in shown
    assert ROW_52.format(n=2) in shown
    assert "Back to the schedule" in shown
    assert SamplingSchedule.objects.count() == len(rows) + 2
    assert SamplingSchedule.objects.get(pk=rows["A"].pk).frequency == "quarterly"
    assert SamplingSchedule.objects.get(pk=rows["A"].pk).notes == "keep me exactly"


# -- one code path ---------------------------------------------------------------


def test_the_screen_and_the_command_write_the_same_rows(auth_client, system, analytes, tmp_path):
    text = file_text([
        line(**{"FREQ MONTHS": "45", "GROUP": "Invented Group Q", "NOTES": "A note.",
                "LAST SAMPLE": "8/21/2023", "NEXT SAMPLE DUE": "2035/07"}),
        line(PSCODE=PS_2, **{"ANALYTE CODE": "", "ANALYTE": "Brand New Group", "FREQ MONTHS": "72",
                             "NEXT SAMPLE DUE": "7/15/2035"}),
        line(**{"ANALYTE CODE": "", "ANALYTE": "test analyte beta", "FREQ MONTHS": "1",
                "LAST SAMPLE": "2023-08-21", "NEXT SAMPLE DUE": "2036/02"}),
        line(PSCODE="XX0000001_999_001"),
    ])
    screen_import(auth_client, text)
    from_screen = snapshot()
    assert len(from_screen) == 3

    SamplingSchedule.objects.all().delete()
    path = tmp_path / "same.csv"
    path.write_text(text, encoding="utf-8")
    run(str(path))

    assert snapshot() == from_screen


def test_a_label_row_is_found_again_once_its_analyte_is_added(system, tmp_path):
    """The first import has no such analyte, so the row is saved under a label.
    After the analyte is added with that code, the same file finds the label
    row: nothing is added, nothing changes, and the row stays a label row."""
    path = write_file(tmp_path, [line(**{
        "ANALYTE CODE": "9777", "ANALYTE": "  Invented Late Analyte ",
    })])
    run(str(path))
    first = only_row()
    assert first.analyte is None
    assert first.group_label == "Invented Late Analyte"

    AnalyteFactory(name="Invented Late Analyte", ddw_code="9777")
    before = snapshot()
    lines = run(str(path))

    assert SamplingSchedule.objects.count() == 1
    assert snapshot() == before
    assert only_row().analyte is None
    assert lines[-1] == ROW_62.format(n=0, m=0, k=0)
    assert not any(ln.startswith("Not in this file") for ln in lines)


def test_a_blank_date_in_a_newer_file_keeps_the_offices_own_date(system, analytes, tmp_path):
    # Invented test data. A typed Last done must not be erased by a file whose
    # LAST SAMPLE cell is blank: a blank changes nothing.
    run_rows(tmp_path, [line(**{"LAST SAMPLE": "3/5/2024"})])
    row = only_row()
    assert row.last_done == date(2024, 3, 5)
    run_rows(tmp_path, [line(**{"LAST SAMPLE": "", "FREQ MONTHS": "36"})])
    row = only_row()
    assert row.last_done == date(2024, 3, 5)
    assert row.frequency == "every_3_years"
