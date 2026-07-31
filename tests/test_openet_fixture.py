# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the OpenET cache dump/load pair.

These two commands are what make the demonstration reproducible from the
repository: without them a rebuild either has no evapotranspiration at all (and
the accounting engine computes nothing) or spends OpenET quota re-fetching
numbers that have not moved since WY 2024-25 closed.

The load side's refusal is tested for TOTALITY, not just for raising. A command
that raises after writing half its rows leaves a database that looks seeded and
is not, and asserting only the exception would pass that.
"""

import datetime as dt
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from datasync.models import OpenETCache
from parcels.models import Parcel
from tests.factories import ParcelFactory

FIXTURE_PATH = "data/merced/openet_cache.json"


def _cache_row(parcel, variable="ET", model_name="Ensemble", et_mm=100.0):
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=parcel.geometry,
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
        variable=variable,
        model_name=model_name,
        et_data=[{"et": et_mm, "date": "2024-10", "unit": "mm"}],
    )


@pytest.fixture
def seeded_cache(db):
    """Two parcels, two variables each — a small stand-in for the real 380."""
    parcels = [
        ParcelFactory(parcel_number="MER-TEST-001"),
        ParcelFactory(parcel_number="MER-TEST-002"),
    ]
    for index, parcel in enumerate(parcels):
        _cache_row(parcel, variable="ET", et_mm=100.0 + index)
        _cache_row(parcel, variable="precip", et_mm=200.0 + index)
    return parcels


@pytest.mark.django_db
def test_round_trip_restores_every_field(seeded_cache, tmp_path):
    """Dump, delete everything, load back — the rows return field for field."""
    out = tmp_path / "cache.json"
    call_command("dump_openet_fixture", output=str(out))

    def snapshot():
        return sorted(
            (
                row.parcel.parcel_number,
                row.start_date,
                row.end_date,
                row.variable,
                row.model_name,
                json.dumps(row.et_data, sort_keys=True),
                row.geometry.wkt,
            )
            for row in OpenETCache.objects.select_related("parcel")
        )

    before = snapshot()
    assert len(before) == 4

    OpenETCache.objects.all().delete()
    assert OpenETCache.objects.count() == 0

    call_command("load_openet_fixture", fixture=str(out))

    assert snapshot() == before

    # Geometry is not stored in the file at all — it is refilled from the
    # parcel. Prove that is what happened rather than trusting the equality.
    assert "geometry" not in json.loads(out.read_text())["rows"][0]
    for row in OpenETCache.objects.select_related("parcel"):
        assert row.geometry.wkt == row.parcel.geometry.wkt


@pytest.mark.django_db
def test_refusal_writes_absolutely_nothing(seeded_cache, tmp_path):
    """A fixture naming an absent parcel must not write a single row."""
    out = tmp_path / "cache.json"
    call_command("dump_openet_fixture", output=str(out))

    payload = json.loads(out.read_text())
    payload["rows"][0]["parcel_number"] = "MER-DOES-NOT-EXIST"
    out.write_text(json.dumps(payload))

    OpenETCache.objects.all().delete()
    assert OpenETCache.objects.count() == 0

    with pytest.raises(CommandError) as excinfo:
        call_command("load_openet_fixture", fixture=str(out))

    assert "MER-DOES-NOT-EXIST" in str(excinfo.value)
    # The whole point: the refusal happened BEFORE any write. Asserting only
    # the exception would pass a command that had already written the other
    # three rows and then given up.
    assert OpenETCache.objects.count() == 0


@pytest.mark.django_db
def test_refusal_names_a_geometryless_parcel_before_writing(seeded_cache, tmp_path):
    """OpenETCache.geometry is NOT NULL — a bare parcel must refuse up front."""
    out = tmp_path / "cache.json"
    call_command("dump_openet_fixture", output=str(out))

    Parcel.objects.filter(parcel_number="MER-TEST-001").update(geometry=None)
    OpenETCache.objects.all().delete()

    with pytest.raises(CommandError) as excinfo:
        call_command("load_openet_fixture", fixture=str(out))

    assert "MER-TEST-001" in str(excinfo.value)
    assert "geometry" in str(excinfo.value)
    assert OpenETCache.objects.count() == 0


@pytest.mark.django_db
def test_pending_rows_never_leave_the_database(seeded_cache, tmp_path):
    """A reservation row is an in-flight fetch, not data."""
    _cache_row(seeded_cache[0], variable="ET", model_name=OpenETCache.PENDING_MARKER)

    out = tmp_path / "cache.json"
    call_command("dump_openet_fixture", output=str(out))

    payload = json.loads(out.read_text())
    assert all(
        row["model_name"] != OpenETCache.PENDING_MARKER for row in payload["rows"]
    )
    assert payload["meta"]["row_count"] == 4


@pytest.mark.django_db
def test_dump_is_byte_identical_on_an_unchanged_database(seeded_cache, tmp_path):
    """No timestamp anywhere, so `git diff` is a real answer to "has it moved?"."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    call_command("dump_openet_fixture", output=str(first))
    call_command("dump_openet_fixture", output=str(second))

    assert first.read_bytes() == second.read_bytes()


@pytest.mark.django_db
def test_loading_twice_creates_nothing_the_second_time(seeded_cache, tmp_path):
    out = tmp_path / "cache.json"
    call_command("dump_openet_fixture", output=str(out))
    OpenETCache.objects.all().delete()

    call_command("load_openet_fixture", fixture=str(out))
    after_first = OpenETCache.objects.count()
    assert after_first == 4

    call_command("load_openet_fixture", fixture=str(out))
    assert OpenETCache.objects.count() == after_first


def test_committed_fixture_is_internally_consistent():
    """Read the real committed file — a lost variable breaks the arithmetic.

    Asserting only "not empty" would pass a fixture that had silently lost 90%
    of itself, which is the failure this whole plan exists to make impossible.
    """
    payload = json.loads(open(FIXTURE_PATH).read())
    meta, rows = payload["meta"], payload["rows"]

    assert meta["row_count"] == len(rows)
    assert meta["parcel_count"] == len({row["parcel_number"] for row in rows})
    assert sorted(meta["variables"]) == sorted({row["variable"] for row in rows})
    assert meta["row_count"] == (
        meta["parcel_count"] * len(meta["variables"]) * len(meta["windows"])
    )

    # No stamp of any kind may appear, or every regeneration reads as a change.
    raw = open(FIXTURE_PATH).read()
    for banned in ("generated_at", "timestamp", "hostname", "git_hash"):
        assert banned not in raw
