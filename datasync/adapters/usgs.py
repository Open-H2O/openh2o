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
        """
        Discover USGS stream gauges and groundwater wells in the boundary.

        Uses the Site Service in RDB (tab-delimited) format. The older
        ``format=mapper`` endpoint was retired and now 404s; RDB is the stable
        machine-readable format. We require ``hasDataTypeCd=dv`` so we only wire
        sites that actually publish daily values, and pass a representative
        ``parameterCd`` so we don't return gauges that lack the variable we want.
        """
        bbox = boundary_geometry.extent  # (xmin, ymin, xmax, ymax)
        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

        site_type_configs = [
            {"siteType": "ST", "params": STREAM_PARAMS, "label": "stream",
             "parameterCd": "00060"},
            {"siteType": "GW", "params": GW_PARAMS, "label": "groundwater",
             "parameterCd": "72019"},
        ]

        stations = []
        seen = set()
        for config in site_type_configs:
            params = {
                "format": "rdb",
                "bBox": bbox_str,
                "siteType": config["siteType"],
                "siteStatus": "active",
                "hasDataTypeCd": "dv",
                "parameterCd": config["parameterCd"],
            }
            try:
                resp = self._request("GET", SITE_URL, params=params)
                rows = self._parse_rdb(resp.text)
            except Exception as exc:
                logger.warning(
                    "USGS %s discovery failed: %s", config["label"], exc
                )
                continue

            for row in rows:
                sid = row.get("site_no", "")
                lat = row.get("dec_lat_va", "")
                lon = row.get("dec_long_va", "")
                name = row.get("station_nm", "")
                site_type = row.get("site_tp_cd", config["siteType"])
                if not (sid and lat and lon) or sid in seen:
                    continue
                try:
                    lat_f, lon_f = float(lat), float(lon)
                except (ValueError, TypeError):
                    continue
                seen.add(sid)
                stations.append({
                    "station_id": sid,
                    "name": name,
                    "latitude": lat_f,
                    "longitude": lon_f,
                    "parameters": config["params"],
                    "site_type": site_type,
                })

        return stations

    @staticmethod
    def _parse_rdb(text):
        """
        Parse a USGS RDB (tab-delimited) response into a list of dict rows.

        RDB files have ``#`` comment lines, then a header row of column names,
        then a format-spec row (e.g. ``5s 15s``) which must be skipped, then
        tab-delimited data rows.
        """
        import re
        fmt_token = re.compile(r"^\d+[sndSND]$")
        header = None
        rows = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if header is None:
                header = fields
                continue
            # Skip the format-spec row that follows the header (e.g. "5s\t15s\t50s").
            nonempty = [f.strip() for f in fields if f.strip()]
            if nonempty and all(fmt_token.match(f) for f in nonempty):
                continue
            rows.append(dict(zip(header, fields)))
        return rows


register_adapter("usgs", USGSAdapter)
