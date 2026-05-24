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

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet"
STATION_URL = "https://cdec.water.ca.gov/dynamicapp/staMeta"

PARAMETER_MAP = {
    "15": {"name": "Reservoir Storage", "unit": "AF"},
    "1": {"name": "River Stage", "unit": "ft"},
    "20": {"name": "Flow", "unit": "cfs"},
    "2": {"name": "Precipitation", "unit": "in"},
}


class CDECAdapter(BaseAdapter):
    source_code = "cdec"
    rate_limit_seconds = 0.5

    def fetch(self, station, start_date, end_date):
        """Fetch data from CDEC JSON API."""
        records = []
        for param_code in station.parameters or ["15"]:
            params = {
                "Stations": station.external_station_id,
                "SensorNums": param_code,
                "dur_code": "D",
                "Start": start_date.strftime("%Y-%m-%d"),
                "End": end_date.strftime("%Y-%m-%d"),
            }
            resp = self._request("GET", BASE_URL, params=params)
            data = resp.json()
            if isinstance(data, list):
                records.extend(data)
        return records

    def parse(self, raw_data):
        """Parse CDEC JSON response into standard records."""
        records = []
        for item in raw_data:
            param_code = str(item.get("sensorNumber", ""))
            param_info = PARAMETER_MAP.get(param_code, {})
            records.append({
                "station_id": item.get("stationId", ""),
                "observation_date": item.get("date", item.get("obsDate", "")),
                "parameter_code": param_code,
                "value": item.get("value"),
                "unit": param_info.get("unit", ""),
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
        Discover CDEC stations near a boundary.
        Uses the CDEC station metadata endpoint.
        """
        centroid = boundary_geometry.centroid
        # CDEC doesn't have a spatial search API, so we fetch nearby
        # counties and filter by distance. For now, use a bounding box.
        bbox = boundary_geometry.extent  # (xmin, ymin, xmax, ymax)

        params = {
            "north": bbox[3],
            "south": bbox[1],
            "east": bbox[2],
            "west": bbox[0],
        }

        try:
            resp = self._request("GET", STATION_URL, params=params)
            data = resp.json()
        except Exception as exc:
            logger.warning("CDEC station discovery failed: %s", exc)
            return []

        stations = []
        if isinstance(data, list):
            for item in data:
                lat = item.get("latitude") or item.get("Latitude")
                lon = item.get("longitude") or item.get("Longitude")
                sid = item.get("stationId") or item.get("id", "")
                name = item.get("stationName") or item.get("name", "")
                if lat and lon and sid:
                    stations.append({
                        "station_id": sid,
                        "name": name,
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "parameters": list(PARAMETER_MAP.keys()),
                    })
        return stations


register_adapter("cdec", CDECAdapter)
