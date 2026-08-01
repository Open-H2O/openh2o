# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three adapter bugs that only a long backfill could find (v2.9, 2026-08-01).

The v2.8 cutover shipped a demonstration built from this repository, and it came
up with every station chart blank: the build makes no network calls, so it
carried zero telemetry. Fixing that means freezing two water years of readings
into a committed fixture, and generating that fixture means asking each source
for two years of history — something nothing had ever done. The nightly sync
pulls 7 days.

All three sources broke, each in a different way, and every one of them had been
broken for months behind a window too short to reach it:

  A. CDEC returned 60,017 event rows for ONE station-sensor over two water
     years. The fetch is fast (9.9s, measured); putting 2.3 million such rows
     through the staging table is a ten-hour crawl.
  B. NOAA 400s on any range past a year, AND silently truncates any successful
     response at 1,000 rows.
  C. USGS lost four of its five stations to a gzip decode failure that the
     retry loop did not treat as retryable.

These tests pin the fixes. They make no network calls.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import requests

from datasync.adapters.base import RETRYABLE_TRANSPORT_ERRORS, BaseAdapter
from datasync.adapters.cdec import CDECAdapter
from datasync.adapters.noaa import MAX_SPAN_DAYS, PAGE_LIMIT, NOAAAdapter, _date_chunks


# ── A. CDEC downsamples a long backfill, and only a long one ────────────────


def _event_rows(day, sensor="20", per_day=96, value=12.5):
    """One calendar day of 15-minute CDEC event readings, unpadded like the API."""
    return [
        {
            "stationId": "BDV",
            "durCode": "E",
            "SENSOR_NUM": int(sensor),
            "obsDate": f"{day.year}-{day.month}-{day.day} "
                       f"{(i * 15) // 60:02d}:{(i * 15) % 60:02d}",
            "value": value + i,
            "units": "CFS",
        }
        for i in range(per_day)
    ]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _event_only_transport(payload):
    """Stand in for CDEC: nothing at daily or hourly, everything at event.

    That is not a convenience — it is what the live API does. Probing BDV, MSN,
    BUR and H59 on 2026-08-01 returned 0 rows at ``dur_code=D`` for every
    station-sensor pair, which is why "just ask for daily" is not the fix.
    """
    def transport(method, url, **kwargs):
        dur = kwargs.get("params", {}).get("dur_code")
        return _FakeResponse(payload if dur == "E" else [])
    return transport


