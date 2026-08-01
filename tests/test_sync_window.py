# SPDX-License-Identifier: AGPL-3.0-or-later
"""The default sync window is sized to the source's own publishing cadence.

Until 2026-08-01 every source was pulled with a flat 7-day window. `dwr_sgma`
and `dwr_wdl` publish roughly quarterly, so a 7-day pull returned zero rows
every night, forever, for 19 of the Merced demonstration's 42 active stations.
Nothing went red, because `freshness.classify_freshness` is cadence-aware and
those stations kept a green dot from a reading fetched months earlier. The
silence only became visible when something cleared `last_data_at`.

These tests pin the property that made the bug possible: the window the FETCH
uses and the interval the UI JUDGES by must come from the same table.
"""
from datetime import date, timedelta
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command

from datasync import freshness
from datasync.management.commands.sync_source import (
    MINIMUM_WINDOW_DAYS,
    WINDOW_INTERVAL_MULTIPLIER,
    default_window_days,
)
from datasync.models import DataSource, MonitoredStation


def test_a_quarterly_source_gets_a_window_that_can_actually_reach_its_data():
    """The whole bug in one assertion.

    dwr_sgma's expected interval is 120 days. A window shorter than that cannot
    reach the most recent publication, so every sync returns nothing and
    `last_data_at` is never set.
    """
    for code in ("dwr_sgma", "dwr_wdl"):
        interval_days = freshness.expected_interval_hours(code) / 24
        assert default_window_days(code) >= interval_days, (
            f"{code} publishes every {interval_days:.0f} days but would be "
            f"pulled over {default_window_days(code)} days — it can never fetch."
        )


def test_no_source_gets_a_narrower_window_than_the_old_flat_seven_days():
    """The change must be strictly widening.

    A daily source that missed several nights used to catch up inside the old
    7-day window. Deriving the window from a 2-day cadence would have quietly
    narrowed that to 4 days and lost data nobody was watching for.
    """
    codes = set(freshness.EXPECTED_DATA_INTERVAL_HOURS) | {"a-source-nobody-listed"}
    for code in codes:
        assert default_window_days(code) >= MINIMUM_WINDOW_DAYS


def test_the_window_is_derived_from_the_same_table_the_dashboard_judges_by():
    """Not a coincidence test — the coupling IS the fix.

    If someone adds a source to EXPECTED_DATA_INTERVAL_HOURS for the dashboard's
    benefit and the fetch keeps its own separate notion of "recent", the bug
    comes straight back for that source.
    """
    for code, hours in freshness.EXPECTED_DATA_INTERVAL_HOURS.items():
        expected = max(
            MINIMUM_WINDOW_DAYS, int((hours / 24) * WINDOW_INTERVAL_MULTIPLIER)
        )
        assert default_window_days(code) == expected


def test_an_unknown_source_falls_back_to_the_floor_rather_than_zero():
    """A source with no recorded cadence must not end up with a 2-day window.

    `expected_interval_hours` returns DEFAULT_INTERVAL_HOURS (24) for anything
    unlisted; twice that is 2 days, which is narrower than the old behaviour.
    The floor is what stops that being a silent regression.
    """
    assert default_window_days("brand-new-source") == MINIMUM_WINDOW_DAYS


@pytest.mark.django_db
def test_sync_source_reports_the_widened_window_for_a_quarterly_source(capsys):
    """End to end through the command, since the fix is a default it computes.

    Asserted on the range the command PRINTS, because that string is what an
    operator reads when they are working out why a source fetched nothing.
    """
    src = DataSource.objects.create(
        code="dwr_sgma", name="DWR SGMA Portal", is_active=True
    )
    MonitoredStation.objects.create(
        data_source=src,
        external_station_id="TEST-001",
        station_name="Test Well",
        location=Point(-120.5, 37.3, srid=4326),
        is_active=True,
    )

    out = StringIO()
    # --end pins the far edge so the assertion does not depend on today's date;
    # --mock keeps it off the network.
    call_command("sync_source", "dwr_sgma", "--end", "2026-08-01", "--mock", stdout=out)

    printed = out.getvalue()
    expected_start = date(2026, 8, 1) - timedelta(days=default_window_days("dwr_sgma"))
    assert str(expected_start) in printed, printed
    # And prove it is materially wider than the week it used to be.
    assert expected_start < date(2026, 8, 1) - timedelta(days=MINIMUM_WINDOW_DAYS)
