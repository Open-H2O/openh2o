# SPDX-License-Identifier: AGPL-3.0-or-later
"""151.6-06: what the map-file readers do with real files.

Each file is in ``tests/fixtures/real_map_files/`` (README.md names its source
and what was changed). The facts the tests read off them:

* ``central_sj_wcd_gsa.zip`` is one agency boundary near Stockton in Web
  Mercator; ``_esri_prj`` is the same outline in California zone 3 feet with a
  ``.prj`` written in Esri's form, which names no EPSG code; ``_no_prj`` has no
  ``.prj`` at all.
* ``wbd_20_hu8.zip`` is 19 Hawaii watersheds in NAD83 (EPSG 4269), each with a
  different ``name``.
* ``us_watersheds_two_layers.kml.gz`` is a KML with two layers, 77 points and
  589 lines, 666 features in all, each with a name.
* ``sj_valley_subbasins_2227.zip`` is five subbasins; none of their points on
  surface lies inside the Central San Joaquin district.
"""
import gzip
import json
import re
from html import unescape
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from core.geofiles import features_from_upload
from core.models import User
from geography.models import Boundary
from infrastructure import importer
from parcels.models import Parcel
from setup.boundaries import boundary_from_upload
from tests.import_flow import import_and_read, token_of

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "real_map_files"
PREVIEW = reverse("parcels:use_area_import_preview")
COMMIT = reverse("parcels:use_area_import_commit")

NOT_LONGITUDE_LATITUDE = (
    "The coordinates in this file are not longitude and latitude, and the file "
    "does not say which projection they are in. For a shapefile, include its "
    ".prj file in the zip."
)
STOCKTON_BOX = (-122.0, 37.0, -120.0, 39.0)
# Region 20 runs from the island of Hawaii out to Kure Atoll (about -178.4).
HAWAII_BOX = (-179.0, 18.0, -154.0, 29.0)


def _upload(name, data=None):
    return SimpleUploadedFile(name, data if data is not None else (FIXTURES / name).read_bytes())


def _client():
    user = User.objects.create_user(
        username="mapper", email="mapper@example.org", password="x", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


def _text(response):
    return unescape(response.content.decode())


def _preview(client, name, data=None):
    return client.post(PREVIEW, {"file": _upload(name, data)}, HTTP_HX_REQUEST="true")


def _row(html, count, words):
    return bool(re.search(
        rf'<td class="td-num">{re.escape(count)}</td>\s*<td[^>]*>\s*{re.escape(words)}', html
    ))


def _inside(extent, box):
    xmin, ymin, xmax, ymax = extent
    return box[0] <= xmin and xmax <= box[2] and box[1] <= ymin and ymax <= box[3]


def _coordinates(geometry):
    if isinstance(geometry, (list, tuple)):
        if geometry and not isinstance(geometry[0], (list, tuple)):
            yield tuple(geometry[:2])
        else:
            for part in geometry:
                yield from _coordinates(part)
    elif isinstance(geometry, dict):
        yield from _coordinates(geometry.get("coordinates") or [])


def _geojson_of(features):
    return json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": f["geometry"], "properties": f["properties"]}
            for f in features
        ],
    }).encode()


# ---------------------------------------------------------------------------
# A .prj GDAL cannot match to an EPSG code is still used
# ---------------------------------------------------------------------------


def test_the_esri_prj_file_reads_in_longitude_and_latitude_in_the_setup_wizard():
    _name, geometry, _attrs, _count = boundary_from_upload(
        _upload("central_sj_wcd_gsa_esri_prj.zip"), fallback_name="x"
    )
    assert _inside(geometry.extent, STOCKTON_BOX), geometry.extent


