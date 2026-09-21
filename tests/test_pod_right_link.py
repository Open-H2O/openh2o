# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-02 Task 2, D2: a point of diversion names its right, on every path that
creates or edits one.

Three doors proven here, each RED against the unfixed tree (the exact quotes
live in 146-02-EVIDENCE.md):

  1. The POD page's "Water right" panel (an HTMX POST to
     surface:pod_link_right): link and unlink through the endpoint.
  2. The Add Infrastructure diversion form writes the FK at creation.
  3. The bulk importer resolves an `APPL_ID` / `water_right` column against
     WaterRight.right_id, and rejects an unresolved value as a named row
     error rather than silently leaving the point unlinked.
"""
import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from infrastructure import importer
from surface.models import PointOfDiversion
from tests.factories import PointOfDiversionFactory, WaterRightFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"linkuser{n}")
    email = factory.Sequence(lambda n: f"linkuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. The POD page's link-right endpoint
# ---------------------------------------------------------------------------


def test_link_right_sets_fk_and_renders_link(auth_client):
    right = WaterRightFactory(right_id="A001885")
    pod = PointOfDiversionFactory(water_right=None)

    resp = auth_client.post(
        reverse("surface:pod_link_right", args=[pod.pk]),
        {"water_right_id": right.pk},
    )

    assert resp.status_code == 200
    pod.refresh_from_db()
    assert pod.water_right_id == right.pk
    assert b"A001885" in resp.content
    assert b"No water right linked." not in resp.content


def test_unlink_right_clears_fk_and_renders_no_right(auth_client):
    right = WaterRightFactory(right_id="A005724")
    pod = PointOfDiversionFactory(water_right=right)

    resp = auth_client.post(
        reverse("surface:pod_link_right", args=[pod.pk]),
        {"water_right_id": ""},
    )

    assert resp.status_code == 200
    pod.refresh_from_db()
    assert pod.water_right_id is None
    assert b"No water right linked." in resp.content


def test_link_right_a_bare_get_is_405(auth_client):
    pod = PointOfDiversionFactory(water_right=None)
    resp = auth_client.get(reverse("surface:pod_link_right", args=[pod.pk]))
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# 2. The Add Infrastructure diversion form writes the FK
# ---------------------------------------------------------------------------


def test_add_form_writes_water_right_fk(auth_client):
    right = WaterRightFactory(right_id="A006111")

    resp = auth_client.post(reverse("infrastructure:add"), {
        "infra_type": "diversion",
        "name": "New Intake",
        "status": "active",
        "notes": "",
        "geometry_json": json.dumps({"type": "Point", "coordinates": [-120.5, 37.3]}),
        "water_right_id": right.pk,
    })

    assert resp.status_code == 302
    pod = PointOfDiversion.objects.get(name="New Intake")
    assert pod.water_right_id == right.pk


def test_add_form_with_no_right_selected_leaves_it_unlinked(auth_client):
    resp = auth_client.post(reverse("infrastructure:add"), {
        "infra_type": "diversion",
        "name": "Unlinked Intake",
        "status": "active",
        "notes": "",
        "geometry_json": json.dumps({"type": "Point", "coordinates": [-120.5, 37.3]}),
        "water_right_id": "",
    })

    assert resp.status_code == 302
    pod = PointOfDiversion.objects.get(name="Unlinked Intake")
    assert pod.water_right_id is None


# ---------------------------------------------------------------------------
# 3. The bulk importer resolves and rejects
# ---------------------------------------------------------------------------


def test_importer_resolves_water_right_by_right_id():
    right = WaterRightFactory(right_id="A007012")
    rows = [{
        "NAME": "POD A007012_01",
        "LAT": "37.35",
        "LON": "-120.90",
        "APPL_ID": "A007012",
    }]
    mapping = {
        "name": "NAME", "latitude": "LAT", "longitude": "LON",
        "water_right": "APPL_ID",
    }
    results = importer.validate_rows(rows, mapping, "diversion", set())
    assert results[0]["errors"] == []
    assert results[0]["data"]["water_right_id"] == right.pk

    created = importer.commit_rows(results, "diversion")
    assert created == 1
    pod = PointOfDiversion.objects.get(name="POD A007012_01")
    assert pod.water_right_id == right.pk


def test_importer_rejects_unresolved_water_right_id():
    rows = [{
        "NAME": "POD Orphan",
        "LAT": "37.35",
        "LON": "-120.90",
        "APPL_ID": "A999999",
    }]
    mapping = {
        "name": "NAME", "latitude": "LAT", "longitude": "LON",
        "water_right": "APPL_ID",
    }
    results = importer.validate_rows(rows, mapping, "diversion", set())

    assert results[0]["errors"] == [
        "no water right with id A999999; import the rights list first."
    ]
    created = importer.commit_rows(results, "diversion")
    assert created == 0
    assert not PointOfDiversion.objects.filter(name="POD Orphan").exists()


def test_importer_leaves_water_right_unset_when_column_blank():
    rows = [{
        "NAME": "POD No Right Column",
        "LAT": "37.35",
        "LON": "-120.90",
        "APPL_ID": "",
    }]
    mapping = {
        "name": "NAME", "latitude": "LAT", "longitude": "LON",
        "water_right": "APPL_ID",
    }
    results = importer.validate_rows(rows, mapping, "diversion", set())
    assert results[0]["errors"] == []
    assert "water_right_id" not in results[0]["data"]

    created = importer.commit_rows(results, "diversion")
    assert created == 1
    pod = PointOfDiversion.objects.get(name="POD No Right Column")
    assert pod.water_right_id is None


def test_water_right_alias_resolves_appl_id_column_name():
    """auto_map_columns finds APPL_ID unassisted (146-02's own crosswalk)."""
    mapping = importer.auto_map_columns(
        ["APPL_ID", "APPL_POD", "SOURCE_NAME", "LATITUDE", "LONGITUDE"], "diversion",
    )
    assert mapping["water_right"] == "APPL_ID"
    # APPL_POD is the state's natural POD id (146-02's crosswalk note: POD_NAME
    # is blank on every row of the real shape-1 export).
    assert mapping["name"] == "APPL_POD"


def test_preview_shows_the_resolved_water_right_per_row(auth_client):
    WaterRightFactory(right_id="A001885")
    csv_content = (
        "APPL_ID,APPL_POD,SOURCE_NAME,LATITUDE,LONGITUDE\r\n"
        "A001885,A001885_01,MERCED RIVER,37.35,-120.90\r\n"
        "A999999,A999999_01,OWENS CREEK,37.10,-120.10\r\n"
    )
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("points.csv", csv_content.encode(), content_type="text/csv")
    resp = auth_client.post(reverse("infrastructure:import_preview"), {
        "infra_type": "diversion", "file": upload,
    })

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Water right (resolved)" in body
    assert "A001885" in body
    assert "not found: A999999" in body
