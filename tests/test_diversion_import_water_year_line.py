# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-387: `import_diversion_records` says when records landed in no water year.

A record whose month falls in no water year is saved with no water year. The
command used to report that as "attached to 'No water year assigned'", which
reads as if a water year by that name existed. Now it writes one plain line that
says what to do, and names real water years only.

Test data is INVENTED: "Example Ditch Company" right EX-0001 with one point.
"""
import io
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command

from surface.models import DiversionRecord
from tests.factories import (
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
)

pytestmark = pytest.mark.django_db

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "AI-OPERATOR-GUIDE.md"

BOOK_CSV = (
    "date,run,headgate,turnout,order_no,start,stop,flow_cfs,miners_inches,hours,acre_feet,event\n"
    "2024-03-01,2 Run,Example Headgate,Turnout 1,2024-001,2024-03-01 06:00,2024-03-16 06:00,0.55,22,360,16.50,irrigation\n"
    "2024-04-01,2 Run,Example Headgate,Turnout 1,2024-002,2024-04-01 06:00,2024-04-16 06:00,0.86,34,360,25.50,irrigation\n"
)

NO_YEAR_LINE = (
    "2 record(s) are not in a water year yet. Create each water year that covers "
    "their months with create_water_year. OpenH2O then attaches them."
)
OLD_LINE = "attached to 'No water year assigned'"


@pytest.fixture
def csv_path(tmp_path):
    right = WaterRightFactory(right_id="EX-0001")
    PointOfDiversionFactory(
        water_right=right, name="EX-0001_01", local_name="Example Headgate", status="active",
    )
    path = tmp_path / "book.csv"
    path.write_text(BOOK_CSV)
    return path


def _run(path):
    out = io.StringIO()
    call_command("import_diversion_records", str(path), stdout=out)
    return out.getvalue()


def test_a_site_with_no_water_year_gets_the_new_line_and_not_the_old_one(csv_path):
    output = _run(csv_path)

    assert DiversionRecord.objects.count() == 2
    assert NO_YEAR_LINE in output.splitlines()[:4]
    assert OLD_LINE not in output


def test_a_site_with_a_covering_water_year_gets_no_such_line(csv_path):
    ReportingPeriodFactory(
        name="2024 Example Water Year", start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
    )

    output = _run(csv_path)

    assert NO_YEAR_LINE not in output
    assert "not in a water year yet" not in output
    assert "2 record(s) attached to '2024 Example Water Year'" in output


def test_the_operator_guide_points_at_create_water_year_for_diversion_records():
    rows = [
        line for line in GUIDE.read_text().splitlines()
        if line.startswith("| A year of diversion volumes")
    ]
    assert len(rows) == 1
    assert "create_water_year" in rows[0]
