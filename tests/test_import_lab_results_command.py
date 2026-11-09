# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.2: the ``import_lab_results`` command, and the importer functions it shares with the screen.

All data is INVENTED: ``tests/fixtures/drinking_sample_results.csv`` is a file for
the invented Demonstration Water District (CA0000042), with sampling points made
here for its PS Codes. Nothing reaches the network.

Every sentence a person reads is one named constant per row of
``.planning/phases/152-proven-by-strangers/152-03.2-ROWS.md``. Row numbers in
errors are the spreadsheet's (the header is row 1), as the screen shows them;
they are read from ``importer.validate_rows`` so a file edit cannot drift them.
"""

import csv
import io
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from drinking import importer
from drinking.models import Analyte, SampleEvent, SampleResult, WaterSystem
from tests.factories import SamplingPointFactory, SystemFacilityFactory, WaterSystemFactory
from tests.import_flow import import_and_read, token_of

FIXTURE = Path(__file__).parent / "fixtures" / "drinking_sample_results.csv"

# -- the rows (Fixed column) -------------------------------------------------
ROW_11 = (
    "Import sample results from a .csv, .tab or .txt lab results file. The Import "
    "lab results screen reads the same files."
)
ROW_12 = "The path of the file inside the container."
ROW_13 = (
    "Report what the import would do. The command does not save any record during "
    "a dry run."
)
ROW_40 = "[DRY RUN] The command does not save any record."
ROW_41_HEAD = "Columns read:"
ROW_41_NONE = "no column"
ROW_43 = (
    "OpenH2O cannot find the file {path}. Copy the file into the container with "
    "docker compose cp first."
)
ROW_44 = (
    "The command imports .csv, .tab and .txt files only. Save the file as CSV and "
    "run the command again."
)
ROW_45 = "This file has no {columns} column."
ROW_45_SCREEN_TAIL = " The table below lists the columns OpenH2O imports."
ROW_46 = "No sampling point on the site has these PS Codes:"
ROW_47 = "Add each sampling point with add_sampling_point. Then import the file again."
ROW_48 = "New analytes OpenH2O will add:"
ROW_49 = "OpenH2O added {n} new {analytes} from this file."
ROW_50 = "OpenH2O will record {agency} as the regulating agency of {system}."
ROW_51 = "OpenH2O recorded {agency} as the regulating agency of {system}."
ROW_52 = (
    "{system} already has {agency} on file as its regulating agency. This file "
    "names the same agency."
)
ROW_56 = "{n} rows are already on file."  # row 56
ROW_56_ONE = "1 row is already on file."  # row 64
ROW_57 = "{n} {rows} repeat an earlier row of the file."
ROW_57_ONE = "1 row repeats an earlier row of the file."
ROW_58 = "{n} {rows} have errors."
ROW_58_ONE = "1 row has errors."
ROW_61 = "OpenH2O added {n} {events}."
ROW_62 = "OpenH2O would import {n} sample {results} and skip {m} {rows}."
ROW_63 = "OpenH2O imported {n} sample {results} and skipped {m} {rows}."

# What the fixture is built to produce (see tests/test_drinking_import.py).
TOTAL_ROWS = 30
EXPECTED_RESULTS = 27
EXPECTED_EVENTS = 6
EXPECTED_ERRORS = 2
EXPECTED_REPEATS = 1
SYSTEM_NAME = "Demonstration Water District"
AGENCY = "District 99"


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"labcmd{n}")
    email = factory.Sequence(lambda n: f"labcmd{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def system(db):
    call_command("seed_drinking", verbosity=0)
    ws = WaterSystemFactory(pwsid="CA0000042", name=SYSTEM_NAME)
    well = SystemFacilityFactory(system=ws, facility_id="001", facility_type="WL")
    plant = SystemFacilityFactory(system=ws, facility_id="002", facility_type="TP")
    dist = SystemFacilityFactory(system=ws, facility_id="DS", facility_type="DS")
    SamplingPointFactory(ps_code="CA0000042_001_001", facility=well, point_type="source")
    SamplingPointFactory(ps_code="CA0000042_002_001", facility=plant, point_type="entry_point")
    SamplingPointFactory(ps_code="CA0000042_DS_001", facility=dist, point_type="distribution")
    return ws


@pytest.fixture
def auth_client(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


def fixture_rows():
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def lab_file(tmp_path):
    target = tmp_path / "lab.csv"
    target.write_bytes(FIXTURE.read_bytes())
    return target


def run(*args):
    from io import StringIO

    out = StringIO()
    call_command("import_lab_results", *args, stdout=out, stderr=StringIO())
    text = out.getvalue()
    return text, [line.rstrip() for line in text.splitlines() if line.strip()]


def plural(n, one, many):
    return one if n == 1 else many


def result_tuples():
    return sorted(
        (
            r.event.sampling_point.ps_code,
            r.event.sample_date,
            r.analyte.name,
            r.result_value,
            r.presence,
            r.unit,
            r.less_than_rl,
        )
        for r in SampleResult.objects.select_related("event__sampling_point", "analyte")
    ), sorted(
        (e.sampling_point.ps_code, e.sample_date)
        for e in SampleEvent.objects.select_related("sampling_point")
    )


def validated_of(path):
    parsed = importer.parse_upload(io.BytesIO(Path(path).read_bytes()), "lab.csv")
    mapping = importer.auto_map_columns(parsed["columns"])
    return parsed, mapping, importer.validate_rows(parsed["rows"], mapping)


# -- help lines --------------------------------------------------------------


def test_help_lines_are_the_rows():
    command = load_command_class("drinking", "import_lab_results")
    text = " ".join(command.create_parser("manage.py", "import_lab_results").format_help().split())
    for row in (ROW_11, ROW_12, ROW_13):
        assert row in text


# -- the screen and the command write the same rows ----------------------------


def test_the_screen_and_the_command_write_the_same_rows(auth_client, system, lab_file):
    analytes_before = set(Analyte.objects.values_list("pk", flat=True))
    # A named upload, as the browser makes it.
    from django.core.files.uploadedfile import SimpleUploadedFile

    preview = auth_client.post(
        reverse("drinking:import_preview"),
        {"file": SimpleUploadedFile("lab.csv", lab_file.read_bytes(), content_type="text/csv")},
    )
    import_and_read(auth_client, reverse("drinking:import_commit"), token_of(preview))
    from_screen = result_tuples()
    agency_after_screen = WaterSystem.objects.get(pwsid="CA0000042").regulating_agency
    assert len(from_screen[0]) == EXPECTED_RESULTS

    SampleEvent.objects.all().delete()
    Analyte.objects.exclude(pk__in=analytes_before).delete()
    WaterSystem.objects.filter(pwsid="CA0000042").update(regulating_agency="")
    assert SampleResult.objects.count() == 0

    run(str(lab_file))

    assert result_tuples() == from_screen
    assert WaterSystem.objects.get(pwsid="CA0000042").regulating_agency == agency_after_screen


# -- dry run -----------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_reports(system, lab_file):
    analytes = Analyte.objects.count()
    parsed, mapping, validated = validated_of(lab_file)
    text, lines = run(str(lab_file), "--dry-run")

    assert SampleResult.objects.count() == 0
    assert SampleEvent.objects.count() == 0
    assert Analyte.objects.count() == analytes
    assert WaterSystem.objects.get(pwsid="CA0000042").regulating_agency == ""

    assert lines[0] == ROW_40  # row 40
    assert ROW_41_HEAD in lines  # row 41
    assert lines.index(ROW_41_HEAD) > 0
    assert "  PS Code: PS Code" in lines
    for field, label in importer.FIELD_LABELS.items():
        value = mapping.get(field) or ROW_41_NONE
        assert f"  {label}: {value}" in lines, label

    assert ROW_48 in lines  # row 48
    assert "Perchlorate" in [line.strip() for line in lines]
    assert ROW_50.format(agency=AGENCY, system=SYSTEM_NAME) in lines  # row 50
    assert lines[-1] == ROW_62.format(  # row 62
        n=EXPECTED_RESULTS, m=TOTAL_ROWS - EXPECTED_RESULTS,
        results="results", rows="rows",
    )


# -- a run -------------------------------------------------------------------


def test_a_run_prints_its_counts_and_row_63_last(system, lab_file):
    text, lines = run(str(lab_file))
    assert SampleResult.objects.count() == EXPECTED_RESULTS

    assert ROW_49.format(n=1, analytes="analyte") in lines  # rows 49 and 64
    assert ROW_61.format(n=EXPECTED_EVENTS, events="sample events") in lines
    assert ROW_57_ONE in lines  # row 57 (one repeat)
    assert ROW_58.format(n=EXPECTED_ERRORS, rows="rows") in lines  # row 58
    assert ROW_51.format(agency=AGENCY, system=SYSTEM_NAME) in lines  # row 51
    assert lines[-1] == ROW_63.format(  # row 63
        n=EXPECTED_RESULTS, m=TOTAL_ROWS - EXPECTED_RESULTS,
        results="results", rows="rows",
    )


def test_a_second_run_reports_the_rows_already_on_file(auth_client, system, lab_file):
    run(str(lab_file))
    from django.core.files.uploadedfile import SimpleUploadedFile

    preview = auth_client.post(
        reverse("drinking:import_preview"),
        {"file": SimpleUploadedFile("lab.csv", lab_file.read_bytes(), content_type="text/csv")},
    )
    on_file = preview.context["duplicate_count"]
    assert on_file > 1

    text, lines = run(str(lab_file))

    assert (ROW_56.format(n=on_file) if on_file != 1 else ROW_56_ONE) in lines  # row 56
    assert lines[-1] == ROW_63.format(  # row 63
        n=0, m=TOTAL_ROWS, results="results", rows="rows",
    )
    assert ROW_52.format(system=SYSTEM_NAME, agency=AGENCY) in lines  # row 52
    assert SampleResult.objects.count() == EXPECTED_RESULTS


# -- rows with no sampling point -----------------------------------------------


def test_a_row_with_an_unknown_ps_code_names_it(system, lab_file):
    _, _, validated = validated_of(lab_file)
    bad = [item for item in validated if item["errors"]]
    unknown = sorted({
        item["data"]["ps_code"] for item in validated
        if item["data"].get("ps_code") and item["data"].get("sampling_point_id") is None
    })
    assert unknown == ["CA0000042_999_001"]

    text, lines = run(str(lab_file))

    for item in bad:
        row_line = next(line for line in lines if line.startswith(f"Row {item['index'] + 2}: "))  # row 42
        assert item["errors"][0] in row_line
    at = lines.index(ROW_46)  # row 46
    assert lines[at + 1] == "  CA0000042_999_001"
    assert lines[at + 2] == ROW_47  # row 47


# -- refusals ----------------------------------------------------------------


def test_a_missing_path_is_row_43(system, tmp_path):
    missing = tmp_path / "nope.csv"
    with pytest.raises(CommandError) as raised:
        run(str(missing))
    assert str(raised.value) == ROW_43.format(path=missing)


def test_an_xlsx_is_row_44(system, tmp_path):
    sheet = tmp_path / "lab.xlsx"
    sheet.write_bytes(b"PK\x03\x04")
    with pytest.raises(CommandError) as raised:
        run(str(sheet))
    assert str(raised.value) == ROW_44
    assert SampleResult.objects.count() == 0


def test_a_file_without_a_result_column_is_row_45(system, tmp_path):
    fieldnames, rows = fixture_rows()
    kept = [name for name in fieldnames if name != "Result"]
    path = write_rows(tmp_path / "lab.csv", kept, [{k: r[k] for k in kept} for r in rows])
    from io import StringIO

    out = StringIO()
    with pytest.raises(CommandError) as raised:
        call_command("import_lab_results", str(path), stdout=out, stderr=StringIO())
    assert str(raised.value) == ROW_45.format(columns="Result")
    printed = [line.rstrip() for line in out.getvalue().splitlines()]
    assert ROW_41_HEAD in printed  # the columns list comes first
    assert f"  Result: {ROW_41_NONE}" in printed
    assert SampleResult.objects.count() == 0


# -- singular forms (row 64) ---------------------------------------------------


def test_one_good_row_reads_in_the_singular(system, tmp_path):
    fieldnames, rows = fixture_rows()
    path = write_rows(tmp_path / "lab.csv", fieldnames, rows[:1])
    _, lines = run(str(path))
    assert ROW_61.format(n=1, events="sample event") in lines
    assert lines[-1] == ROW_63.format(n=1, m=0, results="result", rows="rows")
    assert lines[-1] == "OpenH2O imported 1 sample result and skipped 0 rows."

    _, again = run(str(path))
    assert ROW_56_ONE in again  # row 64
    assert again[-1] == "OpenH2O imported 0 sample results and skipped 1 row."


def test_one_repeat_and_one_error_read_in_the_singular(system, tmp_path):
    fieldnames, rows = fixture_rows()
    bad = dict(rows[0], **{"PS Code": "CA0000042_999_001"})
    path = write_rows(tmp_path / "lab.csv", fieldnames, [rows[0], rows[0], bad])
    _, lines = run(str(path))
    assert ROW_57_ONE in lines
    assert ROW_58_ONE in lines
    assert lines[-1] == "OpenH2O imported 1 sample result and skipped 2 rows."


# -- the importer functions the screen now shares -------------------------------


def test_preview_counts_match_the_screen(auth_client, system, lab_file):
    from django.core.files.uploadedfile import SimpleUploadedFile

    preview = auth_client.post(
        reverse("drinking:import_preview"),
        {"file": SimpleUploadedFile("lab.csv", lab_file.read_bytes(), content_type="text/csv")},
    )
    _, _, validated = validated_of(lab_file)
    counts = importer.preview_counts(validated)

    assert set(counts) >= {
        "error_count", "duplicate_count", "repeat_count", "new_analytes",
        "committable", "limits_fill_count",
    }
    for key in ("error_count", "duplicate_count", "repeat_count", "new_analytes",
                "committable", "limits_fill_count"):
        assert counts[key] == preview.context[key], key
    assert counts["error_count"] == EXPECTED_ERRORS
    assert counts["repeat_count"] == EXPECTED_REPEATS
    assert counts["committable"] == EXPECTED_RESULTS
    assert counts["new_analytes"] == ["Perchlorate"]


def test_import_lab_rows_maps_validates_commits_and_records_the_agency(system, lab_file):
    parsed, _, _ = validated_of(lab_file)
    outcome = importer.import_lab_rows(parsed["columns"], parsed["rows"], source_file="lab.csv")

    assert set(outcome) >= {"validated", "counts", "agency"}
    assert outcome["counts"]["results"] == EXPECTED_RESULTS
    assert len(outcome["validated"]) == TOTAL_ROWS
    assert outcome["agency"][0]["value"] == AGENCY
    assert SampleResult.objects.count() == EXPECTED_RESULTS
    assert WaterSystem.objects.get(pwsid="CA0000042").regulating_agency == AGENCY


def test_missing_columns_sentence_is_only_the_first_sentence():
    assert importer.missing_columns_sentence(["result"]) == ROW_45.format(columns="Result")
    assert importer.missing_columns_sentence(["sample_date", "analyte_name", "result"]) == (
        ROW_45.format(columns="Sample Date, Analyte Name or Result")
    )
    # The screen keeps its second sentence.
    assert importer.missing_columns_message(["result"]) == (
        ROW_45.format(columns="Result") + ROW_45_SCREEN_TAIL
    )
