# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-200: the Setup Wizard's boundary drop reads a zipped shapefile and a KML,
not only GeoJSON.

Before this, step 1 refused the format most district GIS staff hand out. Measured
2026-10-08 (READER-TASKS-150-03.md, "The wizard's boundary drop, today"): a
shapefile zip got "That file couldn't be read as text ... not a shapefile or a
zip archive", a KML got "The file isn't valid JSON ...", while the bulk importer
at /infrastructure/import/ already read both.

The design these tests are written to (150-03 Task 4):

  * ``core/geofiles.py`` holds the zip and KML readers moved out of
    ``infrastructure/importer.py`` (with ``MAX_UPLOAD_BYTES`` and
    ``MAX_EXTRACTED_BYTES``), plus ``features_from_upload(uploaded_file)``,
    which dispatches on the extension and refuses any other one in words that
    name the three formats. ``core`` is a module every deployment gets, so
    ``setup`` reading it adds no edge to an optional module.
  * ``setup.boundaries.boundary_from_upload(uploaded_file, *, fallback_name)``
    returns ``(name, geometry, attrs, polygon_count)``: every polygon kept,
    points and lines dropped, reprojected to EPSG:4326, dissolved into one
    MultiPolygon, ``polygon_count`` the number of polygons combined.
  * the wizard stores ``polygon_count`` in the session under
    ``setup_wizard_polygon_count`` and the confirm step says "N polygons
    combined" when N > 1.

The fixtures under ``tests/fixtures/boundaries/`` are one square near Merced,
-120.6,37.2 to -120.5,37.3, written by ``ogr2ogr`` (GDAL 3.10) in the web
container; the KMLs are hand-written. ``two-squares.zip`` adds a second,
disjoint square at -120.4,37.2 to -120.3,37.3.