def test_the_esri_prj_file_reads_in_longitude_and_latitude_in_the_bulk_import():
    parsed = importer.parse_upload(
        _upload("central_sj_wcd_gsa_esri_prj.zip"), "central_sj_wcd_gsa_esri_prj.zip"
    )
    assert len(parsed["rows"]) == 1
    geometry = json.loads(parsed["rows"][0][importer.GEOMETRY_COL])
    xs, ys = zip(*_coordinates(geometry))
    assert _inside((min(xs), min(ys), max(xs), max(ys)), STOCKTON_BOX)


def test_the_esri_prj_file_reads_in_longitude_and_latitude_on_the_use_area_page():
    client = _client()
    preview = _preview(client, "central_sj_wcd_gsa_esri_prj.zip")
    assert _row(_text(preview), "1", "new use area, ")
    import_and_read(
        client, COMMIT, token_of(preview), {"map:parcel_number": "GSA_ID", "map:owner_name": ""}
    )
    assert _inside(Parcel.objects.get().geometry.extent, STOCKTON_BOX)


def test_the_esri_prj_file_reads_in_longitude_and_latitude_in_import_parcels():
    call_command(
        "import_parcels", str(FIXTURES / "central_sj_wcd_gsa_esri_prj.zip"),
        "--parcel-number-field", "GSA_ID", stdout=StringIO(),
    )
    assert _inside(Parcel.objects.get().geometry.extent, STOCKTON_BOX)


# ---------------------------------------------------------------------------
# A file with no projection at all is refused where a projection is needed
# ---------------------------------------------------------------------------


def test_the_file_with_no_prj_is_refused_on_the_use_area_page():
    response = _preview(_client(), "central_sj_wcd_gsa_no_prj.zip")
    assert NOT_LONGITUDE_LATITUDE in _text(response)
    assert Parcel.objects.count() == 0


def test_the_file_with_no_prj_is_refused_by_import_parcels():
    with pytest.raises(CommandError) as raised:
        call_command(
            "import_parcels", str(FIXTURES / "central_sj_wcd_gsa_no_prj.zip"),
            "--parcel-number-field", "GSA_ID", stdout=StringIO(),
        )
    assert NOT_LONGITUDE_LATITUDE in str(raised.value)
    assert Parcel.objects.count() == 0


def test_the_file_with_no_prj_is_still_refused_in_the_setup_wizard():
    with pytest.raises(ValueError) as raised:
        boundary_from_upload(_upload("central_sj_wcd_gsa_no_prj.zip"), fallback_name="x")
    assert str(raised.value) == NOT_LONGITUDE_LATITUDE


def test_the_bulk_import_still_reads_the_file_with_no_prj_and_leaves_the_check_to_its_rows():
    parsed = importer.parse_upload(
        _upload("central_sj_wcd_gsa_no_prj.zip"), "central_sj_wcd_gsa_no_prj.zip"
    )
    assert len(parsed["rows"]) == 1


# ---------------------------------------------------------------------------
# Hawaii, in NAD83 (EPSG 4269)
# ---------------------------------------------------------------------------


def test_the_hawaii_watersheds_read_in_longitude_and_latitude_as_a_boundary():
    _name, geometry, _attrs, count = boundary_from_upload(
        _upload("wbd_20_hu8.zip"), fallback_name="x"
    )
    assert _inside(geometry.extent, HAWAII_BOX), geometry.extent
    assert count >= 19


def test_the_hawaii_watersheds_read_in_longitude_and_latitude_as_use_areas():
    client = _client()
    preview = _preview(client, "wbd_20_hu8.zip")
    html = _text(preview)
    # "name" is the column OpenH2O picks; the file has 19 outlines with 19 names.
    assert re.search(r'<option value="name" selected', html)
    assert _row(html, "19", "new use areas, ")
    import_and_read(
        client, COMMIT, token_of(preview), {"map:parcel_number": "name", "map:owner_name": ""}
    )
    assert Parcel.objects.count() == 19
    for parcel in Parcel.objects.all():
        assert _inside(parcel.geometry.extent, HAWAII_BOX), parcel.parcel_number


