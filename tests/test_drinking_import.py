# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the lab sample-result importer (drinking.importer).

Four functions the import UI is thin glue over, mirroring
``infrastructure.importer``'s contract:

  parse_upload(file, filename)  -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns)     -> {logical_field: source_column}
  validate_rows(rows, mapping)  -> [{index, data, errors, warnings}]
  commit_rows(valid_results)    -> {"events", "results", "analytes", ...}

These lock the contract the views depend on, and three promises that are the
whole reason this importer is separate from a generic CSV loader:

  1. A result is stored as the shape the lab reported — a number, a bound, or a
     presence/absence reading — and NEVER coerced into a number it isn't.
  2. Sampling points are never invented from a lab file; analytes are.
  3. Re-importing the same file is a no-op, not a doubling.

The fixture is a realistic 30-row file in the DDW SDWIS.CSV layout for the
obviously-fictional PWSID CA0000042.
"""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from drinking import importer
from drinking.models import (
    RESULT_KIND_NUMERIC,
    RESULT_KIND_PRESENCE_ABSENCE,
    Analyte,
    SampleEvent,
    SampleResult,
)
from tests.factories import SamplingPointFactory, SystemFacilityFactory, WaterSystemFactory

FIXTURE = Path(__file__).parent / "fixtures" / "drinking_sample_results.csv"

# The format the state ACTUALLY publishes: a slice cut verbatim out of DDW's
# real `SDWIS4.zip` (EDT Library, refreshed 2026-06-23) for CA1010001, Bakman
# Water Company. The .csv fixture above is a faithful copy of a layout DDW
# retired; this one is the layout an operator downloads today. Both are kept
# deliberately — one proves the legacy path still works, one proves the live
# path works at all.
TAB_FIXTURE = Path(__file__).parent / "fixtures" / "drinking_sdwis4_slice.tab"
TAB_COLUMNS = 29  # the live header; the 2021 dictionary described 27
TAB_ROWS = 40

# What the fixture is built to produce on a clean import. Stated once, here, so
# a change to the file has to change these numbers deliberately.
EXPECTED_EVENTS = 6
EXPECTED_RESULTS = 27
EXPECTED_NEW_ANALYTES = 1  # Perchlorate — named in the file, not in the seed
EXPECTED_DUPLICATES = 1  # row 29 exactly repeats row 1
EXPECTED_ERRORS = 2  # row 28 unknown PS Code, row 30 unreadable result
TOTAL_ROWS = 30


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"labimporter{n}")
    email = factory.Sequence(lambda n: f"labimporter{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_text():
    return FIXTURE.read_text(encoding="utf-8")


def _csv_file(text, name="lab.csv"):
    """A file-like object standing in for an uploaded CSV."""
    buf = io.BytesIO(text.encode("utf-8"))
    buf.name = name
    return buf


@pytest.fixture
def system(db):
    """The three sampling points the fixture references, and the seeded
    federal analyte vocabulary 78-01 ships.

    The real seed command is used rather than hand-built analytes on purpose:
    the fixture matches analytes BY NAME, so if a seeded name is ever reworded
    this test fails loudly instead of quietly creating duplicate vocabulary.
    """
    call_command("seed_drinking", verbosity=0)
    ws = WaterSystemFactory(pwsid="CA0000042", name="Demonstration Water District")
    well = SystemFacilityFactory(system=ws, facility_id="001", facility_type="WL")
    plant = SystemFacilityFactory(system=ws, facility_id="002", facility_type="TP")
    dist = SystemFacilityFactory(system=ws, facility_id="DS", facility_type="DS")
    return {
        "system": ws,
        "points": [
            SamplingPointFactory(
                ps_code="CA0000042_001_001", facility=well, point_type="source"
            ),
            SamplingPointFactory(
                ps_code="CA0000042_002_001", facility=plant, point_type="entry_point"
            ),
            SamplingPointFactory(
                ps_code="CA0000042_DS_001", facility=dist, point_type="distribution"
            ),
        ],
    }


@pytest.fixture
def tab_fixture_text():
    return TAB_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def parsed(fixture_text):
    return importer.parse_upload(_csv_file(fixture_text), "lab.csv")


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


class TestParseUpload:
    def test_reads_every_row_and_column(self, parsed):
        assert len(parsed["rows"]) == TOTAL_ROWS
        # The DDW layout's 27 published fields, headers verbatim.
        assert parsed["columns"][0] == "Regulating Agency"
        assert "PS Code" in parsed["columns"]
        assert "Analyte Name" in parsed["columns"]
        assert "Less Than Reporting Level" in parsed["columns"]

    def test_tolerates_a_utf8_bom(self, fixture_text):
        """Excel writes a BOM; the first column name must not absorb it."""
        with_bom = "﻿" + fixture_text
        result = importer.parse_upload(_csv_file(with_bom), "lab.csv")
        assert result["columns"][0] == "Regulating Agency"
        assert len(result["rows"]) == TOTAL_ROWS

    def test_rejects_a_non_csv(self, fixture_text):
        with pytest.raises(ImportError, match="Unsupported format"):
            importer.parse_upload(_csv_file(fixture_text), "results.xlsx")

    def test_rejects_an_empty_file(self):
        header = "PS Code,Sample Date,Analyte Name,Result\n"
        with pytest.raises(ImportError, match="No rows"):
            importer.parse_upload(_csv_file(header), "lab.csv")

    def test_rejects_an_oversize_upload_before_parsing(self, fixture_text):
        f = _csv_file(fixture_text)
        f.size = importer.MAX_UPLOAD_BYTES + 1
        with pytest.raises(ImportError, match="too large"):
            importer.parse_upload(f, "lab.csv")

    def test_rejects_more_than_max_rows(self, fixture_text):
        lines = fixture_text.strip().split("\n")
        header, first = lines[0], lines[1]
        bloated = "\n".join([header] + [first] * (importer.MAX_ROWS + 1))
        with pytest.raises(ImportError, match="row import cap"):
            importer.parse_upload(_csv_file(bloated), "lab.csv")


class TestParseUploadReadsTheStatesRealFormat:
    """DDW retired `SDWIS*.CSV`; the EDT Library ships `SDWIS*.tab` today.

    An operator who downloads the correct file must not be told their file is
    the wrong format — and must not have it silently mis-parsed either, which
    is the more dangerous of the two failures. See ISS-073.
    """

    def test_a_tab_extract_parses_into_its_real_columns_and_rows(
        self, tab_fixture_text
    ):
        result = importer.parse_upload(
            _csv_file(tab_fixture_text), "SDWIS4.tab"
        )
        assert len(result["columns"]) == TAB_COLUMNS
        assert len(result["rows"]) == TAB_ROWS
        assert result["columns"][0] == "Regulating Agency"
        assert "PS Code" in result["columns"]
        assert "Analyte Name" in result["columns"]

    def test_a_comma_inside_a_tab_delimited_value_stays_one_field(
        self, tab_fixture_text
    ):
        """The test that proves the DELIMITER changed, not just the gate.

        `1,2,3-Trichloropropane` and `1,1-Dichloroethane` are real regulated
        analytes. Under a comma reader a renamed .tab file does not merely
        parse badly — it shreds analyte names into extra columns and carries
        on, which is a silent data defect rather than a loud failure.
        """
        result = importer.parse_upload(
            _csv_file(tab_fixture_text), "SDWIS4.tab"
        )
        names = {row["Analyte Name"] for row in result["rows"]}
        commas = {n for n in names if "," in n}
        assert commas, "fixture must carry a comma-bearing analyte name"
        assert "1,1-DICHLOROETHANE" in commas
        # Every row keeps the full 29-key shape: nothing spilled into surplus
        # cells, and no row was padded out from a short split.
        for row in result["rows"]:
            assert len(row) == TAB_COLUMNS

    def test_a_txt_extract_is_read_as_tab_delimited(self, tab_fixture_text):
        result = importer.parse_upload(
            _csv_file(tab_fixture_text), "extract.txt"
        )
        assert len(result["columns"]) == TAB_COLUMNS
        assert len(result["rows"]) == TAB_ROWS

    def test_the_legacy_csv_path_is_untouched(self, fixture_text):
        """Regression guard: widening the gate must not move the .csv path."""
        result = importer.parse_upload(_csv_file(fixture_text), "results.csv")
        assert len(result["rows"]) == TOTAL_ROWS
        assert result["columns"][0] == "Regulating Agency"

    def test_the_rejection_message_names_every_accepted_format(
        self, tab_fixture_text
    ):
        """The old copy named .csv as the only true format — actively
        misleading an operator holding the state's own .tab download."""
        with pytest.raises(ImportError) as exc:
            importer.parse_upload(_csv_file(tab_fixture_text), "results.xlsx")
        message = str(exc.value)
        assert ".csv" in message
        assert ".tab" in message
        assert ".txt" in message

    def test_the_real_header_maps_with_no_manual_assignment(
        self, tab_fixture_text
    ):
        """ISS-073's good news, pinned: the live header needs no new aliases."""
        result = importer.parse_upload(
            _csv_file(tab_fixture_text), "SDWIS4.tab"
        )
        mapping = importer.auto_map_columns(result["columns"])
        assert importer.missing_required(mapping) == []
        assert mapping["ps_code"] == "PS Code"
        assert mapping["analyte_name"] == "Analyte Name"
        assert mapping["sample_date"] == "Sample Date"
        assert mapping["result"] == "Result"


