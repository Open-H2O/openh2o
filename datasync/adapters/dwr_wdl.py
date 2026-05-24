"""
DWR Water Data Library adapter.

API docs: https://wdl.water.ca.gov/waterdatalibrary/
No authentication required.

Parameters:
  gw_level - Groundwater level (ft below ground surface)
"""

import logging

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://wdl.water.ca.gov/waterdatalibrary/waterqualitydata.aspx"
GW_URL = "https://wdl.water.ca.gov/waterdatalibrary"

PARAMETER_MAP = {
    "gw_level": {"name": "Groundwater Level", "unit": "ft bgs"},
}


class DWRWDLAdapter(BaseAdapter):
    source_code = "dwr_wdl"
    rate_limit_seconds = 2.0

    def fetch(self, station, start_date, end_date):
        """Fetch groundwater level data from DWR Water Data Library."""
        params = {
            "stationNumber": station.external_station_id,
            "startDate": start_date.strftime("%m/%d/%Y"),
            "endDate": end_date.strftime("%m/%d/%Y"),
            "format": "json",
        }
        resp = self._request("GET", f"{GW_URL}/groundwater.aspx", params=params)
        return resp.json()

    def parse(self, raw_data):
        """Parse DWR WDL response into standard records."""
        records = []
        if isinstance(raw_data, list):
            data_list = raw_data
        elif isinstance(raw_data, dict):
            data_list = raw_data.get("data", raw_data.get("records", []))
        else:
            return records

        for item in data_list:
            records.append({
                "station_id": item.get("station_id", item.get("stn", "")),
                "observation_date": item.get(
                    "measurement_date", item.get("date", item.get("observation_date", ""))
                ),
                "parameter_code": "gw_level",
                "value": item.get(
                    "gs_elevation", item.get("depth", item.get("value"))
                ),
                "unit": "ft bgs",
            })
        return records

    def validate(self, records):
        """Validate groundwater level records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif isinstance(rec["value"], (int, float)) and rec["value"] < -500:
                rec["rejection_reason"] = "depth below -500 ft (implausible)"
                rejected.append(rec)
            elif isinstance(rec["value"], (int, float)) and rec["value"] > 2000:
                rec["rejection_reason"] = "depth exceeds 2000 ft (implausible)"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover DWR WDL wells near a boundary."""
        bbox = boundary_geometry.extent
        params = {
            "north": bbox[3],
            "south": bbox[1],
            "east": bbox[2],
            "west": bbox[0],
            "format": "json",
        }

        try:
            resp = self._request("GET", f"{GW_URL}/map.aspx", params=params)
            data = resp.json()
        except Exception as exc:
            logger.warning("DWR WDL station discovery failed: %s", exc)
            return []

        stations = []
        wells = data if isinstance(data, list) else data.get("wells", [])
        for well in wells:
            lat = well.get("latitude")
            lon = well.get("longitude")
            sid = well.get("station_number", well.get("well_id", ""))
            name = well.get("station_name", well.get("name", ""))
            if lat and lon and sid:
                stations.append({
                    "station_id": str(sid),
                    "name": name,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "parameters": ["gw_level"],
                })
        return stations


register_adapter("dwr_wdl", DWRWDLAdapter)
