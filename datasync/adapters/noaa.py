# SPDX-License-Identifier: AGPL-3.0-or-later
"""
NOAA NCEI (National Centers for Environmental Information) adapter.

API docs: https://www.ncei.noaa.gov/cdo-web/api/v2/
Auth: Token header (token auth_type on DataSource).

Parameters:
  PRCP - Precipitation (tenths of mm)
  TMAX - Maximum temperature (tenths of deg C)
  TMIN - Minimum temperature (tenths of deg C)
  SNOW - Snowfall (mm)
"""

import logging
import os
from datetime import timedelta

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2"

# NOAA's CDO v2 API refuses a single GHCND request spanning more than a year,
# and it caps any one response at 1,000 rows. Both were measured against the
# live API on 2026-08-01 with the Merced airport station (USW00023257):
#
#   2024-10-01 -> 2026-08-01  (22 months)  HTTP 400, no body worth reading
#   2025-01-01 -> 2026-01-01  (12 months)  HTTP 200, metadata count=1423, 1000 returned
#   2025-01-01 -> 2025-06-30  ( 6 months)  HTTP 200, metadata count= 699,  699 returned
#
# Those two lines are two separate bugs and the second is the nastier one. The
# 400 is loud — a whole backfill returns "0 fetched" and somebody notices. The
# 1,000-row cap is SILENT: the request succeeds, the rows look right, and 423 of
# them simply are not there. Four datatypes on a daily station is ~1,460 rows a
# year, so any pull longer than about eight months has been quietly truncating.
# Neither ever fired on the nightly 7-day sync, which is why both survived.
#
# So the fetch below does two things the old one did not: it splits a long range
# into chunks no longer than a year, and it pages each chunk with `offset` until
# the response's own `metadata.resultset.count` is satisfied.
MAX_SPAN_DAYS = 365
PAGE_LIMIT = 1000

# A backstop, not a real limit. Each page is 1,000 rows, so 50 pages is 50,000
# rows from one station-year — an order of magnitude past anything GHCND can
# produce. It exists so a malformed `count` can never spin the loop forever.
MAX_PAGES_PER_CHUNK = 50


def _date_chunks(start_date, end_date, max_span_days):
    """Split [start_date, end_date] into consecutive spans of at most N days.

    Inclusive of both ends, no gaps and no overlap: each chunk begins the day
    after the previous one ended, so no reading is fetched twice and none falls
    between two chunks.
    """
    chunks = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=max_span_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks

PARAMETER_MAP = {
    "PRCP": {"name": "Precipitation", "unit": "mm", "scale": 0.1},
    "TMAX": {"name": "Max Temperature", "unit": "deg C", "scale": 0.1},
    "TMIN": {"name": "Min Temperature", "unit": "deg C", "scale": 0.1},
    "SNOW": {"name": "Snowfall", "unit": "mm", "scale": 1.0},
}


