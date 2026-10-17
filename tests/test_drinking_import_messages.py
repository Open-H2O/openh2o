# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab results import's messages and the code changes made with
them (150.1-02).

Each test pins a behaviour the old code got wrong, not only a wording: the
file picker let only a .csv be chosen although the importer reads the
Division of Drinking Water's .tab file; a 25.5 MB file read "25 MB" against a
25 MB cap; an empty file and a file of column names alone read the same.
"""
import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from drinking import importer


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"labmsguser{n}")
    email = factory.Sequence(lambda n: f"labmsguser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _preview(client, name, text):
    upload = SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")
    return client.post(reverse("drinking:import_preview"), {"file": upload})


class TestTheImportPage:
    def test_the_picker_accepts_the_files_the_importer_reads(self, auth_client):
        body = auth_client.get(reverse("drinking:import")).content.decode()
        assert 'accept=".csv,.tab,.txt"' in body

    def test_the_page_says_what_it_imports_and_when_it_saves(self, auth_client):
        body = auth_client.get(reverse("drinking:import")).content.decode()
        assert "This page imports sample results from a lab results file." in body
        assert "OpenH2O saves nothing until you press Import on the preview." in body
        assert "A .csv, .tab or .txt file of up to 5,000 rows and 25 MB." in body
        assert "Upload only the rows for the water systems on file." in body
        assert "SDWIS.CSV export" not in body


class TestWholeFileMessages:
    def test_no_file(self, auth_client):
        body = auth_client.post(reverse("drinking:import_preview"), {}).content.decode()
        assert "Choose a lab results file to upload." in body

    def test_a_tab_file_is_read(self, auth_client):
        body = _preview(
            auth_client, "SDWIS4.tab",
            "PS Code\tSample Date\tAnalyte Name\tResult\nX_1_1\t2024-01-02\tNitrate\t1\n",
        ).content.decode()
        assert "This page imports" not in body
        assert "Import 1 result" not in body  # the point is not on file
        assert "Preview" in body

    def test_wrong_type(self, auth_client):
        body = _preview(auth_client, "lab.xlsx", "x").content.decode()
        assert (
            "This page imports .csv, .tab and .txt files only. Save the file as "
            "CSV and upload it again."
        ) in body

    def test_one_missing_column_is_named_alone(self, auth_client):
        body = _preview(
            auth_client, "lab.csv", "PS Code,Sample Date,Analyte Name\nA,2024-01-01,N\n"
        ).content.decode()
        assert "This file has no Result column." in body

    def test_three_missing_columns(self):
        assert importer.missing_columns_message(
            ["sample_date", "analyte_name", "result"]
        ) == (
            "This file has no Sample Date, Analyte Name or Result column. "
            "The table below lists the columns OpenH2O imports."
        )


class TestTheImportStep:
    @pytest.mark.parametrize("rows_json", ["", "[]", "[1]", "not json"])
    def test_rows_not_received(self, auth_client, rows_json):
        body = auth_client.post(
            reverse("drinking:import_commit"), {"rows_json": rows_json}
        ).content.decode()
        assert (
            "OpenH2O did not receive the file&#x27;s rows from the preview. "
            "Upload the file again."
        ) in body or (
            "OpenH2O did not receive the file's rows from the preview. "
            "Upload the file again."
        ) in body

    def test_the_preview_button_reads_import(self, auth_client):
        body = _preview(
            auth_client, "lab.csv", "PS Code,Sample Date,Analyte Name,Result\n"
            "X_1_1,2024-01-02,Nitrate,1\n",
        ).content.decode()
        assert "Import 0 results" in body
        assert "Commit" not in body


class TestRowErrors:
    """The row-error messages."""

    MAPPING = {"ps_code": "Station", "sample_date": "Collection Date",
               "analyte_name": "Analyte Name", "result": "Result",
               "less_than_rl": "Less Than Reporting Level",
               "analysis_date": "Analysis Date"}

    def _one(self, **cells):
        row = {"Station": "X_1_1", "Collection Date": "2024-03-05",
               "Analyte Name": "Nitrate", "Result": "1",
               "Less Than Reporting Level": "", "Analysis Date": ""}
        row.update(cells)
        return importer.validate_rows([row], self.MAPPING)[0]

    def test_blank_cells_are_named_by_the_files_column(self, db):
        assert "Station is blank." in self._one(Station="")["errors"]
        assert "Collection Date is blank." in self._one(**{"Collection Date": ""})["errors"]
        assert "Analyte Name is blank." in self._one(**{"Analyte Name": ""})["errors"]

    def test_a_point_not_on_file(self, db):
        assert (
            "No sampling point on file has the PS Code X_1_1. Add the sampling "
            "point first, or correct the code in the file."
        ) in self._one()["errors"]

    def test_a_spreadsheet_date_is_read_month_first(self, db):
        row = self._one(**{"Collection Date": "3/5/2024", "Analysis Date": "3/7/2024"})
        assert row["data"]["sample_date"].isoformat() == "2024-03-05"
        assert row["data"]["analysis_date"].isoformat() == "2024-03-07"

    def test_an_unreadable_date(self, db):
        assert (
            "Collection Date '13/45/2024' is not a date written YYYY-MM-DD, "
            "MM-DD-YYYY or M/D/YYYY."
        ) in self._one(**{"Collection Date": "13/45/2024"})["errors"]

    def test_below_the_reporting_level_with_no_level(self, db):
        row = self._one(Result="", **{"Less Than Reporting Level": "Y"})
        assert (
            "This row reports the result as below the reporting level and gives "
            "no reporting level."
        ) in row["errors"]

    def test_an_unreadable_result(self, db):
        assert (
            "OpenH2O does not recognize the result 'high'. Use a number, a value "
            "below the reporting level such as <0.005, or P or A."
        ) in self._one(Result="high")["errors"]

    def test_the_page_names_the_date_formats(self, auth_client):
        body = auth_client.get(reverse("drinking:import")).content.decode()
        assert (
            "The date the sample was collected, written YYYY-MM-DD, MM-DD-YYYY "
            "or M/D/YYYY."
        ) in body

    def test_a_failure_at_import_keeps_its_details(self, db, monkeypatch):
        from drinking.models import SampleResult
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        row = {"Station": point.ps_code, "Collection Date": "2024-03-05",
               "Analyte Name": "Nitrate", "Result": "1",
               "Less Than Reporting Level": "", "Analysis Date": ""}
        validated = importer.validate_rows([row], self.MAPPING)

        def boom(**kwargs):
            raise ValueError("bad value")

        monkeypatch.setattr(SampleResult.objects, "create", boom)
        counts = importer.commit_rows(validated)
        assert counts["skipped"] == 1
        assert validated[0]["errors"] == [
            "An unexpected error stopped OpenH2O from saving this result. "
            "Details: ValueError: bad value"
        ]


class TestPreviewNotes:
    """The preview notes."""

    MAPPING = TestRowErrors.MAPPING | {
        "sample_time": "Sample Time", "sample_type": "Sample Type",
        "mcl_as_reported": "MCL", "dlr_as_reported": "DLR",
    }

    def _one(self, **cells):
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        row = {"Station": point.ps_code, "Collection Date": "2024-03-05",
               "Analyte Name": "Nitrate", "Result": "1",
               "Less Than Reporting Level": "", "Analysis Date": "",
               "Sample Time": "", "Sample Type": "", "MCL": "", "DLR": ""}
        row.update(cells)
        return importer.validate_rows([row], self.MAPPING)[0]

    @pytest.mark.parametrize("raw", ["9am", "25:99"])
    def test_an_unreadable_or_impossible_time_is_a_note(self, db, raw):
        row = self._one(**{"Sample Time": raw})
        assert row["errors"] == []
        assert (
            f"OpenH2O cannot read the Sample Time '{raw}' and will import this "
            "result without a time."
        ) in row["warnings"]

    def test_the_other_notes(self, db):
        row = self._one(**{"Sample Type": "XX", "MCL": "ten", "DLR": "n/a",
                           "Analysis Date": "2024-99-99"})
        assert row["warnings"] == [
            "OpenH2O does not recognize the sample type 'XX' and will record "
            "this sample as routine.",
            "No analyte on file is named Nitrate. OpenH2O will add Nitrate as a "
            "new analyte.",
            "OpenH2O cannot read the MCL 'ten' and will import this result "
            "without an MCL.",
            "OpenH2O cannot read the DLR 'n/a' and will import this result "
            "without a detection limit for purposes of reporting.",
            "OpenH2O cannot read the Analysis Date '2024-99-99' and will import "
            "this result without an analysis date.",
        ]

    def test_a_repeat_in_the_file_is_counted_apart(self, auth_client):
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        line = f"{point.ps_code},2024-03-05,Nitrate,1\n"
        body = _preview(
            auth_client, "lab.csv",
            "PS Code,Sample Date,Analyte Name,Result\n" + line + line,
        ).content.decode()
        assert "1 to import" in body
        assert "1 repeated in this file" in body
        assert "already on file</span>" not in body
        assert (
            "An earlier row in this file has the same result, so OpenH2O will "
            "skip this row."
        ) in body
        assert "rows were read" not in body
        assert "never written twice" not in body


class TestThePreviewsOtherLines:
    """The preview's status, blank-cell and box lines."""

    def test_status_blank_cells_and_the_box(self, auth_client):
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        good = f"{point.ps_code},2024-03-05,Nitrate,1\n"
        body = _preview(
            auth_client, "lab.csv",
            "PS Code,Sample Date,Analyte Name,Result\n" + good + good
            + "NOCODE,2024-03-05,Nitrate,1\n" + ",2024-03-05,Nitrate,1\n",
        ).content.decode()
        assert "Will import" in body
        assert "Will skip" in body
        assert ">Blank<" in body
        assert "Not recorded" not in body
        assert "Correct the rows below in the file and upload the file again." in body
        assert "matches no sampling point in OpenH2O." in body
        assert "Where to add the sampling point" in body
        assert "This PS Code is not in the form" in body
        assert "Correct the code in the file." in body
        assert "New analytes OpenH2O will add:" in body
        assert "Rows with a note" in body
        assert "Will create" not in body

    def test_column_labels(self):
        assert importer.FIELD_LABELS["lab_cert_no"] == "ELAP certificate number"
        assert importer.FIELD_LABELS["mcl_as_reported"] == "MCL"
        assert importer.FIELD_LABELS["dlr_as_reported"] == "DLR"


