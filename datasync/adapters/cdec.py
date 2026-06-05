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

import logging
import re

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


class CDECAdapter(BaseAdapter):
    source_code = "cdec"
    rate_limit_seconds = 0.5

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
                resp = self._request("GET", BASE_URL, params=params)
                data = resp.json()
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
