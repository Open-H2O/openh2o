# SPDX-License-Identifier: AGPL-3.0-or-later
"""
USGS Water Data APIs adapter (daily values and station discovery).

API docs: https://api.waterdata.usgs.gov/docs/ogcapi/
USGS retires its older WaterServices site on 2027-02-22; this
adapter talks to the OGC API collections that replace it: ``daily`` for the
readings, ``time-series-metadata`` for what each site measures and until when,
and ``monitoring-locations`` for names and coordinates.

No key is required. A free key from USGS (set USGS_API_KEY) raises the request
allowance, and when it is set it travels in the ``X-Api-Key`` header, never in
the URL, so it stays out of logged addresses.

Parameters:
  00060 - Discharge (cfs)
  00065 - Gage height (ft)
  00010 - Water temperature (deg C)
  72019 - Depth to water level below land surface (ft)
  72020 - Elevation above NGVD 1929 (ft), any water surface
  62610 - Groundwater level above NGVD 1929 (ft)
"""

import logging
import os
from datetime import date

from datasync.adapters import register_adapter
from datasync.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections"
DAILY_URL = f"{BASE_URL}/daily/items"
SERIES_URL = f"{BASE_URL}/time-series-metadata/items"
LOCATIONS_URL = f"{BASE_URL}/monitoring-locations/items"

# A "next" link is followed only when it stays on the USGS host, so the key
# header can never be sent anywhere else.
TRUSTED_PREFIX = "https://api.waterdata.usgs.gov/"
MAX_PAGES = 20
LOCATION_CHUNK = 100
FRESH_DAYS = 365

PARAMETER_MAP = {
    "00060": {"name": "Discharge", "unit": "cfs"},
    "00065": {"name": "Gage Height", "unit": "ft"},
    "00010": {"name": "Water Temperature", "unit": "deg C"},
    "72019": {"name": "Depth to Water Level", "unit": "ft below surface"},
    "72020": {"name": "Elevation above NGVD 1929", "unit": "ft above NGVD 1929"},
    "62610": {"name": "Groundwater level above NGVD 1929", "unit": "ft above NGVD 1929"},
}

STREAM_PARAMS = ["00060", "00065", "00010"]
GW_PARAMS = ["72019", "72020", "62610"]

# The service spells two units differently from the pages and charts here.
UNIT_MAP = {"ft^3/s": "ft3/s", "degC": "deg C"}


def _today():
    """Today's date; a function so a test can fix the clock."""
    return date.today()