# ---------------------------------------------------------------------------
# auto_map_columns
# ---------------------------------------------------------------------------


class TestAutoMapColumns:
    def test_raw_ddw_headers_map_with_no_manual_assignment(self, parsed):
        mapping = importer.auto_map_columns(parsed["columns"])
        assert mapping["ps_code"] == "PS Code"
        assert mapping["sample_date"] == "Sample Date"
        assert mapping["sample_time"] == "Sample Time"
        assert mapping["analyte_name"] == "Analyte Name"
        assert mapping["ddw_code"] == "Analyte Code"
        assert mapping["result"] == "Result"
        assert mapping["unit"] == "Units of Measure"
        assert mapping["less_than_rl"] == "Less Than Reporting Level"
        assert mapping["reporting_level"] == "Reporting Level"
        assert mapping["counting_error"] == "Counting Error (±)"
        assert mapping["lab_cert_no"] == "ELAP Cert#"
        assert mapping["method"] == "Method"
        assert importer.missing_required(mapping) == []

    def test_matching_ignores_case_and_punctuation(self):
        mapping = importer.auto_map_columns(
            ["ps_code", "SAMPLE DATE", "analyte name", "Result"]
        )
        assert mapping["ps_code"] == "ps_code"
        assert mapping["sample_date"] == "SAMPLE DATE"
        assert mapping["analyte_name"] == "analyte name"

    def test_the_regulatory_limit_columns_are_deliberately_not_mapped(self, parsed):
        """MCL and DLR are limits, not findings.

        Storing a limit on the result row beside the value is one template
        change away from a compliance verdict, and RegulatoryLimit is the
        versioned home for what a limit was on a given date.
        """
        mapping = importer.auto_map_columns(parsed["columns"])
        assert "MCL" not in mapping.values()
        assert "DLR" not in mapping.values()

    def test_missing_required_columns_are_named(self):
        mapping = importer.auto_map_columns(["Analyte Name", "Result"])
        missing = importer.missing_required(mapping)
        assert "PS Code" in missing
        assert "Sample date" in missing


