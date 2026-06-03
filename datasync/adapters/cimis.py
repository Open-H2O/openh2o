# SPDX-License-Identifier: AGPL-3.0-or-later
"""
CIMIS (California Irrigation Management Information System) adapter.

API docs: https://et.water.ca.gov/Rest/Index
Auth: appKey query parameter (api_key auth_type on DataSource).

Parameters:
  ETo - Reference evapotranspiration (in)
  Precip - Precipitation (in)
  Sol Rad - Solar radiation (Ly/day)
  Wind - Average wind speed (mph)
  Air Temp - Average air temperature (F)
"""

import logging
import os

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://et.water.ca.gov/api/data"
STATION_URL = "https://et.water.ca.gov/api/station"

PARAMETER_MAP = {
    "day-eto": {"name": "Reference ET", "unit": "in"},
    "day-precip": {"name": "Precipitation", "unit": "in"},
    "day-sol-rad-avg": {"name": "Solar Radiation", "unit": "Ly/day"},
    "day-wind-spd-avg": {"name": "Wind Speed", "unit": "mph"},
    "day-air-tmp-avg": {"name": "Air Temperature", "unit": "F"},
}


class CIMISAdapter(BaseAdapter):
    source_code = "cimis"
    rate_limit_seconds = 1.0

    def _get_api_key(self):
        return os.environ.get("CIMIS_API_KEY", "")

    def missing_required_credential(self):
        """CIMIS station + data APIs require an appKey (ISS-007)."""
        return None if self._get_api_key() else "CIMIS appKey (set CIMIS_API_KEY)"

    def fetch(self, station, start_date, end_date):
        """Fetch daily data from CIMIS."""
        params = {
            "appKey": self._get_api_key(),
            "targets": station.external_station_id,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "dataItems": "day-eto,day-precip,day-sol-rad-avg,day-wind-spd-avg,day-air-tmp-avg",
        }
        resp = self._request("GET", BASE_URL, params=params)
        return resp.json()

    def parse(self, raw_data):
        """Parse CIMIS API response into standard records."""
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
            elif rec["parameter_code"] == "day-eto" and rec["value"] < 0:
                rec["rejection_reason"] = "negative ETo"
                rejected.append(rec)
            elif rec["parameter_code"] == "day-eto" and rec["value"] > 1.0:
                rec["rejection_reason"] = "ETo exceeds 1.0 in/day"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover CIMIS stations near a boundary."""
        try:
            params = {"appKey": self._get_api_key()}
            resp = self._discover_request("GET", STATION_URL, params=params)
            data = resp.json()
        except Exception as exc:
            logger.warning("CIMIS station discovery failed: %s", exc)
            return []

        stations_list = data.get("Stations", [])
        if not isinstance(stations_list, list):
            return []

        from django.contrib.gis.geos import Point
        from django.contrib.gis.measure import D

        buffered = boundary_geometry.buffer(radius_km / 111.0)  # rough deg conversion

        results = []
        for stn in stations_list:
            lat = stn.get("HmsLatitude") or stn.get("Latitude")
            lon = stn.get("HmsLongitude") or stn.get("Longitude")
            sid = str(stn.get("StationNbr", ""))
            name = stn.get("Name", "")

            if not lat or not lon or not sid:
                continue

            try:
                point = Point(float(lon), float(lat), srid=4326)
            except (ValueError, TypeError):
                continue

            if buffered.contains(point):
                results.append({
                    "station_id": sid,
                    "name": name,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "parameters": list(PARAMETER_MAP.keys()),
                })

        return results


register_adapter("cimis", CIMISAdapter)
