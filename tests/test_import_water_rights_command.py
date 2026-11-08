# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1 step A and ISS-365: ``import_water_rights`` and the NA / NaN rule.

The command reads the same eWRIMS rights list as the Water Rights Import screen
and writes the same ``WaterRight`` rows, because the screen's worker and the
command call one function. Every message a person reads is copied word for word
from the approved rows (``152-03.1-ROWS.md``, the "Fixed" column); the row number
is named beside each one.

Test data is INVENTED: "Example Ditch Company" holds two invented water rights,
X000001 and X000002. No real basin, district or water right number appears.
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from io import StringIO

from surface import importer
from surface.models import WaterRight, WaterRightType
from tests.import_flow import csv_text_of, import_and_read, token_of

pytestmark = pytest.mark.django_db

# Row 19 to 24, 30 to 33 (152-03.1-ROWS.md, Fixed column).
ROW_19 = "[DRY RUN] The command does not save any record."
ROW_20 = "Columns read:"
ROW_31 = "Write each --column as OpenH2O's name for a value, an equals sign and a column name."


def _row_23(n, m):
    # Row 23, with row 29's singular forms when a count is 1.
    records = "water right record" if n == 1 else "water right records"
    rows = "row" if m == 1 else "rows"
    return f"OpenH2O created {n} {records} and skipped {m} {rows}."


