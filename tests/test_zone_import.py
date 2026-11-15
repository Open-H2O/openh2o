# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import zones: one zone for each name in a map file, its type chosen once for the file.

A district's administrator holds its GSA boundaries as a map file. The Zones page's
Import zones reads it, previews what it would make, and writes nothing until Import
is pressed. ``import_zones`` runs the same function. The words asserted here are
the approved rows, word for word.
"""
import json
from html import unescape

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse, reverse_lazy

from core.models import User
from geography.models import Boundary, Zone
from tests.factories import BoundaryFactory, ZoneFactory
from tests.import_flow import import_and_read, token_of

pytestmark = pytest.mark.django_db

PREVIEW = reverse_lazy("geography:zone_import_preview")
COMMIT = reverse_lazy("geography:zone_import_commit")


def _square(x, y, size=0.01):
    return [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]


def _feature(props, coords, kind="Polygon"):
    return {"type": "Feature", "properties": props, "geometry": {"type": kind, "coordinates": coords}}


def _geojson(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


THREE = [
    _feature({"GSA_Name": "Eastside GSA", "GSA_ID": 1}, _square(-119.52, 36.49)),
    _feature({"GSA_Name": "Westside GSA", "GSA_ID": 2}, _square(-119.51, 36.49)),
    _feature({"GSA_Name": "North Fork GSA", "GSA_ID": 3}, _square(-119.50, 36.49)),
]


def _client():
    user = User.objects.create_user(
        username="admin", email="admin@example.org", password="x", is_active=True,
        is_staff=True, is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _upload(client, features, name="gsa-boundaries.geojson"):
    return client.post(
        PREVIEW, {"file": SimpleUploadedFile(name, _geojson(features))}, HTTP_HX_REQUEST="true"
    )


def _write(tmp_path, features, name="gsa-boundaries.geojson"):
    path = tmp_path / name
    path.write_bytes(_geojson(features))
    return str(path)


@pytest.fixture
def boundary():
    return BoundaryFactory()


def test_three_outlines_make_three_zones_of_the_chosen_type(boundary):
    client = _client()
    preview = _upload(client, THREE)
    assert preview.status_code == 200
    page = preview.content.decode()
    assert "Name the zones" in page
    assert "OpenH2O found 3 outlines and 2 columns in gsa-boundaries.geojson." in page
    assert "What Import would do" in page
    assert "Import 3 zones" in page
    result = import_and_read(
        client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "subbasin"}
    )
    assert "OpenH2O imported 3 zones." in result.content.decode()
    zones = Zone.objects.order_by("name")
    assert [z.name for z in zones] == ["Eastside GSA", "North Fork GSA", "Westside GSA"]
    assert {z.zone_type for z in zones} == {"subbasin"}
    assert {z.boundary_id for z in zones} == {boundary.pk}


def test_the_preview_writes_nothing(boundary):
    _upload(_client(), THREE)
    assert Zone.objects.count() == 0


def test_the_command_gives_the_screen_result(boundary, tmp_path):
    call_command(
        "import_zones", _write(tmp_path, THREE), name_column="GSA_Name", zone_type="management_area",
        stdout=open("/dev/null", "w"),
    )
    by_command = {(z.name, z.zone_type, round(z.geometry.area, 12)) for z in Zone.objects.all()}
    Zone.objects.all().delete()
    client = _client()
    preview = _upload(client, THREE)
    import_and_read(client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"})
    by_screen = {(z.name, z.zone_type, round(z.geometry.area, 12)) for z in Zone.objects.all()}
    assert by_command == by_screen
    assert len(by_screen) == 3


def test_a_dry_run_saves_nothing_and_says_so(boundary, tmp_path, capsys):
    call_command("import_zones", _write(tmp_path, THREE), name_column="GSA_Name",
                 zone_type="management_area", dry_run=True)
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "Dry run: OpenH2O did not save anything."
    assert "3 new zones: Imported" in out
    assert Zone.objects.count() == 0


def test_a_name_already_used_by_a_zone_of_that_type_is_listed_and_not_loaded(boundary):
    ZoneFactory(name="Westside GSA", zone_type="management_area", boundary=boundary)
    ZoneFactory(name="Eastside GSA", zone_type="subbasin", boundary=boundary)
    client = _client()
    preview = _upload(client, THREE)
    page = preview.content.decode()
    assert "name already used by a zone of this type" in page
    assert "Westside GSA" in page
    assert "Import 2 zones" in page
    result = import_and_read(
        client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"}
    )
    assert "OpenH2O imported 2 zones and left out the 1 outline the preview listed." in result.content.decode()
    assert Zone.objects.filter(name="Westside GSA").count() == 1
    # A zone of another type with the same name does not block the import.
    assert Zone.objects.filter(name="Eastside GSA", zone_type="management_area").count() == 1


def test_an_outline_without_a_name_is_counted_and_not_loaded(boundary):
    features = THREE + [_feature({"GSA_Name": "", "GSA_ID": 4}, _square(-119.49, 36.49))]
    client = _client()
    preview = _upload(client, features)
    page = preview.content.decode()
    assert "outline without a name" in page
    import_and_read(client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"})
    assert Zone.objects.count() == 3


def test_outlines_that_share_a_name_become_one_zone(boundary):
    features = THREE + [_feature({"GSA_Name": "Eastside GSA", "GSA_ID": 5}, _square(-119.48, 36.49))]
    client = _client()
    preview = _upload(client, features)
    page = preview.content.decode()
    assert "2 outlines in this file share the name Eastside GSA. OpenH2O joins them into one zone." in page
    import_and_read(client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"})
    eastside = Zone.objects.get(name="Eastside GSA")
    assert len(eastside.geometry) == 2
    assert Zone.objects.count() == 3


def test_changing_the_name_column_updates_the_counts(boundary):
    client = _client()
    preview = _upload(client, THREE)
    again = client.post(
        PREVIEW, {"token": token_of(preview), "name_column": "GSA_ID", "zone_type": "management_area"},
        HTTP_HX_REQUEST="true",
    )
    assert "Import 3 zones" in again.content.decode()
    import_and_read(client, COMMIT, token_of(again), {"name_column": "GSA_ID", "zone_type": "management_area"})
    assert sorted(Zone.objects.values_list("name", flat=True)) == ["1", "2", "3"]


def test_outlines_with_no_columns_are_refused(boundary):
    response = _upload(_client(), [_feature({}, _square(-119.52, 36.49))])
    assert (
        "The outlines in this file have no columns to name the zones from. Add a column of zone "
        "names in a GIS program and upload the file again."
    ) in response.content.decode()
    assert Zone.objects.count() == 0


def test_a_site_with_no_boundary_is_refused():
    assert not Boundary.objects.exists()
    response = _upload(_client(), THREE)
    assert (
        "This site's boundary is not set yet. Set it in the Setup Wizard, then import your zones."
        in unescape(response.content.decode())
    )


def test_a_second_import_of_the_same_file_writes_nothing_new(boundary):
    client = _client()
    for _ in range(2):
        preview = _upload(client, THREE)
        if "Import 3 zones" in preview.content.decode():
            import_and_read(client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"})
    assert Zone.objects.count() == 3
    assert "OpenH2O has nothing to import from this file." in preview.content.decode()


def test_the_zones_page_carries_the_two_actions(boundary):
    ZoneFactory(boundary=boundary)
    page = _client().get(reverse("geography:zone_list")).content.decode()
    assert "Import zones" in page
    assert "Assign use areas to zones" in page


def test_the_import_page_reads_as_approved(boundary):
    page = _client().get(reverse("geography:zone_import")).content.decode()
    assert "This page imports zones from a map file, one zone for each name in the file." in page
    assert "Zone outlines" in page
    assert "On the preview you choose the column that holds each zone's name and the zone type." in unescape(page)
    assert "Back to Zones" in page


def test_a_multipolygon_outline_keeps_its_parts(boundary):
    two_parts = [_square(-119.52, 36.49), _square(-119.50, 36.49)]
    client = _client()
    preview = _upload(client, [_feature({"GSA_Name": "Split GSA"}, two_parts, kind="MultiPolygon")])
    import_and_read(client, COMMIT, token_of(preview), {"name_column": "GSA_Name", "zone_type": "management_area"})
    zone = Zone.objects.get(name="Split GSA")
    assert len(zone.geometry) == 2
    assert zone.geometry.equals(GEOSGeometry(json.dumps({"type": "MultiPolygon", "coordinates": two_parts}), srid=4326))
