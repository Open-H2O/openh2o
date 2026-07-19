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

# Ensemble spread. OpenET's "Ensemble" is NOT a plain average of the six member
# models (DisALEXI, eeMETRIC, geeSEBAL, PT-JPL, SIMS, SSEBop): it drops outliers
# with a median-absolute-deviation filter and averages whatever survives
# (Melton et al. 2022). These variables expose that filtering, which is
# otherwise discarded — we would be filing a modeled number as though it were
# exact.
#
#   et_mad_min / et_mad_max — the lowest / highest SURVIVING member, i.e. the
#       envelope of models the filter kept. Note this is not a symmetric error
#       bar: the ensemble value can sit anywhere inside the range.
#   model_count            — how many of the six survived. 6 means the models
#       agree closely; 3 means half were thrown out as outliers and the value
#       deserves a second look.
#
# Fetching all three is 3 extra calls per parcel-window, because the API takes
# one variable per call. That is still far cheaper than the 5 extra calls that
# querying each member model separately would cost, and the bounds come from
# OpenET's own filter rather than from us re-deriving it.
SPREAD_VARIABLES = ("et_mad_min", "et_mad_max", "model_count")

# model_count is a tally of models, not a depth of water. Keeping it out of the
# mm-based validation thresholds and unit labels.
UNITLESS_VARIABLES = frozenset({"model_count"})


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

    def parse(self, raw_data, variable="ET"):
        """Parse OpenET timeseries response.

        OpenET returns ET in millimeters (mm). To convert to acre-feet consumed:
          ET (AF) = ET (mm) x area (acres) / 304.8
        See accounting.services.et_mm_to_acre_feet() for the full derivation.
        Reference: USGS Water Science School; California Department of Water Resources unit conversion tables.

        ``variable`` selects which key to read out of each timeseries item. The
        API echoes the requested variable back as the value key, so an
        et_mad_min request returns {"time": ..., "et_mad_min": ...}. We try the
        requested name first and only then fall back to the generic keys, so a
        spread request can never silently read the ET column.
        """
        records = []
        if isinstance(raw_data, dict):
            timeseries = raw_data.get("timeseries", raw_data.get("data", []))
        elif isinstance(raw_data, list):
            timeseries = raw_data
        else:
            return records

        key = variable.lower()
        for item in timeseries:
            if key in item:
                value = item[key]
            elif variable in item:
                value = item[variable]
            else:
                # Single-variable responses sometimes use a bare "value" column.
                # Only fall back to "et" for an ET request — doing so for a
                # spread request would file the ensemble mean as if it were a
                # bound, which reads as a zero-width (falsely certain) range.
                value = item.get("value")
                if value is None and key == "et":
                    value = item.get("et")
            records.append({
                "station_id": item.get("field_id", item.get("station_id", "openet")),
                "observation_date": item.get("date", item.get("time", "")),
                "parameter_code": variable,
                "value": value,
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

    def fetch_polygon(self, geometry, start_date, end_date, variable="ET"):
        """Fetch a monthly OpenET timeseries for a polygon.

        Synchronous single POST. OpenET wants the polygon ring as a flat
        coordinate list [lon, lat, lon, lat, ...]. Falls back to the centroid
        point if the polygon request is rejected.

        ``variable`` is one of ET (the ensemble value) or a member of
        SPREAD_VARIABLES. The API takes exactly ONE variable and ONE model per
        call, which is why the spread costs additional calls rather than riding
        along on the ET request.
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
            "variable": variable,
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
        from django.db import transaction

        from datasync.models import OpenETCache

        # The variable filter is load-bearing, not defensive. OpenETCache is a
        # multi-variable table: it already holds variable="precip" rows, and the
        # ensemble-spread work adds et_mad_min / et_mad_max / model_count. Without
        # this filter the newest row for the window wins regardless of what it
        # measures, so a fresh precip row reads as an ET cache hit and the ET fetch
        # is skipped outright — the parcel silently keeps whatever ET it had.
        existing = OpenETCache.objects.filter(
            parcel=parcel,
            variable="ET",
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
        #
        # F-math-08: retire any STALE row for the identical window first. We only
        # get here on a miss, and the miss that reaches a same-span row is the
        # is_stale() refresh — leaving the old row would both trip the
        # openetcache_one_row_per_parcel_window constraint on save and, before
        # that constraint existed, leave two rows the engine summed into a
        # doubled ET. The refreshed values supersede the stale ones outright.
        with transaction.atomic():
            OpenETCache.objects.filter(
                parcel=parcel,
                start_date=reservation.start_date,
                end_date=reservation.end_date,
                variable=reservation.variable,
                model_name="Ensemble",
            ).exclude(pk=reservation.pk).delete()
            reservation.model_name = "Ensemble"
            reservation.et_data = et_data
            reservation.save(update_fields=["model_name", "et_data"])
        logger.info("OpenET cache miss, stored %d records for parcel %s", len(et_data), parcel.pk)
        return et_data

    def sync_spread_variable(self, parcel, start_date, end_date, variable):
        """Cache-aware sync of ONE ensemble-spread variable for a parcel.

        Mirrors sync_with_cache — same budget reservation, same stale-row
        retirement — but writes its own row keyed on ``variable``. Each spread
        variable is stored separately rather than folded into the ET row so that
        a partial fetch (bounds retrieved, count refused) degrades to "no
        confidence signal" instead of corrupting the ET value itself.

        Payload values are keyed by the variable name, matching the convention
        build_precip_data established: a row's values live under a key named for
        what they measure, never a generic "et".
        """
        from django.db import transaction

        from datasync.models import OpenETCache

        if variable not in SPREAD_VARIABLES:
            raise ValueError(
                f"{variable!r} is not an ensemble-spread variable; "
                f"expected one of {SPREAD_VARIABLES}"
            )

        existing = OpenETCache.objects.filter(
            parcel=parcel,
            variable=variable,
            start_date__lte=start_date,
            end_date__gte=end_date,
        ).exclude(model_name=OpenETCache.PENDING_MARKER).order_by("-queried_at").first()

        if existing and not existing.is_stale():
            logger.info("OpenET %s cache hit for parcel %s", variable, parcel.pk)
            return existing.et_data

        reservation = OpenETCache.reserve_query_slot(
            parcel, parcel.geometry, start_date, end_date, variable=variable
        )
        if reservation is None:
            logger.warning(
                "OpenET budget exceeded, skipping %s for parcel %s", variable, parcel.pk
            )
            return None

        try:
            raw_data = self.fetch_polygon(
                parcel.geometry, start_date, end_date, variable=variable
            )
        except Exception as exc:
            reservation.delete()
            logger.error(
                "OpenET %s fetch failed for parcel %s: %s", variable, parcel.pk, exc
            )
            return None

        parsed = self.parse(raw_data, variable=variable)
        if variable in UNITLESS_VARIABLES:
            # A model tally has no mm threshold to clear; the ET validators would
            # be measuring the wrong thing entirely.
            valid = [r for r in parsed if r.get("value") is not None]
        else:
            valid, _rejected = self.validate(parsed, temporal_resolution="monthly")

        unit = "count" if variable in UNITLESS_VARIABLES else "mm"
        values = [
            {
                "date": r.get("observation_date", ""),
                variable: r.get("value"),
                "unit": unit,
            }
            for r in valid
        ]

        with transaction.atomic():
            OpenETCache.objects.filter(
                parcel=parcel,
                start_date=reservation.start_date,
                end_date=reservation.end_date,
                variable=variable,
                model_name="Ensemble",
            ).exclude(pk=reservation.pk).delete()
            reservation.model_name = "Ensemble"
            reservation.et_data = values
            reservation.save(update_fields=["model_name", "et_data"])

        logger.info(
            "OpenET %s stored %d records for parcel %s", variable, len(values), parcel.pk
        )
        return values

    def sync_spread(self, parcel, start_date, end_date):
        """Fetch every ensemble-spread variable for one parcel.

        Returns {variable: payload or None}. A None means that variable was not
        retrieved (budget exhausted or the call failed); callers must treat a
        missing bound as "spread unknown" and show no range, never as a
        zero-width range.
        """
        results = {}
        for variable in SPREAD_VARIABLES:
            self._rate_limit()
            results[variable] = self.sync_spread_variable(
                parcel, start_date, end_date, variable
            )
        return results

    def sync_parcel_et(self, parcels, start_date, end_date):
        """Batch sync ET data for multiple parcels with rate limiting."""
        summary = {"cached": 0, "fetched": 0, "budget_blocked": 0, "failed": 0}

        for parcel in parcels:
            from datasync.models import OpenETCache

            # Same variable filter as sync_with_cache — this is the pre-check that
            # decides whether to spend a budget slot at all, so a precip row read
            # as ET here skips the parcel before sync_with_cache ever sees it.
            existing = OpenETCache.objects.filter(
                parcel=parcel,
                variable="ET",
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
