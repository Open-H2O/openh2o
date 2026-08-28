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


class ArcGISTraversalError(RuntimeError):
    """A traversal that ended part-way through, carrying its resume key.

    ``last_oid`` is the last OBJECTID this generator successfully yielded before
    the failure, or None when the features carried no OID field. When it is
    known, ``str()`` ends with a paste-ready ``--resume-from`` hint, which is
    what makes the cheap resume shape work: ``auto_populate.handle()`` already
    prints the exception text, so the hint reaches the operator with no second
    reporting path and nothing stored anywhere.

    The hint is attached ONLY where resuming can actually help — an exhausted
    retry budget. A non-retryable error code means the query itself is wrong, so
    resuming would fail in exactly the same place; promising otherwise would be
    the same kind of false promise this phase exists to remove.
    """

    def __init__(self, message, last_oid=None):
        self.last_oid = last_oid
        if last_oid is not None:
            message = f"{message} — resume with --resume-from {last_oid}"
        super().__init__(message)


def _validated_resume_key(value):
    """Return ``value`` as an int, or raise ValueError.

    This is the one boundary in this module where hostile input matters: the
    resume key is string-interpolated into a ``where`` expression sent to a
    remote service, while everything else in that clause is a literal or a
    caller-supplied constant.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"resume_from must be an integer OBJECTID, got {value!r}."
        ) from None


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
    resume_from=None,
    oid_field="OBJECTID",
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
    raises ArcGISTraversalError naming it, carrying the last OBJECTID yielded so
    the traversal can be restarted from there rather than from zero.

    An empty page ends the traversal only when the service also stops setting
    ``exceededTransferLimit``. An empty page that still claims there is more is
    treated as a retryable failure, because taking it at face value silently
    truncates the import and reports success.

    ``resume_from`` is an OBJECTID to start after. It is COMPOSED onto any
    existing ``where`` (never replacing it) as ``(<where>) AND <oid_field> >
    <resume_from>``, and the results are ordered by the OID field ascending so
    "after N" means the same thing on every page.

    ``oid_field`` defaults to "OBJECTID" because that is the measured-correct
    answer for every service this repository calls, and that is why the code does
    not go and discover it. All four captured service descriptions —
    LightBox parcels, 3DHP flowlines, B118 basins and TIGERweb counties — list
    exactly one field of type ``esriFieldTypeOID`` and it is named OBJECTID in
    all four; but only B118 publishes an ``objectIdField`` key in its layer
    metadata, so reading that key would work on B118 and break on the other
    three. A plain parameter with a measured default beats a metadata round-trip
    that is wrong three times out of four.
    """
    if resume_from is not None:
        resume_from = _validated_resume_key(resume_from)

    # Always request the OID field, so a failure can always name a resume key.
    # out_fields="*" already returns it; a specific field list has to ask.
    # Callers read named attribute keys and ignore extras, so this is additive.
    if out_fields != "*":
        requested = [f.strip() for f in str(out_fields).split(",")]
        if oid_field not in requested:
            out_fields = f"{out_fields},{oid_field}"

    # Compose, never overwrite: load_counties.py really does pass its own
    # `where` (STATE='<fips>'), so replacing it would silently widen that import
    # to every county in the country.
    effective_where = where
    order_by_fields = None
    if resume_from is not None:
        effective_where = f"({where}) AND {oid_field} > {resume_from}"
        order_by_fields = f"{oid_field} ASC"

    offset = 0
    page_num = 0
    last_oid = None

    while True:
        params = {
            "where": effective_where,
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
        if order_by_fields is not None:
            params["orderByFields"] = order_by_fields

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
                    if data.get("features") or not data.get(
                        "exceededTransferLimit", False
                    ):
                        break  # the only success path

                    # An empty page is the traversal's terminator ONLY when the
                    # service also agrees there is nothing more. Measured
                    # 2026-08-28 against the live LightBox service: while it was
                    # degraded it answered this query with ZERO features and
                    # exceededTransferLimit STILL TRUE, on a where-clause that
                    # returnCountOnly put at 57,290 rows. Taking that as the end
                    # of the traversal is how an import reports "Done. 0
                    # record(s)" and exit 0 having read nothing at all — the
                    # exact silent undercount every other guard in this module
                    # exists to prevent. Retry it; if it persists, fail loudly
                    # and carry the resume key out.
                    last_failure = (
                        "the service returned an empty page while still "
                        "reporting exceededTransferLimit=true"
                    )
                    logger.warning(
                        "ArcGIS returned an empty page but says there is more "
                        "(attempt %d/%d, offset %d)",
                        attempt + 1,
                        MAX_ATTEMPTS,
                        offset,
                    )
                    if attempt < MAX_ATTEMPTS - 1:
                        time.sleep(_backoff_seconds(attempt))
                    continue

                if isinstance(error, dict):
                    code = error.get("code")
                    message = error.get("message", error)
                else:
                    code = None
                    message = error

                if code not in RETRYABLE_ARCGIS_ERROR_CODES:
                    # Ours, not the network's: a bad field name or a malformed
                    # `where`. Fail fast and legibly — no sleep, no second try.
                    raise ArcGISTraversalError(
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
            raise ArcGISTraversalError(
                f"ArcGIS query failed after {MAX_ATTEMPTS} attempts "
                f"(offset {offset}): {last_failure}",
                last_oid=last_oid,
            )

        features = data.get("features", [])
        page_num += 1
        logger.info(
            "Page %d: %d features (offset %d)", page_num, len(features), offset
        )

        if not features:
            break

        # The resume key: the last OBJECTID this page carried. Tolerate its
        # absence — a page whose features have no OID leaves last_oid as it was
        # and simply produces no hint. A missing OID must never turn a
        # recoverable failure into a different failure.
        last_attributes = (features[-1] or {}).get("attributes") or {}
        page_last_oid = last_attributes.get(oid_field)
        if page_last_oid is not None:
            last_oid = page_last_oid

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
