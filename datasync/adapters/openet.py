# SPDX-License-Identifier: AGPL-3.0-or-later
"""
OpenET adapter.

API docs: https://etdata.org/api/api-documentation/ (host: openet-api.org)
Auth: the API key is sent in the `Authorization` header (raw key, no "Bearer").

The OpenET timeseries API is synchronous: a single POST to the point or
polygon endpoint returns the ET timeseries directly as a JSON array of
{"time": "<date>", "et": <value>} objects. (The older submit / poll-status /
fetch-results workflow no longer exists.)

Since OpenET is field-geometry-based (not station-based),
discover_stations returns an empty list.
"""

import logging
import os

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

POINT_URL = "https://openet-api.org/raster/timeseries/point"
POLYGON_URL = "https://openet-api.org/raster/timeseries/polygon"


class OpenETAdapter(BaseAdapter):
    source_code = "openet"
    rate_limit_seconds = 2.0
    max_retries = 2

    def _get_api_key(self):
        return os.environ.get("OPENET_API_KEY", "")

    def _headers(self):
        return {
            "Authorization": self._get_api_key(),
            "Content-Type": "application/json",
        }

    def fetch(self, station, start_date, end_date):
        """Fetch monthly ET for a station's point location.

        The OpenET API is synchronous: one POST returns the timeseries as a
        JSON array, which parse() consumes directly.
        """
        payload = {
            "date_range": [
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ],
            "interval": "monthly",
            "geometry": [station.location.x, station.location.y],
            "model": "Ensemble",
            "variable": "ET",
            "reference_et": "gridMET",
            "units": "mm",
            "file_format": "JSON",
        }
        resp = self._request(
            "POST", POINT_URL, json=payload, headers=self._headers()
        )
        return resp.json()

    def parse(self, raw_data):
        """Parse OpenET timeseries response.

        OpenET returns ET in millimeters (mm). To convert to acre-feet consumed:
          ET (AF) = ET (mm) x area (acres) / 304.8
        See accounting.services.et_mm_to_acre_feet() for the full derivation.
        Reference: USGS Water Science School; California Department of Water Resources unit conversion tables.
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
        """Fetch monthly ET for a polygon.

        Synchronous single POST. OpenET wants the polygon ring as a flat
        coordinate list [lon, lat, lon, lat, ...]. Falls back to the centroid
        point if the polygon request is rejected.
        """
        ring = self._geometry_to_geojson_coords(geometry)
        flat_coords = [value for vertex in ring for value in vertex]
        payload = {
            "date_range": [
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ],
            "interval": "monthly",
            "geometry": flat_coords,
            "model": "Ensemble",
            "variable": "ET",
            "reference_et": "gridMET",
            "units": "mm",
            "file_format": "JSON",
        }
        try:
            resp = self._request(
                "POST", POLYGON_URL, json=payload, headers=self._headers()
            )
        except Exception as exc:
            logger.warning(
                "OpenET polygon endpoint failed (%s), falling back to centroid", exc
            )
            centroid = geometry.centroid
            payload["geometry"] = [centroid.x, centroid.y]
            resp = self._request(
                "POST", POINT_URL, json=payload, headers=self._headers()
            )
        return resp.json()

    def sync_with_cache(self, parcel, start_date, end_date):
        """Cache-aware OpenET sync for a single parcel."""
        from datasync.models import OpenETCache

        existing = OpenETCache.objects.filter(
            parcel=parcel,
            start_date__lte=start_date,
            end_date__gte=end_date,
        ).exclude(model_name=OpenETCache.PENDING_MARKER).order_by("-queried_at").first()

        if existing and not existing.is_stale():
            logger.info("OpenET cache hit for parcel %s", parcel.pk)
            return existing.et_data

        # Reserve the budget slot BEFORE fetching so two concurrent syncs near the
        # ceiling can't both pass the check and both spend (P2-6). The reservation
        # is a PENDING row that counts immediately; we finalize or release it below.
        reservation = OpenETCache.reserve_query_slot(
            parcel, parcel.geometry, start_date, end_date
        )
        if reservation is None:
            logger.warning("OpenET budget exceeded, skipping parcel %s", parcel.pk)
            return None

        try:
            raw_data = self.fetch_polygon(parcel.geometry, start_date, end_date)
        except Exception as exc:
            # Release the slot: a failed call should not count against the budget.
            reservation.delete()
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

        # Finalize the reservation into a real cache row.
        reservation.model_name = "Ensemble"
        reservation.et_data = et_data
        reservation.save(update_fields=["model_name", "et_data"])
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
            ).exclude(model_name=OpenETCache.PENDING_MARKER).order_by("-queried_at").first()

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
