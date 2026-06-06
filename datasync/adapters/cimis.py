# SPDX-License-Identifier: AGPL-3.0-or-later
"""
CIMIS (California Irrigation Management Information System) adapter.

API docs: https://cimis.water.ca.gov/web-api/rest-api/latest  (new 2026 API)
Data host: https://et.water.ca.gov/StationWeb/*  (same host, new paths)
Auth: application key passed in the ``Ocp-Apim-Subscription-Key`` HTTP header
      (Azure API Management gateway). NOT a query parameter. Set CIMIS_API_KEY.

The legacy ``/api/data`` + ``?appKey=`` API retires ~2026-07-31; this adapter
targets the new API so a freshly-cloned deployment keeps working past that date.

Parameters (WSN station readings; Spatial CIMIS is intentionally out of scope):
  ASCE ETo - Reference evapotranspiration (in)
  Precip   - Precipitation (in)
  Sol Rad  - Solar radiation (Ly/day)
  Wind     - Average wind speed (mph)
  Air Temp - Average air temperature (F)
"""

import logging
import os

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://et.water.ca.gov/StationWeb/GetDataByStationNumber"
STATION_URL = "https://et.water.ca.gov/StationWeb/GetAllStations"

PARAMETER_MAP = {
    "day-asce-eto": {"name": "Reference ET (ASCE)", "unit": "in"},
    "day-precip": {"name": "Precipitation", "unit": "in"},
    "day-sol-rad-avg": {"name": "Solar Radiation", "unit": "Ly/day"},
    "day-wind-spd-avg": {"name": "Wind Speed", "unit": "mph"},
    "day-air-tmp-avg": {"name": "Air Temperature", "unit": "F"},
}

DATA_ITEMS = ",".join(PARAMETER_MAP.keys())


def _parse_hms_decimal(value):
    """Parse CIMIS's combined HMS+decimal location string to a float.

    CIMIS returns latitude/longitude as e.g. ``"36º48'52N / 36.814444"`` (and
    a signed ``"-119º43'54W / -119.73167"`` for longitude) — the decimal degrees
    sit after the ``/``. There is no bare decimal field. Calling ``float()`` on
    the raw string raises, which previously made discovery skip every station
    ("synced but 0 stations"). Returns the decimal half as a float, or ``None``
    for empty/malformed input (never raises).
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return float(value.split("/")[-1].strip())
    except (ValueError, TypeError):
        return None


class CIMISAdapter(BaseAdapter):
    source_code = "cimis"
    rate_limit_seconds = 1.0

    def _get_api_key(self):
        return os.environ.get("CIMIS_API_KEY", "")

    def _auth_headers(self):
        """New CIMIS API authenticates via the Ocp-Apim-Subscription-Key header."""
        return {"Ocp-Apim-Subscription-Key": self._get_api_key()}

    def missing_required_credential(self):
        """CIMIS station + data APIs require an application key (ISS-007)."""
        return None if self._get_api_key() else "CIMIS appKey (set CIMIS_API_KEY)"

    def fetch(self, station, start_date, end_date):
        """Fetch daily data from the new CIMIS API (header auth)."""
        params = {
            "stationNbrs": station.external_station_id,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "isHourly": "false",
            "unitOfMeasure": "E",
            "dataItems": DATA_ITEMS,
        }
        resp = self._request("GET", BASE_URL, params=params, headers=self._auth_headers())
        return resp.json()

    def parse(self, raw_data):
        """Parse CIMIS API response into standard records.

        Response shape is unchanged from the legacy API:
        Data > Providers[] > Records[], each value an object {Value, Qc, Unit}.
        """
        records = []
        data_section = raw_data.get("Data", {}) if isinstance(raw_data, dict) else {}
        providers = data_section.get("Providers", [])

        for provider in providers:
            for record in provider.get("Records", []):
                station_id = str(record.get("Station", ""))
                obs_date = record.get("Date", "")

                for param_code, param_info in PARAMETER_MAP.items():
                    data_item = record.get(
                        param_code.replace("-", " ").title().replace(" ", ""),
                        record.get(param_code, {})
                    )
                    if isinstance(data_item, dict):
                        value = data_item.get("Value")
                    else:
                        value = data_item

                    if value is not None and value != "":
                        try:
                            value = float(value)
                        except (ValueError, TypeError):
                            value = None

                    records.append({
                        "station_id": station_id,
                        "observation_date": obs_date,
                        "parameter_code": param_code,
                        "value": value,
                        "unit": param_info["unit"],
                    })
        return records

    def validate(self, records):
        """Validate CIMIS records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif rec["parameter_code"] == "day-asce-eto" and rec["value"] < 0:
                rec["rejection_reason"] = "negative ETo"
                rejected.append(rec)
            elif rec["parameter_code"] == "day-asce-eto" and rec["value"] > 1.0:
                rec["rejection_reason"] = "ETo exceeds 1.0 in/day"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover CIMIS stations near a boundary (new API, header auth)."""
        try:
            resp = self._discover_request("GET", STATION_URL, headers=self._auth_headers())
            data = resp.json()
        except Exception as exc:
            logger.warning("CIMIS station discovery failed: %s", exc)
            return []

        stations_list = data.get("Stations", [])
        if not isinstance(stations_list, list):
            return []

        from django.contrib.gis.geos import Point

        buffered = boundary_geometry.buffer(radius_km / 111.0)  # rough deg conversion

        results = []
        for stn in stations_list:
            lat = _parse_hms_decimal(stn.get("HmsLatitude"))
            lon = _parse_hms_decimal(stn.get("HmsLongitude"))
            sid = str(stn.get("StationNbr", ""))
            name = stn.get("Name", "")

            if lat is None or lon is None or not sid:
                continue

            try:
                point = Point(lon, lat, srid=4326)
            except (ValueError, TypeError):
                continue

            if buffered.contains(point):
                results.append({
                    "station_id": sid,
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    "parameters": list(PARAMETER_MAP.keys()),
                })

        return results


register_adapter("cimis", CIMISAdapter)