class USGSAdapter(BaseAdapter):
    source_code = "usgs"
    rate_limit_seconds = 1.0

    # Discovery makes two calls inside ONE wizard poll, and gunicorn kills a
    # worker at 60 s. The two calls measured 0.2 to 0.5 s on 2026-10-29,
    # against 15 to 47 s for the old site search, so 15 s each is a generous
    # cap that still leaves the poll well inside the worker limit.
    discovery_timeout = 15.0

    @staticmethod
    def _api_key():
        return os.environ.get("USGS_API_KEY", "")

    def _headers(self):
        """Request options carrying the optional key; empty when no key is set."""
        key = self._api_key()
        return {"headers": {"X-Api-Key": key}} if key else {}

    def fetch(self, station, start_date, end_date):
        """Fetch daily values from the USGS Water Data APIs.

        Returns the list of GeoJSON features from every page. The service
        refuses a duration such as P3D for ``datetime`` with a 400, so the
        range is always two explicit dates.
        """
        param_codes = station.parameters or list(PARAMETER_MAP.keys())
        params = {
            "f": "json",
            "monitoring_location_id": f"USGS-{station.external_station_id}",
            "parameter_code": ",".join(param_codes),
            "datetime": f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}",
            "limit": 10000,
        }
        features = []
        url, query = DAILY_URL, params
        for _ in range(MAX_PAGES):
            resp = self._request("GET", url, params=query, **self._headers())
            body = resp.json()
            page = body.get("features", []) if isinstance(body, dict) else []
            if not page:
                break
            features.extend(page)
            next_url = next(
                (lk.get("href") for lk in body.get("links", []) if lk.get("rel") == "next"),
                None,
            )
            if not next_url:
                break
            if not next_url.startswith(TRUSTED_PREFIX):
                logger.warning(
                    "usgs: not following a next link to another host: %s", next_url
                )
                break
            url, query = next_url, None
        return features

    def parse(self, raw_data):
        """Parse Water Data API daily features into standard records.

        Records already in the standard shape (the offline fixture) pass
        through unchanged.
        """
        if isinstance(raw_data, dict):
            raw_data = raw_data.get("features", [])
        records = []
        for feature in raw_data or []:
            props = feature.get("properties") if isinstance(feature, dict) else None
            if props is None:
                if isinstance(feature, dict) and "parameter_code" in feature:
                    records.append(feature)
                continue
            site_code = str(props.get("monitoring_location_id", "")).removeprefix("USGS-")
            day = props.get("time", "")
            raw_val = props.get("value")
            if raw_val in (None, ""):
                value = None
            else:
                # Guard the per-value parse: one non-numeric reading (e.g. a
                # text value like "Ice") must drop only that record, not raise
                # and sink the whole station batch.
                try:
                    value = float(raw_val)
                except (ValueError, TypeError):
                    logger.warning(
                        "usgs: dropping non-numeric reading %r for %s on %s",
                        raw_val, site_code, day,
                    )
                    continue
            code = props.get("parameter_code", "")
            unit_raw = props.get("unit_of_measure")
            unit = UNIT_MAP.get(unit_raw, unit_raw) or PARAMETER_MAP.get(code, {}).get("unit", "")
            qualifiers = []
            status = props.get("approval_status")
            if status == "Provisional":
                qualifiers.append("P")
            elif status == "Approved":
                qualifiers.append("A")
            extra = props.get("qualifier")
            if isinstance(extra, str) and extra:
                qualifiers.append(extra)
            elif isinstance(extra, list):
                qualifiers.extend(str(q) for q in extra if q)
            records.append({
                "station_id": site_code,
                "observation_date": day,
                "parameter_code": code,
                "value": value,
                "unit": unit,
                "qualifiers": qualifiers,
                "statistic_id": props.get("statistic_id", ""),
            })

        # The service returns one feature per statistic (for water temperature
        # the daily maximum, minimum and mean) and in no fixed order, but a
        # station, code and day holds one stored value. Keep the lowest
        # statistic code, the daily maximum for temperature, which is the
        # figure this adapter has always stored.
        best = {}
        passthrough = []
        for rec in records:
            if "statistic_id" not in rec:
                passthrough.append(rec)
                continue
            key = (rec["station_id"], rec["parameter_code"], rec["observation_date"])
            held = best.get(key)
            if held is None or rec["statistic_id"] < held["statistic_id"]:
                best[key] = rec
        return list(best.values()) + passthrough

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

        Two calls. The first asks ``time-series-metadata`` which daily series
        for discharge (00060) and depth to water (72019) exist in the box; a
        series that ended more than a year ago belongs to a site that no longer
        reports, so only recent ones count. The second asks
        ``monitoring-locations`` for the names and coordinates of those sites.
        """
        # Expand the boundary box by the search radius (a small GSA boundary
        # often contains no active daily gauges on its own). ~111 km per degree
        # of latitude; widen lon by the same rough amount.
        deg = max(radius_km, 1) / 111.0
        x0, y0, x1, y1 = boundary_geometry.extent  # (xmin, ymin, xmax, ymax)
        bbox_str = f"{x0 - deg:.4f},{y0 - deg:.4f},{x1 + deg:.4f},{y1 + deg:.4f}"

        # A timeout, a refused connection or an error status propagates, so
        # the caller reports a provider that did not answer.
        resp = self._discover_request(
            "GET", SERIES_URL,
            params={
                "f": "json",
                "bbox": bbox_str,
                "parameter_code": "00060,72019",
                "computation_period_identifier": "Daily",
                "limit": 10000,
            },
            **self._headers(),
        )
        today = _today()
        kept = set()
        has_flow = set()
        for feature in resp.json().get("features", []):
            props = feature.get("properties", {})
            site = props.get("monitoring_location_id") or ""
            if not site.startswith("USGS-"):
                continue
            try:
                ended = date.fromisoformat((props.get("end") or "")[:10])
            except ValueError:
                continue
            if (today - ended).days > FRESH_DAYS:
                continue
            kept.add(site)
            if props.get("parameter_code") == "00060":
                has_flow.add(site)
        if not kept:
            return []

        ids = sorted(kept)
        stations = []
        seen = set()
        for i in range(0, len(ids), LOCATION_CHUNK):
            resp = self._discover_request(
                "GET", LOCATIONS_URL,
                params={
                    "f": "json",
                    "id": ",".join(ids[i:i + LOCATION_CHUNK]),
                    "properties": "monitoring_location_name,site_type_code",
                    "limit": 10000,
                },
                **self._headers(),
            )
            for feature in resp.json().get("features", []):
                site = feature.get("id") or ""
                coords = (feature.get("geometry") or {}).get("coordinates") or []
                if site not in kept or site in seen or len(coords) < 2:
                    continue
                try:
                    lon_f, lat_f = float(coords[0]), float(coords[1])
                except (ValueError, TypeError):
                    continue
                props = feature.get("properties", {})
                seen.add(site)
                stations.append({
                    "station_id": site.removeprefix("USGS-"),
                    "name": props.get("monitoring_location_name") or "",
                    "latitude": lat_f,
                    "longitude": lon_f,
                    "parameters": STREAM_PARAMS if site in has_flow else GW_PARAMS,
                    "site_type": props.get("site_type_code") or "",
                })
        stations.sort(key=lambda st: st["station_id"])
        return stations


register_adapter("usgs", USGSAdapter)