class TestThePageAfterImport:
    """The counts and lines on the page after an import."""

    def test_counts_and_lines(self, auth_client):
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        good = {"PS Code": point.ps_code, "Sample Date": "2024-03-05",
                "Analyte Name": "Nitrate", "Result": "1"}
        bad = dict(good, **{"PS Code": ""})
        body = auth_client.post(
            reverse("drinking:import_commit"),
            {"rows_json": json.dumps([good, good, bad])},
        ).content.decode()
        assert "1 result</span>" in body
        assert "1 repeated in this file" in body
        assert "already on file</span>" not in body
        assert "1 with errors" in body
        assert "3 rows read" in body
        assert "OpenH2O imported 1 sample result and added 1 sample event." in body
        assert "OpenH2O added 1 new analyte from this file." in body
        assert "Rows OpenH2O did not import" in body
        assert (
            "Correct these rows in the file and upload the file again. OpenH2O "
            "skips every row already on file."
        ) in body

    def test_three_agencies_state_the_rule(self, auth_client):
        from tests.factories import SamplingPointFactory

        point = SamplingPointFactory()
        rows = [
            {"PS Code": point.ps_code, "Sample Date": "2024-03-05",
             "Analyte Name": "Nitrate", "Result": str(n), "Regulating Agency": a}
            for n, a in enumerate(["A", "B", "C"], start=1)
        ]
        body = auth_client.post(
            reverse("drinking:import_commit"), {"rows_json": json.dumps(rows)}
        ).content.decode()
        assert (
            "The rows of this file name 3 different regulating agencies for "
            f"{point.facility.system.name}: A, B and C. OpenH2O records a "
            "regulating agency only when every row names the same agency."
        ) in body