class TestCDECLongRangeDownsample:
    def test_a_two_year_backfill_keeps_one_reading_per_sensor_per_day(self):
        """The bug in one assertion: 96 readings a day must not become 96 rows."""
        days = [date(2025, 6, d) for d in range(1, 11)]
        payload = [row for day in days for row in _event_rows(day)]
        assert len(payload) == 960

        adapter = CDECAdapter()
        station = SimpleNamespace(external_station_id="BDV", parameters=["20"])
        with patch.object(adapter, "_request",
                          side_effect=_event_only_transport(payload)):
            got = adapter.fetch(station, date(2024, 10, 1), date(2026, 8, 1))

        assert len(got) == len(days), (
            f"expected one row per day, got {len(got)} for {len(days)} days"
        )

    def test_the_nightly_seven_day_window_keeps_every_reading(self):
        """Routine operation must lose nothing. This is the whole safety case."""
        payload = _event_rows(date(2025, 6, 1))
        adapter = CDECAdapter()
        station = SimpleNamespace(external_station_id="BDV", parameters=["20"])
        with patch.object(adapter, "_request",
                          side_effect=_event_only_transport(payload)):
            got = adapter.fetch(station, date(2025, 6, 1), date(2025, 6, 7))
        assert len(got) == len(payload) == 96

    def test_full_resolution_opts_back_in_on_a_long_range(self):
        payload = _event_rows(date(2025, 6, 1)) + _event_rows(date(2025, 6, 2))
        adapter = CDECAdapter()
        adapter.full_resolution = True
        station = SimpleNamespace(external_station_id="BDV", parameters=["20"])
        with patch.object(adapter, "_request",
                          side_effect=_event_only_transport(payload)):
            got = adapter.fetch(station, date(2024, 10, 1), date(2026, 8, 1))
        assert len(got) == 192

    def test_the_survivor_is_the_days_last_reading(self):
        rows = _event_rows(date(2025, 6, 1))
        kept = CDECAdapter._coarsen_to_daily(rows)
        assert len(kept) == 1
        assert kept[0]["obsDate"].endswith("23:45")

    def test_a_sentinel_never_wins_the_day_over_a_real_reading(self):
        """CDEC posts -9999 when a gauge drops out.

        Taking the day's literal last row would hand validate() a sentinel and
        drop the whole day — turning a downsample into data loss on exactly the
        days a gauge went briefly offline.
        """
        rows = _event_rows(date(2025, 6, 1), per_day=4)
        rows[-1]["value"] = -9999
        rows[-2]["value"] = -9999
        kept = CDECAdapter._coarsen_to_daily(rows)
        assert len(kept) == 1
        assert kept[0]["value"] != -9999
        assert kept[0]["obsDate"].endswith("00:15")

    def test_a_day_of_nothing_but_sentinels_still_reports_a_row(self):
        """A fully-dead day must stay visible in the rejection counters."""
        rows = _event_rows(date(2025, 6, 1), per_day=4)
        for row in rows:
            row["value"] = -9999
        kept = CDECAdapter._coarsen_to_daily(rows)
        assert len(kept) == 1
        assert kept[0]["value"] == -9999

    def test_two_sensors_are_downsampled_independently(self):
        rows = (_event_rows(date(2025, 6, 1), sensor="20", per_day=8)
                + _event_rows(date(2025, 6, 1), sensor="1", per_day=8))
        kept = CDECAdapter._coarsen_to_daily(rows)
        assert len(kept) == 2
        assert {str(r["SENSOR_NUM"]) for r in kept} == {"1", "20"}

    def test_the_output_order_is_deterministic(self):
        """expected_shape.json pins this fixture at tolerance 0.

        A generator whose row order wanders would make every future `make
        deploy` fail gate 2, so the ordering is part of the contract.
        """
        rows = [row
                for day in (date(2025, 6, 2), date(2025, 6, 1))
                for sensor in ("20", "1")
                for row in _event_rows(day, sensor=sensor, per_day=4)]
        first = CDECAdapter._coarsen_to_daily(rows)
        second = CDECAdapter._coarsen_to_daily(list(reversed(rows)))
        key = lambda rs: [(str(r["SENSOR_NUM"]), r["obsDate"]) for r in rs]  # noqa: E731
        assert key(first) == key(second)

    def test_an_unreadable_timestamp_is_passed_through_not_dropped(self):
        rows = _event_rows(date(2025, 6, 1), per_day=2)
        rows.append({"stationId": "BDV", "SENSOR_NUM": 20,
                     "obsDate": "not a date", "value": 3.0})
        kept = CDECAdapter._coarsen_to_daily(rows)
        assert any(r["obsDate"] == "not a date" for r in kept)

    def test_unpadded_cdec_dates_parse(self):
        """The live API returns "2025-6-1 23:00" — fromisoformat rejects that."""
        assert CDECAdapter._obs_datetime({"obsDate": "2025-6-1 23:00"}) == (
            datetime(2025, 6, 1, 23, 0)
        )
        assert CDECAdapter._obs_datetime({"obsDate": "2025-06-01 23:00"}) == (
            datetime(2025, 6, 1, 23, 0)
        )
        assert CDECAdapter._obs_datetime({"obsDate": ""}) is None


# ── B. NOAA chunks by year and pages to exhaustion ──────────────────────────


class TestNOAADateChunking:
    def test_a_two_water_year_range_is_split_below_the_api_cap(self):
        """22 months in one request is the measured HTTP 400."""
        chunks = _date_chunks(date(2024, 10, 1), date(2026, 8, 1), MAX_SPAN_DAYS)
        assert len(chunks) > 1
        for start, end in chunks:
            assert (end - start).days + 1 <= MAX_SPAN_DAYS

    def test_the_chunks_cover_the_range_with_no_gap_and_no_overlap(self):
        chunks = _date_chunks(date(2024, 10, 1), date(2026, 8, 1), MAX_SPAN_DAYS)
        assert chunks[0][0] == date(2024, 10, 1)
        assert chunks[-1][1] == date(2026, 8, 1)
        for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
            assert (next_start - prev_end).days == 1

    def test_a_short_range_stays_one_request(self):
        chunks = _date_chunks(date(2026, 7, 25), date(2026, 8, 1), MAX_SPAN_DAYS)
        assert chunks == [(date(2026, 7, 25), date(2026, 8, 1))]