# ---------------------------------------------------------------------------
# A KML of points and lines has no outlines
# ---------------------------------------------------------------------------


@pytest.fixture
def two_layer_kml(tmp_path):
    path = tmp_path / "us_watersheds_two_layers.kml"
    path.write_bytes(gzip.decompress((FIXTURES / "us_watersheds_two_layers.kml.gz").read_bytes()))
    return path


def test_a_kml_of_points_and_lines_is_refused_as_a_boundary(two_layer_kml):
    with pytest.raises(ValueError) as raised:
        boundary_from_upload(_upload(two_layer_kml.name, two_layer_kml.read_bytes()), fallback_name="x")
    assert "only points or lines" in str(raised.value)


def test_a_kml_of_points_and_lines_gives_no_use_areas(two_layer_kml):
    html = _text(_preview(_client(), two_layer_kml.name, two_layer_kml.read_bytes()))
    assert "OpenH2O found 666 outlines" in html
    assert _row(html, "666", "without a readable outline")
    assert "new use area" not in html
    assert "OpenH2O has nothing to import from this file." in html
    # The names are listed up to the page cap, and the page says how many it left out.
    assert "OpenH2O does not list the other 166" in html


# ---------------------------------------------------------------------------
# Outlines outside the site's boundary
# ---------------------------------------------------------------------------


def _subbasin_features():
    return features_from_upload(_upload("sj_valley_subbasins_2227.zip"))


def _centre_inside(boundary, features):
    """How many of ``features`` have a point on surface inside ``boundary``."""
    from django.contrib.gis.geos import GEOSGeometry

    return sum(
        1 for f in features
        if boundary.contains(GEOSGeometry(json.dumps(f["geometry"]), srid=4326).point_on_surface)
    )


def test_outlines_outside_the_site_boundary_are_counted_and_not_imported():
    _name, district, _attrs, _count = boundary_from_upload(
        _upload("central_sj_wcd_gsa.zip"), fallback_name="Central San Joaquin"
    )
    Boundary.objects.create(name="Central San Joaquin", geometry=district)
    features = _subbasin_features()
    inside = _centre_inside(district, features)
    outside = len(features) - inside
    assert outside > 0

    client = _client()
    html = _text(_preview(client, "sj_valley_subbasins_2227.zip"))
    assert _row(html, str(outside), "outside this site's boundary")
    if inside:
        assert _row(html, str(inside), "new use area")
    else:
        assert "OpenH2O has nothing to import from this file." in html


def test_the_outlines_with_their_centre_inside_the_boundary_are_the_ones_imported():
    features = _subbasin_features()
    from django.contrib.gis.geos import GEOSGeometry

    merced = next(f for f in features if f["properties"]["Basin_Subb"] == "5-022.04")
    centre = GEOSGeometry(json.dumps(merced["geometry"]), srid=4326).point_on_surface
    box = Polygon.from_bbox((centre.x - 0.01, centre.y - 0.01, centre.x + 0.01, centre.y + 0.01))
    box.srid = 4326
    Boundary.objects.create(name="Around one centre", geometry=MultiPolygon(box, srid=4326))
    inside = _centre_inside(Boundary.objects.get().geometry, features)
    assert inside >= 1

    client = _client()
    preview = _preview(client, "sj_valley_subbasins_2227.zip")
    html = _text(preview)
    assert _row(html, str(len(features) - inside), "outside this site's boundary")
    assert _row(html, str(inside), "new use area")
    import_and_read(
        client, COMMIT, token_of(preview), {"map:parcel_number": "Basin_Subb", "map:owner_name": ""}
    )
    assert Parcel.objects.count() == inside
    assert Parcel.objects.filter(parcel_number="5-022.04").exists()


def test_with_no_boundary_on_the_site_the_outside_count_does_not_apply():
    html = _text(_preview(_client(), "sj_valley_subbasins_2227.zip"))
    assert "outside this site" not in html
    assert _row(html, "5", "new use areas, ")


