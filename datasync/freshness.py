# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Source-aware freshness and status classification for monitoring stations.

The monitoring page used to judge every station by a single rule: "no data in
24 hours = dead (red)." That is correct for a stream gauge that reports daily,
but wrong for a groundwater well that is hand-measured every few months or a
satellite ET product that updates monthly — those would show red forever and
look broken when they are behaving exactly as expected.

This module classifies freshness against each source's OWN expected data
cadence, and rolls per-station freshness up into an honest per-source status
("healthy", "needs key", "no stations", "no recent data", "failed").
"""

import os

from django.utils import timezone

# Expected interval between fresh observations, per source code, in hours.
# This is the DATA cadence (how often new readings normally arrive), NOT the
# sync cadence. A daily gauge updates every ~24h; periodic groundwater is read
# roughly quarterly; OpenET publishes monthly satellite composites.
EXPECTED_DATA_INTERVAL_HOURS = {
    "cdec": 36,            # daily reservoir / stream telemetry (slight posting lag)
    "usgs": 48,            # daily values (dv) — published with a ~1-2 day lag
    "cimis": 48,           # daily reference ET — posts a day or two behind
    "cnrfc": 36,           # daily river / precip forecasts
    "noaa": 72,            # daily climate, typically lags ~2-3 days
    "dwr_wdl": 24 * 120,   # periodic groundwater (~quarterly) -> 120 days
    "dwr_sgma": 24 * 120,  # periodic SGMA monitoring -> 120 days
    "openet": 24 * 45,     # monthly satellite ET -> ~45 days
}
DEFAULT_INTERVAL_HOURS = 24

# Within FRESH_MULTIPLIER x expected interval -> fresh (green).
# Within STALE_MULTIPLIER x expected interval -> stale (amber).
# Beyond that, or never -> dead (red).
FRESH_MULTIPLIER = 1.5
STALE_MULTIPLIER = 4.0

# Sources that cannot function without an API credential, and the env var that
# supplies it. A source whose key is unset is shown as "needs key", not "failed".
CREDENTIAL_ENV = {
    "cimis": "CIMIS_API_KEY",
    "noaa": "NOAA_CDO_TOKEN",
    "openet": "OPENET_API_KEY",
}

# Short, plain-English description of what each source actually is. Surfaced in
# the UI so "CNRFC" is not an unexplained acronym.
SOURCE_BLURBS = {
    "cdec": "California Data Exchange Center — live reservoir, river and snow telemetry.",
    "usgs": "USGS National Water Information System — daily stream-gauge flow and stage.",
    "cimis": "CA Irrigation Management Information System — daily reference ET (needs an API key).",
    "cnrfc": "California Nevada River Forecast Center (NOAA) — river-flow and precipitation forecasts.",
    "noaa": "NOAA climate data — daily temperature and precipitation (needs an API token).",
    "dwr_wdl": "DWR Water Data Library — periodic (roughly quarterly) groundwater-level readings.",
    "dwr_sgma": "DWR SGMA portal — groundwater monitoring submitted under Sustainable Groundwater law.",
    "openet": "OpenET — monthly satellite evapotranspiration estimates (needs an API key).",
}

# Short display labels for the source chips — proper acronym casing rather than
# the lowercase internal code. Falls back to code.upper() for anything unlisted.
SOURCE_DISPLAY = {
    "cdec": "CDEC",
    "usgs": "USGS",
    "cimis": "CIMIS",
    "cnrfc": "CNRFC",
    "noaa": "NOAA",
    "dwr_wdl": "DWR-WDL",
    "dwr_sgma": "DWR-SGMA",
    "openet": "OpenET",
}

# Human-readable status label + the freshness colour family each status maps to.
STATUS_META = {
    "healthy": {"label": "Healthy", "tone": "fresh"},
    "needs_key": {"label": "Needs API key", "tone": "info"},
    "no_stations": {"label": "No stations wired", "tone": "neutral"},
    "no_data": {"label": "No recent data", "tone": "stale"},
    "running": {"label": "Syncing…", "tone": "stale"},
    "failed": {"label": "Last sync failed", "tone": "dead"},
    "never": {"label": "Not yet synced", "tone": "neutral"},
}


def expected_interval_hours(source_code):
    """Hours between expected fresh readings for a source."""
    return EXPECTED_DATA_INTERVAL_HOURS.get(source_code, DEFAULT_INTERVAL_HOURS)


def credential_missing(source_code):
    """True if the source needs an API credential and it is not set."""
    env_var = CREDENTIAL_ENV.get(source_code)
    if not env_var:
        return False
    return not os.environ.get(env_var)


def source_blurb(source_code):
    """Plain-English description of a source, or empty string."""
    return SOURCE_BLURBS.get(source_code, "")


def source_display(source_code):
    """Proper-cased short label for a source (e.g. 'USGS', 'OpenET')."""
    return SOURCE_DISPLAY.get(source_code, (source_code or "").upper())


def classify_freshness(source_code, last_data_at, now=None):
    """
    Return 'fresh' | 'stale' | 'dead' for a station, judged against its
    source's own expected data cadence rather than a flat 24-hour rule.
    """
    if last_data_at is None:
        return "dead"
    now = now or timezone.now()
    interval = expected_interval_hours(source_code)
    age_hours = (now - last_data_at).total_seconds() / 3600
    if age_hours <= interval * FRESH_MULTIPLIER:
        return "fresh"
    if age_hours <= interval * STALE_MULTIPLIER:
        return "stale"
    return "dead"


def classify_source_status(source_code, active_stations, last_log, fresh_count):
    """
    Roll per-station state up into one honest per-source status code.

    Returns a status key from STATUS_META. The order of checks matters: a
    missing credential or zero wired stations explains the silence before we
    ever blame a "failed" sync.
    """
    if credential_missing(source_code):
        return "needs_key"
    if active_stations == 0:
        return "no_stations"
    if last_log is None:
        return "never"
    # Fresh data outranks a single bad run. A live demo's hourly gauge sync hits
    # cranky upstreams (CDEC routinely drops the connection mid-burst), so one
    # failed or unfinished run is routine and self-heals on the next hourly pass.
    # If the readings on screen are still current (fresh_count > 0) the source is
    # genuinely healthy — don't cry wolf with a red "failed" card over data that
    # is actually fine. Only when nothing is fresh do we surface the run state.
    if fresh_count > 0:
        return "healthy"
    if last_log.status == "running":
        return "running"
    if last_log.status == "failed":
        return "failed"
    return "no_data"


def status_label(status_code):
    return STATUS_META.get(status_code, {}).get("label", status_code)


def status_tone(status_code):
    return STATUS_META.get(status_code, {}).get("tone", "neutral")