class NOAAAdapter(BaseAdapter):
    source_code = "noaa"
    rate_limit_seconds = 1.0
    max_retries = 3

    def _get_token(self):
        return os.environ.get("NOAA_CDO_TOKEN", "")

    def missing_required_credential(self):
        """NOAA CDO Web Services require a token."""
        return None if self._get_token() else "NOAA CDO token (set NOAA_CDO_TOKEN)"

    def _headers(self):
        return {"token": self._get_token()}

    def fetch(self, station, start_date, end_date):
        """Fetch daily observations from NOAA CDO Web Services.

        Chunked by year and paged to exhaustion — see MAX_SPAN_DAYS above for
        the two API limits that make both necessary. Returns a flat list of
        result items, which ``parse`` already accepts.
        """
        all_results = []
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, MAX_SPAN_DAYS):
            all_results.extend(
                self._fetch_chunk(station, chunk_start, chunk_end)
            )
        return all_results

    def _fetch_chunk(self, station, start_date, end_date):
        """Page one date chunk to exhaustion. CDO's ``offset`` is 1-based."""
        results = []
        offset = 1
        for _ in range(MAX_PAGES_PER_CHUNK):
            params = {
                "datasetid": "GHCND",
                "stationid": f"GHCND:{station.external_station_id}",
                "startdate": start_date.strftime("%Y-%m-%d"),
                "enddate": end_date.strftime("%Y-%m-%d"),
                "datatypeid": ",".join(PARAMETER_MAP.keys()),
                "units": "metric",
                "limit": PAGE_LIMIT,
                "offset": offset,
            }
            resp = self._request(
                "GET", f"{BASE_URL}/data", params=params, headers=self._headers()
            )
            # A range with no observations comes back as an EMPTY BODY, not as
            # an empty results list, so .json() would raise ValueError on it.
            # An empty chunk is ordinary (a station installed mid-range), never
            # an error.
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            if not isinstance(payload, dict):
                break

            page = payload.get("results") or []
            results.extend(page)
            if len(page) < PAGE_LIMIT:
                break

            total = (
                payload.get("metadata", {}).get("resultset", {}).get("count")
            )
            offset += len(page)
            if not isinstance(total, int) or offset > total:
                break
        else:
            logger.warning(
                "NOAA %s %s→%s: hit the %d-page backstop; results may be "
                "incomplete.",
                station.external_station_id, start_date, end_date,
                MAX_PAGES_PER_CHUNK,
            )
        return results

    def parse(self, raw_data):
        """Parse NOAA CDO response into standard records."""
        records = []
        results = []
        if isinstance(raw_data, dict):
            results = raw_data.get("results", [])
        elif isinstance(raw_data, list):
            results = raw_data

        for item in results:
            datatype = item.get("datatype", "")
            param_info = PARAMETER_MAP.get(datatype, {})
            scale = param_info.get("scale", 1.0)
            raw_value = item.get("value")

            # NOAA stores values in tenths, scale to standard units
            value = raw_value * scale if raw_value is not None else None

            station_id = item.get("station", "")
            if station_id.startswith("GHCND:"):
                station_id = station_id[6:]

            records.append({
                "station_id": station_id,
                "observation_date": item.get("date", ""),
                "parameter_code": datatype,
                "value": value,
                "unit": param_info.get("unit", ""),
            })
        return records

    def validate(self, records):
        """Validate NOAA weather records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif rec["parameter_code"] in ("TMAX", "TMIN"):
                if rec["value"] < -90 or rec["value"] > 60:
                    rec["rejection_reason"] = "temperature out of range (-90 to 60 C)"
                    rejected.append(rec)
                else:
                    valid.append(rec)
            elif rec["parameter_code"] == "PRCP":
                if rec["value"] < 0:
                    rec["rejection_reason"] = "negative precipitation"
                    rejected.append(rec)
                elif rec["value"] > 1000:
                    rec["rejection_reason"] = "precipitation exceeds 1000mm"
                    rejected.append(rec)
                else:
                    valid.append(rec)
            elif rec["parameter_code"] == "SNOW":
                if rec["value"] < 0:
                    rec["rejection_reason"] = "negative snowfall"
                    rejected.append(rec)
                else:
                    valid.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover NOAA GHCND stations near a boundary."""
        bbox = boundary_geometry.extent
        extent_str = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
        params = {
            "datasetid": "GHCND",
            "extent": extent_str,
            "limit": 1000,
        }

        try:
            resp = self._discover_request(
                "GET", f"{BASE_URL}/stations",
                params=params, headers=self._headers(),
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("NOAA station discovery failed: %s", exc)
            return []

        stations = []
        results = data.get("results", [])
        for stn in results:
            sid = stn.get("id", "")
            if sid.startswith("GHCND:"):
                sid = sid[6:]
            lat = stn.get("latitude")
            lon = stn.get("longitude")
            name = stn.get("name", "")
            if lat and lon and sid:
                stations.append({
                    "station_id": sid,
                    "name": name,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "parameters": list(PARAMETER_MAP.keys()),
                })
        return stations


register_adapter("noaa", NOAAAdapter)
