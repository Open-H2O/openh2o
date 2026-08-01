# SPDX-License-Identifier: AGPL-3.0-or-later
"""A source with stations and none switched on gets different advice (ISS-107).

`/datasync/monitoring/`'s CIMIS card read "No stations wired yet — run station
discovery for this source" directly above its own body text printing "0 active /
15 total". Two things wrong at once: the card contradicted itself on screen, and
the advice could not work. `discover_stations.py:113` creates rows with
`is_active=False`, so running discovery adds more dormant stations and leaves
the card saying exactly the same thing — a loop with no exit, and the same dead
end that killed the `rediscover` option in 104-01's checkpoint.

The two states need opposite advice, so they are now two states.
"""

from datasync import freshness


class TestNoneActivatedIsItsOwnState:
    def test_a_source_with_stations_but_none_active_is_not_no_stations(self):
        """CIMIS: 15 known, 0 active. The card must stop saying it has none."""
        status = freshness.classify_source_status(
            "usgs", active_stations=0, last_log=None, fresh_count=0,
            total_stations=15,
        )
        assert status == "none_activated"
        assert freshness.status_label(status) == "None activated"

    def test_a_source_with_no_stations_at_all_still_says_so(self):
        status = freshness.classify_source_status(
            "usgs", active_stations=0, last_log=None, fresh_count=0,
            total_stations=0,
        )
        assert status == "no_stations"

    def test_a_missing_credential_still_outranks_both(self, monkeypatch):
        """Order of checks matters: explain the silence before blaming stations.

        The env var is cleared explicitly — CIMIS_API_KEY is genuinely present
        on staging and production, which is exactly why ISS-109 could measure
        that CIMIS is configured, has stations, and can still never sync.
        """
        monkeypatch.delenv("CIMIS_API_KEY", raising=False)
        status = freshness.classify_source_status(
            "cimis", active_stations=0, last_log=None, fresh_count=0,
            total_stations=15,
        )
        assert status == "needs_key"

    def test_both_states_have_a_label(self):
        """A status with no STATUS_META entry renders its raw key at the user."""
        for code in ("no_stations", "none_activated"):
            assert code in freshness.STATUS_META
            assert freshness.status_label(code) != code

    def test_the_old_three_argument_call_still_classifies(self):
        """total_stations is optional so an unconverted caller cannot crash."""
        assert freshness.classify_source_status("usgs", 0, None, 0) == "no_stations"