Every expected sentence below is pasted as a literal. A sentence the view
renders goes through ``{{ error }}``, which escapes an apostrophe, so the
assertions read ``response.context["errors"]`` (the raw strings) and the new
sentences carry no apostrophe at all.
"""
import io
import re
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from geography.models import Boundary

User = get_user_model()

FIXTURES = Path(__file__).parent / "fixtures" / "boundaries"

WIZARD_URL = reverse("setup:wizard")
CONFIRM_URL = reverse("setup:confirm")

# The upload form's file input name (templates/setup/wizard.html). Kept as
# geojson_file; TestTheDropZone checks the template still uses it.
FILE_FIELD = "geojson_file"

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"
SESSION_KEY_POLYGON_COUNT = "setup_wizard_polygon_count"

# The square every single-polygon fixture holds, as (xmin, ymin, xmax, ymax).
SQUARE_EXTENT = (-120.6, 37.2, -120.5, 37.3)

# --- Sentences the new code must say, verbatim ------------------------------

DROP_ZONE_SENTENCE = (
    "Drag and drop a zipped shapefile (.zip), a KML (.kml) or a GeoJSON "
    "(.geojson or .json) file here, or click to browse."
)
UNSUPPORTED_SENTENCE = (
    "That file type cannot be read here. Upload a zipped shapefile (.zip), "
    "a KML (.kml) or a GeoJSON (.geojson or .json) file."
)
NO_POLYGON_SENTENCE = (
    "That file holds no polygon, only points or lines. The boundary must be "
    "an area outline, in a zipped shapefile (.zip), a KML (.kml) or a GeoJSON "
    "(.geojson or .json) file."
)
NO_FILE_SENTENCE = (
    "Please choose a boundary file to upload: a zipped shapefile (.zip), "
    "a KML (.kml) or a GeoJSON (.geojson or .json) file."
)
NOT_TEXT_SENTENCE = (
    "That file could not be read as text, so it is not GeoJSON. Upload a "
    "zipped shapefile (.zip), a KML (.kml) or a GeoJSON (.geojson or .json) file."
)
NOT_JSON_SENTENCE = (
    "The file is not valid JSON, so it is not GeoJSON. Upload a zipped "
    "shapefile (.zip), a KML (.kml) or a GeoJSON (.geojson or .json) file."
)

# --- Sentences the importer already says, moved with its readers -------------

NO_SHP_SENTENCE = "No .shp file found in archive."
UNSAFE_PATH_SENTENCE = "Unsafe path in archive: '../evil.shp'."
# The cap figure is MAX_UPLOAD_BYTES in whole MB, so a test that shrinks the
# cap to bytes reads "0 MB"; the phrase after the figure is what is pinned.
UPLOAD_CAP_PHRASE = "MB upload cap."
ZIP_BOMB_PHRASE = "refusing to extract (possible zip bomb)."

# --- GeoJSON-shaped failures that keep today's wording -----------------------
# (two of today's three carry an em dash mid-sentence, so the part before it
# is pinned; the third is pinned whole)

GEOJSON_EMPTY_COLLECTION = (
    "The GeoJSON FeatureCollection is empty"
)
GEOJSON_POINT_GEOMETRY = (
    "The boundary geometry is a Point, but a Polygon or MultiPolygon is required"
)
GEOJSON_NO_GEOMETRY = (
    "No geometry found in the file. Provide a GeoJSON Feature or "
    "FeatureCollection whose feature has Polygon or MultiPolygon geometry."
)

# Today's GeoJSON-only advice, which must be gone from every refusal.
OLD_EXPORT_GEOJSON_ADVICE = ("make sure you exported GeoJSON", "check you exported GeoJSON")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _admin_client():
    user = User.objects.create_user(
        username="wizard-admin-200", email="wizard-admin-200@example.com",
        password="x", is_active=True, is_staff=True, is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _fixture_bytes(filename):
    return (FIXTURES / filename).read_bytes()


def _upload_file(filename, data=None):
    if data is None:
        data = _fixture_bytes(filename)
    return SimpleUploadedFile(filename, data)


def _post(client, filename, data=None):
    return client.post(
        WIZARD_URL, {"action": "upload", FILE_FIELD: _upload_file(filename, data)},
    )


def _errors(resp):
    """The wizard re-rendered with its errors: the raw error strings."""
    assert resp.status_code == 200, (
        f"expected the wizard to re-render with an error, got {resp.status_code}"
    )
    return list(resp.context["errors"])


def _assert_lands_on_confirm(resp):
    assert resp.status_code == 302, (
        f"upload did not redirect; errors: {resp.context and resp.context.get('errors')}"
    )
    assert resp["Location"] == CONFIRM_URL


def _assert_extent(geom, expected, tolerance):
    for got, want in zip(geom.extent, expected):
        assert got == pytest.approx(want, abs=tolerance), (geom.extent, expected)


def _zip_slip_bytes():
    """The in-memory zip test_upload_hardening.py uses for the zip-slip guard."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.shp", b"pwned")
    return buf.getvalue()


def _kml(*placemarks):
    """A KML document holding the given <Placemark> bodies."""
    body = "".join(f"<Placemark>{p}</Placemark>" for p in placemarks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"{body}"
        "</Document></kml>"
    ).encode()


def _kml_square(name, west, south, east, north):
    ring = (
        f"{west},{south},0 {east},{south},0 {east},{north},0 "
        f"{west},{north},0 {west},{south},0"
    )
    return (
        f"<name>{name}</name><Polygon><outerBoundaryIs><LinearRing>"
        f"<coordinates>{ring}</coordinates>"
        "</LinearRing></outerBoundaryIs></Polygon>"
    )


