# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Department of Water Resources (DWR) SGMA Portal adapter.

Data source: CNRA Open Data Portal (CKAN) — Periodic Groundwater Level Measurements
Dataset: https://data.cnra.ca.gov/dataset/periodic-groundwater-level-measurements

The sgma.water.ca.gov/webservice/ endpoint does not exist. SGMA monitoring well
data is in the same CNRA CKAN dataset as CASGEM, filterable by monitoring_program='SGMA'.

Station IDs use the CNRA site_code format: e.g. "362273N1191386W002"
Parameters:
  gw_level - Groundwater level (ft msl, using wlm_rpe field = RP elevation)
             or depth below ground surface (gse_gwe field)
"""

import logging

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter, sql_float, sql_str_literal

logger = logging.getLogger(__name__)

MEASUREMENTS_RESOURCE_ID = "bfa9f262-24a1-45bd-8dc8-138bc8107266"
STATIONS_RESOURCE_ID = "af157380-fb42-4abf-b72a-6f9f98868077"
CNRA_BASE = "https://data.cnra.ca.gov/api/3/action"

PARAMETER_MAP = {
    "gw_level": {"name": "Groundwater Level", "unit": "ft bgs"},
}


class DWRSGMAAdapter(BaseAdapter):
    source_code = "dwr_sgma"
    rate_limit_seconds = 1.0

    def fetch(self, station, start_date, end_date):
        """Fetch SGMA monitoring well data from CNRA Open Data Portal."""
        # Values escaped via sql_str_literal — apostrophe-safe and injection-safe
        # (CKAN datastore_search_sql has no bound-param form). See base.py.
        sql = (
            f"SELECT site_code, msmt_date, gse_gwe "
            f"FROM \"{MEASUREMENTS_RESOURCE_ID}\" "
            f"WHERE site_code = {sql_str_literal(station.external_station_id)} "
            f"AND monitoring_program = 'SGMA' "
            f"AND msmt_date >= {sql_str_literal(start_date.strftime('%Y-%m-%d'))} "
            f"AND msmt_date <= {sql_str_literal(end_date.strftime('%Y-%m-%d'))} "
            f"ORDER BY msmt_date"
        )
        params = {"sql": sql}
        resp = self._request("GET", f"{CNRA_BASE}/datastore_search_sql", params=params)
        return resp.json()

    def parse(self, raw_data):
        """Parse CNRA CKAN response into standard records."""
        records = []
        result = raw_data.get("result", {}) if isinstance(raw_data, dict) else {}
        rows = result.get("records", [])

        for item in rows:
            raw_val = item.get("gse_gwe")
            try:
                value = float(raw_val) if raw_val is not None else None
            except (ValueError, TypeError):
                value = None

            records.append({
                "station_id": item.get("site_code", ""),
                "observation_date": item.get("msmt_date", ""),
                "parameter_code": "gw_level",
                "value": value,
                "unit": "ft bgs",
            })
        return records

    def validate(self, records):
        """Validate SGMA monitoring records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif isinstance(rec["value"], (int, float)) and rec["value"] < 0:
                rec["rejection_reason"] = "negative depth (implausible for ft bgs)"
                rejected.append(rec)
            elif isinstance(rec["value"], (int, float)) and rec["value"] > 2000:
                rec["rejection_reason"] = "depth exceeds 2000 ft (implausible)"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """Discover SGMA monitoring sites from CNRA Open Data Portal near a boundary."""
        bbox = boundary_geometry.extent
        # bbox floats are validated finite before interpolation (sql_float).
        sql = (
            f"SELECT s.site_code, s.well_name, s.latitude, s.longitude "
            f"FROM \"{STATIONS_RESOURCE_ID}\" s "
            f"WHERE CAST(s.latitude AS FLOAT) BETWEEN {sql_float(bbox[1])} AND {sql_float(bbox[3])} "
            f"AND CAST(s.longitude AS FLOAT) BETWEEN {sql_float(bbox[0])} AND {sql_float(bbox[2])} "
            f"AND EXISTS ("
            f"  SELECT 1 FROM \"{MEASUREMENTS_RESOURCE_ID}\" m "
            f"  WHERE m.site_code = s.site_code AND m.monitoring_program = 'SGMA'"
            f") "
            f"LIMIT 50"
        )
        try:
            resp = self._discover_request(
                "GET", f"{CNRA_BASE}/datastore_search_sql", params={"sql": sql}
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("DWR SGMA (CNRA) station discovery failed: %s", exc)
            return []

        stations = []
        for row in data.get("result", {}).get("records", []):
            lat = row.get("latitude")
            lon = row.get("longitude")
            sid = row.get("site_code", "")
            name = row.get("well_name", "") or sid
            if lat and lon and sid:
                try:
                    stations.append({
                        "station_id": sid,
                        "name": name,
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "parameters": list(PARAMETER_MAP.keys()),
                    })
                except (ValueError, TypeError):
                    continue
        return stations


register_adapter("dwr_sgma", DWRSGMAAdapter)