class TestTheImportPagesTables:
    """The tables on the import page."""

    def test_the_tables(self, auth_client):
        body = auth_client.get(reverse("drinking:import")).content.decode()
        for line in (
            "What OpenH2O saves from a lab file",
            "OpenH2O imports each row that has no error, unless the same result "
            "is already on file or appears earlier in the file.",
            "OpenH2O never adds a sampling point or a facility from a lab file.",
            "Columns OpenH2O reads",
            "OpenH2O reads only the columns listed below.",
            "OpenH2O matches an analyte on file by Analyte Code first, then by "
            "Analyte Name.",
        ):
            assert line in body
        for gone in ("Will create", "What the commit does", "needs no mapping",
                     "the state&#x27;s file", "the state's file"):
            assert gone not in body

    def test_the_column_cells(self, auth_client):
        """The column cells."""
        body = auth_client.get(reverse("drinking:import")).content.decode()
        for line in (
            "OpenH2O stores the reporting level with every numeric result.",
            "OpenH2O records the collector only for a sample not already on file.",
            "OpenH2O stores the file&rsquo;s MCL with the result and does not "
            "compare the result with the MCL.",
            "The detection limit for purposes of reporting.",
        ):
            assert line in body
        assert "stored with a result below it" not in body


class TestRowNumbers:
    """Every import numbers rows as the spreadsheet does, the column names
    being row 1."""

    def test_the_lab_preview_and_result(self, auth_client):
        csv_text = "PS Code,Sample Date,Analyte Name,Result\n,2024-03-05,Nitrate,1\n"
        body = _preview(auth_client, "lab.csv", csv_text).content.decode()
        assert '<td class="text-mono">2</td>' in body
        body = auth_client.post(
            reverse("drinking:import_commit"),
            {"rows_json": json.dumps([{"PS Code": "", "Sample Date": "2024-03-05",
                                       "Analyte Name": "Nitrate", "Result": "1"}])},
        ).content.decode()
        assert '<td class="text-mono">2</td>' in body

    def test_the_water_rights_result(self, db):
        from django.template.loader import render_to_string

        html = render_to_string(
            "surface/partials/_right_import_result.html",
            {"created": 0, "skipped": [{"index": 0, "errors": ["x"]}], "total": 1},
        )
        assert '<td class="text-mono">2</td>' in html


