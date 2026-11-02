# SPDX-License-Identifier: AGPL-3.0-or-later
"""151.6-06: the Import use areas page, tested with real map files.

A district clerk or a ditch company holds a county parcel file or a Google
Earth file. The page reads a zipped shapefile, a KML or a GeoJSON, shows the
column matches and what Import would do, then writes use areas in the
background the way the water level import does.

The files are in ``tests/fixtures/real_map_files/`` (README.md names each one's
source). ``sj_valley_subbasins_2227.zip`` holds five San Joaquin Valley
subbasins in California zone 3 feet (EPSG 2227): 5-022.01, 5-022.02, 5-022.03,
5-022.04 (two parts) and 5-022.16 (an outline with three holes). The KML holds
the same five with only a name each (SAN JOAQUIN VALLEY - EASTERN SAN JOAQUIN,
TURLOCK, MODESTO, MERCED, COSUMNES).

Expected counts are literals read off the files, never the code's own sums.
"""
import json
import re
from html import unescape
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from core.access import READ_ONLY_MESSAGE
from core.geofiles import features_from_upload
from core.models import User
from geography.models import Boundary
from parcels.models import Parcel
from tests.factories import ParcelFactory
from tests.import_flow import import_and_read, token_of

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "real_map_files"
SUBBASINS_ZIP = "sj_valley_subbasins_2227.zip"
SUBBASINS_KML = "sj_valley_subbasins_names.kml"

PAGE = reverse("parcels:use_area_import")
PREVIEW = reverse("parcels:use_area_import_preview")
COMMIT = reverse("parcels:use_area_import_commit")

NUMBERS = ["5-022.01", "5-022.02", "5-022.03", "5-022.04", "5-022.16"]
NAMES = [
    "SAN JOAQUIN VALLEY - EASTERN SAN JOAQUIN",
    "SAN JOAQUIN VALLEY - MODESTO",
    "SAN JOAQUIN VALLEY - TURLOCK",
    "SAN JOAQUIN VALLEY - MERCED",
    "SAN JOAQUIN VALLEY - COSUMNES",
]

NOT_LONGITUDE_LATITUDE = (
    "The coordinates in this file are not longitude and latitude, and the file "
    "does not say which projection they are in. For a shapefile, include its "
    ".prj file in the zip."
)
SEVERAL_SHAPEFILES = (
    "This zip holds 7 shapefiles: NWISDrainageArea.shp, NWISDrainageLine.shp, "
    "NonContributingDrainageArea.shp, NonContributingDrainageLine.shp, "
    "WBDHU14.shp, WBDHU16.shp, WBDHU2.shp. Upload a zip with only the one you want."
)


def _user(username="clerk", **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="x",
        is_active=True, **flags,
    )


def _client(user=None):
    client = Client()
    client.force_login(user or _user())
    return client


def _bytes(name):
    return (FIXTURES / name).read_bytes()


def _upload(name, data=None):
    return SimpleUploadedFile(name, data if data is not None else _bytes(name))


def _features(name):
    return features_from_upload(_upload(name))


def _geojson_of(features):
    """A GeoJSON FeatureCollection (bytes) holding ``features`` as the reader gives them."""
    return json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": f["geometry"], "properties": f["properties"]}
            for f in features
        ],
    }).encode()


def _preview(client, name, data=None, **extra):
    return client.post(
        PREVIEW, {"file": _upload(name, data), **extra}, HTTP_HX_REQUEST="true"
    )


def _text(response):
    return unescape(response.content.decode())


def _import(client, name, column, data=None, owner=""):
    """Upload, press Import with ``column`` as the parcel number, return the status response."""
    preview = _preview(client, name, data)
    assert preview.status_code == 200
    return import_and_read(
        client, COMMIT, token_of(preview),
        {"map:parcel_number": column, "map:owner_name": owner},
    )