# --------------------------------------------------------------------------
# One test per format, through the wizard view
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestEachFormatThroughTheWizard:

    def test_zipped_shapefile_becomes_a_boundary(self):
        client = _admin_client()
        resp = _post(client, "square.zip")
        _assert_lands_on_confirm(resp)

        boundary = Boundary.objects.get()
        assert boundary.name == "Merced Test Square"
        assert boundary.geometry.geom_type == "MultiPolygon"
        assert boundary.geometry.srid == 4326
        assert boundary.geometry.num_geom == 1
        assert boundary.geometry.valid
        _assert_extent(boundary.geometry, SQUARE_EXTENT, 1e-6)
        assert client.session[SESSION_KEY_BOUNDARY] == boundary.pk
        assert client.session[SESSION_KEY_POLYGON_COUNT] == 1

    def test_kml_becomes_a_boundary(self):
        """KML coordinates carry an altitude (GDAL reads them as 3D); the
        Boundary column is a 2D MultiPolygon, so the Z must not reach it. The
        KML driver names the property ``Name``, capitalised."""
        client = _admin_client()
        resp = _post(client, "square.kml")
        _assert_lands_on_confirm(resp)

        boundary = Boundary.objects.get()
        assert boundary.name == "Merced Test Square"
        assert boundary.geometry.geom_type == "MultiPolygon"
        assert boundary.geometry.srid == 4326
        assert boundary.geometry.num_geom == 1
        assert not boundary.geometry.hasz
        assert boundary.geometry.valid
        _assert_extent(boundary.geometry, SQUARE_EXTENT, 1e-6)
        assert client.session[SESSION_KEY_POLYGON_COUNT] == 1

    @pytest.mark.parametrize("filename", ["square.geojson", "square.json"])
    def test_geojson_still_becomes_a_boundary(self, filename):
        client = _admin_client()
        resp = _post(client, filename, _fixture_bytes("square.geojson"))
        _assert_lands_on_confirm(resp)

        boundary = Boundary.objects.get()
        assert boundary.name == "Merced Test Square"
        assert boundary.geometry.geom_type == "MultiPolygon"
        assert boundary.geometry.srid == 4326
        assert boundary.geometry.num_geom == 1
        _assert_extent(boundary.geometry, SQUARE_EXTENT, 1e-6)

    def test_epsg3310_zip_lands_where_the_4326_zip_does(self):
        """The same square written in California Albers (EPSG:3310, with its
        .prj) is reprojected to 4326 and lands on the 4326 square. NAD83 to
        WGS84 differ by about a metre here, far inside 1e-4 degrees."""
        client = _admin_client()
        _assert_lands_on_confirm(_post(client, "square.zip"))
        from_4326 = Boundary.objects.get()

        _assert_lands_on_confirm(_post(client, "square3310.zip"))
        from_3310 = Boundary.objects.exclude(pk=from_4326.pk).get()

        assert from_3310.geometry.srid == 4326
        assert from_3310.geometry.geom_type == "MultiPolygon"
        _assert_extent(from_3310.geometry, from_4326.geometry.extent, 1e-4)
        _assert_extent(from_3310.geometry, SQUARE_EXTENT, 1e-4)


# --------------------------------------------------------------------------
# Several polygons: dissolved into one boundary, and the count said
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestSeveralPolygonsAreCombined:

    def test_two_squares_zip_is_one_multipolygon_of_two(self):
        client = _admin_client()
        resp = _post(client, "two-squares.zip")
        _assert_lands_on_confirm(resp)

        boundary = Boundary.objects.get()
        assert boundary.name == "Merced Two Squares"
        assert boundary.geometry.geom_type == "MultiPolygon"
        assert boundary.geometry.srid == 4326
        assert boundary.geometry.num_geom == 2
        assert boundary.geometry.valid
        _assert_extent(boundary.geometry, (-120.6, 37.2, -120.3, 37.3), 1e-6)
        assert client.session[SESSION_KEY_POLYGON_COUNT] == 2

        confirm = client.get(CONFIRM_URL)
        assert confirm.status_code == 200
        assert "2 polygons combined" in confirm.content.decode()

    def test_one_polygon_confirm_does_not_say_combined(self):
        client = _admin_client()
        _assert_lands_on_confirm(_post(client, "square.zip"))
        confirm = client.get(CONFIRM_URL)
        assert confirm.status_code == 200
        assert "polygons combined" not in confirm.content.decode()

    def test_boundary_from_upload_unions_the_two_squares(self):
        from setup.boundaries import boundary_from_upload

        name, geom, attrs, polygon_count = boundary_from_upload(
            _upload_file("two-squares.zip"), fallback_name="two-squares",
        )
        assert name == "Merced Two Squares"
        assert geom.geom_type == "MultiPolygon"
        assert geom.srid == 4326
        assert geom.num_geom == 2
        assert geom.valid
        assert polygon_count == 2
        assert attrs == {}

    def test_overlapping_polygons_dissolve_into_one(self):
        """Dissolve, not collect: two overlapping squares become one outline,
        and the count still says two polygons went into it."""
        from setup.boundaries import boundary_from_upload

        kml = _kml(
            _kml_square("West", -120.6, 37.2, -120.5, 37.3),
            _kml_square("East", -120.55, 37.2, -120.45, 37.3),
        )
        name, geom, _attrs, polygon_count = boundary_from_upload(
            _upload_file("overlap.kml", kml), fallback_name="overlap",
        )
        assert name == "West"
        assert geom.geom_type == "MultiPolygon"
        assert geom.srid == 4326
        assert geom.num_geom == 1
        assert geom.valid
        assert not geom.hasz
        assert polygon_count == 2
        _assert_extent(geom, (-120.6, 37.2, -120.45, 37.3), 1e-6)

    def test_points_and_lines_beside_a_polygon_are_dropped(self):
        from setup.boundaries import boundary_from_upload

        kml = _kml(
            _kml_square("Outline", -120.6, 37.2, -120.5, 37.3),
            "<name>A well</name><Point><coordinates>-120.55,37.25,0</coordinates></Point>",
            "<name>A canal</name><LineString><coordinates>"
            "-120.7,37.1,0 -120.4,37.4,0</coordinates></LineString>",
        )
        _name, geom, _attrs, polygon_count = boundary_from_upload(
            _upload_file("mixed.kml", kml), fallback_name="mixed",
        )
        assert geom.geom_type == "MultiPolygon"
        assert geom.num_geom == 1
        assert polygon_count == 1
        _assert_extent(geom, SQUARE_EXTENT, 1e-6)

    def test_name_falls_back_when_no_feature_has_one(self):
        from setup.boundaries import boundary_from_upload

        kml = _kml(
            "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
            "-120.6,37.2,0 -120.5,37.2,0 -120.5,37.3,0 -120.6,37.3,0 -120.6,37.2,0"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        )
        name, _geom, _attrs, _count = boundary_from_upload(
            _upload_file("unnamed.kml", kml), fallback_name="My District",
        )
        assert name == "My District"