class TestTheProductionImport:
    """The production import page."""

    def test_the_page(self, auth_client):
        body = auth_client.get(reverse("drinking:production_import")).content.decode()
        assert "This page imports monthly production figures from a CSV file" in body
        assert "OpenH2O saves nothing until you press Import on the preview." in body
        assert "OpenH2O skips a row whose month and type of water are already on file." in body
        assert "A CSV file of up to 2,000 rows and 25 MB." in body
        assert "Production file" in body

    def test_whole_file_messages(self):
        from drinking import production_import as svc

        class F:
            size = svc.MAX_UPLOAD_BYTES + 512 * 1024

            def read(self):
                return b""

        with pytest.raises(ImportError, match="This file is 26 MB"):
            svc.parse_csv(F(), "p.csv")
        with pytest.raises(ImportError, match="This page imports CSV files only"):
            svc.parse_csv(F(), "p.xlsx")
        with pytest.raises(ImportError, match="OpenH2O does not recognize the columns in this file: Well, Date"):
            svc.recognise_layout(["Well", "Date"])


class TestTheProductionRowErrors:
    """The production import's row errors."""

    E = ("PWSID,Year,Month,DateStartOfMonth,TypeCode,"
         "Units of Measure As Reported,Quantity as in Units Reported\n")

    def _errors(self, system, *lines):
        from drinking import production_import as svc

        columns, rows = svc.parse_csv(
            __import__("io").StringIO(self.E + "\n".join(lines) + "\n"), "p.csv"
        )
        return [e["message"] for e in svc.import_production_rows(
            columns, rows, system=system, dry_run=True)["errors"]]

    def test_the_messages(self, db):
        from tests.factories import WaterSystemFactory

        ws = WaterSystemFactory(pwsid="CA2410009")
        assert self._errors(ws, ",2024,May,,GW,G,1") == ["PWSID is blank."]
        assert self._errors(ws, "CA9999999,2024,May,,GW,G,1") == [
            "This row's PWSID CA9999999 does not match the water system's "
            "PWSID CA2410009."]
        assert self._errors(ws, "CA2410009,20x4,May,,GW,G,1") == ["Year '20x4' is not a year."]
        assert self._errors(ws, "CA2410009,2024,Smarch,13/45/2024,GW,G,1") == [
            "OpenH2O cannot read a month from Month 'Smarch' or DateStartOfMonth "
            "'13/45/2024'."]
        assert self._errors(ws, "CA2410009,2024,May,,Well,lbs,") == [
            "OpenH2O does not recognize the TypeCode 'Well'. Use GW, SW, "
            "Purchased, Sold, Recycled, NonPotable or NonPotableSold. "
            "OpenH2O does not recognize the unit 'lbs'. Use G, MG, AF or CCF. "
            "Quantity as in Units Reported is blank."]
        assert self._errors(ws, "CA2410009,2024,May,,GW,,1") == [
            "Units of Measure As Reported is blank. Choose a unit for blank rows "
            "in the settings above, then press Update preview."]

    def test_a_log_with_no_year_asks_under_the_year_box(self, auth_client):
        from tests.factories import WaterSystemFactory

        WaterSystemFactory()
        log = ("Date/Month,Water Produced from Groundwater (Wells)\n"
               "January,100\n")
        upload = SimpleUploadedFile("log.csv", log.encode(), content_type="text/csv")
        body = auth_client.post(
            reverse("drinking:production_import_preview"), {"file": upload}
        ).content.decode()
        assert "Enter the report year above, then press Update preview." in body
        assert "carries no year;" not in body
        rows = json.dumps([{"Date/Month": "January",
                            "Water Produced from Groundwater (Wells)": "100"}])
        body = auth_client.post(
            reverse("drinking:production_import_commit"), {"rows_json": rows}
        ).content.decode()
        assert "Enter the report year above, then press Update preview." in body

    def test_the_preview_and_result_lines(self, auth_client):
        """The preview and result lines."""
        from tests.factories import WaterSystemFactory

        ws = WaterSystemFactory(pwsid="CA2410009")
        csv_text = self.E + "CA2410009,2024,May,,GW,G,1\nCA2410009,2024,May,,GW,G,1\n,2024,June,,GW,G,1\n"
        upload = SimpleUploadedFile("p.csv", csv_text.encode(), content_type="text/csv")
        body = auth_client.post(
            reverse("drinking:production_import_preview"), {"file": upload}
        ).content.decode()
        for line in ("3 rows from an eAR export", "1 to import", "1 repeated in this file",
                     "1 with errors", "Rows with errors", "What is wrong",
                     "OpenH2O applies this unit to every row that gives no unit.",
                     ">Not chosen<"):
            assert line in body, line
        rows = json.dumps([{"PWSID": "CA2410009", "Year": "2024", "Month": "May",
                            "DateStartOfMonth": "", "TypeCode": "GW",
                            "Units of Measure As Reported": "G",
                            "Quantity as in Units Reported": "1"}])
        body = auth_client.post(
            reverse("drinking:production_import_commit"), {"rows_json": rows}
        ).content.decode()
        assert "1 imported" in body
        assert "OpenH2O imported 1 production record." in body
        assert ws.production_records.count() == 1

    def test_the_column_tables(self, auth_client):
        """The column tables."""
        body = auth_client.get(reverse("drinking:production_import")).content.decode()
        for line in ("Columns OpenH2O reads", "The eAR export",
                     "A monthly log on the eAR template",
                     "The sum of groundwater, surface water and purchased water. "
                     "OpenH2O does not read this column.",
                     "At least one of the six", "Gallons is the default."):
            assert line in body, line
        assert "totals the source columns above" not in body


class TestThePointBuilder:
    """The point builder's messages."""

    def test_the_ps_code_messages(self):
        from drinking.ps_codes import compose_ps_code

        cases = {
            "": "Enter the point number.",
            "A_1": "The point number 'A_1' contains an underscore. A PS Code uses "
                   "underscores only between its three parts.",
            "A 1": "The point number 'A 1' contains a space. A PS Code uses only "
                   "letters, digits and hyphens, such as 010, DST or LCR.",
            "A#1": "The point number 'A#1' contains the character '#'. A PS Code "
                   "uses only letters, digits and hyphens, such as 010, DST or LCR.",
        }
        for value, message in cases.items():
            with pytest.raises(ValueError) as exc:
                compose_ps_code("CA2410009", "001", value)
            assert str(exc.value) == message
        with pytest.raises(ValueError, match="has 64 characters, and OpenH2O stores "
                                             "PS Codes of up to 60. Shorten the point number."):
            compose_ps_code("CA2410009", "001", "X" * 50)