# ---------------------------------------------------------------------------
# validate_rows — the error / warning taxonomy
# ---------------------------------------------------------------------------


@pytest.fixture
def validated(system, parsed):
    mapping = importer.auto_map_columns(parsed["columns"])
    return importer.validate_rows(parsed["rows"], mapping)


class TestValidateRows:
    def test_the_taxonomy_lands_on_exactly_the_right_rows(self, validated):
        errored = [v["index"] for v in validated if v["errors"]]
        # 0-based indexes of file rows 28 and 30.
        assert errored == [27, 29]

    def test_an_unknown_ps_code_is_a_row_error_not_an_auto_create(self, validated):
        row = validated[27]
        assert any("not a known sampling point" in e for e in row["errors"])

    def test_an_unreadable_result_is_rejected_never_coerced_to_zero(self, validated):
        row = validated[29]
        assert any("neither a number nor a presence/absence" in e for e in row["errors"])
        assert row["data"].get("result_value") is None

    def test_an_unknown_analyte_is_a_warning_not_an_error(self, validated):
        row = validated[10]  # Perchlorate
        assert row["errors"] == []
        assert any("new analyte" in w for w in row["warnings"])
        assert row["data"].get("analyte_id") is None

    def test_a_repeated_row_is_flagged_duplicate_within_the_same_file(self, validated):
        row = validated[28]  # exact repeat of row 1
        assert row["errors"] == []
        assert row["data"]["is_duplicate"] is True
        assert any("repeats an earlier row" in w for w in row["warnings"])

    def test_a_plain_numeric_result_keeps_its_value_and_unit(self, validated):
        row = validated[0]  # Nitrate 3.2 mg/L
        assert row["data"]["result_kind"] == RESULT_KIND_NUMERIC
        assert row["data"]["result_value"] == Decimal("3.2")
        assert row["data"]["less_than_rl"] is False
        assert row["data"]["unit"] == "mg/L"

    def test_a_less_than_prefix_becomes_a_bound_not_a_measurement(self, validated):
        row = validated[2]  # Selenium <0.005
        assert row["data"]["less_than_rl"] is True
        assert row["data"]["reporting_level"] == Decimal("0.005")
        # The number on a non-detect row is the level the lab could report down
        # to, not a concentration anybody measured.
        assert row["data"]["result_value"] is None

    def test_the_less_than_rl_column_also_marks_a_non_detect(self, validated):
        row = validated[5]  # Cadmium, Result 0.001 with LT RL = Y
        assert row["data"]["less_than_rl"] is True
        assert row["data"]["result_value"] is None
        assert row["data"]["reporting_level"] == Decimal("0.001")

    def test_presence_and_absence_are_read_as_presence_absence(self, validated):
        absent = validated[16]  # Total Coliforms, "A"
        present = validated[18]  # Total Coliforms, "P"
        assert absent["data"]["result_kind"] == RESULT_KIND_PRESENCE_ABSENCE
        assert absent["data"]["presence"] is False
        assert present["data"]["presence"] is True
        # Neither may carry a number or the non-detect flag: "absent" is not
        # "below reporting level".
        for row in (absent, present):
            assert row["data"]["result_value"] is None
            assert row["data"]["less_than_rl"] is False

    def test_a_radionuclide_keeps_its_counting_error(self, validated):
        row = validated[20]  # Gross Alpha 2.4 ± 0.8 pCi/L
        assert row["data"]["result_value"] == Decimal("2.4")
        assert row["data"]["counting_error"] == Decimal("0.8")
        assert row["data"]["unit"] == "pCi/L"

    def test_lab_provenance_is_carried_through(self, validated):
        row = validated[0]
        assert row["data"]["lab_name"] == "Central Valley Analytical"
        assert row["data"]["lab_cert_no"] == "1234"
        assert row["data"]["method"] == "EPA 300.0"

    def test_a_blank_result_is_an_error(self, system):
        mapping = {"ps_code": "PS Code", "sample_date": "Sample Date",
                   "analyte_name": "Analyte Name", "result": "Result"}
        rows = [{"PS Code": "CA0000042_001_001", "Sample Date": "2026-03-10",
                 "Analyte Name": "Arsenic", "Result": ""}]
        out = importer.validate_rows(rows, mapping)
        assert any("Result is blank" in e for e in out[0]["errors"])

    def test_an_unparseable_sample_date_is_an_error(self, system):
        mapping = {"ps_code": "PS Code", "sample_date": "Sample Date",
                   "analyte_name": "Analyte Name", "result": "Result"}
        rows = [{"PS Code": "CA0000042_001_001", "Sample Date": "March 10th",
                 "Analyte Name": "Arsenic", "Result": "1.0"}]
        out = importer.validate_rows(rows, mapping)
        assert any("is not a date" in e for e in out[0]["errors"])


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


