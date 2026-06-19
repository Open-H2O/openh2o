# SPDX-License-Identifier: AGPL-3.0-or-later
"""
CDEC (California Data Exchange Center) adapter.

API docs: https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet
No authentication required.

Parameters:
  15 - Reservoir Storage (AF)
   1 - River Stage (ft)
  20 - Flow (cfs)
   2 - Precipitation, Incremental (in)
"""

import json
import logging
import re
import subprocess
import time
from urllib.parse import urlencode

import requests

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet"

# CDEC has no station-search JSON endpoint. ``staMeta`` is a human-facing HTML
# page (calling .json() on it is the ISS-048 crash). The only machine-reachable
# station list is the ``staSearch`` results table, which renders every station
# server-side — ID, name, river basin, county, longitude, latitude, elevation,
# operator — when ``sensor_chk`` is left blank. We fetch it once and filter to
# the boundary extent ourselves (CDEC's lon/lat params do not filter the table).
STATION_URL = "https://cdec.water.ca.gov/dynamicapp/staSearch"
STATION_SEARCH_PARAMS = {
    "sta_chk": "on",
    "sensor_chk": "",  # blank (not "on") is what makes staSearch return rows
    "collect": "NONE SPECIFIED",
    "dur": "",
    "active": "",
    "loc_chk": "on",
    "lon1": "",
    "lon2": "",
    "lat1": "",
    "lat2": "",
    "elev1": "-5",
    "elev2": "99000",
    "nearby": "",
    "basin_chk": "on",
    "basin": "",
    "hydro": "",
    "county": "",
    "agency_num": "",
    "display": "staSearch",
}

# Pull each results-table row, then the station_id from its detail link and the
# plain text of every <td> in row order: [id, name, basin, county, lon, lat, …].
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_STATION_ID_RE = re.compile(r"staMeta\?station_id=([A-Za-z0-9]+)", re.I)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

PARAMETER_MAP = {
    "15": {"name": "Reservoir Storage", "unit": "AF"},
    "6": {"name": "Reservoir Elevation", "unit": "ft"},
    "76": {"name": "Reservoir Inflow", "unit": "cfs"},
    "23": {"name": "Reservoir Outflow", "unit": "cfs"},
    "1": {"name": "River Stage", "unit": "ft"},
    "20": {"name": "Flow", "unit": "cfs"},
    "2": {"name": "Precipitation", "unit": "in"},
}


class _CurlResponse:
    """Minimal requests.Response stand-in for the curl transport below.

    Exposes only the surface the CDEC adapter actually touches — ``.text``,
    ``.json()``, ``.status_code``, ``.raise_for_status()`` — so swapping the
    transport needs no changes in fetch()/discover_stations().
    """

    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        return None