def _row(html, count, words):
    """Whether the counts table has a row with ``count`` beside ``words``."""
    return bool(re.search(
        rf'<td class="td-num">{re.escape(count)}</td>\s*<td[^>]*>\s*{re.escape(words)}', html
    ))


def _in_san_joaquin_valley(geometry):
    xmin, ymin, xmax, ymax = geometry.extent
    return -121.7 <= xmin and xmax <= -119.9 and 36.9 <= ymin and ymax <= 38.6


# ---------------------------------------------------------------------------
# (a) a zipped shapefile, a KML and a GeoJSON each become use areas
# ---------------------------------------------------------------------------

#: (file name, the column holding the number, the number of the outline with
#: holes, the number of the outline in two parts)
FORMATS = [
    (SUBBASINS_ZIP, "Basin_Subb", "5-022.16", "5-022.04"),
    (SUBBASINS_KML, "Name", NAMES[4], NAMES[3]),
    ("subbasins.geojson", "Basin_Subb", "5-022.16", "5-022.04"),
]


def _format_bytes(name):
    if name == "subbasins.geojson":
        return _geojson_of(_features(SUBBASINS_ZIP))
    return _bytes(name)


@pytest.mark.parametrize("name,column,holed,two_parts", FORMATS)
def test_a_map_file_becomes_use_areas_with_their_outlines(name, column, holed, two_parts):
    client = _client()
    done = _import(client, name, column, _format_bytes(name))
    html = _text(done)

    assert Parcel.objects.count() == 5
    for parcel in Parcel.objects.all():
        assert parcel.geometry.srid == 4326
        assert parcel.geometry.geom_type == "MultiPolygon"
        assert _in_san_joaquin_valley(parcel.geometry), parcel.parcel_number
        assert parcel.area_acres and parcel.area_acres > 0, parcel.parcel_number
        assert parcel.status == "active"
    assert len(Parcel.objects.get(parcel_number=holed).geometry[0]) == 4
    assert Parcel.objects.get(parcel_number=two_parts).geometry.num_geom == 2

    assert "Import complete" in html
    assert "OpenH2O imported 5 use areas, " in html
    shown = int(re.search(r"OpenH2O imported 5 use areas, ([\d,]+) acres\.", html).group(1).replace(",", ""))
    stored = sum(p.area_acres for p in Parcel.objects.all())
    # The page's figure and the stored one are two ways to measure the same
    # outlines; they agree to the percent.
    assert abs(shown - float(stored)) / float(stored) < 0.01


def test_the_done_card_links_to_the_list_and_to_another_import():
    done = _text(_import(_client(), SUBBASINS_ZIP, "Basin_Subb"))
    assert f'href="{reverse("parcels:list")}"' in done
    assert "View Use Areas" in done
    assert f'href="{PAGE}"' in done
    assert "Import another file" in done


def test_a_use_area_keeps_the_owner_column_when_one_is_chosen():
    _import(_client(), SUBBASINS_ZIP, "Basin_Subb", owner="Basin_Su_1")
    parcel = Parcel.objects.get(parcel_number="5-022.04")
    assert parcel.owner_name == "SAN JOAQUIN VALLEY - MERCED"
    done = _import(_client(_user("second")), SUBBASINS_ZIP, "Basin_Subb")
    assert "OpenH2O imported 0 use areas, 0 acres." in _text(done)


# ---------------------------------------------------------------------------
# The preview
# ---------------------------------------------------------------------------


def test_the_preview_replaces_the_upload_card_with_the_column_match():
    response = _preview(_client(), SUBBASINS_ZIP)
    html = _text(response)
    assert "Match the file's columns" in html
    assert "OpenH2O found 5 outlines and 2 columns in sj_valley_subbasins_2227.zip. Changing a column re-counts below." in html
    assert 'hx-swap-oob="true"' in html
    assert 'id="import-card"' in html
    # Basin_Subb is picked without being asked; Owner defaults to Not imported.
    assert re.search(r'<option value="Basin_Subb" selected', html)
    assert re.search(r'name="map:owner_name"[^>]*>\s*<option value="" selected>Not imported', html)
    assert "5-022.01, 5-022.03, 5-022.02, 5-022.04, 5-022.16" in html
    assert 'name="token"' in html
    assert "Choose another file" in html
    assert "Import 5 use areas" in html
    assert _row(html, "5", "new use areas, ")
    assert "Imported" in html


