# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Reusable client for querying ArcGIS REST FeatureServer endpoints.

Handles pagination, rate limiting, retries, and geometry conversion
between ArcGIS JSON and Django GEOSGeometry formats.
"""

import json
import logging
import random
import time

import requests
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Polygon

logger = logging.getLogger(__name__)


# Transport-level failures worth retrying. Defined LOCALLY rather than imported
# from datasync/adapters/base.py:46-51, which holds the identical tuple: this is
# the house idiom copied, not the code reused. `geography` is a standard module
# and `datasync` is optional (core/modules.py), so a standard module reaching
# into an optional one is exactly the arrow the composition rule exists to stop.
#
# Measured 2026-08-28 against all three services this repo calls: transport
# errors were 0 of 60 requests. This tuple therefore preserves existing
# behaviour rather than fixing an observed failure — the observed failure is the
# in-body one below.
RETRYABLE_TRANSPORT_ERRORS = (
    requests.HTTPError,          # a real 4xx/5xx status; raise_for_status raised it
    requests.ConnectionError,    # DNS failure, refused connection, TCP reset
    requests.Timeout,            # the 60s read timeout expired mid-request
    requests.exceptions.ContentDecodingError,   # half-delivered gzip body
    requests.exceptions.ChunkedEncodingError,   # half-delivered chunked body
    requests.exceptions.JSONDecodeError,        # body arrived truncated; same class
                                                # of half-delivered response as the
                                                # two decoding errors above
)

# In-body error codes worth retrying. ArcGIS reports a server-side query failure
# as HTTP 200 carrying {"error": {...}} in the JSON body, which is why a status-
# code retry never fires on it.
#
# Measured 2026-08-28 against the DWR LightBox parcel service, two regions: the
# ONLY code observed was 500, body {'code': 500, 'message': 'Error performing
# query operation', 'details': []}, and it cleared on retry 8 of 8 times.
# 500 is therefore the whole list. A second code gets added WITH its measurement,
# never speculatively — a malformed `where` or a bad field name comes back the
# same way with code 400, and retrying that six times turns an instant, legible
# "that field does not exist" into a 60-second wait ending in the same message.
RETRYABLE_ARCGIS_ERROR_CODES = (500,)

# Retry budget per page.
#
# Measured 2026-08-28: 16 of 60 requests failed = 26.7% per-request failure rate.
# Across a ~104-page traversal (the Merced Subbasin parcel import) that gives a
# whole-traversal survival probability of 13.7% at 3 attempts and 96.3% at 6.
# 6 is chosen for robustness across a range of rates rather than tuned to 26.7%
# exactly — it is still above 99.9% at a 15% rate.
MAX_ATTEMPTS = 6

# Ceiling on a single backoff wait. At MAX_ATTEMPTS the un-capped ladder is
# 1, 2, 4, 8, 16 seconds; the cap bounds a future budget increase.
BACKOFF_CAP_SECONDS = 30


def _backoff_seconds(attempt):
    """Exponential backoff with jitter, in seconds, for a zero-based attempt.

    The jitter matters: without it every page of a stalled traversal retries on
    the same instants and the retries re-synchronise on the same server.
    """
    return min(2 ** attempt, BACKOFF_CAP_SECONDS) + random.uniform(0, 1)


def query_feature_server(
    url,
    where="1=1",
    geometry=None,
    geometry_type=None,
    spatial_rel=None,
    out_fields="*",
    return_geometry=True,
    out_sr=4326,
    max_record_count=1000,
):
    """Generator that yields pages of features from an ArcGIS FeatureServer.

    Each page is a list of dicts with 'attributes' and 'geometry' keys.
    Handles pagination via resultOffset/resultRecordCount.
    Rate limits 0.5s between pages.

    Each page is requested up to MAX_ATTEMPTS (6) times with jittered
    exponential backoff. Retry covers BOTH transport failures
    (RETRYABLE_TRANSPORT_ERRORS) and the API's in-body error object — ArcGIS
    reports a server-side query failure as HTTP 200 with {"error": {...}} in the
    body, so a status-code-only retry never sees it. Only the error codes in
    RETRYABLE_ARCGIS_ERROR_CODES are retried; any other code (a bad field name,
    a malformed `where`) raises immediately with no sleep. Exhausting the budget
    raises an error that names it.
    """
    offset = 0
    page_num = 0

    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": str(return_geometry).lower(),
            "outSR": out_sr,
            "f": "json",
            "resultRecordCount": max_record_count,
            "resultOffset": offset,
        }

        if geometry is not None:
            params["geometry"] = (
                json.dumps(geometry) if isinstance(geometry, dict) else geometry
            )
        if geometry_type is not None:
            params["geometryType"] = geometry_type
        if spatial_rel is not None:
            params["spatialRel"] = spatial_rel

        # Retry with jittered exponential backoff.
        #
        # The success condition is "response parsed AND no error object", not
        # "raise_for_status() passed" — every failure this API actually produces
        # is an HTTP 200 (measured 2026-08-28, 16 of 60 requests). That is why
        # response.json() is INSIDE the loop and the dispatch below reads the
        # parsed body.
        #
        # Deliberately NOT urllib3.util.Retry / HTTPAdapter(max_retries=...):
        # every stock Python retry sits below the JSON parse and dispatches on
        # status code and transport failure only, so against this service it
        # would fire zero times — a fix that looks installed and does nothing.
        # Deliberately NOT `tenacity` either: retry_if_result is the right
        # abstraction, but it is a new dependency for one call site in a project
        # whose stated constraint is a small runtime, and the house already has a
        # retry idiom (datasync/adapters/base.py:195-208). Do not re-litigate.
        #
        # POST, not GET: the spatial query sends the boundary geometry as a
        # parameter. A full-resolution boundary (e.g. the Merced Subbasin's
        # 8,446-vertex polygon) serialized into a GET query string blows past
        # the server's URL-length limit and returns "414 Request-URI Too
        # Large", silently yielding zero features. ArcGIS REST /query accepts
        # the identical parameters form-encoded in a POST body, which has no
        # such limit, so POST works for boundaries of any size.
        data = None
        last_failure = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.post(url, data=params, timeout=60)
                response.raise_for_status()
                data = response.json()
            except RETRYABLE_TRANSPORT_ERRORS as exc:
                last_failure = exc
                logger.warning(
                    "ArcGIS request failed at the transport "
                    "(attempt %d/%d): %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    exc,
                )
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(_backoff_seconds(attempt))
            else:
                error = data.get("error")
                if error is None:
                    break  # the only success path

                if isinstance(error, dict):
                    code = error.get("code")
                    message = error.get("message", error)
                else:
                    code = None
                    message = error

                if code not in RETRYABLE_ARCGIS_ERROR_CODES:
                    # Ours, not the network's: a bad field name or a malformed
                    # `where`. Fail fast and legibly — no sleep, no second try.
                    raise RuntimeError(
                        f"ArcGIS API error (code {code}, not retryable): {message}"
                    )

                last_failure = f"code {code}: {message}"
                logger.warning(
                    "ArcGIS returned an in-body error "
                    "(attempt %d/%d): code %s: %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    code,
                    message,
                )
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(_backoff_seconds(attempt))
        else:
            logger.error(
                "ArcGIS request failed after %d attempts: %s",
                MAX_ATTEMPTS,
                last_failure,
            )
            raise RuntimeError(
                f"ArcGIS query failed after {MAX_ATTEMPTS} attempts "
                f"(offset {offset}): {last_failure}"
            )

        features = data.get("features", [])
        page_num += 1
        logger.info(
            "Page %d: %d features (offset %d)", page_num, len(features), offset
        )

        if not features:
            break

        yield features

        # Check if there are more pages
        if not data.get("exceededTransferLimit", False):
            break

        offset += len(features)
        time.sleep(0.5)  # Rate limit between pages


def query_by_boundary(url, boundary_geometry, out_fields="*", return_geometry=True):
    """Query a FeatureServer for features that intersect a boundary.

    Takes a GEOSGeometry (MultiPolygon), converts to ArcGIS JSON,
    and returns a flat list of all matching features.
    """
    esri_geom = geos_to_esri_geometry(boundary_geometry)

    all_features = []
    for page in query_feature_server(
        url,
        geometry=esri_geom,
        geometry_type="esriGeometryPolygon",
        spatial_rel="esriSpatialRelIntersects",
        out_fields=out_fields,
        return_geometry=return_geometry,
    ):
        all_features.extend(page)

    logger.info("Total features from boundary query: %d", len(all_features))
    return all_features


def esri_polygon_to_geos(esri_geometry):
    """Convert an ArcGIS JSON polygon to a Django GEOSGeometry MultiPolygon.

    Input format: {'rings': [[[x, y], ...], ...]}
    Returns a MultiPolygon with SRID 4326, or None for empty/null input.
    """
    if not esri_geometry or not esri_geometry.get("rings"):
        return None

    rings = esri_geometry["rings"]
    if not rings:
        return None

    # ArcGIS convention: the first ring with clockwise winding is the
    # exterior, subsequent counter-clockwise rings are holes belonging
    # to the preceding exterior ring. For simplicity and because most
    # basin boundaries are simple polygons, we treat each ring set as
    # a single polygon. Django/GEOS will normalize winding order.
    polygons = []
    exterior = None
    holes = []

    for ring in rings:
        coords = [tuple(pt[:2]) for pt in ring]
        # Ensure ring is closed
        if coords[0] != coords[-1]:
            coords.append(coords[0])

        # Determine winding: positive area = clockwise (exterior in ArcGIS)
        # Use the shoelace formula
        area = sum(
            (coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1])
            for i in range(len(coords) - 1)
        )

        if area >= 0 or exterior is None:
            # New exterior ring: flush previous polygon if any
            if exterior is not None:
                polygons.append(Polygon(exterior, *holes))
                holes = []
            exterior = coords
        else:
            holes.append(coords)

    # Flush final polygon
    if exterior is not None:
        polygons.append(Polygon(exterior, *holes))

    if not polygons:
        return None

    mp = MultiPolygon(polygons, srid=4326)
    return mp


def esri_polyline_to_geos(esri_geometry):
    """Convert an ArcGIS JSON polyline to a Django GEOSGeometry MultiLineString.

    Input format: {'paths': [[[x, y], ...], ...]}
    Returns a MultiLineString with SRID 4326, or None for empty/null input.
    """
    if not esri_geometry or not esri_geometry.get("paths"):
        return None

    paths = esri_geometry["paths"]
    if not paths:
        return None

    lines = []
    for path in paths:
        coords = [tuple(pt[:2]) for pt in path]
        if len(coords) < 2:
            continue
        lines.append(LineString(coords))

    if not lines:
        return None

    return MultiLineString(lines, srid=4326)


def geos_to_esri_geometry(geos_geometry):
    """Convert a GEOSGeometry to ArcGIS JSON geometry dict.

    Returns: {'rings': [[[x, y], ...], ...], 'spatialReference': {'wkid': 4326}}
    """
    geojson = json.loads(geos_geometry.geojson)
    rings = []

    if geojson["type"] == "MultiPolygon":
        for polygon_coords in geojson["coordinates"]:
            for ring in polygon_coords:
                rings.append([[pt[0], pt[1]] for pt in ring])
    elif geojson["type"] == "Polygon":
        for ring in geojson["coordinates"]:
            rings.append([[pt[0], pt[1]] for pt in ring])
    else:
        raise ValueError(f"Unsupported geometry type: {geojson['type']}")

    return {
        "rings": rings,
        "spatialReference": {"wkid": 4326},
    }
