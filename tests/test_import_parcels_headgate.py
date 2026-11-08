# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-366: ``import_parcels`` links each use area to its headgate.

A headgate column (default ``HEADGATE``, option ``--headgate-field``) names a
point of diversion by its local name, else by its name. The link is a
``surface.PointOfDiversionParcel`` at the model's default fraction; a link already
on the site keeps its share and is never duplicated. Messages are copied from
rows 18 and 39 to 41 of ``152-03.1-ROWS.md``.

Test data is INVENTED: "Example Ditch Company" has two headgates, the points of
diversion X000001_01 ("North Headgate") and X000001_02 ("South Headgate"), and
three use areas, parcels EX-001, EX-002 and EX-003.
"""
import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from parcels.models import CropType, Parcel, UsageLocation
from surface.models import PointOfDiversionParcel
from tests.factories import ParcelFactory, PointOfDiversionFactory

pytestmark = pytest.mark.django_db

ROW_18 = (
    "The column that names each use area's headgate. The command reads the column "
    "HEADGATE unless you name another. Each value must be the local name of a point "
    "of diversion on the site. A point's name works too."
)
ROW_40 = (
    "The command did not import any use area. Add the missing points of diversion or "
    "correct the names in the file. Then run the command again."
)


def _default_fraction():
    return Decimal(str(PointOfDiversionParcel._meta.get_field("fraction").default))


def _ring(x):
    return [[[x, 36.5], [x + 0.01, 36.5], [x + 0.01, 36.51], [x, 36.51], [x, 36.5]]]


def _feature(apn, x, **props):
    return {
        "type": "Feature",
        "properties": {"APN": apn, "OWNER": "Example Ditch Company", **props},
        "geometry": {"type": "Polygon", "coordinates": _ring(x)},
    }


def _file(tmp_path, headgates, **extra):
    """Three use areas, EX-001 to EX-003, with the given HEADGATE values (None: no column)."""
    features = []
    for i, (apn, hg) in enumerate(zip(["EX-001", "EX-002", "EX-003"], headgates)):
        props = dict(extra)
        if hg is not None:
            props["HEADGATE"] = hg
        features.append(_feature(apn, -119.5 + i * 0.1, **props))
    path = tmp_path / "use-areas.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return str(path)


@pytest.fixture
def headgates(db):
    north = PointOfDiversionFactory(name="X000001_01", local_name="North Headgate")
    south = PointOfDiversionFactory(name="X000001_02", local_name="South Headgate")
    return north, south


def _run(*args):
    out, err = StringIO(), StringIO()
    error = ""
    try:
        call_command("import_parcels", *args, stdout=out, stderr=err)
    except CommandError as exc:
        error = str(exc)
    return " ".join((out.getvalue() + err.getvalue() + " " + error).split())


def _links():
    return {
        (ln.parcel.parcel_number, ln.point_of_diversion.name): ln.fraction
        for ln in PointOfDiversionParcel.objects.select_related("parcel", "point_of_diversion")
    }


def test_each_use_area_is_linked_to_its_point_at_the_default_fraction(headgates, tmp_path):
    out = _run(_file(tmp_path, ["North Headgate", "North Headgate", "X000001_02"]))

    default = _default_fraction()
    assert _links() == {
        ("EX-001", "X000001_01"): default,
        ("EX-002", "X000001_01"): default,
        ("EX-003", "X000001_02"): default,
    }
    # Row 41, with the counts filled in.
    assert "OpenH2O linked 3 use areas to their headgates." in out
    assert "Another" not in out


def test_a_use_area_already_on_the_site_gets_its_link_and_a_kept_link_keeps_its_share(
    headgates, tmp_path
):
    north, south = headgates
    kept = ParcelFactory(parcel_number="EX-002")
    PointOfDiversionParcel.objects.create(
        point_of_diversion=north, parcel=kept, fraction=Decimal("0.4")
    )
    ParcelFactory(parcel_number="EX-003")  # on the site, not yet linked

    out = _run(_file(tmp_path, ["North Headgate", "North Headgate", "X000001_02"]))

    links = _links()
    assert links[("EX-002", "X000001_01")] == Decimal("0.4")
    assert links[("EX-001", "X000001_01")] == _default_fraction()
    assert links[("EX-003", "X000001_02")] == _default_fraction()
    assert PointOfDiversionParcel.objects.count() == 3, "a link was duplicated"
    # Row 41: two new links, one use area already linked.
    assert (
        "OpenH2O linked 2 use areas to their headgates. "
        "Another 1 use area in the file was already linked to its headgate."
    ) in out


def test_running_it_twice_adds_no_second_link(headgates, tmp_path):
    path = _file(tmp_path, ["North Headgate", "North Headgate", "X000001_02"])
    _run(path)

    out = _run(path)

    assert PointOfDiversionParcel.objects.count() == 3
    assert (
        "OpenH2O linked 0 use areas to their headgates. "
        "Another 3 use areas in the file were already linked to their headgates."
    ) in out


def test_a_local_name_is_tried_before_a_points_name(headgates, tmp_path):
    north, _south = headgates
    # A third point whose NAME is another point's local name: the local name wins.
    PointOfDiversionFactory(name="North Headgate", local_name="")

    _run(_file(tmp_path, ["North Headgate", "North Headgate", "North Headgate"]))

    assert {p for (_, p) in _links()} == {"X000001_01"}


def test_a_value_no_point_holds_imports_nothing_and_is_named(headgates, tmp_path):
    parcels_before = Parcel.objects.count()

    out = _run(_file(tmp_path, ["North Headgate", "East Dock", "X000001_02"]))

    assert Parcel.objects.count() == parcels_before
    assert PointOfDiversionParcel.objects.count() == 0
    # Row 39 for that use area, then row 40.
    assert "Use area EX-002: OpenH2O did not find a point of diversion named 'East Dock'." in out
    assert ROW_40 in out


def test_a_crop_column_creates_no_land_use_record_and_no_crop_type(headgates, tmp_path):
    crops_before = CropType.objects.count()

    _run(_file(tmp_path, ["North Headgate", "North Headgate", "X000001_02"], CROP="Alfalfa"))

    assert Parcel.objects.filter(parcel_number__in=["EX-001", "EX-002", "EX-003"]).count() == 3
    assert UsageLocation.objects.count() == 0
    assert CropType.objects.count() == crops_before


def test_headgate_field_names_another_column(headgates, tmp_path):
    path = tmp_path / "other.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        _feature("EX-001", -119.5, GATE="South Headgate"),
    ]}))

    _run(str(path), "--headgate-field", "GATE")

    assert _links() == {("EX-001", "X000001_02"): _default_fraction()}


def test_headgate_field_help_is_row_18():
    from parcels.management.commands.import_parcels import Command

    parser = Command().create_parser("manage.py", "import_parcels")
    action = next(a for a in parser._actions if "--headgate-field" in a.option_strings)

    assert action.help == ROW_18


def test_dry_run_with_a_headgate_column_writes_no_link(headgates, tmp_path):
    _run(_file(tmp_path, ["North Headgate", "North Headgate", "X000001_02"]), "--dry-run")

    assert PointOfDiversionParcel.objects.count() == 0
    assert not Parcel.objects.filter(parcel_number="EX-001").exists()


def test_a_headgate_field_the_file_lacks_is_refused_with_row_33(headgates, tmp_path):
    # Main session, 152-03.1: a mistyped column name must not skip every link
    # without a word. Row 33's sentence, shared with the two import commands.
    path = tmp_path / "other.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        _feature("EX-001", -119.5, GATE="South Headgate"),
    ]}))

    out = _run(str(path), "--headgate-field", "GAET")

    assert out.endswith(
        "The file does not have a column named GAET. "
        "Check the spelling against the file's first row."
    )
    assert not Parcel.objects.filter(parcel_number="EX-001").exists()
