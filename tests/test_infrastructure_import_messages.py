# SPDX-License-Identifier: AGPL-3.0-or-later
"""The infrastructure import's messages and the code changes Brent approved
with them (150.1-02 screen 18, message V, 2026-10-15 17:55).

Each test pins a behaviour the old code got wrong, not only a wording: a
damaged GeoJSON, KML or zip file was a server error (the page showed
nothing); a points of diversion, storage pond or recharge site file imported
twice created every record twice; an empty CSV and a CSV of column names only
read the same; the size was floored.
"""
import io
import json
import zipfile

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from infrastructure import importer
from wells.models import Well


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"inframsguser{n}")
    email = factory.Sequence(lambda n: f"inframsguser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _upload(name, content):
    return SimpleUploadedFile(name, content if isinstance(content, bytes) else content.encode())


def _preview(client, name, content, infra_type="well"):
    data = {"infra_type": infra_type}
    if name is not None:
        data["file"] = _upload(name, content)
    resp = client.post(reverse("infrastructure:import_preview"), data)
    assert resp.status_code == 200
    return resp.content.decode().replace("&#x27;", "'")


class TestWholeFileMessages:
    def test_no_file(self, auth_client):
        assert "Choose a file to upload." in _preview(auth_client, None, "")

    def test_wrong_type(self, auth_client):
        assert (
            "This page imports .csv, .zip, .geojson, .json and .kml files only. "
            "Save the file as CSV and upload it again."
        ) in _preview(auth_client, "wells.txt", "x")

    def test_size_rounded_up(self):
        f = _upload("wells.csv", "name\nA\n")
        f.size = importer.MAX_UPLOAD_BYTES + 512 * 1024
        with pytest.raises(ImportError, match="This file is 26 MB. OpenH2O imports files of up to 25 MB."):
            importer.parse_upload(f, "wells.csv")

    def test_empty_csv_and_column_names_only_told_apart(self, auth_client):
        assert "This file has no column names on its first line." in _preview(
            auth_client, "wells.csv", ""
        )
        assert "This file has column names but no rows below them." in _preview(
            auth_client, "wells.csv", "name,lat,lon\n"
        )

    def test_row_cap_csv_and_map_file(self, auth_client):
        csv_text = "name,lat,lon\n" + "".join(f"W{i},37.3,-120.5\n" for i in range(501))
        assert (
            "This file has 501 rows, and OpenH2O imports up to 500 rows from one "
            "file. Split the file and import each part."
        ) in _preview(auth_client, "wells.csv", csv_text)
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-120.5, 37.3]},
             "properties": {"name": f"W{i}"}}
            for i in range(501)
        ]
        gj = json.dumps({"type": "FeatureCollection", "features": features})
        assert (
            "This file has 501 map features, and OpenH2O imports up to 500 map "
            "features from one file. Split the file and import each part."
        ) in _preview(auth_client, "wells.geojson", gj)

    def test_map_file_with_no_features(self, auth_client):
        gj = json.dumps({"type": "FeatureCollection", "features": []})
        assert "This file has no map features." in _preview(auth_client, "wells.geojson", gj)

    @pytest.mark.parametrize("content", ["{not json", "[1, 2]", "\xff\xfe"])
    def test_damaged_geojson_is_a_sentence_not_a_500(self, auth_client, content):
        assert (
            "OpenH2O cannot read this file as GeoJSON. Check that the file opens "
            "in a GIS program, then upload it again."
        ) in _preview(auth_client, "wells.geojson", content.encode("latin-1"))

    def test_damaged_kml_is_a_sentence_not_a_500(self, auth_client):
        assert (
            "OpenH2O cannot read this file as KML. Check that the file opens in a "
            "GIS program, then upload it again."
        ) in _preview(auth_client, "wells.kml", "<kml>")

    def test_damaged_zip_is_a_sentence_not_a_500(self, auth_client):
        assert "OpenH2O cannot open this file as a zip archive." in _preview(
            auth_client, "wells.zip", "notazip"
        )

    def test_unreadable_shapefile_in_a_zip(self, auth_client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("wells.shp", b"not a shapefile")
        assert (
            "OpenH2O cannot read the shapefile in this zip file. Check that the "
            "file opens in a GIS program, then upload it again."
        ) in _preview(auth_client, "wells.zip", buf.getvalue())

    def test_rows_not_received_at_create(self, auth_client):
        resp = auth_client.post(
            reverse("infrastructure:import_commit"), {"infra_type": "well", "rows_json": ""}
        )
        body = resp.content.decode().replace("&#x27;", "'")
        assert (
            "OpenH2O did not receive the file's rows from the preview. Upload the file again."
        ) in body

    def test_row_cap_at_create_names_map_features_for_a_map_file(self, auth_client):
        rows = [{"name": f"W{i}", importer.GEOMETRY_COL: ""} for i in range(501)]
        resp = auth_client.post(
            reverse("infrastructure:import_commit"),
            {"infra_type": "well", "rows_json": json.dumps(rows)},
        )
        assert "This file has 501 map features" in resp.content.decode()


class TestImportPage:
    def test_well_page_lines(self, auth_client):
        body = auth_client.get(reverse("infrastructure:import") + "?type=well").content.decode()
        body = body.replace("&#x27;", "'").replace("&hellip;", "…")
        assert (
            "This page imports well records from a CSV file, a zipped shapefile, "
            "a GeoJSON file or a KML file."
        ) in body
        assert "OpenH2O saves nothing until you press Create." in body
        assert (
            "OpenH2O skips a row whose name or registration ID is already on file "
            "or appears earlier in the file."
        ) in body
        assert "To enter one well record by hand, use" in body
        assert "A file of up to 500 rows or map features and 25 MB." in body
        assert "Reading the file…" in body
        assert "A row already on file" not in body

    def test_point_of_diversion_page_lines(self, auth_client):
        body = auth_client.get(reverse("infrastructure:import") + "?type=diversion").content.decode()
        assert "This page imports point of diversion records from a CSV file" in body
        assert (
            "OpenH2O skips a row whose name is already on file or appears earlier "
            "in the file."
        ) in body
        assert "To enter one point of diversion record by hand, use" in body


@pytest.mark.django_db
class TestRowsAlreadyOnFile:
    def _validate(self, infra_type, rows):
        mapping = {"name": "name", "latitude": "lat", "longitude": "lon"}
        return importer.validate_rows(
            rows, mapping, infra_type, set(),
            existing_names=importer.existing_names(infra_type),
        )

    def test_well_name_already_on_file_is_skipped(self):
        Well.objects.create(name="North Well", location=Point(-120.5, 37.3, srid=4326))
        results = self._validate("well", [{"name": "North Well", "lat": "37.3", "lon": "-120.5"}])
        assert results[0]["errors"]

    def test_point_of_diversion_imported_twice_creates_it_once(self):
        rows = [{"name": "Headgate 9", "lat": "37.3", "lon": "-120.5"}]
        from surface.models import PointOfDiversion

        before = PointOfDiversion.objects.count()
        importer.commit_rows(self._validate("diversion", rows), "diversion")
        importer.commit_rows(self._validate("diversion", rows), "diversion")
        assert PointOfDiversion.objects.count() == before + 1

    def test_name_repeated_in_the_file_is_skipped(self):
        rows = [
            {"name": "Pond A", "lat": "37.3", "lon": "-120.5"},
            {"name": "Pond A", "lat": "37.4", "lon": "-120.5"},
        ]
        results = self._validate("storage", rows)
        assert results[0]["errors"] == []
        assert results[1]["errors"]


class TestMatchingStep:
    """Message W (2026-10-15 18:12): the column table and the matching step."""

    def test_page_table(self, auth_client):
        body = auth_client.get(reverse("infrastructure:import") + "?type=storage").content.decode()
        body = body.replace("&#x27;", "'").replace("&rsquo;", "'")
        assert "Columns OpenH2O reads" in body
        assert "The storage pond's name." in body
        assert "For a line or an area, OpenH2O records the center point." in body
        assert "On the next step, OpenH2O matches each column to a field by name." in body

    def test_csv_matching_step(self, auth_client):
        body = _preview(auth_client, "wells.csv", "name,lat,lon,Casing Dia\nW1,37.3,-120.5,8\n")
        assert "Match the file's columns" in body
        assert (
            "OpenH2O found <strong>1</strong> row and <strong>4</strong> columns, and "
            "matched the fields below to the file's columns by name. Change any match "
            "that is wrong, then press Create."
        ) in body
        assert ">Not imported<" in body
        assert "Local registration ID" in body
        assert "The file's first 1 row" in body
        assert "__geometry__<" not in body

    def test_map_file_matching_step(self, auth_client):
        gj = json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [
                [[-120.5, 37.3], [-120.4, 37.3], [-120.4, 37.4], [-120.5, 37.3]]]},
             "properties": {"name": "Pond A"}},
        ]})
        body = _preview(auth_client, "ponds.geojson", gj, infra_type="storage")
        assert "OpenH2O found <strong>1</strong> map feature and" in body
        assert "The file's first 1 map feature" in body
        assert ">The file's geometry</option>" in body
        assert "<td>Polygon</td>" in body
        assert "coordinates" not in body.split("The file's first")[1]
        assert ">Geometry<" in body

    def test_sample_cell_shows_the_shape_type(self):
        assert importer.sample_cell(importer.GEOMETRY_COL, '{"type": "Point", "coordinates": [1, 2]}') == "Point"
        assert importer.sample_cell("depth", "200") == "200"