def test_a_select_change_re_counts_from_the_stored_file():
    client = _client()
    first = _preview(client, SUBBASINS_ZIP)
    again = client.post(
        PREVIEW,
        {"token": token_of(first), "map:parcel_number": "Basin_Su_1", "map:owner_name": ""},
        HTTP_HX_REQUEST="true",
    )
    html = _text(again)
    assert again.status_code == 200
    assert re.search(r'<option value="Basin_Su_1" selected', html)
    assert "SAN JOAQUIN VALLEY - EASTERN SAN JOAQUIN" in html


def test_the_preview_form_selects_re_post_the_preview_on_change():
    html = _text(_preview(_client(), SUBBASINS_ZIP))
    assert 'hx-trigger="change"' in html
    assert f'hx-post="{PREVIEW}"' in html
    assert f'hx-post="{COMMIT}"' in html


# ---------------------------------------------------------------------------
# (b) a parcel number already on file is skipped and left as it is
# ---------------------------------------------------------------------------


def test_a_parcel_number_already_on_file_is_skipped_counted_and_unchanged():
    existing = ParcelFactory(parcel_number="5-022.01", owner_name="Keep Me")
    before = (existing.owner_name, existing.area_acres, existing.geometry.wkt, existing.status)
    client = _client()

    preview = _text(_preview(client, SUBBASINS_ZIP))
    assert _row(preview, "1", "already on file")
    assert "Not imported" in preview
    assert _row(preview, "4", "new use areas, ")
    assert "Import 4 use areas" in preview

    done = _text(_import(client, SUBBASINS_ZIP, "Basin_Subb"))
    assert "OpenH2O imported 4 use areas, " in done
    existing.refresh_from_db()
    assert (existing.owner_name, existing.area_acres, existing.geometry.wkt, existing.status) == before
    assert Parcel.objects.count() == 5


def test_a_number_added_after_the_preview_is_on_file_at_import():
    client = _client()
    preview = _preview(client, SUBBASINS_ZIP)
    ParcelFactory(parcel_number="5-022.02")
    done = _text(import_and_read(
        client, COMMIT, token_of(preview), {"map:parcel_number": "Basin_Subb", "map:owner_name": ""}
    ))
    assert "OpenH2O imported 4 use areas, " in done


# ---------------------------------------------------------------------------
# (c) a feature with no readable outline is refused, counted and named
# ---------------------------------------------------------------------------


def _with_unreadable():
    features = _features(SUBBASINS_ZIP)
    features.append({"geometry": {"type": "Point", "coordinates": [-121.0, 37.5]},
                     "properties": {"Basin_Subb": "POINT-1"}})
    features.append({"geometry": None, "properties": {"Basin_Subb": "NOSHAPE-1"}})
    return _geojson_of(features)


def test_a_point_and_a_missing_outline_are_counted_and_named_while_the_rest_import():
    client = _client()
    data = _with_unreadable()
    preview = _text(_preview(client, "mixed.geojson", data))
    assert _row(preview, "2", "without a readable outline")
    assert "POINT-1" in preview and "NOSHAPE-1" in preview
    assert _row(preview, "5", "new use areas, ")

    _import(client, "mixed.geojson", "Basin_Subb", data)
    assert sorted(Parcel.objects.values_list("parcel_number", flat=True)) == NUMBERS