class CDECAdapter(BaseAdapter):
    source_code = "cdec"
    rate_limit_seconds = 0.5

    # Fail fast instead of retrying into a throttle. CDEC rate-limits bursts by
    # dropping connections, and an immediate retry just hits the same throttle —
    # so the base default (3 attempts with 2s+4s backoff) turns a cranky-CDEC
    # sync into ~11 minutes of mostly-sleeping for no extra data. We sync hourly,
    # so the NEXT run is the real retry: take one shot per sensor, let the fetch
    # guard skip a drop, and move on. Keeps a bad-mood sync to ~40s, not minutes.
    max_retries = 1

    # CDEC's edge firewall fingerprints the TLS handshake and drops Python's
    # urllib3 client after a burst (RemoteDisconnected mid-handshake) while the
    # system curl binary's handshake passes — proven on the box at the same
    # instant, same IP: host curl 200, container requests dropped, and a browser
    # User-Agent on requests did NOT help (so it's the TLS fingerprint, not the
    # UA). Rather than pull in a heavy TLS-impersonation dependency, route CDEC's
    # HTTP through curl. Only CDEC needs this; every other adapter keeps urllib3.
    CURL_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    def _request(self, method, url, timeout=60, max_retries=None, **kwargs):
        """CDEC transport via the system curl binary (see CURL_USER_AGENT note).

        Returns a minimal response object with the .text/.json()/
        .raise_for_status() surface fetch() and discovery use, so the rest of the
        adapter is unchanged. Honours the adapter's rate limit and max_retries; a
        curl failure (timeout, dropped connection, non-zero exit) raises
        requests.ConnectionError so the existing guards treat it exactly like a
        urllib3 ConnectionError. Built with a list of args (never a shell string),
        so the station id / date params cannot inject a command.
        """
        retries = self.max_retries if max_retries is None else max_retries
        params = kwargs.get("params") or {}
        full_url = url + ("?" + urlencode(params) if params else "")
        last_err = None
        for attempt in range(1, retries + 1):
            self._rate_limit()
            try:
                proc = subprocess.run(
                    ["curl", "-sS", "--compressed", "-A", self.CURL_USER_AGENT,
                     "--max-time", str(int(timeout)), full_url],
                    capture_output=True, text=True, timeout=timeout + 5,
                )
            except subprocess.TimeoutExpired as exc:
                last_err = requests.ConnectionError(f"curl timed out: {exc}")
            else:
                if proc.returncode == 0:
                    return _CurlResponse(proc.stdout)
                last_err = requests.ConnectionError(
                    f"curl exit {proc.returncode}: {proc.stderr.strip()[:160]}"
                )
            if attempt < retries:
                time.sleep(2 ** attempt)
        raise last_err

    # CDEC sensors post at different durations: reservoirs report a Daily value,
    # but most river/stream gauges only publish Hourly or Event ("E", ~15-min)
    # readings and return NOTHING for a daily-duration query. Querying "D" alone
    # left every flow gauge looking dead (59-02). Try coarsest→finest and stop at
    # the first duration that returns rows, so reservoirs stay compact (daily) while
    # flow gauges still land their native-cadence data. The staging unique key
    # (station, parameter_code, observation_date) dedups sub-daily rows on re-sync.
    DURATION_CODES = ("D", "H", "E")

    def fetch(self, station, start_date, end_date):
        """Fetch data from CDEC JSON API, falling back across sensor durations."""
        records = []
        for param_code in station.parameters or ["15"]:
            for dur_code in self.DURATION_CODES:
                params = {
                    "Stations": station.external_station_id,
                    "SensorNums": param_code,
                    "dur_code": dur_code,
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                }
                try:
                    resp = self._request("GET", BASE_URL, params=params)
                    data = resp.json()
                except (requests.RequestException, ValueError) as exc:
                    # CDEC is queried for every sensor a station MIGHT carry, so a
                    # creek gauge gets asked for reservoir storage etc. Most such
                    # misses return an empty list (handled below), but under the
                    # resulting request burst CDEC intermittently drops the
                    # connection (RemoteDisconnected) or returns a non-JSON error
                    # page — and resp.json() then raises ValueError. Treat one bad
                    # sensor/duration as "nothing here" and move on: a single
                    # flaky response must never fail the whole station, and we
                    # never crash on .json() (mirrors the discovery contract,
                    # ISS-048). Stations with real data on other sensors still
                    # publish it; truly-empty stations report honestly as stale.
                    logger.warning(
                        "CDEC %s sensor %s dur %s: %s",
                        station.external_station_id, param_code, dur_code, exc,
                    )
                    continue
                if isinstance(data, list) and data:
                    records.extend(data)
                    break  # got this sensor's data at its native duration
        return records

    def parse(self, raw_data):
        """Parse CDEC JSON response into standard records."""
        records = []
        for item in raw_data:
            param_code = str(item.get("SENSOR_NUM", item.get("sensorNumber", "")))
            param_info = PARAMETER_MAP.get(param_code, {})
            unit = item.get("units", "") or param_info.get("unit", "")
            records.append({
                "station_id": item.get("stationId", ""),
                "observation_date": item.get("obsDate", item.get("date", "")),
                "parameter_code": param_code,
                "value": item.get("value"),
                "unit": unit,
                "raw": item,
            })
        return records

    def validate(self, records):
        """Filter out null values and impossible readings."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None or rec["value"] == -9999:
                rec["rejection_reason"] = "null or sentinel value"
                rejected.append(rec)
            elif rec["value"] < -1000 or rec["value"] > 50_000_000:
                rec["rejection_reason"] = "value out of plausible range"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """
        Discover CDEC stations within a boundary's extent.

        Fetches CDEC's ``staSearch`` results table (HTML), parses every station
        row, and keeps those whose coordinates fall inside the boundary's
        bounding box. CDEC publishes no station-search JSON, so this is the only
        machine-reachable list.

        Defensive by contract (ISS-048): any response we can't parse into
        stations — the human-facing HTML page, an empty body, a changed
        endpoint — yields [] and ONE clear, greppable warning naming CDEC,
        never a bare JSONDecodeError and never an unhandled crash. One provider
        failing must not abort discovery.
        """
        xmin, ymin, xmax, ymax = boundary_geometry.extent  # (lon, lat) extent

        try:
            resp = self._discover_request("GET", STATION_URL, params=STATION_SEARCH_PARAMS)
            body = resp.text or ""
        except requests.Timeout as exc:
            # Bounded discovery timeout fired — fail fast, never hang the wizard.
            logger.warning("CDEC discovery timed out: %s", exc)
            return []
        except Exception as exc:
            logger.warning("CDEC station discovery request failed: %s", exc)
            return []

        parsed = self._parse_station_table(body)
        if not parsed:
            ctype = ""
            try:
                ctype = resp.headers.get("Content-Type", "")
            except Exception:
                pass
            logger.warning(
                "CDEC station discovery: no parseable station table in response "
                "(endpoint changed?) — %d bytes, content-type=%r",
                len(body), ctype,
            )
            return []

        params_all = list(PARAMETER_MAP.keys())
        stations = []
        for sid, name, lon, lat in parsed:
            if xmin <= lon <= xmax and ymin <= lat <= ymax:
                stations.append({
                    "station_id": sid,
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    # The table carries no per-station sensor list; the fetch
                    # step probes which parameters actually return data.
                    "parameters": params_all,
                })
        return stations

    @staticmethod
    def _parse_station_table(html):
        """Parse a CDEC staSearch results table into (id, name, lon, lat) tuples.

        Returns [] for any body without recognisable station rows (the metadata
        HTML page, the bare search form, an empty/JSON body), which is what lets
        ``discover_stations`` degrade to a clean warning instead of crashing.
        """
        rows = []
        for row_html in _ROW_RE.findall(html):
            id_match = _STATION_ID_RE.search(row_html)
            if not id_match:
                continue
            cells = [_TAG_RE.sub("", c).strip() for c in _CELL_RE.findall(row_html)]
            # Column order: [id, name, basin, county, longitude, latitude, …].
            if len(cells) < 6:
                continue
            try:
                lon = float(cells[4].replace(",", ""))
                lat = float(cells[5].replace(",", ""))
            except ValueError:
                continue
            rows.append((id_match.group(1), cells[1], lon, lat))
        return rows


register_adapter("cdec", CDECAdapter)