# ---------------------------------------------------------------------------
# Two features on one number, in the command
# ---------------------------------------------------------------------------


def _shared_number_file(tmp_path):
    by_number = {f["properties"]["Basin_Subb"]: f for f in _subbasin_features()}
    first, second = dict(by_number["5-022.01"]), dict(by_number["5-022.04"])
    first["properties"] = {"Basin_Subb": "SHARED"}
    second["properties"] = {"Basin_Subb": "SHARED"}
    path = tmp_path / "shared.geojson"
    path.write_bytes(_geojson_of([first, second]))
    return path


def test_import_parcels_dry_run_reports_the_joined_count(tmp_path):
    path = _shared_number_file(tmp_path)
    out = StringIO()
    call_command("import_parcels", str(path), "--parcel-number-field", "Basin_Subb",
                 "--dry-run", stdout=out)
    assert out.getvalue().splitlines()[-1] == "Imported 1 parcels, 0 duplicates skipped, 0 errors"
    assert Parcel.objects.count() == 0


def test_import_parcels_imports_the_joined_use_area(tmp_path):
    path = _shared_number_file(tmp_path)
    out = StringIO()
    call_command("import_parcels", str(path), "--parcel-number-field", "Basin_Subb", stdout=out)
    assert out.getvalue().splitlines()[-1] == "Imported 1 parcels, 0 duplicates skipped, 0 errors"
    parcel = Parcel.objects.get()
    assert parcel.parcel_number == "SHARED"
    assert parcel.geometry.num_geom == 3


# ---------------------------------------------------------------------------
# import_parcels reads every format the page reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,field", [
    ("sj_valley_subbasins_2227.zip", "Basin_Subb"),
    ("sj_valley_subbasins_names.kml", "Name"),
])
def test_import_parcels_reads_a_zip_and_a_kml(name, field):
    out = StringIO()
    call_command("import_parcels", str(FIXTURES / name), "--parcel-number-field", field, stdout=out)
    assert out.getvalue().splitlines()[-1] == "Imported 5 parcels, 0 duplicates skipped, 0 errors"
    assert Parcel.objects.count() == 5


def test_a_zip_made_on_a_mac_reads_its_one_shapefile():
    """A Mac zip carries ``__MACOSX/._name.shp`` beside the real shapefile.

    That metadata copy is not a second shapefile, so the zip reads as the one
    it holds instead of being refused as two.
    """
    import io
    import zipfile

    source = zipfile.ZipFile(FIXTURES / "central_sj_wcd_gsa.zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as mac_zip:
        for info in source.infolist():
            mac_zip.writestr(info.filename, source.read(info))
            mac_zip.writestr(f"__MACOSX/._{info.filename}", b"\x00\x05\x16\x07")
    features = features_from_upload(_upload("Central_SJ_WCD_GSA.zip", buffer.getvalue()))
    assert len(features) == 1
    xmin, ymin, xmax, ymax = boundary_from_upload(
        _upload("Central_SJ_WCD_GSA.zip", buffer.getvalue()), fallback_name="x"
    )[1].extent
    assert STOCKTON_BOX[0] < xmin < xmax < STOCKTON_BOX[2]
    assert STOCKTON_BOX[1] < ymin < ymax < STOCKTON_BOX[3]


def test_a_viewer_sees_no_import_link_on_the_empty_use_areas_list():
    """The empty list's link goes to a write page, so a Viewer is not offered it."""
    viewer = User.objects.create_user(
        username="looker", email="looker@example.org", password="x", is_active=True,
        read_only=True,
    )
    client = Client()
    client.force_login(viewer)
    html = _text(client.get(reverse("parcels:list")))
    assert "No use areas yet." in html
    assert reverse("parcels:use_area_import") not in html

    operator = _client()
    html = _text(operator.get(reverse("parcels:list")))
    assert reverse("parcels:use_area_import") in html
