"""
Reusable client for querying ArcGIS REST FeatureServer endpoints.

Handles pagination, rate limiting, retries, and geometry conversion
between ArcGIS JSON and Django GEOSGeometry formats.
"""

import json
import logging
import time

import requests
from django.contrib.gis.geos import MultiPolygon, Polygon

logger = logging.getLogger(__name__)


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
    Rate limits 0.5s between pages. Retries up to 3 times with
    exponential backoff on HTTP errors.
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

        # Retry with exponential backoff
        response = None
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=60)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(
                        "Request failed (attempt %d/3), retrying in %ds: %s",
                        attempt + 1,
                        wait,
                        exc,
                    )
                    time.sleep(wait)
                else:
                    logger.error("Request failed after 3 attempts: %s", exc)
                    raise

        data = response.json()

        if "error" in data:
            raise RuntimeError(
                f"ArcGIS API error: {data['error'].get('message', data['error'])}"
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