def test_a_feature_without_a_number_and_a_number_over_fifty_characters_are_counted():
    features = _features(SUBBASINS_ZIP)
    features.append({"geometry": features[0]["geometry"], "properties": {"Basin_Subb": ""}})
    features.append({"geometry": features[0]["geometry"], "properties": {"Basin_Subb": "X" * 51}})
    data = _geojson_of(features)
    client = _client()
    preview = _text(_preview(client, "mixed.geojson", data))
    assert _row(preview, "1", "without a parcel number")
    assert _row(preview, "1", "with a parcel number over 50 characters")
    assert _row(preview, "5", "new use areas, ")

    _import(client, "mixed.geojson", "Basin_Subb", data)
    # The long number is never cut down to 50 characters and saved.
    assert sorted(Parcel.objects.values_list("parcel_number", flat=True)) == NUMBERS


def test_a_count_of_zero_is_not_shown():
    preview = _text(_preview(_client(), SUBBASINS_ZIP))
    for words in ("already on file", "outside this site", "without a readable outline",
                  "without a parcel number", "with a parcel number over 50"):
        assert words not in preview


def test_a_file_with_nothing_to_import_says_so_and_shows_no_import_button():
    for number in NUMBERS:
        ParcelFactory(parcel_number=number)
    preview = _text(_preview(_client(), SUBBASINS_ZIP))
    assert _row(preview, "5", "already on file")
    assert "OpenH2O has nothing to import from this file." in preview
    assert "Import 0 use areas" not in preview
    assert not re.search(r">\s*Import \d", preview)


# ---------------------------------------------------------------------------
# (d) a zip holding several shapefiles is refused on all four paths
# ---------------------------------------------------------------------------


def test_the_use_area_page_refuses_a_zip_of_several_shapefiles():
    response = _preview(_client(), "wbd_20_several_shapefiles.zip")
    assert SEVERAL_SHAPEFILES in _text(response)
    assert Parcel.objects.count() == 0


def test_the_setup_wizard_boundary_reader_refuses_a_zip_of_several_shapefiles():
    from setup.boundaries import boundary_from_upload

    with pytest.raises(ImportError) as raised:
        boundary_from_upload(_upload("wbd_20_several_shapefiles.zip"), fallback_name="x")
    assert str(raised.value) == SEVERAL_SHAPEFILES


def test_the_setup_wizard_page_shows_that_refusal():
    admin = _user("wizard-admin", is_staff=True, is_superuser=True)
    response = _client(admin).post(
        reverse("setup:wizard"),
        {"action": "upload", "geojson_file": _upload("wbd_20_several_shapefiles.zip")},
    )
    assert response.status_code == 200
    assert SEVERAL_SHAPEFILES in list(response.context["errors"])
    assert Boundary.objects.count() == 0


def test_the_bulk_import_refuses_a_zip_of_several_shapefiles():
    response = _client().post(
        reverse("infrastructure:import_preview"),
        {"infra_type": "well", "file": _upload("wbd_20_several_shapefiles.zip")},
    )
    assert SEVERAL_SHAPEFILES in _text(response)


def test_import_parcels_refuses_a_zip_of_several_shapefiles():
    from django.core.management import CommandError, call_command

    with pytest.raises(CommandError) as raised:
        call_command("import_parcels", str(FIXTURES / "wbd_20_several_shapefiles.zip"))
    assert SEVERAL_SHAPEFILES in str(raised.value)


# ---------------------------------------------------------------------------
# (e) a Google Earth file with only names: the Name column is the number
# ---------------------------------------------------------------------------


def test_a_names_only_kml_offers_name_and_makes_numbers_from_it():
    client = _client()
    preview = _text(_preview(client, SUBBASINS_KML))
    assert re.search(r'<option value="Name" selected', preview)
    for style_field in ("altitudeMode", "tessellate", "extrude", "visibility", "drawOrder",
                        "icon", "snippet", "begin", "end", "timestamp", "description"):
        assert f'value="{style_field}"' not in preview
    assert "SAN JOAQUIN VALLEY - TURLOCK" in preview

    _import(client, SUBBASINS_KML, "Name")
    assert sorted(Parcel.objects.values_list("parcel_number", flat=True)) == sorted(NAMES)