class TestCommitRows:
    def test_counts_are_correct(self, validated):
        counts = importer.commit_rows(validated)
        assert counts["events"] == EXPECTED_EVENTS
        assert counts["results"] == EXPECTED_RESULTS
        assert counts["analytes"] == EXPECTED_NEW_ANALYTES
        assert counts["duplicates"] == EXPECTED_DUPLICATES
        assert counts["skipped"] == EXPECTED_ERRORS
        assert SampleResult.objects.count() == EXPECTED_RESULTS
        assert SampleEvent.objects.count() == EXPECTED_EVENTS

    def test_events_group_by_point_date_and_time(self, validated):
        importer.commit_rows(validated)
        # The 11-row inorganics batch is ONE event, not eleven.
        event = SampleEvent.objects.get(
            sampling_point__ps_code="CA0000042_001_001",
            sample_date="2026-03-10",
        )
        assert event.results.count() == 11
        # Same point, different date = a different event.
        assert SampleEvent.objects.filter(
            sampling_point__ps_code="CA0000042_001_001"
        ).count() == 2

    def test_presence_absence_rows_store_no_numeric_value(self, validated):
        importer.commit_rows(validated)
        coliform = SampleResult.objects.filter(
            analyte__name="Total Coliforms"
        ).order_by("event__sample_date")
        assert coliform.count() == 2
        for result in coliform:
            assert result.result_kind == RESULT_KIND_PRESENCE_ABSENCE
            assert result.result_value is None
            assert result.less_than_rl is False
        assert [r.presence for r in coliform] == [False, True]

    def test_a_non_detect_stores_the_bound_not_a_value(self, validated):
        importer.commit_rows(validated)
        selenium = SampleResult.objects.get(analyte__name="Selenium")
        assert selenium.less_than_rl is True
        assert selenium.reporting_level == Decimal("0.005000")
        assert selenium.result_value is None

    def test_an_unknown_analyte_is_created_from_the_files_own_vocabulary(
        self, validated
    ):
        assert not Analyte.objects.filter(name="Perchlorate").exists()
        importer.commit_rows(validated)
        perchlorate = Analyte.objects.get(name="Perchlorate")
        # Name AND code come from the file — that is DDW's vocabulary, not ours.
        assert perchlorate.ddw_code == "1095"

    def test_a_code_is_learned_for_an_analyte_seeded_without_one(self, validated):
        """78-01 seeded every ddw_code NULL because DDW publishes no code list.
        A file that carries one teaches it."""
        assert Analyte.objects.get(name="Arsenic").ddw_code is None
        importer.commit_rows(validated)
        assert Analyte.objects.get(name="Arsenic").ddw_code == "1005"

    def test_no_sampling_point_is_ever_created(self, validated, system):
        before = set(
            SamplingPointFactory._meta.model.objects.values_list("ps_code", flat=True)
        )
        importer.commit_rows(validated)
        after = set(
            SamplingPointFactory._meta.model.objects.values_list("ps_code", flat=True)
        )
        assert before == after
        assert "CA0000042_999_001" not in after

    def test_errored_and_duplicate_rows_are_not_written(self, validated):
        importer.commit_rows(validated)
        # The unknown-PS-Code row's analyte/date combination must not exist.
        assert not SampleEvent.objects.filter(
            sampling_point__ps_code="CA0000042_999_001"
        ).exists()
        # Nitrate at the duplicated event appears once, not twice.
        assert SampleResult.objects.filter(
            analyte__name="Nitrate (as N)",
            event__sample_date="2026-03-10",
        ).count() == 1


