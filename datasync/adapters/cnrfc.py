"""
CNRFC (California Nevada River Forecast Center) adapter.

Data source: https://www.cnrfc.noaa.gov/data/
No authentication required.
File-based: downloads CSV forecast files.

Parameters:
  streamflow - Streamflow forecast (cfs)
  precip - Precipitation forecast (in)
"""

import csv
import io
import logging

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cnrfc.noaa.gov/data"

PARAMETER_MAP = {
    "streamflow": {"name": "Streamflow Forecast", "unit": "cfs"},
    "precip": {"name": "Precipitation Forecast", "unit": "in"},
}


class CNRFCAdapter(BaseAdapter):
    source_code = "cnrfc"
    rate_limit_seconds = 1.0

    def fetch(self, station, start_date, end_date):
        """Download CSV forecast data from CNRFC."""
        station_id = station.external_station_id.upper()
        # CNRFC uses station IDs like FOLC1 for Folsom
        url = f"{BASE_URL}/{station_id}.csv"

        resp = self._request("GET", url)
        return resp.text

    def parse(self, raw_data):
        """Parse CNRFC CSV into standard records."""
        records = []
        if not isinstance(raw_data, str):
            # Already parsed (mock data returns list)
            if isinstance(raw_data, list):
                return raw_data
            return records

        reader = csv.reader(io.StringIO(raw_data))
        header = None

        for row in reader:
            if not row:
                continue
            # Skip comment lines
            if row[0].startswith("#"):
                continue
            # First non-comment row is the header
            if header is None:
                header = [col.strip().lower() for col in row]
                continue

            if len(row) < 2:
                continue

            try:
                obs_date = row[0].strip()
                for i, col_name in enumerate(header[1:], start=1):
                    if i >= len(row):
                        break
                    value = row[i].strip()
                    if not value or value in ("-", "M", ""):
                        continue

                    param_code = "streamflow" if "flow" in col_name else "precip"
                    records.append({
                        "station_id": "",
                        "observation_date": obs_date,
                        "parameter_code": param_code,
                        "value": float(value),
                        "unit": PARAMETER_MAP.get(param_code, {}).get("unit", ""),
                    })
            except (ValueError, IndexError) as exc:
                logger.debug("CNRFC: skipping row: %s (%s)", row, exc)

        return records

    def validate(self, records):
        """Validate CNRFC forecast records."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null value"
                rejected.append(rec)
            elif rec["parameter_code"] == "streamflow" and rec["value"] < 0:
                rec["rejection_reason"] = "negative streamflow"
                rejected.append(rec)
            elif rec["parameter_code"] == "precip" and rec["value"] < 0:
                rec["rejection_reason"] = "negative precipitation"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """
        Discover CNRFC forecast points.
        CNRFC doesn't have a spatial search API, so we return known
        California forecast points from a curated list.
        """
        # CNRFC station discovery would require scraping their site.
        # In practice, stations are added manually or via fixture.
        logger.info(
            "CNRFC station discovery is not API-supported. "
            "Use fixture data or add stations manually."
        )
        return []


register_adapter("cnrfc", CNRFCAdapter)
