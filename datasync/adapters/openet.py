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
POLYGON_URL = "https://openet-api.org/raster/timeseries/polygon"
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
        """Parse OpenET timeseries response.

        OpenET returns ET in millimeters (mm). To convert to acre-feet consumed:
          ET (AF) = ET (mm) x area (acres) / 304.8
        See accounting.services.et_mm_to_acre_feet() for the full derivation.
        Reference: USGS Water Science School; CA DWR unit conversion tables.
        """
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

    def validate(self, records, temporal_resolution="monthly"):
        """Validate ET values. Threshold depends on temporal granularity.

        The 500mm/month cap is reasonable for monthly data (that is roughly
        20 inches/month — extremely high for any California crop). But OpenET
        can return data at daily or annual granularity. For annual totals,
        Central Valley alfalfa or rice can legitimately exceed 1200mm/year.

        Thresholds (with agronomic citations):
        - daily:   15mm (~0.6 in/day, peak alfalfa ET from UC Davis CIMIS)
        - monthly: 500mm (generous cap for any CA irrigated crop)
        - annual:  2000mm (~79 in, exceeds any CA crop)

        Reference: UC Davis CIMIS peak ET rates for Central Valley crops.
        Alfalfa peak: ~8-10mm/day, ~250mm/month, ~1500mm/year.
        Rice peak: similar range. 500mm/month cap is generous.
        """
        THRESHOLDS = {
            "daily": 15,
            "monthly": 500,
            "annual": 2000,
        }
        max_et = THRESHOLDS.get(temporal_resolution, 500)

        valid = []
        rejected = []
        for rec in records:
            if rec["value"] is None:
                rec["rejection_reason"] = "null ET value"
                rejected.append(rec)
            elif rec["value"] < 0:
                rec["rejection_reason"] = "negative ET"
                rejected.append(rec)
            elif rec["value"] > max_et:
                rec["rejection_reason"] = (
                    f"ET exceeds {max_et}mm ({temporal_resolution} threshold)"
                )
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

    def _geometry_to_geojson_coords(self, geometry):
        """Convert a GEOSGeometry (Polygon or MultiPolygon) to GeoJSON coordinate list."""
        if geometry.geom_type == "MultiPolygon":
            poly = geometry[0]
        else:
            poly = geometry
        return [list(coord) for coord in poly.exterior_ring.coords]

    def fetch_polygon(self, geometry, start_date, end_date):
        """Submit a polygon-based OpenET request, poll, and return results."""
        coords = self._geometry_to_geojson_coords(geometry)
        payload = {
            "geometry": coords,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "variable": "ET",
            "model": "Ensemble",
            "units": "mm",
            "file_format": "JSON",
        }

        try:
            resp = self._request(
                "POST", POLYGON_URL, json=payload, headers=self._headers()
            )
        except Exception as exc:
            logger.warning("OpenET polygon endpoint failed (%s), falling back to centroid", exc)
            centroid = geometry.centroid
            payload["geometry"] = [centroid.x, centroid.y]
            resp = self._request(
                "POST", SUBMIT_URL, json=payload, headers=self._headers()
            )

        job_data = resp.json()
        job_id = job_data.get("job_id") or job_data.get("uuid", "")
        if not job_id:
            logger.warning("OpenET: no job_id in polygon response: %s", job_data)
            return []

        for _attempt in range(MAX_POLL_ATTEMPTS):
            time.sleep(POLL_INTERVAL_SECONDS)
            status_resp = self._request(
                "GET", f"{STATUS_URL}/{job_id}", headers=self._headers()
            )
            status_data = status_resp.json()
            job_status = status_data.get("status", "").lower()
            if job_status == "complete":
                break
            elif job_status in ("failed", "error"):
                logger.error("OpenET polygon job %s failed: %s", job_id, status_data)
                return []
        else:
            logger.error("OpenET polygon job %s timed out", job_id)
            return []

        results_resp = self._request(
            "GET", f"{RESULTS_URL}/{job_id}", headers=self._headers()
        )
        return results_resp.json()

    def sync_with_cache(self, parcel, start_date, end_date):
        """Cache-aware OpenET sync for a single parcel."""
        from datasync.models import OpenETCache

        existing = OpenETCache.objects.filter(
            parcel=parcel,
            start_date__lte=start_date,
            end_date__gte=end_date,
        ).order_by("-queried_at").first()

        if existing and not existing.is_stale():
            logger.info("OpenET cache hit for parcel %s", parcel.pk)
            return existing.et_data

        can_query, used, limit = OpenETCache.check_budget()
        if not can_query:
            logger.warning(
                "OpenET budget exceeded (%d/%d), skipping parcel %s",
                used, limit, parcel.pk,
            )
            return None

        try:
            raw_data = self.fetch_polygon(parcel.geometry, start_date, end_date)
        except Exception as exc:
            logger.error("OpenET fetch failed for parcel %s: %s", parcel.pk, exc)
            return None

        parsed = self.parse(raw_data)
        valid, _rejected = self.validate(parsed, temporal_resolution="monthly")

        et_data = [
            {
                "date": r.get("observation_date", ""),
                "et": r.get("value"),
                "unit": r.get("unit", "mm"),
            }
            for r in valid
        ]

        OpenETCache.objects.create(
            parcel=parcel,
            geometry=parcel.geometry,
            start_date=start_date,
            end_date=end_date,
            variable="ET",
            model_name="Ensemble",
            et_data=et_data,
        )
        logger.info("OpenET cache miss, stored %d records for parcel %s", len(et_data), parcel.pk)
        return et_data

    def sync_parcel_et(self, parcels, start_date, end_date):
        """Batch sync ET data for multiple parcels with rate limiting."""
        summary = {"cached": 0, "fetched": 0, "budget_blocked": 0, "failed": 0}

        for parcel in parcels:
            from datasync.models import OpenETCache

            existing = OpenETCache.objects.filter(
                parcel=parcel,
                start_date__lte=start_date,
                end_date__gte=end_date,
            ).order_by("-queried_at").first()

            if existing and not existing.is_stale():
                summary["cached"] += 1
                continue

            can_query, used, limit = OpenETCache.check_budget()
            if not can_query:
                summary["budget_blocked"] += 1
                continue

            self._rate_limit()
            result = self.sync_with_cache(parcel, start_date, end_date)
            if result is None:
                summary["failed"] += 1
            else:
                summary["fetched"] += 1

        return summary


register_adapter("openet", OpenETAdapter)
