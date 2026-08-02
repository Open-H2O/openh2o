# SPDX-License-Identifier: AGPL-3.0-or-later
"""A sync that failed says so, and a sustained failure alerts (2026-08-02).

USGS failed every one of its five stations on repeated hourly runs across
2026-08-01 and 02, and nobody was told. Two things had to be wrong at once for
that to happen, and they were:

* ``sync_source`` printed its "Done: N fetched..." line in SUCCESS green
  whatever the outcome, so a total failure signed off looking like a success.
* It exited 0 regardless, and ``run-sync.sh`` keys off the exit status — so
  cron wrote "all sources OK: cdec usgs" directly beneath five station errors.

The fix is deliberately NOT "exit non-zero whenever a run fails". Simultaneous
probes from Butler and an off-LAN VPS on 2026-08-02 measured USGS's outages at
about **40 seconds**, hitting both networks in the same wall-clock window and
gone by the next hourly run. ``run-sync.sh`` alerts at ntfy Priority: high, and
a high alert means "broken now" — waking somebody for a 40-second blip that the
next run repairs (the pull window is 7 days) is how alarms get muted, and then
the real one is muted too.

So: report every outcome honestly, and reserve the non-zero exit for a source
that has failed three runs back to back.
"""

from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from datasync.management.commands.sync_source import (
    CONSECUTIVE_FAILURES_BEFORE_ALERT,
    Command,
)
from datasync.models import DataSource, DataSyncLog, MonitoredStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(db):
    src, _ = DataSource.objects.get_or_create(
        code="usgs", defaults={"name": "USGS NWIS"}
    )
    src.is_active = True
    src.save()
    MonitoredStation.objects.create(
        data_source=src,
        external_station_id="11261500",
        station_name="SAN JOAQUIN R A FREMONT FORD BRIDGE CA",
        location=Point(-120.9, 37.3, srid=4326),
        is_active=True,
    )
    return src


def _log(source, status, minutes_ago):
    """A finished run in this source's history."""
    when = timezone.now() - timedelta(minutes=minutes_ago)
    return DataSyncLog.objects.create(
        data_source=source, status=status, started_at=when, completed_at=when
    )


class TestTheStreakCounter:
    def test_a_clean_run_resets_the_streak(self, source):
        """One success between failures means the source is not down."""
        _log(source, "failed", 180)
        _log(source, "success", 120)
        _log(source, "failed", 60)
        assert Command._consecutive_failures(source) == 1

    def test_back_to_back_failures_accumulate(self, source):
        for minutes in (180, 120, 60):
            _log(source, "failed", minutes)
        assert Command._consecutive_failures(source) == 3

    def test_partial_does_not_count_as_down(self, source):
        """Partial means some stations DID return data. That is not an outage."""
        _log(source, "failed", 180)
        _log(source, "partial", 120)
        _log(source, "failed", 60)
        assert Command._consecutive_failures(source) == 1

    def test_a_running_log_is_ignored_rather_than_breaking_the_streak(self, source):
        """An in-flight run is not evidence either way.

        Counting it as a non-failure would silently reset a real streak.
        """
        for minutes in (180, 120, 60):
            _log(source, "failed", minutes)
        _log(source, "running", 1)
        assert Command._consecutive_failures(source) == 3

    def test_no_history_is_not_a_failure_streak(self, source):
        assert Command._consecutive_failures(source) == 0


class TestTheExitStatus:
    """The end-to-end property: does cron find out?"""

    def _run_failing_sync(self, monkeypatch):
        """Make every station error the way a real upstream outage does."""
        from datasync.adapters.base import BaseAdapter

        def fail(self, station, start_date, end_date, sync_log=None, mock=False):
            sync_log.error_message = (
                "('Received response with content-encoding: gzip, but failed "
                "to decode it.', error('Error -3 ...'))"
            )
            return sync_log

        monkeypatch.setattr(BaseAdapter, "sync", fail)
        call_command("sync_source", "usgs")

    def test_one_bad_run_is_reported_but_does_not_alert(self, source, monkeypatch):
        """A 40-second upstream outage must not raise a high-priority alarm."""
        self._run_failing_sync(monkeypatch)  # must not raise
        assert DataSyncLog.objects.filter(
            data_source=source, status="failed"
        ).exists(), "the run should still be RECORDED as failed"

    def test_the_third_consecutive_failure_exits_non_zero(self, source, monkeypatch):
        """This is what reaches run-sync.sh, and through it, a person."""
        for minutes in (180, 120):
            _log(source, "failed", minutes)
        with pytest.raises(CommandError) as exc:
            self._run_failing_sync(monkeypatch)
        assert "consecutive" in str(exc.value)

    def test_a_success_in_between_prevents_the_alert(self, source, monkeypatch):
        """Two failures, a good run, then a failure is weather, not an outage."""
        _log(source, "failed", 240)
        _log(source, "failed", 180)
        _log(source, "success", 120)
        self._run_failing_sync(monkeypatch)  # must not raise

    def test_the_threshold_is_what_the_module_says_it_is(self, source, monkeypatch):
        """Guard against the constant and the behaviour drifting apart."""
        for minutes in range(CONSECUTIVE_FAILURES_BEFORE_ALERT - 1, 0, -1):
            _log(source, "failed", minutes * 60)
        with pytest.raises(CommandError):
            self._run_failing_sync(monkeypatch)
