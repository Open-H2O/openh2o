# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant guard for the ``activate_stations`` management command (Phase 107-01).

These tests are the SPEC for ``activate_stations``, and their primary job is not
coverage — it is to make one specific mistake unrepresentable.

The x86 clean-room blind run (2026-08-02) hit a wall: discovery creates stations
inactive, ``sync_source`` refuses to run without active ones, and no command
existed to bridge the two. The agent opened a Django shell and ran

    MonitoredStation.objects.filter(is_active=False).update(is_active=True)

which enabled 238 stations platform-wide with no boundary filter, then reported
it had activated "this basin's" stations. It had not.
``test_does_not_activate_stations_outside_the_named_boundary`` is the assertion
that hand-written ``.update()`` would have failed.

The fixture is built directly via the ORM in the style of
``tests/test_teardown_demo.py``: two non-overlapping boundaries, two data
sources, and stations placed at explicit coordinates — small, fast, hermetic, no
network and no large GeoJSON.
"""
from io import StringIO

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import CommandError, call_command

from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary


def _box(cx, cy, size=0.2):
    half = size / 2
    ring = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


# Two boundaries far enough apart that no point can fall in both.
INSIDE_CENTER = (-120.5, 37.3)
OUTSIDE_CENTER = (-118.0, 35.0)


@pytest.fixture
def world(db):
    """Two basins, two sources, stations in every combination of the two."""
    inside = Boundary.objects.create(
        name="Inside Basin", geometry=_box(*INSIDE_CENTER)
    )
    outside = Boundary.objects.create(
        name="Outside Basin", geometry=_box(*OUTSIDE_CENTER)
    )
    cdec = DataSource.objects.create(name="CDEC", code="cdec")
    usgs = DataSource.objects.create(name="USGS", code="usgs")

    def station(source, ident, center, is_active, offset=0.0):
        return MonitoredStation.objects.create(
            data_source=source,
            external_station_id=ident,
            station_name=f"{ident} station",
            location=Point(center[0] + offset, center[1], srid=4326),
            is_active=is_active,
        )

    return {
        "inside": inside,
        "outside": outside,
        "cdec": cdec,
        "usgs": usgs,
        # Inside Basin
        "in_cdec_a": station(cdec, "IN-CDEC-A", INSIDE_CENTER, False),
        "in_cdec_b": station(cdec, "IN-CDEC-B", INSIDE_CENTER, False, 0.01),
        "in_usgs_a": station(usgs, "IN-USGS-A", INSIDE_CENTER, False, 0.02),
        "in_cdec_live": station(cdec, "IN-CDEC-LIVE", INSIDE_CENTER, True, 0.03),
        # Outside Basin — the stations that must not move.
        "out_cdec_a": station(cdec, "OUT-CDEC-A", OUTSIDE_CENTER, False),
        "out_usgs_a": station(usgs, "OUT-USGS-A", OUTSIDE_CENTER, False, 0.01),
    }


def _refresh(station):
    station.refresh_from_db()
    return station.is_active


@pytest.mark.django_db
def test_does_not_activate_stations_outside_the_named_boundary(world):
    """The ISS-113 guard: scoping is the whole point of the command.

    A bare ``.update(is_active=True)`` passes every other assertion in this file
    and fails this one.
    """
    call_command("activate_stations", boundary_name="Inside Basin")

    assert _refresh(world["in_cdec_a"]) is True
    assert _refresh(world["in_cdec_b"]) is True
    assert _refresh(world["in_usgs_a"]) is True

    assert _refresh(world["out_cdec_a"]) is False
    assert _refresh(world["out_usgs_a"]) is False


@pytest.mark.django_db
def test_source_filter_narrows_to_one_data_source(world):
    """``--source`` leaves the other source's stations in the same basin alone."""
    call_command("activate_stations", boundary_name="Inside Basin", source="cdec")

    assert _refresh(world["in_cdec_a"]) is True
    assert _refresh(world["in_cdec_b"]) is True
    assert _refresh(world["in_usgs_a"]) is False
    assert _refresh(world["out_cdec_a"]) is False


@pytest.mark.django_db
def test_dry_run_changes_nothing_but_still_reports_the_count(world):
    before = MonitoredStation.objects.filter(is_active=False).count()

    out = StringIO()
    call_command(
        "activate_stations", boundary_name="Inside Basin", dry_run=True, stdout=out
    )

    after = MonitoredStation.objects.filter(is_active=False).count()
    assert after == before
    # Three inactive stations sit inside the basin; the fourth is already active.
    assert "Would activate 3 station(s)." in out.getvalue()


@pytest.mark.django_db
def test_already_active_stations_are_not_counted_a_second_time(world):
    """The command reports what it CHANGED, so a second run reports zero."""
    first = StringIO()
    call_command("activate_stations", boundary_name="Inside Basin", stdout=first)
    assert "Activated 3 station(s)." in first.getvalue()

    second = StringIO()
    call_command("activate_stations", boundary_name="Inside Basin", stdout=second)
    assert "Activated 0 station(s)." in second.getvalue()


@pytest.mark.django_db
def test_unknown_boundary_name_raises_command_error(world):
    with pytest.raises(CommandError, match="Nonexistent Basin"):
        call_command("activate_stations", boundary_name="Nonexistent Basin")

    assert _refresh(world["in_cdec_a"]) is False


@pytest.mark.django_db
def test_unknown_source_code_raises_command_error(world):
    with pytest.raises(CommandError, match="nosuchsource"):
        call_command(
            "activate_stations", boundary_name="Inside Basin", source="nosuchsource"
        )

    assert _refresh(world["in_cdec_a"]) is False


@pytest.mark.django_db
def test_all_boundaries_activates_across_every_basin(world):
    """The escape hatch works — but only when it is asked for explicitly."""
    out = StringIO()
    call_command("activate_stations", all_boundaries=True, stdout=out)

    assert _refresh(world["in_cdec_a"]) is True
    assert _refresh(world["out_cdec_a"]) is True
    assert _refresh(world["out_usgs_a"]) is True
    assert "Activated 5 station(s)." in out.getvalue()
