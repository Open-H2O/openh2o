# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-190: `import_wells` reads the columns docs/DATA-IMPORT.md says it reads.

Before this fix (145-02's walk of shape 4, S3): a file carrying `depth_ft`,
`casing_diameter_in`, `wcr_number` and `owner_name` imported with "Imported 20
wells, 0 errors" and all four fields blank, and a well with the same name as
an existing one imported as a silent second row ("0 duplicates skipped").

The primary fixture below is the shape-4 dataset's own `wells.csv`
(`~/Documents/Vadose/Products/openh2o/six-shapes-2026-09/datasets/
shape-4-well-registry/wells.csv`, header and three rows reproduced verbatim,
read 2026-09-23) -- not `district-well-inventory.csv`, which the 146-06 plan
names but which carries no `wcr_number` or `owner_name` column at all (its
header is `well_id,owner,apn,use,depth_ft,casing_diameter_in,pump,meter,
record_type,section`); `wells.csv` is the file the shape-4 walker actually ran
`import_wells` against and is what ISS-190 itself describes. A second,
clearly-synthetic fixture covers `owner_name` non-blank, `capacity_gpm`,
`year_pumping_began` and `well_type`, none of which the real file's 20 rows
ever populate (every row's `owner_name` cell is empty).
"""
import io
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.factories import WellFactory, WellTypeFactory
from wells.models import Well

pytestmark = pytest.mark.django_db

# Shape-4's wells.csv, header + 3 rows, byte-for-byte from the real file.
SHAPE_4_WELLS_CSV = """WELL_NAME,LATITUDE,LONGITUDE,WELL_REG_ID,wcr_number,state_well_number,depth_ft,casing_diameter_in,owner_name
T11S R11E well 01,37.00429,-120.7361,WCR0066445,WCR0066445,,485,8,
T11S R11E well 04,37.00542,-120.80939,WCR2016-008961,WCR2016-008961,,270,8.625,
T11S R11E well 06,36.99087,-120.80956,WCR0013848,WCR0013848,,255,6,
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_shape4_wells_csv_reads_depth_casing_wcr_and_owner(tmp_path):
    path = _write(tmp_path, "wells.csv", SHAPE_4_WELLS_CSV)
    out = io.StringIO()
    call_command("import_wells", str(path), stdout=out)

    well1 = Well.objects.get(name="T11S R11E well 01")
    assert well1.depth_ft == Decimal("485")
    assert well1.casing_diameter_in == Decimal("8")
    assert well1.wcr_number == "WCR0066445"
    assert well1.owner_name == ""  # present in the file, empty on every row

    well4 = Well.objects.get(name="T11S R11E well 04")
    assert well4.depth_ft == Decimal("270")
    # Well.casing_diameter_in is decimal_places=2 (wells/models.py); the
    # file's own 8.625 rounds at the database, not a command bug.
    assert well4.casing_diameter_in == Decimal("8.63")
    assert well4.wcr_number == "WCR2016-008961"

    # WELL_REG_ID is this agency's own local id, never conflated with the
    # state's WCR number, even though this file happens to carry the same
    # string in both columns.
    assert well1.well_registration_id == "WCR0066445"

    assert Well.objects.count() == 3
    assert "Imported 3 wells" in out.getvalue()


def test_unknown_column_warns_but_still_imports(tmp_path):
    csv_text = (
        "WELL_NAME,LATITUDE,LONGITUDE,driller_name\n"
        "Test Well A,37.0,-120.0,Acme Drilling\n"
    )
    path = _write(tmp_path, "wells.csv", csv_text)
    out = io.StringIO()
    call_command("import_wells", str(path), stdout=out)

    assert "column driller_name not read" in out.getvalue()
    assert Well.objects.filter(name="Test Well A").exists()


def test_same_name_second_row_warns_by_default_and_still_imports(tmp_path):
    WellFactory(name="Existing Well", well_registration_id=None)

    csv_text = "WELL_NAME,LATITUDE,LONGITUDE\nExisting Well,37.0,-120.0\n"
    path = _write(tmp_path, "wells.csv", csv_text)
    out = io.StringIO()
    call_command("import_wells", str(path), stdout=out)

    assert (
        "a well named Existing Well exists; imported as a second row; "
        "pass --skip-duplicates to skip" in out.getvalue()
    )
    assert Well.objects.filter(name="Existing Well").count() == 2


def test_skip_duplicates_flag_skips_the_same_name_row(tmp_path):
    WellFactory(name="Existing Well", well_registration_id=None)

    csv_text = "WELL_NAME,LATITUDE,LONGITUDE\nExisting Well,37.0,-120.0\n"
    path = _write(tmp_path, "wells.csv", csv_text)
    out = io.StringIO()
    call_command("import_wells", str(path), skip_duplicates=True, stdout=out)

    assert Well.objects.filter(name="Existing Well").count() == 1
    assert "skipped" in out.getvalue().lower()


def test_owner_capacity_year_and_well_type_columns(tmp_path):
    production = WellTypeFactory(name="Production (test)")

    csv_text = (
        "WELL_NAME,LATITUDE,LONGITUDE,WELL_REG_ID,owner_name,capacity_gpm,"
        "year_pumping_began,well_type\n"
        "Synthetic Well 1,37.1,-120.1,LOCAL-001,Jane Farmer,450,1998,"
        "Production (test)\n"
        "Synthetic Well 2,37.2,-120.2,LOCAL-002,John Rancher,900,2005,"
        "Nonexistent Type\n"
    )
    path = _write(tmp_path, "synthetic-wells.csv", csv_text)
    out = io.StringIO()
    call_command("import_wells", str(path), stdout=out)

    w1 = Well.objects.get(name="Synthetic Well 1")
    assert w1.owner_name == "Jane Farmer"
    assert w1.capacity_gpm == Decimal("450")
    assert w1.year_pumping_began == 1998
    assert w1.well_type_id == production.pk

    w2 = Well.objects.get(name="Synthetic Well 2")
    assert w2.well_type_id is None
    assert "well type 'Nonexistent Type' not found" in out.getvalue()


def test_dry_run_prints_columns_read_and_ignored(tmp_path):
    csv_text = (
        "WELL_NAME,LATITUDE,LONGITUDE,wcr_number,driller_name\n"
        "Test Well A,37.0,-120.0,WCR001,Acme Drilling\n"
    )
    path = _write(tmp_path, "wells.csv", csv_text)
    out = io.StringIO()
    call_command("import_wells", str(path), dry_run=True, stdout=out)

    assert Well.objects.count() == 0
    body = out.getvalue()
    assert "Columns that will be read: WELL_NAME, LATITUDE, LONGITUDE, wcr_number" in body
    assert "Columns that will be ignored: driller_name" in body


def test_file_not_found_names_docker_compose_cp(tmp_path):
    missing = tmp_path / "nope.csv"
    with pytest.raises(CommandError, match="docker compose cp"):
        call_command("import_wells", str(missing), stdout=io.StringIO())
