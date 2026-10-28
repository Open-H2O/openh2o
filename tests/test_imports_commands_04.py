# SPDX-License-Identifier: AGPL-3.0-or-later
"""Imports, commands and seeds: one green, plain lock errors, import honesty, clean seed text."""
import ast
import datetime as dt
import json
import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from accounting.models import ReportingPeriod
from core.history import command_context
from infrastructure.importer import auto_map_columns
from parcels.models import Parcel, ParcelStaging
from tests.factories import ParcelLedgerFactory

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = ROOT / "static/css/tokens.css"
MAP_CORE_JS = ROOT / "static/js/map-core.js"
COMMANDS = ROOT / "core/management/commands"


# ── Zone fill uses the supply green ──────────────────────────────────────────
def _supply_green():
    return re.search(r"--color-supply\s*:\s*(#[0-9a-fA-F]{6})", TOKENS_CSS.read_text()).group(1)


def test_zone_fill_token_is_the_supply_green():
    match = re.search(r"--color-entity-green\s*:\s*(#[0-9a-fA-F]{6})", TOKENS_CSS.read_text())
    assert match.group(1).lower() == _supply_green().lower()


def test_zone_fill_in_the_map_toolkit_is_the_supply_green():
    match = re.search(r"\bgreen:\s*'(#[0-9a-fA-F]{6})'", MAP_CORE_JS.read_text())
    assert match.group(1).lower() == _supply_green().lower()


# ── A finalized year is a plain one-line error on every command ──────────────
@pytest.mark.django_db
def test_command_meeting_the_lock_prints_the_sentence_and_exits_1(capsys):
    ReportingPeriod.objects.create(
        name="WY 2024-2025",
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
        is_finalized=True,
    )
    day = dt.date(2025, 3, 1)
    with pytest.raises(SystemExit) as caught:
        with command_context(["manage.py", "some_command"]):
            ParcelLedgerFactory(effective_date=day, transaction_date=day, reporting_period=None)
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert err.strip() == (
        "CommandError: WY 2024-2025 is finalized. "
        "An administrator can reopen it on the water year page."
    )
    assert "Traceback" not in err


def test_an_unrelated_error_is_left_alone():
    with pytest.raises(ValueError):
        with command_context(["manage.py", "some_command"]):
            raise ValueError("not the lock")


# ── Casing diameter alias ────────────────────────────────────────────────────
def test_casingdiameter_header_maps_to_casing_diameter_in():
    mapping = auto_map_columns(["WCRNUMBER", "CASINGDIAMETER"], "well")
    assert mapping["casing_diameter_in"] == "CASINGDIAMETER"


# ── Parcel import: an unreadable outline is refused, promotion is all or nothing
def _ring(x):
    return [[[x, 36.5], [x + 0.01, 36.5], [x + 0.01, 36.51], [x, 36.51], [x, 36.5]]]


def _feature(apn, x, geometry="ok"):
    if geometry == "ok":
        geom = {"type": "Polygon", "coordinates": _ring(x)}
    else:
        geom = None
    return {"type": "Feature", "properties": {"APN": apn, "OWNER": "Owner"}, "geometry": geom}


def _write(tmp_path, features):
    path = tmp_path / "parcels.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def _run(path, *args):
    out = StringIO()
    call_command("import_parcels", str(path), *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_a_file_with_one_unreadable_outline_imports_nothing_and_names_it(tmp_path):
    path = _write(
        tmp_path,
        [_feature("ID-OK-1", -119.5), _feature("ID-BAD", -119.4, geometry=None), _feature("ID-OK-2", -119.3)],
    )
    output = _run(path)
    assert not Parcel.objects.filter(parcel_number__startswith="ID-").exists()
    assert ParcelStaging.objects.count() == 0
    assert "ID-BAD" in output
    assert "feature 2" in output
    assert "Imported 0 parcels" in output


@pytest.mark.django_db
def test_a_dry_run_with_an_unreadable_outline_reports_that_none_would_import(tmp_path):
    path = _write(
        tmp_path,
        [_feature("ID-OK-1", -119.5), _feature("ID-BAD", -119.4, geometry=None)],
    )
    output = _run(path, "--dry-run")
    assert "ID-BAD" in output
    assert "Imported 0 parcels" in output


@pytest.mark.django_db
def test_a_clean_file_imports_every_row(tmp_path):
    path = _write(tmp_path, [_feature("ID-A", -119.5), _feature("ID-B", -119.4)])
    output = _run(path)
    assert Parcel.objects.filter(parcel_number__startswith="ID-").count() == 2
    assert "Imported 2 parcels, 0 duplicates skipped, 0 errors" in output


@pytest.mark.django_db
def test_a_row_the_database_refuses_stops_the_whole_promotion(tmp_path, monkeypatch):
    path = _write(tmp_path, [_feature("ID-P1", -119.5), _feature("ID-P2", -119.4), _feature("ID-P3", -119.3)])
    real_create = Parcel.objects.create

    def refuse_second(**kwargs):
        if kwargs["parcel_number"] == "ID-P2":
            raise ValueError("refused for the test")
        return real_create(**kwargs)

    monkeypatch.setattr(Parcel.objects, "create", refuse_second)
    output = _run(path)
    assert not Parcel.objects.filter(parcel_number__startswith="ID-").exists()
    assert "ID-P2" in output
    assert "Imported 0 parcels" in output


# ── The demonstration's text ─────────────────────────────────────────────────
def _string_literals(path):
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


@pytest.mark.parametrize(
    "name", ["seed_merced_measurements.py", "seed_merced_basins_from_selection.py"]
)
def test_seed_text_has_no_em_dash_and_no_phase_number(name):
    bad = [
        (line, text)
        for line, text in _string_literals(COMMANDS / name)
        if "—" in text or re.search(r"Phase\s+\d", text)
    ]
    assert bad == []
