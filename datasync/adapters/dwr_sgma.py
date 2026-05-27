"""
Department of Water Resources (DWR) SGMA Portal adapter.

API docs: https://sgma.water.ca.gov/webservice/
No authentication required.

Parameters:
  gw_level - Groundwater level (ft msl)
  subsidence - Land subsidence (ft)
  isw - Interconnected surface water (binary/qualitative)
"""

import logging

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://sgma.water.ca.gov/webservice/SGMA"

PARAMETER_MAP = {
    "gw_level": {"name": "Groundwater Level", "unit": "ft msl"},
    "subsidence": {"name": "Land Subsidence", "unit": "ft"},
    "isw": {"name": "Interconnected Surface Water", "unit": ""},
}


class DWRSGMAAdapter(BaseAdapter):
    source_code = "dwr_sgma"
    rate_limit_seconds = 2.0

    def fetch(self, station, start_date, end_date):
        """Fetch monitoring data from DWR SGMA portal."""
        params = {
            "siteCode": station.external_station_id,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        resp = self._request("GET", f"{BASE_URL}/MonitoringSites", params=params)
        return resp.json()

    def parse(self, raw_data):
        """Parse SGMA monitoring data into standard records."""
        records = []
        if isinstance(raw_data, list):
            items = raw_data
        elif isinstance(raw_data, dict):
            items = raw_data.get("data", raw_data.get("records", []))
        else:
            return records

        for item in items:
            param = item.get("parameter", item.get("parameter_code", "gw_level"))
            records.append({
                "station_id": item.get("site_code", item.get("station_id", "")),
                "observation_date": item.get(
                    "measurement_date", item.get("date", item.get("observation_date", ""))
                ),
                "parameter_code": param,
                "value": item.get("value", item.get("measurement_value")),
                "unit": PARAMETER_MAP.get(param, {}).get("unit", ""),
            })
        return records

    def validate(self, records):
        """Validate SGMA records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif rec["parameter_code"] == "gw_level":
                val = rec["value"]
                if isinstance(val, (int, float)) and (val < -1000 or val > 15000):
                    rec["rejection_reason"] = "GW level out of range"
                    rejected.append(rec)
                else:
                    valid.append(rec)
            elif rec["parameter_code"] == "subsidence":
                val = rec["value"]
                if isinstance(val, (int, float)) and (val < -50 or val > 50):
                    rec["rejection_reason"] = "subsidence out of range"
                    rejected.append(rec)
                else:
                    valid.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover SGMA monitoring sites near a boundary."""
        bbox = boundary_geometry.extent
        params = {
            "north": bbox[3],
            "south": bbox[1],
            "east": bbox[2],
            "west": bbox[0],
        }

        try:
            resp = self._request("GET", f"{BASE_URL}/MonitoringSites", params=params)
            data = resp.json()
        except Exception as exc:
            logger.warning("DWR SGMA station discovery failed: %s", exc)
            return []

        stations = []
        sites = data if isinstance(data, list) else data.get("sites", [])
        for site in sites:
            lat = site.get("latitude")
            lon = site.get("longitude")
            sid = site.get("site_code", site.get("siteCode", ""))
            name = site.get("site_name", site.get("siteName", ""))
            if lat and lon and sid:
                stations.append({
                    "station_id": str(sid),
                    "name": name,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "parameters": list(PARAMETER_MAP.keys()),
                })
        return stations


register_adapter("dwr_sgma", DWRSGMAAdapter)