class TestIdempotency:
    def test_a_second_import_of_the_same_file_creates_nothing(
        self, system, fixture_text
    ):
        def run():
            parsed = importer.parse_upload(_csv_file(fixture_text), "lab.csv")
            mapping = importer.auto_map_columns(parsed["columns"])
            return importer.commit_rows(
                importer.validate_rows(parsed["rows"], mapping)
            )

        first = run()
        assert first["results"] == EXPECTED_RESULTS

        second = run()
        assert second["results"] == 0
        assert second["events"] == 0
        assert second["analytes"] == 0
        # Everything that was committable the first time is now a duplicate.
        assert second["duplicates"] == EXPECTED_RESULTS + EXPECTED_DUPLICATES

        assert SampleResult.objects.count() == EXPECTED_RESULTS
        assert SampleEvent.objects.count() == EXPECTED_EVENTS


# ---------------------------------------------------------------------------
# The view flow
# ---------------------------------------------------------------------------


class TestImportViews:
    def test_the_import_page_renders(self, auth_client):
        response = auth_client.get(reverse("drinking:import"))
        assert response.status_code == 200
        assert b"Import lab results" in response.content

    def test_upload_preview_commit_end_to_end(
        self, auth_client, system, fixture_text
    ):
        preview = auth_client.post(
            reverse("drinking:import_preview"),
            {"file": _csv_file(fixture_text)},
        )
        assert preview.status_code == 200
        body = preview.content.decode()
        # The preview must show what will happen BEFORE anything is written.
        assert "Perchlorate" in body  # the new-analyte warning
        assert "not a known sampling point" in body  # the blocking error
        assert SampleResult.objects.count() == 0

        rows_json = preview.context["rows_json"]
        assert preview.context["committable"] == EXPECTED_RESULTS
        assert preview.context["error_count"] == EXPECTED_ERRORS
        assert preview.context["duplicate_count"] == EXPECTED_DUPLICATES

        commit = auth_client.post(
            reverse("drinking:import_commit"), {"rows_json": rows_json}
        )
        assert commit.status_code == 200
        assert commit.context["counts"]["results"] == EXPECTED_RESULTS
        assert SampleResult.objects.count() == EXPECTED_RESULTS

    def test_the_results_page_shows_imported_rows(
        self, auth_client, system, fixture_text
    ):
        parsed = importer.parse_upload(_csv_file(fixture_text), "lab.csv")
        importer.commit_rows(
            importer.validate_rows(
                parsed["rows"], importer.auto_map_columns(parsed["columns"])
            )
        )
        response = auth_client.get(reverse("drinking:results"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Nitrate (as N)" in body
        assert "Absent" in body  # a presence/absence row rendered honestly
        assert "&lt; 0.005 mg/L" in body or "< 0.005 mg/L" in body  # the bound

    def test_a_file_missing_required_columns_is_refused_by_name(self, auth_client):
        bad = "Analyte Name,Result\nArsenic,0.004\n"
        response = auth_client.post(
            reverse("drinking:import_preview"), {"file": _csv_file(bad)}
        )
        assert response.status_code == 200
        assert "PS Code" in response.content.decode()

    def test_a_missing_file_is_reported_not_crashed(self, auth_client):
        response = auth_client.post(reverse("drinking:import_preview"), {})
        assert response.status_code == 200
        assert "No file provided" in response.content.decode()

    def test_commit_re_enforces_the_row_cap(self, auth_client, system):
        """rows_json is a hidden field the browser posts back, so the cap has
        to hold on commit too — otherwise it is trivially bypassed."""
        import json

        rows = [
            {"PS Code": "CA0000042_001_001", "Sample Date": "2026-03-10",
             "Analyte Name": "Arsenic", "Result": "0.004"}
        ] * (importer.MAX_ROWS + 1)
        response = auth_client.post(
            reverse("drinking:import_commit"), {"rows_json": json.dumps(rows)}
        )
        assert "over the" in response.content.decode()
        assert SampleResult.objects.count() == 0

    @pytest.mark.parametrize(
        "url_name", ["import", "import_preview", "import_commit"]
    )
    def test_anonymous_users_are_rejected(self, db, url_name):
        client = Client()
        url = reverse(f"drinking:{url_name}")
        response = client.get(url) if url_name == "import" else client.post(url, {})
        assert response.status_code in (302, 403)
        if response.status_code == 302:
            assert "/login" in response.url or "login" in response.url

    def test_preview_rejects_a_get(self, auth_client):
        assert auth_client.get(reverse("drinking:import_preview")).status_code == 405

    def test_commit_rejects_a_get(self, auth_client):
        assert auth_client.get(reverse("drinking:import_commit")).status_code == 405


class TestEntryPoints:
    def test_the_results_page_links_the_import(self, auth_client, system):
        response = auth_client.get(reverse("drinking:results"))
        assert reverse("drinking:import") in response.content.decode()

    def test_the_empty_results_state_offers_the_import(self, auth_client, db):
        response = auth_client.get(reverse("drinking:results"))
        body = response.content.decode()
        assert reverse("drinking:import") in body

    def test_the_empty_system_state_does_not_offer_the_import(self, auth_client, db):
        """Importing a lab file cannot create a water system, so offering it
        there would be a dead end."""
        response = auth_client.get(reverse("drinking:overview"))
        assert reverse("drinking:import") not in response.content.decode()


class TestNoComplianceVerdict:
    """The importer reads MCL and DLR columns from the file and stores neither.
    Nothing it writes can be read as a compliance determination."""

    def test_no_limit_value_is_stored_on_a_result(self, validated):
        importer.commit_rows(validated)
        nitrate = SampleResult.objects.get(
            analyte__name="Nitrate (as N)", event__sample_date="2026-03-10"
        )
        # The file's MCL cell for this row was 10; nothing on the result carries it.
        stored = [nitrate.result_value, nitrate.reporting_level, nitrate.counting_error]
        assert Decimal("10") not in [v for v in stored if v is not None]

    def test_the_import_pages_render_no_verdict_language(
        self, auth_client, system, fixture_text
    ):
        preview = auth_client.post(
            reverse("drinking:import_preview"), {"file": _csv_file(fixture_text)}
        )
        body = preview.content.decode().lower()
        for word in ("exceed", "violation", "compliant", "non-compliant", "pass", "fail"):
            assert word not in body


# ---------------------------------------------------------------------------
# The real DDW row conventions (ISS-074)
# ---------------------------------------------------------------------------
#
# 80-01 made the state's real `.tab` file PARSE. These lock the three
# value-level conventions the retired 2021 `.csv` fixture invented differently,
# and which therefore stayed invisible right through v2.1:
#
#   1. dates are `MM-DD-YYYY`, not ISO      (40/40 rows)
#   2. a non-detect is a BLANK `Result` plus the
#      `Less Than Reporting Level` flag     (30/40 rows)
#   3. the sample type is DDW's code `RT`   (40/40 rows)
#
# Everything here is asserted against `drinking_sdwis4_slice.tab` — 40 genuine
# CA1010001 rows — rather than a hand-built file, because a hand-built fixture
# is exactly how these gaps hid for a whole milestone. The synthetic single
# rows below exist ONLY for the negative guards: the real file, being real,
# contains no `13-01-2026` and no blank result without the flag.


# What the 40 real rows are built to produce. Measured on the file during
# planning, not inferred.
DDW_NON_DETECT_ROWS = 30  # blank Result + Less Than Reporting Level = Y
DDW_VALUE_ROWS = 10  # a number in the Result cell
DDW_PS_CODE_COUNT = 18
DDW_EVENTS = 28  # distinct (point, date, time, type)


def _ddw_parse():
    """The real `.tab` fixture, through the importer's own front door."""
    return importer.parse_upload(
        _csv_file(TAB_FIXTURE.read_text(encoding="utf-8")), "SDWIS4.tab"
    )


# Facility type code -> the sampling-point vocabulary this platform uses.
_DDW_POINT_TYPES = {"WL": "source", "TP": "entry_point", "DS": "distribution"}


@pytest.fixture
def ddw_parsed(db):
    return _ddw_parse()


@pytest.fixture
def ddw_system(db, ddw_parsed):
    """CA1010001 with every sampling point the real file references.

    The PS Codes are READ OUT OF THE FIXTURE at test time rather than pasted
    in as a literal list. A hardcoded list silently rots the day the fixture is
    re-cut from a fresh state download, and the row-error count — the thing
    this phase's acceptance gate turns on — would start measuring the staleness
    of the list instead of the behaviour of the importer.
    """
    call_command("seed_drinking", verbosity=0)
    ws = WaterSystemFactory(pwsid="CA1010001", name="BAKMAN WATER COMPANY")

    facilities = {}
    points = {}
    for row in ddw_parsed["rows"]:
        ps_code = row["PS Code"].strip()
        if ps_code in points:
            continue
        facility_id = ps_code.split("_")[1]
        facility_type = row["Facility Type"].strip()
        if facility_id not in facilities:
            facilities[facility_id] = SystemFacilityFactory(
                system=ws, facility_id=facility_id, facility_type=facility_type
            )
        points[ps_code] = SamplingPointFactory(
            ps_code=ps_code,
            name=row["Sampling Point Name"].strip(),
            facility=facilities[facility_id],
            point_type=_DDW_POINT_TYPES.get(facility_type, "source"),
        )

    assert len(points) == DDW_PS_CODE_COUNT
    return {"system": ws, "points": points}


@pytest.fixture
def ddw_validated(ddw_system, ddw_parsed):
    mapping = importer.auto_map_columns(ddw_parsed["columns"])
    return importer.validate_rows(ddw_parsed["rows"], mapping)


# The mapping and row shape for the negative guards. Same logical fields the
# real header maps to, so a guard cannot pass by dodging the real code path.
_SYNTHETIC_MAPPING = {
    "ps_code": "PS Code",
    "sample_date": "Sample Date",
    "sample_type": "Sample Type",
    "analysis_date": "Analysis Date",
    "analyte_name": "Analyte Name",
    "result": "Result",
    "less_than_rl": "Less Than Reporting Level",
    "reporting_level": "Reporting Level",
}


def _synthetic_row(**overrides):
    row = {
        "PS Code": "CA1010001_011_011",
        "Sample Date": "03-27-2023",
        "Sample Type": "RT",
        "Analysis Date": "",
        "Analyte Name": "NITRATE",
        "Result": "1.0",
        "Less Than Reporting Level": "",
        "Reporting Level": "",
    }
    row.update(overrides)
    return row


def _validate_one(**overrides):
    return importer.validate_rows(
        [_synthetic_row(**overrides)], _SYNTHETIC_MAPPING
    )[0]


class TestRealDDWDates:
    """Gap 1 — 40/40 real rows carry `MM-DD-YYYY`, which `parse_date` rejects.

    32 of those 40 sample dates carry a second component greater than 12
    (`01-13-2026` and the like), which is impossible to read as `DD-MM`. That
    measurement is why a STRICT `%m-%d-%Y` is correct and a permissive or
    sniffing parser is not: a format that can silently swap month and day
    misdates lab evidence, and the swap is invisible for 12 days of every month.
    """

    def test_a_real_sample_date_is_read_as_month_first(self, ddw_validated):
        row = ddw_validated[0]  # Sample Date 03-27-2023
        assert row["errors"] == []
        assert row["data"]["sample_date"] == date(2023, 3, 27)

    def test_no_real_row_errors_on_its_sample_date(self, ddw_validated):
        offenders = [
            v["index"]
            for v in ddw_validated
            if any("is not a date" in e for e in v["errors"])
        ]
        assert offenders == []

    def test_a_real_analysis_date_is_read_without_a_warning(self, ddw_validated):
        row = ddw_validated[0]  # Analysis Date 03-28-2023
        assert row["data"]["analysis_date"] == date(2023, 3, 28)
        assert not [w for w in row["warnings"] if "Analysis date" in w]

    def test_iso_dates_still_parse(self, ddw_system):
        """Regression guard — the legacy `.csv` path is ISO and must not move."""
        row = _validate_one(
            **{"Sample Date": "2023-03-27", "Analysis Date": "2023-03-28"}
        )
        assert row["errors"] == []
        assert row["data"]["sample_date"] == date(2023, 3, 27)
        assert row["data"]["analysis_date"] == date(2023, 3, 28)

    def test_a_day_first_date_is_rejected_not_silently_swapped(self, ddw_system):
        """THE test that proves a strict `%m-%d-%Y` was added, not a permissive
        parser. `13-01-2026` has no month 13, so it is unreadable — not a
        licence to read it as 13 January."""
        row = _validate_one(**{"Sample Date": "13-01-2026"})
        assert any("is not a date" in e for e in row["errors"])
        assert row["data"]["sample_date"] is None

    def test_genuine_garbage_is_an_error_naming_both_accepted_formats(
        self, ddw_system
    ):
        row = _validate_one(**{"Sample Date": "not-a-date"})
        message = next(e for e in row["errors"] if "is not a date" in e)
        assert "YYYY-MM-DD" in message
        assert "MM-DD-YYYY" in message


class TestRealDDWNonDetects:
    """Gap 2 — 30/40 real rows report a non-detect as a BLANK `Result` cell
    plus `Less Than Reporting Level = Y` and a `Reporting Level`.

    Today the blank-cell check fires before the flag is ever consulted, so
    three quarters of a genuine export errors out. A non-detect is a BOUND:
    `result_value` stays NULL and the bound lives in `reporting_level`. It is
    never coerced to zero, and an absent result is still not a non-detect.
    """

    def test_a_blank_result_with_the_flag_is_a_bound_not_an_error(
        self, ddw_validated
    ):
        row = ddw_validated[0]  # blank Result, LT RL = Y, RL 0.500000000
        assert row["errors"] == []
        assert row["data"]["result_kind"] == RESULT_KIND_NUMERIC
        assert row["data"]["result_value"] is None
        assert row["data"]["less_than_rl"] is True
        assert row["data"]["reporting_level"] == Decimal("0.5")

    def test_no_real_row_errors_on_a_blank_result(self, ddw_validated):
        offenders = [
            v["index"]
            for v in ddw_validated
            if any("Result is blank" in e for e in v["errors"])
        ]
        assert offenders == []

    def test_a_blank_result_without_the_flag_is_still_an_error(self, ddw_system):
        """Absence of a result is not a non-detect. Nothing about an empty cell
        says the lab looked and found nothing."""
        row = _validate_one(**{"Result": "", "Less Than Reporting Level": ""})
        assert any("Result is blank" in e for e in row["errors"])

    def test_a_flagged_blank_with_no_reporting_level_is_an_error(self, ddw_system):
        """A bound with no level is not information. Nothing downstream stops
        it from rendering as `< None`, so it is refused at the door."""
        row = _validate_one(
            **{
                "Result": "",
                "Less Than Reporting Level": "Y",
                "Reporting Level": "",
            }
        )
        assert row["errors"], "a flagged blank with no level must not pass"
        assert any("Reporting Level" in e for e in row["errors"])
        assert row["data"].get("result_value") is None

    def test_the_retired_less_than_prefix_still_works(self, ddw_system):
        row = _validate_one(**{"Result": "<0.5"})
        assert row["errors"] == []
        assert row["data"]["less_than_rl"] is True
        assert row["data"]["result_value"] is None
        assert row["data"]["reporting_level"] == Decimal("0.5")

    def test_a_real_numeric_result_is_still_stored_as_a_value(self, ddw_validated):
        row = ddw_validated[1]  # CHROMIUM, HEX 2.5, LT RL = N
        assert row["errors"] == []
        assert row["data"]["result_value"] == Decimal("2.5")
        assert row["data"]["less_than_rl"] is False


class TestRealDDWSampleType:
    """Gap 3 — 40/40 real rows carry `Sample Type = RT`, DDW's code for a
    routine sample. Non-blocking, but it warns on every single row of a genuine
    export, which trains an operator to ignore the warning column entirely."""

    def test_the_ddw_routine_code_is_recognised_with_no_warning(
        self, ddw_validated
    ):
        row = ddw_validated[0]
        assert row["data"]["sample_type"] == "routine"
        assert not [w for w in row["warnings"] if "Sample type" in w]

    def test_no_real_row_warns_about_its_sample_type(self, ddw_validated):
        offenders = [
            v["index"]
            for v in ddw_validated
            if any("Sample type" in w for w in v["warnings"])
        ]
        assert offenders == []

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("routine", "routine"),
            ("Repeat", "repeat"),
            ("CONFIRMATION", "confirmation"),
            ("Special", "special"),
        ],
    )
    def test_the_platforms_own_vocabulary_still_passes_through(
        self, ddw_system, raw, expected
    ):
        row = _validate_one(**{"Sample Type": raw})
        assert row["data"]["sample_type"] == expected
        assert not [w for w in row["warnings"] if "Sample type" in w]

    def test_an_unrecognised_code_still_warns_and_records_routine(
        self, ddw_system
    ):
        row = _validate_one(**{"Sample Type": "ZQ"})
        assert row["data"]["sample_type"] == "routine"
        assert any("Sample type" in w for w in row["warnings"])

    def test_the_warning_echoes_the_code_as_the_file_wrote_it(self, ddw_system):
        """An operator searches their file for the string the warning shows.
        Lowercasing it means the search finds nothing."""
        row = _validate_one(**{"Sample Type": "ZQ"})
        warning = next(w for w in row["warnings"] if "Sample type" in w)
        assert "'ZQ'" in warning