def test_the_column_list_leaves_out_kml_styling_fields_and_empty_columns():
    from parcels.use_area_import import columns_of

    features = [
        {"geometry": None, "properties": {
            "Name": "A", "id": "1", "description": "d", "altitudeMode": "clampToGround",
            "tessellate": "1", "extrude": "0", "visibility": "1", "drawOrder": "0",
            "icon": "x", "snippet": "s", "begin": "2020", "end": "2021",
            "timestamp": "2020", "empty": "", "blank": "  "}},
        {"geometry": None, "properties": {"Name": "B", "id": "2", "empty": ""}},
    ]
    assert columns_of(features, kml=True) == ["Name", "id", "description"]
    # Only a KML has styling fields; a shapefile column called "end" is a column.
    assert "end" in columns_of(features, kml=False)
    assert "empty" not in columns_of(features, kml=False)


def test_the_number_column_is_picked_by_preference():
    from parcels.use_area_import import auto_map

    assert auto_map(["OBJECTID", "NAME", "APN"])["parcel_number"] == "APN"
    assert auto_map(["x", "parcel_number", "PARCEL"])["parcel_number"] == "parcel_number"
    assert auto_map(["x", "PARCELNO", "PARCEL"])["parcel_number"] == "PARCEL"
    assert auto_map(["x", "APN_1", "Name"])["parcel_number"] == "APN_1"
    assert auto_map(["id", "Name"])["parcel_number"] == "Name"
    assert auto_map(["first", "second"])["parcel_number"] == "first"
    assert auto_map(["APN", "owner"])["owner_name"] == ""


# ---------------------------------------------------------------------------
# Two outlines on one number become one use area
# ---------------------------------------------------------------------------


def test_outlines_sharing_a_number_become_one_use_area_holding_all_of_them():
    # 5-022.01 has one part and 5-022.04 has two, and they are far apart.
    by_number = {f["properties"]["Basin_Subb"]: f for f in _features(SUBBASINS_ZIP)}
    first, second = dict(by_number["5-022.01"]), dict(by_number["5-022.04"])
    first["properties"] = {"Basin_Subb": "SHARED"}
    second["properties"] = {"Basin_Subb": "SHARED"}
    data = _geojson_of([first, second])
    client = _client()

    preview = _text(_preview(client, "shared.geojson", data))
    assert _row(preview, "1", "new use area, ")
    assert "Import 1 use area" in preview

    _import(client, "shared.geojson", "Basin_Subb", data)
    parcel = Parcel.objects.get()
    assert parcel.parcel_number == "SHARED"
    assert parcel.geometry.geom_type == "MultiPolygon"
    assert parcel.geometry.num_geom == 3


# ---------------------------------------------------------------------------
# Refusals render below the upload card
# ---------------------------------------------------------------------------


def test_a_wrong_file_type_and_a_missing_file_are_refused_in_one_sentence():
    client = _client()
    wrong = client.post(PREVIEW, {"file": SimpleUploadedFile("x.csv", b"a,b")}, HTTP_HX_REQUEST="true")
    assert "This page imports .zip, .kml, .geojson and .json files only." in _text(wrong)
    none = client.post(PREVIEW, {}, HTTP_HX_REQUEST="true")
    assert "Choose a file to upload." in _text(none)


def test_a_file_with_no_projection_is_refused_with_the_setup_wizards_sentence():
    response = _preview(_client(), "central_sj_wcd_gsa_no_prj.zip")
    assert NOT_LONGITUDE_LATITUDE in _text(response)
    assert "Match the file's columns" not in _text(response)
    assert Parcel.objects.count() == 0


def test_an_expired_or_foreign_token_is_refused():
    client = _client()
    token = token_of(_preview(client, SUBBASINS_ZIP))
    other = _client(_user("other"))
    refused = other.post(COMMIT, {"token": token, "map:parcel_number": "Basin_Subb"},
                         HTTP_HX_REQUEST="true")
    assert "This upload has expired or belongs to someone else. Upload the file again." in _text(refused)


