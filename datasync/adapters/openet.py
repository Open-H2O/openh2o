"""
OpenET adapter.

API docs: https://openet.dri.edu/docs
Auth: X-API-KEY header (api_key auth_type on DataSource).

OpenET uses a 3-stage async workflow:
  1. POST to submit a raster/timeseries request
  2. GET to poll job status
  3. GET to retrieve results

Since this is field-geometry-based (not station-based),
discover_stations returns an empty list.
"""

import logging
import os
import time

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

SUBMIT_URL = "https://openet-api.org/raster/timeseries/point"
STATUS_URL = "https://openet-api.org/raster/timeseries/status"
RESULTS_URL = "https://openet-api.org/raster/timeseries/results"

MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 10


class OpenETAdapter(BaseAdapter):
    source_code = "openet"
    rate_limit_seconds = 2.0
    max_retries = 2

    def _get_api_key(self):
        return os.environ.get("OPENET_API_KEY", "")

    def _headers(self):
        return {
            "X-API-KEY": self._get_api_key(),
            "Content-Type": "application/json",
        }

    def fetch(self, station, start_date, end_date):
        """Submit an OpenET request, poll for completion, return results."""
        # Use station location as the point geometry
        lon = station.location.x
        lat = station.location.y

        payload = {
            "geometry": [lon, lat],
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "variable": "ET",
            "model": "Ensemble",
            "units": "mm",
            "file_format": "JSON",
        }

        # Step 1: Submit
        resp = self._request(
            "POST", SUBMIT_URL, json=payload, headers=self._headers()
        )
        job_data = resp.json()
        job_id = job_data.get("job_id") or job_data.get("uuid", "")

        if not job_id:
            logger.warning("OpenET: no job_id in response: %s", job_data)
            return []

        # Step 2: Poll for completion
        for attempt in range(MAX_POLL_ATTEMPTS):
            time.sleep(POLL_INTERVAL_SECONDS)
            status_resp = self._request(
                "GET", f"{STATUS_URL}/{job_id}", headers=self._headers()
            )
            status_data = status_resp.json()
            job_status = status_data.get("status", "").lower()

            if job_status == "complete":
                break
            elif job_status in ("failed", "error"):
                logger.error("OpenET job %s failed: %s", job_id, status_data)
                return []
        else:
            logger.error("OpenET job %s timed out after %d polls", job_id, MAX_POLL_ATTEMPTS)
            return []

        # Step 3: Retrieve results
        results_resp = self._request(
            "GET", f"{RESULTS_URL}/{job_id}", headers=self._headers()
        )
        return results_resp.json()

    def parse(self, raw_data):
        """Parse OpenET timeseries response."""
        records = []
        if isinstance(raw_data, dict):
            timeseries = raw_data.get("timeseries", raw_data.get("data", []))
        elif isinstance(raw_data, list):
            timeseries = raw_data
        else:
            return records

        for item in timeseries:
            records.append({
                "station_id": item.get("field_id", item.get("station_id", "openet")),
                "observation_date": item.get("date", item.get("time", "")),
                "parameter_code": "ET",
                "value": item.get("et", item.get("value")),
                "unit": "mm",
            })
        return records

    def validate(self, records):
        """Validate ET values (must be non-negative, reasonable)."""
        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null ET value"
                rejected.append(rec)
            elif rec["value"] < 0:
                rec["rejection_reason"] = "negative ET"
                rejected.append(rec)
            elif rec["value"] > 500:
                rec["rejection_reason"] = "ET exceeds 500mm (implausible)"
                rejected.append(rec)
            else:
                valid.append(rec)
        return valid, rejected

    def discover_stations(self, boundary_geometry, radius_km=50):
        """
        OpenET is geometry-based, not station-based.
        Returns empty list. Use parcel geometries directly.
        """
        return []


register_adapter("openet", OpenETAdapter)