class TestTheRealDDWSliceValidatesClean:
    """Phase 80's acceptance gate: feed the state's genuine export through the
    importer and get zero row errors, so PS Codes are actually exercised."""

    def test_every_real_row_validates_without_an_error(self, ddw_validated):
        errored = [
            (v["index"], v["errors"]) for v in ddw_validated if v["errors"]
        ]
        assert errored == []
        assert len(ddw_validated) == TAB_ROWS

    def test_the_rows_were_read_correctly_not_merely_uncomplained_about(
        self, ddw_validated
    ):
        """Zero errors is only half the claim. The SHAPE of the result set is
        the other half: 30 bounded non-detects and 10 measured values."""
        non_detects = [
            v
            for v in ddw_validated
            if v["data"]["less_than_rl"] and v["data"]["result_value"] is None
        ]
        values = [v for v in ddw_validated if v["data"]["result_value"] is not None]
        assert len(non_detects) == DDW_NON_DETECT_ROWS
        assert len(values) == DDW_VALUE_ROWS
        # Every non-detect carries the bound it is a bound OF.
        for row in non_detects:
            assert row["data"]["reporting_level"] is not None

    def test_only_new_analyte_warnings_remain(self, ddw_validated):
        """New-analyte warnings are the vocabulary-extension path working as
        designed. Nothing else should be left."""
        other = [
            w
            for v in ddw_validated
            for w in v["warnings"]
            if "new analyte" not in w
        ]
        assert other == []

    def test_the_whole_slice_commits_without_tripping_a_check_constraint(
        self, ddw_validated
    ):
        counts = importer.commit_rows(ddw_validated)
        assert counts["skipped"] == 0
        assert counts["results"] == TAB_ROWS
        assert counts["events"] == DDW_EVENTS
        assert SampleResult.objects.count() == TAB_ROWS
        assert SampleEvent.objects.count() == DDW_EVENTS
        # The bounds survived the write as bounds.
        assert (
            SampleResult.objects.filter(
                less_than_rl=True, result_value__isnull=True
            ).count()
            == DDW_NON_DETECT_ROWS
        )
        assert (
            SampleResult.objects.filter(result_value__isnull=False).count()
            == DDW_VALUE_ROWS
        )

    def test_every_ps_code_in_the_file_is_actually_exercised(
        self, ddw_validated, ddw_system
    ):
        """Phase 80's gate is not merely "no errors" — it is that the PS Codes
        get exercised at all. Until this plan landed, every row died on its date
        or its blank Result BEFORE the sampling-point lookup meant anything, so
        a clean run proved nothing about the lookup. Assert the file's 18
        distinct codes each carried at least one result through to the DB."""
        importer.commit_rows(ddw_validated)
        landed = set(
            SampleEvent.objects.values_list(
                "sampling_point__ps_code", flat=True
            )
        )
        assert landed == set(ddw_system["points"])
        assert len(landed) == DDW_PS_CODE_COUNT