# --------------------------------------------------------------------------
# Refusals: each says what was wrong, and nothing is created
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestRefusals:

    def test_zip_without_a_shp_says_so(self):
        client = _admin_client()
        errors = _errors(_post(client, "no-shp.zip"))
        assert any(NO_SHP_SENTENCE in e for e in errors), errors
        assert not Boundary.objects.exists()

    def test_kml_with_only_points_says_it_holds_no_polygon(self):
        client = _admin_client()
        errors = _errors(_post(client, "points-only.kml"))
        assert errors == [NO_POLYGON_SENTENCE]
        assert not Boundary.objects.exists()

    def test_boundary_from_upload_refuses_a_file_with_no_polygon(self):
        from setup.boundaries import boundary_from_upload

        with pytest.raises(ValueError) as exc:
            boundary_from_upload(_upload_file("points-only.kml"), fallback_name="x")
        assert str(exc.value) == NO_POLYGON_SENTENCE

    def test_unsupported_extension_names_the_three_formats(self):
        client = _admin_client()
        errors = _errors(_post(client, "notes.txt", b"just some notes"))
        assert errors == [UNSUPPORTED_SENTENCE]
        assert not Boundary.objects.exists()

    def test_features_from_upload_refuses_an_unsupported_extension(self):
        from core.geofiles import features_from_upload

        with pytest.raises(ValueError) as exc:
            features_from_upload(_upload_file("notes.txt", b"just some notes"))
        assert str(exc.value) == UNSUPPORTED_SENTENCE

    def test_no_file_chosen_names_the_three_formats(self):
        client = _admin_client()
        errors = _errors(client.post(WIZARD_URL, {"action": "upload"}))
        assert errors == [NO_FILE_SENTENCE]

    @pytest.mark.parametrize("filename", ["square.zip", "square.kml", "square.geojson"])
    def test_an_upload_over_the_cap_is_refused(self, monkeypatch, filename):
        """The importer's upload cap applies to every format the wizard takes.
        The cap is read from ``core.geofiles`` when the upload is handled (not
        copied at import time), which is what lets this test shrink it."""
        monkeypatch.setattr("core.geofiles.MAX_UPLOAD_BYTES", 100)
        assert len(_fixture_bytes(filename)) > 100

        client = _admin_client()
        errors = _errors(_post(client, filename))
        assert any(UPLOAD_CAP_PHRASE in e for e in errors), errors
        assert not Boundary.objects.exists()

    def test_a_zip_over_the_extraction_cap_is_refused(self, monkeypatch):
        monkeypatch.setattr("core.geofiles.MAX_EXTRACTED_BYTES", 10)

        client = _admin_client()
        errors = _errors(_post(client, "square.zip"))
        assert any(ZIP_BOMB_PHRASE in e for e in errors), errors
        assert not Boundary.objects.exists()

    def test_a_zip_slip_entry_is_refused(self):
        client = _admin_client()
        errors = _errors(_post(client, "slip.zip", _zip_slip_bytes()))
        assert any(UNSAFE_PATH_SENTENCE in e for e in errors), errors
        assert not Boundary.objects.exists()