def test_the_page_polls_the_status_route_while_the_import_runs(settings):
    settings.OPENH2O_IMPORT_INLINE = False
    client = _client()
    token = token_of(_preview(client, SUBBASINS_ZIP))
    import subprocess
    from unittest import mock

    with mock.patch.object(subprocess, "Popen"):
        pressed = client.post(COMMIT, {"token": token, "map:parcel_number": "Basin_Subb",
                                       "map:owner_name": ""}, HTTP_HX_REQUEST="true")
    html = _text(pressed)
    assert reverse("core:pending_import_status", args=[token]) in html
    assert 'hx-trigger="every 2s"' in html
    assert "OpenH2O is importing sj_valley_subbasins_2227.zip." in html


# ---------------------------------------------------------------------------
# The page itself, and where it is reached from
# ---------------------------------------------------------------------------


def test_the_page_offers_the_upload_card_in_the_drawings_words():
    html = _text(_client().get(PAGE))
    assert "Field outlines" in html
    assert "OpenH2O saves nothing until you press Import on the preview." in html
    assert "OpenH2O does not import an outline already on file or outside this site's boundary." in html
    assert "OpenH2O reads a zipped shapefile, a KML or a GeoJSON of up to 25 MB." in html
    assert 'accept=".zip,.kml,.geojson,.json"' in html
    assert 'id="import-area"' in html


def test_the_use_areas_list_offers_the_import_to_a_writer_and_not_to_a_viewer():
    ParcelFactory()
    assert "Import use areas" in _text(_client().get(reverse("parcels:list")))
    viewer = _client(_user("viewer", read_only=True))
    assert "Import use areas" not in _text(viewer.get(reverse("parcels:list")))


def test_the_empty_list_links_to_the_import_page():
    html = _text(_client().get(reverse("parcels:list")))
    assert "The Setup Wizard loads use areas from the statewide parcel layer; you can also " in html
    assert f'<a href="{PAGE}" class="prose-link">import your own file</a>' in html
    assert "there is no add form" not in html


def test_the_bulk_import_sends_a_use_area_type_to_the_use_area_page():
    client = _client()
    for kind in ("parcel", "use_area", "usearea"):
        response = client.get(reverse("infrastructure:import") + f"?type={kind}")
        assert response.status_code == 302, kind
        assert response["Location"] == PAGE, kind
        posted = client.post(reverse("infrastructure:import_preview"), {"infra_type": kind})
        assert posted.status_code == 404, kind
        assert posted.content.decode() == (
            "The bulk import page does not import use areas. "
            "Import them on the Import use areas page."
        )


# ---------------------------------------------------------------------------
# (f) a Viewer is refused on the three routes; an operator is not
# ---------------------------------------------------------------------------


def test_a_viewer_is_refused_on_the_page_and_both_posts():
    viewer = _client(_user("viewer", read_only=True))
    page = viewer.get(PAGE)
    assert page.status_code == 403
    assert READ_ONLY_MESSAGE in page.content.decode()
    for url in (PREVIEW, COMMIT):
        response = viewer.post(url, {"file": _upload(SUBBASINS_ZIP)})
        assert response.status_code == 403, url
        assert READ_ONLY_MESSAGE in response.content.decode(), url
    assert Parcel.objects.count() == 0


def test_an_operator_is_not_refused_on_the_page_and_both_posts():
    operator = _client(_user("operator"))
    assert operator.get(PAGE).status_code == 200
    preview = operator.post(PREVIEW, {"file": _upload(SUBBASINS_ZIP)})
    assert preview.status_code == 200
    assert READ_ONLY_MESSAGE not in preview.content.decode()
    commit = operator.post(COMMIT, {"token": token_of(preview), "map:parcel_number": "Basin_Subb",
                                    "map:owner_name": ""}, HTTP_HX_REQUEST="true")
    assert commit.status_code == 200
    assert READ_ONLY_MESSAGE not in commit.content.decode()
