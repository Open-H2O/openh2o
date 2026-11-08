# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1 step B: ``import_infrastructure`` reads what the Import screen reads.

The command and the screen (``/infrastructure/import/``, preview then commit)
write the same rows from the same file, because the screen's worker and the
command call one function. Messages are copied word for word from the approved
rows in ``152-03.1-ROWS.md`` (Fixed column); the row number is named beside each.

Test data is INVENTED: "Example Ditch Company" has two water rights (X000001,
X000002) and two headgates, points of diversion X000001_01 ("North Headgate")
and X000001_02 ("South Headgate"). The ponds and recharge sites are invented too.
"""
from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from infrastructure import importer
from recharge.models import RechargeSite
from surface.models import PointOfDiversion
from tests.factories import WaterRightFactory
from tests.import_flow import infrastructure_import_rows
from wells.models import Well

pytestmark = pytest.mark.django_db

ROW_19 = "[DRY RUN] The command does not save any record."
ROW_20 = "Columns read:"

#: Row 28: (type, singular, plural)
NOUNS = [
    ("well", "well", "wells"),
    ("diversion", "point of diversion", "points of diversion"),
    ("storage", "storage pond", "storage ponds"),
    ("recharge_site", "recharge site", "recharge sites"),
]


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"infracmduser{n}")
    email = factory.Sequence(lambda n: f"infracmduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture
def example_rights(db):
    return [
        WaterRightFactory(right_id="X000001", holder_name="Example Ditch Company"),
        WaterRightFactory(right_id="X000002", holder_name="Example Ditch Company"),
    ]


# ---------------------------------------------------------------------------
# Invented files
# ---------------------------------------------------------------------------

def _diversion_rows():
    return [
        {"name": "X000001_01", "local_name": "North Headgate", "stream": "Example Creek",
         "max_rate_cfs": "12.5", "lat": "36.50", "lon": "-119.50", "water_right": "X000001"},
        {"name": "X000001_02", "local_name": "South Headgate", "stream": "Example Creek",
         "max_rate_cfs": "4", "lat": "36.51", "lon": "-119.51", "water_right": "X000002"},
        # Skipped: no water right X999999 is on the site.
        {"name": "X000009_01", "local_name": "Lost Headgate", "stream": "Example Creek",
         "max_rate_cfs": "1", "lat": "36.52", "lon": "-119.52", "water_right": "X999999"},
    ]


def _pond_rows(site_type):
    return [
        {"name": "Example Pond 1", "site_type": site_type, "capacity_acre_feet": "40.5",
         "operator": "Example Ditch Company", "lat": "36.60", "lon": "-119.60"},
        {"name": "Example Pond 2", "site_type": site_type, "capacity_acre_feet": "12",
         "operator": "Example Ditch Company", "lat": "36.61", "lon": "-119.61"},
        # Skipped: a latitude outside the United States.
        {"name": "Example Pond 3", "site_type": site_type, "capacity_acre_feet": "1",
         "operator": "Example Ditch Company", "lat": "95", "lon": "-119.62"},
    ]


def _well_rows():
    return [
        {"name": "Example Well 1", "lat": "36.70", "lon": "-119.70"},
        {"name": "Example Well 2", "lat": "36.71", "lon": "-119.71"},
        {"name": "", "lat": "36.72", "lon": "-119.72"},
    ]


ROWS_FOR = {
    "diversion": _diversion_rows,
    "storage": lambda: _pond_rows("storage_pond"),
    "recharge_site": lambda: _pond_rows("spreading_basin"),
    "well": _well_rows,
}


def _file(tmp_path, rows, name="points.csv"):
    from tests.import_flow import csv_text_of

    path = tmp_path / name
    path.write_text(csv_text_of(rows))
    return str(path)


def _run(*args):
    out = StringIO()
    call_command("import_infrastructure", *args, stdout=out)
    return out.getvalue()


def _lines(text):
    return [line for line in text.splitlines() if line.strip()]


def _snapshot(infra_type):
    if infra_type == "diversion":
        return {
            p.name: (
                p.local_name, p.stream_name, p.max_rate_cfs,
                p.water_right.right_id if p.water_right else None,
                tuple(round(c, 6) for c in p.location.coords), p.status,
            )
            for p in PointOfDiversion.objects.select_related("water_right")
        }
    if infra_type in ("storage", "recharge_site"):
        return {
            s.name: (
                s.site_type, s.capacity_acre_feet, s.operator,
                tuple(round(c, 6) for c in s.location.coords), s.status,
            )
            for s in RechargeSite.objects.all()
        }
    return {
        w.name: tuple(round(c, 6) for c in w.location.coords) for w in Well.objects.all()
    }


def _wipe(infra_type):
    {"diversion": PointOfDiversion, "storage": RechargeSite,
     "recharge_site": RechargeSite, "well": Well}[infra_type].objects.all().delete()


def _count(infra_type):
    return len(_snapshot(infra_type))


# ---------------------------------------------------------------------------
# The command and the screen write the same rows
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("infra_type", ["diversion", "storage", "recharge_site"])
def test_command_and_screen_write_the_same_rows(auth_client, example_rights, tmp_path, infra_type):
    rows = ROWS_FOR[infra_type]()
    mapping = importer.auto_map_columns(list(rows[0].keys()), infra_type)

    infrastructure_import_rows(
        auth_client, rows, {f"map:{f}": c for f, c in mapping.items()}, infra_type=infra_type
    )
    from_screen = _snapshot(infra_type)
    assert len(from_screen) == 2, "the screen path did not import the two good rows"
    _wipe(infra_type)

    _run(_file(tmp_path, rows), "--type", infra_type)

    assert _snapshot(infra_type) == from_screen


# ---------------------------------------------------------------------------
# What the command prints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("infra_type,singular,plural", NOUNS)
def test_dry_run_writes_nothing_prints_row_19_first_and_row_27_last(
    example_rights, tmp_path, infra_type, singular, plural
):
    out = _run(_file(tmp_path, ROWS_FOR[infra_type]()), "--type", infra_type, "--dry-run")

    assert _count(infra_type) == 0
    lines = _lines(out)
    assert lines[0] == ROW_19
    assert ROW_20 in lines
    assert lines[-1] == f"OpenH2O would create 2 {plural} and skip 1 row."


@pytest.mark.parametrize("infra_type,singular,plural", NOUNS)
def test_a_real_run_prints_row_26_with_the_right_noun(
    example_rights, tmp_path, infra_type, singular, plural
):
    out = _run(_file(tmp_path, ROWS_FOR[infra_type]()), "--type", infra_type)

    assert _count(infra_type) == 2
    assert _lines(out)[-1] == f"OpenH2O created 2 {plural} and skipped 1 row."
    # Row 22: the skipped row is named "Row {n}: " and the import's own sentence.
    assert any(ln.startswith("Row ") and ": " in ln for ln in _lines(out)), out


@pytest.mark.parametrize("infra_type,singular,plural", NOUNS)
def test_the_noun_is_singular_when_the_count_is_one(
    example_rights, tmp_path, infra_type, singular, plural
):
    rows = ROWS_FOR[infra_type]()[:1]

    out = _run(_file(tmp_path, rows), "--type", infra_type)

    # Row 29: singular noun and "row" when a count is 1; "0 rows" otherwise.
    assert _lines(out)[-1] == f"OpenH2O created 1 {singular} and skipped 0 rows."


def test_dry_run_lists_a_value_with_no_column(example_rights, tmp_path):
    rows = [{k: v for k, v in r.items() if k != "stream"} for r in _diversion_rows()]

    out = _run(_file(tmp_path, rows), "--type", "diversion", "--dry-run")

    assert "stream_name: no column" in [line.strip() for line in _lines(out)]


def test_column_option_reads_a_column_the_screen_would_not_recognize(example_rights, tmp_path):
    rows = []
    for r in _diversion_rows():
        r = dict(r)
        r["HEADGATE"] = r.pop("local_name")
        rows.append(r)

    out = _run(
        _file(tmp_path, rows), "--type", "diversion",
        "--column", "local_name=HEADGATE", "--dry-run",
    )

    assert any("local_name" in ln and "HEADGATE" in ln for ln in _lines(out)), out
    _run(_file(tmp_path, rows), "--type", "diversion", "--column", "local_name=HEADGATE")
    assert PointOfDiversion.objects.get(name="X000001_02").local_name == "South Headgate"


# ---------------------------------------------------------------------------
# Refusals: rows 30 to 33, and the importer's own mapping_refusal
# ---------------------------------------------------------------------------

def test_a_missing_file_is_refused_with_row_30(tmp_path):
    path = str(tmp_path / "nothing-here.csv")

    with pytest.raises(CommandError) as err:
        _run(path, "--type", "diversion")

    assert str(err.value) == (
        f"OpenH2O cannot find the file {path}. "
        "Copy the file into the container with docker compose cp first."
    )


def test_a_column_without_an_equals_sign_is_refused_with_row_31(example_rights, tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _diversion_rows()), "--type", "diversion", "--column", "local_name")

    assert str(err.value) == (
        "Write each --column as OpenH2O's name for a value, an equals sign and a column name."
    )


def test_an_unknown_value_name_is_refused_with_row_32(example_rights, tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _diversion_rows()), "--type", "diversion", "--column", "bogus_value=name")

    message = str(err.value)
    assert message.startswith(
        "The import does not read a value named bogus_value. Use one of these names: "
    )
    assert "local_name" in message
    assert PointOfDiversion.objects.count() == 0


def test_a_column_the_file_lacks_is_refused_with_row_33(example_rights, tmp_path):
    with pytest.raises(CommandError) as err:
        _run(_file(tmp_path, _diversion_rows()), "--type", "diversion", "--column", "local_name=NOPE")

    assert str(err.value) == (
        "The file does not have a column named NOPE. "
        "Check the spelling against the file's first row."
    )
    assert PointOfDiversion.objects.count() == 0


def test_a_file_with_no_name_column_saves_nothing_and_names_the_missing_column(tmp_path):
    # The screen's up-front refusal ("... then press Create.") is a screen
    # instruction, so the command does not print it (152-03.1, main session).
    # Its column list shows the gap (row 21) and every row is skipped with the
    # importer's own row error.
    rows = [{"foo": "a", "bar": "b"}]

    out = _run(_file(tmp_path, rows), "--type", "diversion")

    assert "name: no column" in out
    assert out.strip().splitlines()[-1] == "OpenH2O created 0 points of diversion and skipped 1 row."
    assert PointOfDiversion.objects.count() == 0


def test_a_file_with_a_name_but_no_location_saves_nothing(tmp_path):
    rows = [{"name": "X000001_01", "stream": "Example Creek"}]

    out = _run(_file(tmp_path, rows), "--type", "diversion")

    assert "latitude: no column" in out
    assert out.strip().splitlines()[-1] == "OpenH2O created 0 points of diversion and skipped 1 row."
    assert PointOfDiversion.objects.count() == 0
