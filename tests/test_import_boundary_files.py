# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1 step E: ``import_boundary --file`` reads a zipped shapefile and a KML file.

It reads them through the Setup Wizard's own function,
``setup.boundaries.boundary_from_upload``, so a file gives the same boundary on
either path. Help lines are copied from rows 16 and 17 of ``152-03.1-ROWS.md``.
The files are the wizard tests' fixtures (``tests/fixtures/boundaries``).
"""
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from geography.models import Boundary
from setup.boundaries import boundary_from_upload
from setup.management.commands.import_boundary import Command

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "boundaries"

ROW_16 = (
    "Load a boundary from a GeoJSON file, a zipped shapefile or a KML file. "
    "The Setup Wizard's upload step reads the same files. When a boundary of the "
    "same name is already on the site, the command updates that boundary."
)
ROW_17 = "The path of the boundary file inside the container."


@pytest.mark.parametrize("filename", ["square.zip", "square.kml"])
def test_the_command_makes_the_boundary_the_wizards_function_gives(filename):
    path = FIXTURES / filename
    expected_name, expected_geom, _attrs, _count = boundary_from_upload(
        SimpleUploadedFile(filename, path.read_bytes()), fallback_name=path.stem
    )

    call_command("import_boundary", file_path=str(path))

    boundary = Boundary.objects.get()
    assert boundary.name == expected_name
    assert boundary.geometry.srid == 4326
    assert boundary.geometry.equals(expected_geom)


def test_help_line_is_row_16():
    assert Command().help == ROW_16


def test_file_option_help_is_row_17():
    parser = Command().create_parser("manage.py", "import_boundary")
    action = next(a for a in parser._actions if "--file" in a.option_strings)

    assert action.help == ROW_17
