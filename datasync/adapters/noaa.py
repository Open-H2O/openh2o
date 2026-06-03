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

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2"

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
        """Fetch daily observations from NOAA CDO Web Services."""
        params = {
            "datasetid": "GHCND",
            "stationid": f"GHCND:{station.external_station_id}",
            "startdate": start_date.strftime("%Y-%m-%d"),
            "enddate": end_date.strftime("%Y-%m-%d"),
            "datatypeid": ",".join(PARAMETER_MAP.keys()),
            "units": "metric",
            "limit": 1000,
        }
        resp = self._request(
            "GET", f"{BASE_URL}/data", params=params, headers=self._headers()
        )
        return resp.json()

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
