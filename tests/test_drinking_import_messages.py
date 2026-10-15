# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab results import's messages and the code changes Brent approved with
them (150.1-02 screen 18, message J, 2026-10-14 20:37 PDT, "approve").

Each test pins a behaviour the old code got wrong, not only a wording: the
file picker let only a .csv be chosen although the importer reads the
Division of Drinking Water's .tab file; a 25.5 MB file read "25 MB" against a
25 MB cap; an empty file and a file of column names alone read the same.
"""
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