@pytest.mark.django_db
class TestRowErrors:
    """Message X (2026-10-15 18:25): the row errors, the field in plain words."""

    MAPPING = {
        "name": "NAME", "latitude": "lat", "longitude": "lon", "geometry": "geom",
        "well_registration_id": "reg", "casing_diameter_in": "Casing Dia",
        "year_pumping_began": "Year Drilled",
    }

    def _errors(self, row, infra_type="well", mapping=None):
        base = {"NAME": "W1", "lat": "37.3", "lon": "-120.5", "geom": "", "reg": "",
                "Casing Dia": "", "Year Drilled": ""}
        base.update(row)
        return importer.validate_rows([base], mapping or self.MAPPING, infra_type, set())[0]["errors"]

    def test_name_blank(self):
        assert self._errors({"NAME": ""}) == ["The name is blank."]

    def test_not_a_number_and_not_a_year(self):
        assert self._errors({"Casing Dia": "eight", "Year Drilled": "19x0"}) == [
            "The year pumping began is '19x0', which is not a year.",
            "The casing diameter is 'eight', which is not a number.",
        ]

    def test_each_bad_location_value_its_own_sentence(self):
        assert self._errors({"lat": "abc", "lon": ""}) == [
            "The latitude is 'abc', which is not a number.",
            "The longitude is blank.",
        ]
        assert self._errors({"lat": "", "lon": ""}) == [
            "This row has no location. Fill in the latitude and longitude."
        ]

    def test_geometry_unreadable(self):
        assert self._errors({"geom": "POINT(abc)"}) == [
            "The geometry is 'POINT(abc)', which OpenH2O cannot read as GeoJSON or WKT."
        ]

    def test_map_feature_messages(self):
        mapping = {"name": "name", "geometry": importer.GEOMETRY_COL}
        rows = [
            {"name": "A", importer.GEOMETRY_COL: ""},
            {"name": "B", importer.GEOMETRY_COL: '{"type": "Point", "coordinates": ["x", 1]}'},
        ]
        results = importer.validate_rows(rows, mapping, "well", set())
        assert results[0]["errors"] == ["This feature has no geometry."]
        assert results[1]["errors"] == ["OpenH2O cannot read this feature's geometry."]

    def test_geometry_held_to_the_united_states_check(self):
        """Code change: a geometry was checked only against the world."""
        assert self._errors({"geom": '{"type": "Point", "coordinates": [120.5, 37.3]}'}) == [
            "location (37.3, 120.5) is outside the United States; check the sign of the longitude."
        ]
        assert self._errors({"geom": '{"type": "Point", "coordinates": [999, 999]}'}) == [
            "location (999.0, 999.0) is outside the United States; check the sign of the longitude."
        ]

    def test_names_already_on_file_and_repeated(self):
        Well.objects.create(name="North Well", location=Point(-120.5, 37.3, srid=4326))
        rows = [
            {"NAME": "North Well", "lat": "37.3", "lon": "-120.5"},
            {"NAME": "South Well", "lat": "37.3", "lon": "-120.5"},
            {"NAME": "South Well", "lat": "37.3", "lon": "-120.5"},
        ]
        results = importer.validate_rows(
            rows, {"name": "NAME", "latitude": "lat", "longitude": "lon"}, "well", set(),
            existing_names=importer.existing_names("well"),
        )
        assert results[0]["errors"] == ["The name North Well is already on file."]
        assert results[1]["errors"] == []
        assert results[2]["errors"] == ["The name South Well appears earlier in this file."]

    def test_save_failure_keeps_its_details(self, monkeypatch):
        results = importer.validate_rows(
            [{"NAME": "W9", "lat": "37.3", "lon": "-120.5"}],
            {"name": "NAME", "latitude": "lat", "longitude": "lon"}, "well", set(),
        )

        def _boom(**kwargs):
            raise ValueError("synthetic")

        monkeypatch.setattr(Well.objects, "create", _boom)
        assert importer.commit_rows(results, "well") == 0
        assert results[0]["errors"] == [
            "An unexpected error stopped OpenH2O from saving this record. "
            "Details: ValueError: synthetic"
        ]


class TestMatchingStepRefusals:
    @pytest.mark.parametrize("mapping,sentence", [
        ({"map:latitude": "lat", "map:longitude": "lon"},
         "Choose the file's column for the name, then press Create."),
        ({"map:name": "name", "map:latitude": "lat"},
         "Choose the file's columns for latitude and longitude, or the file's "
         "geometry column, then press Create."),
    ])
    def test_refusal_keeps_the_matching_step(self, auth_client, mapping, sentence):
        rows = [{"name": "W1", "lat": "37.3", "lon": "-120.5"}]
        before = Well.objects.count()
        resp = auth_client.post(
            reverse("infrastructure:import_commit"),
            {"infra_type": "well", "rows_json": json.dumps(rows), **mapping},
        )
        body = resp.content.decode().replace("&#x27;", "'")
        assert sentence in body
        assert 'name="rows_json"' in body
        assert Well.objects.count() == before