# --------------------------------------------------------------------------
# A bad GeoJSON: text-level failures name the three formats, GeoJSON-shaped
# failures keep today's wording
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestBadGeoJSON:

    def test_not_json_names_the_three_formats(self):
        client = _admin_client()
        errors = _errors(_post(client, "boundary.geojson", b"this is not json at all"))
        assert errors == [NOT_JSON_SENTENCE]
        # tests/test_setup_polish.py pins this phrase too.
        assert "valid JSON" in errors[0]
        for old in OLD_EXPORT_GEOJSON_ADVICE:
            assert old not in errors[0]
        assert not Boundary.objects.exists()

    def test_not_text_names_the_three_formats(self):
        client = _admin_client()
        errors = _errors(_post(client, "boundary.geojson", b"\xff\xfe\x00\x81binary"))
        assert errors == [NOT_TEXT_SENTENCE]
        for old in OLD_EXPORT_GEOJSON_ADVICE:
            assert old not in errors[0]
        assert not Boundary.objects.exists()

    def test_empty_featurecollection_keeps_its_wording(self):
        client = _admin_client()
        payload = b'{"type": "FeatureCollection", "features": []}'
        errors = _errors(_post(client, "boundary.geojson", payload))
        assert len(errors) == 1
        assert errors[0].startswith(GEOJSON_EMPTY_COLLECTION)
        assert not Boundary.objects.exists()

    def test_point_geometry_keeps_its_wording(self):
        client = _admin_client()
        payload = (
            b'{"type": "Feature", "properties": {}, '
            b'"geometry": {"type": "Point", "coordinates": [-120.55, 37.25]}}'
        )
        errors = _errors(_post(client, "boundary.geojson", payload))
        assert len(errors) == 1
        assert errors[0].startswith(GEOJSON_POINT_GEOMETRY)
        assert not Boundary.objects.exists()

    def test_missing_geometry_keeps_its_wording(self):
        client = _admin_client()
        payload = b'{"type": "Feature", "properties": {}, "geometry": null}'
        errors = _errors(_post(client, "boundary.geojson", payload))
        assert errors == [GEOJSON_NO_GEOMETRY]
        assert not Boundary.objects.exists()


# --------------------------------------------------------------------------
# The drop zone names the three formats
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestTheDropZone:

    def _page(self):
        resp = _admin_client().get(WIZARD_URL)
        assert resp.status_code == 200
        return resp.content.decode()

    def test_file_input_keeps_its_name(self):
        body = self._page()
        assert re.search(rf'<input[^>]*\bname="{FILE_FIELD}"', body), (
            "the upload input's name changed; update FILE_FIELD"
        )

    def test_label_drops_geojson_only(self):
        body = self._page()
        match = re.search(rf'<label[^>]*for="{FILE_FIELD}"[^>]*>(.*?)</label>', body, re.S)
        assert match, "no label for the upload input"
        assert " ".join(match.group(1).split()) == "Boundary map file"

    def test_accept_list_takes_the_three_formats(self):
        body = self._page()
        match = re.search(rf'<input[^>]*\bname="{FILE_FIELD}"[^>]*>', body, re.S)
        assert match
        accept = re.search(r'accept="([^"]*)"', match.group(0))
        assert accept, "the upload input has no accept list"
        assert set(accept.group(1).split(",")) == {".geojson", ".json", ".zip", ".kml"}

    def test_drop_zone_sentence_names_the_three_formats(self):
        body = self._page()
        match = re.search(r'<p id="zone-label"[^>]*>(.*?)</p>', body, re.S)
        assert match, "no drop-zone sentence"
        text = re.sub(r"<[^>]+>", "", match.group(1))
        assert " ".join(text.split()) == DROP_ZONE_SENTENCE