class TestNOAAPaging:
    def _adapter_returning(self, pages):
        adapter = NOAAAdapter()
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(kwargs["params"])
            return _FakeResponse(pages[len(calls) - 1])

        adapter._request = fake_request
        adapter._get_token = lambda: "test-token"
        return adapter, calls

    def test_a_truncated_page_is_followed_by_an_offset_request(self):
        """Measured on the live API: count=1423 with limit=1000 returns 1000.

        The old fetch took that at face value and lost 423 readings without a
        word — the silent half of the NOAA bug, and the worse half.
        """
        full = [{"datatype": "PRCP", "value": 1, "date": "2025-01-01T00:00:00",
                 "station": "GHCND:X"}] * PAGE_LIMIT
        tail = [{"datatype": "PRCP", "value": 2, "date": "2025-01-02T00:00:00",
                 "station": "GHCND:X"}] * 423
        pages = [
            {"metadata": {"resultset": {"offset": 1, "count": 1423,
                                        "limit": PAGE_LIMIT}}, "results": full},
            {"metadata": {"resultset": {"offset": 1001, "count": 1423,
                                        "limit": PAGE_LIMIT}}, "results": tail},
        ]
        adapter, calls = self._adapter_returning(pages)
        station = SimpleNamespace(external_station_id="USW00023257")
        got = adapter.fetch(station, date(2025, 1, 1), date(2025, 12, 31))

        assert len(got) == 1423
        assert [c["offset"] for c in calls] == [1, 1001]

    def test_a_short_page_ends_the_paging(self):
        pages = [{"metadata": {"resultset": {"offset": 1, "count": 699,
                                             "limit": PAGE_LIMIT}},
                  "results": [{"datatype": "PRCP", "value": 1,
                               "date": "2025-01-01T00:00:00",
                               "station": "GHCND:X"}] * 699}]
        adapter, calls = self._adapter_returning(pages)
        station = SimpleNamespace(external_station_id="USW00023257")
        got = adapter.fetch(station, date(2025, 1, 1), date(2025, 6, 30))
        assert len(got) == 699
        assert len(calls) == 1

    def test_an_empty_body_is_an_empty_chunk_not_a_crash(self):
        """CDO answers a range with no observations with an empty body."""
        class _EmptyBody:
            def json(self):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        adapter = NOAAAdapter()
        adapter._get_token = lambda: "test-token"
        adapter._request = lambda *a, **k: _EmptyBody()
        station = SimpleNamespace(external_station_id="US1CAME0006")
        assert adapter.fetch(station, date(2025, 1, 1), date(2025, 6, 30)) == []


# ── C. A mislabelled gzip body is retried, not fatal ────────────────────────


class TestContentDecodingIsRetryable:
    def test_the_decode_failure_that_lost_four_usgs_stations_is_retryable(self):
        assert issubclass(
            requests.exceptions.ContentDecodingError, RETRYABLE_TRANSPORT_ERRORS
        )
        assert issubclass(
            requests.exceptions.ChunkedEncodingError, RETRYABLE_TRANSPORT_ERRORS
        )

    def test_it_is_not_merely_a_connection_error_in_disguise(self):
        """Why the old tuple missed it, pinned so nobody "simplifies" it back.

        ContentDecodingError descends from RequestException, not from
        ConnectionError, so `except (HTTPError, ConnectionError)` never saw it.
        """
        assert not issubclass(
            requests.exceptions.ContentDecodingError, requests.ConnectionError
        )

    def test_a_second_attempt_actually_happens_and_succeeds(self):
        class _Adapter(BaseAdapter):
            source_code = "test"
            rate_limit_seconds = 0.0
            max_retries = 3

            def fetch(self, station, start_date, end_date): ...
            def parse(self, raw_data): ...
            def validate(self, records): ...
            def discover_stations(self, boundary_geometry, radius_km=50): ...

        attempts = []

        def flaky(method, url, **kwargs):
            attempts.append(url)
            if len(attempts) == 1:
                raise requests.exceptions.ContentDecodingError(
                    "Received response with content-encoding: gzip, but failed "
                    "to decode it."
                )
            return SimpleNamespace(raise_for_status=lambda: None, ok=True)

        with patch("requests.request", side_effect=flaky), \
                patch("time.sleep"):
            resp = _Adapter()._request("GET", "https://example.invalid/x")

        assert resp.ok
        assert len(attempts) == 2