def _row_24(n, m):
    return f"OpenH2O would create {n} water right records and skip {m} rows."


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"wrcmduser{n}")
    email = factory.Sequence(lambda n: f"wrcmduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture(autouse=True)
def seeded_types(db):
    WaterRightType.objects.get_or_create(
        code="POST14", defaults={"name": "Post-1914 Appropriative"}
    )


# ---------------------------------------------------------------------------
# The invented file, in eWRIMS's own column names.
# ---------------------------------------------------------------------------

def _right(application_number, **over):
    row = {
        "APPLICATION_NUMBER": application_number,
        "WATER_RIGHT_TYPE": "Appropriative",
        "WATER_RIGHT_STATUS": "Licensed",
        "PRIMARY_OWNER_NAME": "Example Ditch Company",
        "SOURCE_NAME": "Example Creek",
        "WATERSHED": "Example Valley",
        "FACE_VALUE_AMOUNT": "1200.5",
        "FACE_VALUE_UNITS": "Acre-feet per Year",
        "MAX_DD_APPL": "12.5",
        "MAX_DD_UNITS": "Cubic Feet per Second",
        "PRIORITY_DATE": "1955-04-02",
        "LICENSE_ID": "L000001",
        "PERMIT_ID": "P000001",
        "USE_CODE": "Irrigation",
        "USE_NET_ACREAGE": "320",
        "DIRECT_SEASON_START_MONTH_1": "3",
        "DIRECT_DIV_SEASON_START_DAY_1": "1",
        "DIRECT_DIV_SEASON_END_MONTH_1": "10",
        "DIRECT_DIV_SEASON_END_DAY_1": "31",
        "STORAGE_SEASON_START_MONTH_1": "11",
        "STORAGE_SEASON_START_DAY_1": "1",
        "STORAGE_SEASON_END_MONTH_1": "2",
        "STORAGE_SEASON_END_DAY_1": "28",
    }
    row.update(over)
    return row


def _two_rights():
    return [
        _right("X000001"),
        _right(
            "X000002",
            FACE_VALUE_AMOUNT="300",
            MAX_DD_APPL="4",
            USE_NET_ACREAGE="80.25",
            LICENSE_ID="L000002",
            PERMIT_ID="P000002",
            WATER_RIGHT_TYPE="Statutory",
        ),
    ]


def _file(tmp_path, rows, name="rights.csv"):
    path = tmp_path / name
    path.write_text(csv_text_of(rows))
    return str(path)


def _run(*args):
    out = StringIO()
    call_command("import_water_rights", *args, stdout=out)
    return out.getvalue()


def _lines(text):
    return [line for line in text.splitlines() if line.strip()]


# Every model field either path writes.
_COMPARED = (
    "right_id", "holder_name", "state_status", "source_name", "watershed",
    "face_value_acre_feet", "max_rate_cfs", "priority_date", "license_number",
    "permit_number", "purpose_of_use", "net_acreage",
    "direct_season_start_month", "direct_season_start_day",
    "direct_season_end_month", "direct_season_end_day",
    "storage_season_start_month", "storage_season_start_day",
    "storage_season_end_month", "storage_season_end_day",
)


def _snapshot():
    return {
        right.right_id: {
            **{f: getattr(right, f) for f in _COMPARED},
            "right_type_name": right.right_type.name,
        }
        for right in WaterRight.objects.select_related("right_type")
    }


def _through_the_screen(client, rows):
    """Preview, then press Import with every auto-detected column, the way the browser does."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    text = csv_text_of(rows)
    preview = client.post(
        reverse("surface:water_right_import_preview"),
        {"file": SimpleUploadedFile("rights.csv", text.encode(), content_type="text/csv")},
        HTTP_HX_REQUEST="true",
    )
    assert preview.status_code == 200
    columns = list(rows[0].keys())
    mapping = importer.auto_map_columns(columns)
    post = {f"map:{field}": column for field, column in mapping.items()}
    status = import_and_read(
        client, reverse("surface:water_right_import_commit"), token_of(preview), post
    )
    assert status.status_code == 200
    return status


# ---------------------------------------------------------------------------
# The command and the screen write the same rows
# ---------------------------------------------------------------------------

def test_command_and_screen_write_the_same_water_rights(auth_client, tmp_path):
    rows = _two_rights()

    _through_the_screen(auth_client, rows)
    from_screen = _snapshot()
    assert set(from_screen) == {"X000001", "X000002"}, "the screen path imported nothing to compare"
    WaterRight.objects.all().delete()

    _run(_file(tmp_path, rows))
    from_command = _snapshot()

    assert from_command == from_screen
    assert from_command["X000001"]["right_type_name"] == "Post-1914 Appropriative"


def test_a_real_run_prints_row_23_last(tmp_path):
    out = _run(_file(tmp_path, _two_rights()))

    assert _lines(out)[-1] == _row_23(2, 0)
    assert WaterRight.objects.count() == 2


def test_a_skipped_row_is_named_with_the_word_row_and_counted(tmp_path):
    rows = _two_rights() + [_right("X000003", PRIMARY_OWNER_NAME="")]

    out = _run(_file(tmp_path, rows))

    # Row 22: "Row {n}: " and the import's own sentence.
    assert any(line.startswith("Row ") and ": " in line for line in _lines(out)), out
    assert _lines(out)[-1] == _row_23(2, 1)


def test_the_counts_say_record_and_row_in_the_singular_for_one(tmp_path):
    rows = [_right("X000001"), _right("X000002", PRIMARY_OWNER_NAME="")]

    out = _run(_file(tmp_path, rows))

    # Row 29: "water right record, row" when a count is 1.
    assert _lines(out)[-1] == "OpenH2O created 1 water right record and skipped 1 row."


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing_and_prints_row_19_first_and_row_24_last(tmp_path):
    out = _run(_file(tmp_path, _two_rights()), "--dry-run")

    assert WaterRight.objects.count() == 0
    lines = _lines(out)
    assert lines[0] == ROW_19
    assert lines[-1] == _row_24(2, 0)
    assert ROW_20 in lines
    # Row 21: a value with no column reads "{field}: no column" (the file has no
    # right_type column named in this list of columns? it has all but unmapped ones).


def test_dry_run_lists_a_field_with_no_column(tmp_path):
    rows = [{k: v for k, v in r.items() if k != "USE_NET_ACREAGE"} for r in _two_rights()]

    out = _run(_file(tmp_path, rows), "--dry-run")

    assert "net_acreage: no column" in [line.strip() for line in _lines(out)]


def test_two_rights_with_a_note_print_row_25_after_the_last_line(tmp_path):
    rows = [
        _right("X000001", MAX_DD_UNITS="Gallons per Minute"),
        _right("X000002", MAX_DD_UNITS="Gallons per Minute"),
    ]

    out = _run(_file(tmp_path, rows))

    lines = _lines(out)
    assert lines[-2] == _row_23(2, 0)
    assert lines[-1] == "2 rows have a note."


# ---------------------------------------------------------------------------
# --column
# ---------------------------------------------------------------------------

def test_column_option_reads_a_file_whose_acreage_column_is_named_acres(tmp_path):
    rows = []
    for r in _two_rights():
        r = dict(r)
        r["ACRES"] = r.pop("USE_NET_ACREAGE")
        rows.append(r)

    _run(_file(tmp_path, rows), "--column", "net_acreage=ACRES")

    from decimal import Decimal
    assert WaterRight.objects.get(right_id="X000001").net_acreage == Decimal("320")
    assert WaterRight.objects.get(right_id="X000002").net_acreage == Decimal("80.25")


def test_dry_run_lists_the_column_read_for_a_value(tmp_path):
    rows = []
    for r in _two_rights():
        r = dict(r)
        r["ACRES"] = r.pop("USE_NET_ACREAGE")
        rows.append(r)

    out = _run(_file(tmp_path, rows), "--column", "net_acreage=ACRES", "--dry-run")

    # Row 3: "OpenH2O's name for each value and the column the command reads for it."
    assert any("net_acreage" in ln and "ACRES" in ln for ln in _lines(out)), out


# ---------------------------------------------------------------------------
# The refusals: rows 30 to 33
# ---------------------------------------------------------------------------

def test_a_missing_file_is_refused_with_row_30(tmp_path):
    path = str(tmp_path / "nothing-here.csv")

    with pytest.raises(CommandError) as err:
        _run(path)

    assert str(err.value) == (
        f"OpenH2O cannot find the file {path}. "
        "Copy the file into the container with docker compose cp first."
    )


def test_a_column_without_an_equals_sign_is_refused_with_row_31(tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _two_rights()), "--column", "net_acreage")

    assert str(err.value) == ROW_31
    assert WaterRight.objects.count() == 0


def test_an_unknown_value_name_is_refused_with_row_32(tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _two_rights()), "--column", "bogus_value=ACRES")

    message = str(err.value)
    assert message.startswith(
        "The import does not read a value named bogus_value. Use one of these names: "
    )
    assert "net_acreage" in message and "right_id" in message
    assert WaterRight.objects.count() == 0


def test_a_column_the_file_lacks_is_refused_with_row_33(tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _two_rights()), "--column", "net_acreage=ACRES")

    assert str(err.value) == (
        "The file does not have a column named ACRES. "
        "Check the spelling against the file's first row."
    )
    assert WaterRight.objects.count() == 0


# ---------------------------------------------------------------------------
# ISS-365: NA and NaN read as empty, on the command and on the screen
# ---------------------------------------------------------------------------

def _na_rows():
    return [
        _right(
            "X000001",
            USE_NET_ACREAGE="NaN",
            LICENSE_ID="NA",
            DIRECT_SEASON_START_MONTH_1="NaN",
        ),
        _right("X000002"),
    ]


def _assert_na_row_imported_empty():
    right = WaterRight.objects.get(right_id="X000001")
    assert right.net_acreage is None
    assert not right.license_number
    assert right.direct_season_start_month is None
    # The other columns of the same row are read as usual.
    assert right.permit_number == "P000001"
    assert right.direct_season_end_month == 10


def test_na_and_nan_import_as_empty_through_the_command(tmp_path):
    _run(_file(tmp_path, _na_rows()))

    _assert_na_row_imported_empty()
    assert WaterRight.objects.count() == 2


def test_na_and_nan_import_as_empty_through_the_screen(auth_client):
    _through_the_screen(auth_client, _na_rows())

    assert WaterRight.objects.count() == 2
    _assert_na_row_imported_empty()


@pytest.mark.parametrize("spelling", ["na", "Na", "nan", "NAN"])
def test_na_and_nan_in_any_capitals_read_as_empty(auth_client, spelling):
    _through_the_screen(
        auth_client, [_right("X000001", USE_NET_ACREAGE=spelling, LICENSE_ID=spelling)]
    )

    right = WaterRight.objects.get(right_id="X000001")
    assert right.net_acreage is None
    assert not right.license_number
