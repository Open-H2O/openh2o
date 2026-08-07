# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the ``import_boundary`` management command (ISS-122).

Before this command existed, the Setup Wizard's upload view was the ONLY code
able to turn an operator's own GeoJSON into a ``Boundary`` row — a headless
operator (no browser, SSH only) had no equivalent, even though
``docs/AI-OPERATOR-GUIDE.md`` told them the command-line path "reaches the
same end state" as the wizard. This command closes that gap by sharing the
wizard's own parser (``setup/boundaries.py``), including its plain-language
error wording and its new validity-repair step.

Follows the fixture/assertion style of ``tests/test_setup_polish.py`` (the
wizard's own upload tests) and ``tests/test_auto_populate.py`` (the
management-command idiom: ``call_command`` + ``StringIO`` + ``CommandError``).
"""
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from geography.models import Boundary


def _write_geojson(tmp_path, payload, filename="boundary.geojson"):
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    return str(path)


def _feature(properties, name="Uploaded Watershed"):
    """A one-feature FeatureCollection with a valid polygon and given properties.

    Mirrors ``tests/test_setup_polish.py::_feature`` so the same file shape
    proves the wizard and this command agree.
    """
    props = {"name": name}
    props.update(properties)
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-123.0, 38.5], [-122.5, 38.5],
                    [-122.5, 39.0], [-123.0, 39.0], [-123.0, 38.5],
                ]],
            },
        }],
    }


# ---------------------------------------------------------------------------
# Creation + idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_creates_boundary_from_featurecollection(tmp_path):
    path = _write_geojson(tmp_path, _feature({"areasqmi": 1484.9, "huc8": "18010110"}))

    out = StringIO()
    call_command("import_boundary", file_path=path, stdout=out)

    boundary = Boundary.objects.get()
    assert boundary.name == "Uploaded Watershed"
    assert boundary.area_sq_miles == pytest.approx(1484.9)
    assert boundary.huc == "18010110"
    assert boundary.geometry.valid
    output = out.getvalue()
    assert "Created" in output
    assert "auto_populate --boundary" in output
    assert '"Uploaded Watershed"' in output


@pytest.mark.django_db
def test_rerun_updates_in_place_not_duplicate(tmp_path):
    path = _write_geojson(tmp_path, _feature({"areasqmi": 1484.9}))

    call_command("import_boundary", file_path=path, stdout=StringIO())
    assert Boundary.objects.count() == 1

    # Re-run against the same file — a real operator re-running the same
    # command after an interruption, or refreshing a boundary from an updated
    # export.
    out = StringIO()
    call_command("import_boundary", file_path=path, stdout=out)

    assert Boundary.objects.count() == 1
    assert "Updated" in out.getvalue()


# ---------------------------------------------------------------------------
# --name override
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_name_override(tmp_path):
    path = _write_geojson(tmp_path, _feature({}, name="File's Own Name"))

    call_command("import_boundary", file_path=path, name="Operator Chosen Name", stdout=StringIO())

    boundary = Boundary.objects.get()
    assert boundary.name == "Operator Chosen Name"
    assert not Boundary.objects.filter(name="File's Own Name").exists()


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_writes_nothing(tmp_path):
    path = _write_geojson(tmp_path, _feature({"areasqmi": 1484.9}))

    out = StringIO()
    call_command("import_boundary", file_path=path, dry_run=True, stdout=out)

    assert Boundary.objects.count() == 0
    assert "DRY RUN" in out.getvalue()


# ---------------------------------------------------------------------------
# Error paths — reusing the wizard's own operator-facing wording verbatim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_point_geometry_fails_with_wizard_polygon_message(tmp_path):
    point_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-119.0, 36.0]},
        "properties": {},
    }
    path = _write_geojson(tmp_path, point_feature)

    with pytest.raises(CommandError, match="Polygon or MultiPolygon is required"):
        call_command("import_boundary", file_path=path, stdout=StringIO())

    assert not Boundary.objects.exists()


@pytest.mark.django_db
def test_malformed_json_fails_with_wizard_json_message(tmp_path):
    path = tmp_path / "bad.geojson"
    path.write_text("this is not json at all")

    with pytest.raises(CommandError, match="valid JSON"):
        call_command("import_boundary", file_path=str(path), stdout=StringIO())

    assert not Boundary.objects.exists()


@pytest.mark.django_db
def test_missing_file_raises_command_error(tmp_path):
    missing = str(tmp_path / "does-not-exist.geojson")

    with pytest.raises(CommandError, match="does-not-exist.geojson"):
        call_command("import_boundary", file_path=missing, stdout=StringIO())

    assert not Boundary.objects.exists()


# ---------------------------------------------------------------------------
# Area behavior — BLOCKING rule: never compute an area from the geometry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_area_property_is_read_from_the_file(tmp_path):
    path = _write_geojson(tmp_path, _feature({"areasqmi": 1484.9}))

    call_command("import_boundary", file_path=path, stdout=StringIO())

    boundary = Boundary.objects.get()
    assert boundary.area_sq_miles == pytest.approx(1484.9)


@pytest.mark.django_db
def test_file_without_area_property_leaves_area_empty(tmp_path):
    """A file that carries no area property must leave the field empty — on
    purpose, never filled in with a number derived from the polygon itself
    (BLOCKING project rule, Brent 2026-08-05)."""
    path = _write_geojson(tmp_path, _feature({}))

    out = StringIO()
    call_command("import_boundary", file_path=path, stdout=out)

    boundary = Boundary.objects.get()
    assert boundary.area_sq_miles is None
    # The geometry itself has a real, computable extent — a passing test here
    # is proof the command never reached for it, not just an absence of a
    # crash.
    assert boundary.geometry.area > 0
    assert "not specified in the file" in out.getvalue()


# ---------------------------------------------------------------------------
# Validity repair (ISS-122's one deliberate behavior change)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_self_intersecting_polygon_is_repaired_to_valid(tmp_path):
    # A bowtie: the ring crosses itself at its midpoint, which GEOS reports
    # invalid. core/management/commands/seed_merced_base.py has always
    # repaired this shape for its own fixture with buffer(0); until ISS-122
    # the wizard's upload path stored it invalid and silent.
    bowtie = {
        "type": "Feature",
        "properties": {"name": "Bowtie Boundary"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-120.0, 36.0], [-119.0, 37.0],
                [-120.0, 37.0], [-119.0, 36.0], [-120.0, 36.0],
            ]],
        },
    }
    path = _write_geojson(tmp_path, bowtie)

    call_command("import_boundary", file_path=path, stdout=StringIO())

    boundary = Boundary.objects.get()
    assert boundary.geometry.valid
