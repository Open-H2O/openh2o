"""
USGS NWIS (National Water Information System) adapter.

API docs: https://waterservices.usgs.gov/
No auth required (API key optional for higher rate limits).

Parameters:
  00060 - Discharge (cfs)
  00065 - Gage height (ft)
  00010 - Water temperature (deg C)
"""

import logging

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/"

PARAMETER_MAP = {
    "00060": {"name": "Discharge", "unit": "cfs"},
    "00065": {"name": "Gage Height", "unit": "ft"},
    "00010": {"name": "Water Temperature", "unit": "deg C"},
    "72019": {"name": "Depth to Water Level", "unit": "ft below surface"},
    "72020": {"name": "Water Level Elevation", "unit": "ft NAVD88"},
    "62610": {"name": "Groundwater Level", "unit": "ft below datum"},
}

STREAM_PARAMS = ["00060", "00065", "00010"]
GW_PARAMS = ["72019", "72020", "62610"]


class USGSAdapter(BaseAdapter):
    source_code = "usgs"
    rate_limit_seconds = 1.0

    def fetch(self, station, start_date, end_date):
        """Fetch daily values from USGS NWIS."""
        param_codes = station.parameters or list(PARAMETER_MAP.keys())
        params = {
            "format": "json",
            "sites": station.external_station_id,
            "parameterCd": ",".join(param_codes),
            "startDT": start_date.strftime("%Y-%m-%d"),
            "endDT": end_date.strftime("%Y-%m-%d"),
        }
        resp = self._request("GET", DV_URL, params=params)
        return resp.json()

    def parse(self, raw_data):
        """Parse USGS WaterML JSON into standard records."""
        records = []
        time_series = (
            raw_data.get("value", {}).get("timeSeries", [])
            if isinstance(raw_data, dict) else []
        )
        for ts in time_series:
            var_code = (
                ts.get("variable", {})
                .get("variableCode", [{}])[0]
                .get("value", "")
            )
            unit = (
                ts.get("variable", {})
                .get("unit", {})
                .get("unitCode", PARAMETER_MAP.get(var_code, {}).get("unit", ""))
            )
            site_code = (
                ts.get("sourceInfo", {})
                .get("siteCode", [{}])[0]
                .get("value", "")
            )
            for values_set in ts.get("values", []):
                for val in values_set.get("value", []):
                    records.append({
                        "station_id": site_code,
                        "observation_date": val.get("dateTime", ""),
                        "parameter_code": var_code,
                        "value": float(val["value"]) if val.get("value") else None,
                        "unit": unit,
                        "qualifiers": val.get("qualifiers", []),
                    })
        return records

    def validate(self, records):
        """Validate USGS records, reject missing and provisional-bad."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif rec["value"] < -999:
                rec["rejection_reason"] = "sentinel value"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover USGS stream sites, groundwater wells, and springs."""
        bbox = boundary_geometry.extent  # (xmin, ymin, xmax, ymax)
        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

        site_type_configs = [
            {"siteType": "ST", "params": STREAM_PARAMS, "label": "stream"},
            {"siteType": "GW,SP", "params": GW_PARAMS, "label": "groundwater/spring"},
        ]

        stations = []
        for config in site_type_configs:
            params = {
                "format": "mapper",
                "bBox": bbox_str,
                "siteType": config["siteType"],
                "siteStatus": "active",
                "hasDataTypeCd": "dv",
            }
            try:
                resp = self._request("GET", SITE_URL, params=params)
                data = resp.json()
            except Exception as exc:
                logger.warning(
                    "USGS %s discovery failed: %s", config["label"], exc
                )
                continue

            sites = data.get("sites", data.get("value", {}).get("timeSeries", []))
            if not isinstance(sites, list):
                continue

            for site in sites:
                lat = site.get("latitude") or site.get("lat")
                lon = site.get("longitude") or site.get("lng")
                sid = site.get("site_no") or site.get("siteNumber", "")
                name = site.get("station_nm") or site.get("siteName", "")
                site_type = site.get("site_tp_cd", config["siteType"].split(",")[0])
                if lat and lon and sid:
                    stations.append({
                        "station_id": sid,
                        "name": name,
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "parameters": config["params"],
                        "site_type": site_type,
                    })

        return stations


register_adapter("usgs", USGSAdapter)
