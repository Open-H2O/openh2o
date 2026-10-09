# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared GeoJSON-boundary parsing (ISS-122).

Moved out of ``setup/views.py`` (Phase 118 and earlier), where it was the
setup wizard's own private upload logic and the ONLY code in the whole
codebase that could turn an operator's own GeoJSON file into a ``Boundary``
row. ``geography.management.commands.auto_populate`` only ever RESOLVES an
existing ``Boundary`` by name or pk — it never creates one — so a headless
operator (no browser, SSH only) following ``docs/AI-OPERATOR-GUIDE.md``'s own
"Only a basin boundary" row had no way to load one at all. This module is the
one implementation the wizard (``setup/views.py``) and the new
``import_boundary`` management command both call, so a file behaves
identically no matter which path loads it.

Since 150-03 (ISS-200) the wizard reads a file through ``boundary_from_upload``,
which takes a zipped shapefile or a KML as well as GeoJSON (the readers live in
``core/geofiles.py``); a GeoJSON file still goes through
``boundary_from_geojson_text``, which ``import_boundary`` keeps calling.
"""

import json
import logging
import math

from django.contrib.gis.gdal import GDALException
from django.contrib.gis.geos import (
    GeometryCollection,
    GEOSException,
    GEOSGeometry,
    MultiPolygon,
    Polygon,
)

from core.geofiles import (
    GEOJSON_EXTENSIONS,
    THREE_FORMATS,
    check_upload_size,
    extension,
    features_from_upload,
)

logger = logging.getLogger(__name__)

# Property keys that real exports use for the same figure, in priority order.
# The USGS Watershed Boundary Dataset writes them lowercase, ArcGIS exports
# frequently write them uppercase, and hand-built files use underscores — so
# every key is reduced to its letters and digits before it is looked up.
_AREA_SQ_MI_KEYS = ("areasqmi", "areasqmiles", "sqmi")
_AREA_SQ_KM_KEYS = ("areasqkm", "areasqkilometers", "sqkm")
_HUC_KEYS = ("huc8", "huc", "huc12", "huccode")
_BASIN_CODE_KEYS = ("basincode", "basin")

SQ_KM_TO_SQ_MI = 0.386102158542

# Boundary.huc and Boundary.basin_code are both CharField(max_length=20).
_CODE_MAX_LENGTH = 20


def feature_properties(geojson) -> dict:
    """
    The properties dict for whichever shape ``parse_geojson_boundary`` accepted.

    FeatureCollection → the first feature's properties (the same feature whose
    geometry becomes the boundary); Feature → its own; a raw geometry carries
    none. Anything that isn't a dict is treated as no properties at all.
    """
    if not isinstance(geojson, dict):
        return {}

    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        features = geojson.get("features") or []
        first = features[0] if features else None
        properties = first.get("properties") if isinstance(first, dict) else None
    elif gtype == "Feature":
        properties = geojson.get("properties")
    else:
        properties = None

    return properties if isinstance(properties, dict) else {}


def _normalise_property_keys(properties: dict) -> dict:
    """Re-key ``properties`` by lowercase letters-and-digits, first key wins."""
    normalised = {}
    for key, value in properties.items():
        if not isinstance(key, str):
            continue
        slug = "".join(char for char in key.lower() if char.isalnum())
        if slug and slug not in normalised:
            normalised[slug] = value
    return normalised


def _positive_number(value):
    """
    ``value`` as a positive finite float, or None if it is anything else.

    The file is operator-supplied and unvalidated, so a property may be a dict,
    a list, "N/A", or a boolean. ``bool`` is rejected explicitly because
    ``isinstance(True, int)`` is True in Python and True must never become an
    area of 1.0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _short_code(value):
    """
    ``value`` as a stripped code string, or None if it is unusable.

    An integer is accepted because a HUC read as a number is still a HUC (it
    has merely lost any leading zero, which is not this function's to restore).
    The result is truncated to the column width so an absurd value leaves the
    field short rather than raising on save.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    code = value.strip()
    return code[:_CODE_MAX_LENGTH] if code else None


def boundary_attrs_from_properties(properties: dict) -> dict:
    """
    Boundary field values the uploaded file's own properties can supply.

    Returns only the keys it could actually resolve, so an unreadable file
    yields ``{}`` and ``Boundary.objects.create`` behaves exactly as it would
    with no properties at all.

    The square-kilometre fallback is in scope and the geometry is not:
    converting the file's own km² figure still displays the district's number,
    whereas an area computed from the polygon would be a number OpenH2O
    invented (decided 2026-08-05).
    """
    if not isinstance(properties, dict):
        return {}

    values = _normalise_property_keys(properties)
    attrs = {}

    area = None
    for key in _AREA_SQ_MI_KEYS:
        area = _positive_number(values.get(key))
        if area is not None:
            break
    if area is None:
        for key in _AREA_SQ_KM_KEYS:
            square_km = _positive_number(values.get(key))
            if square_km is not None:
                area = square_km * SQ_KM_TO_SQ_MI
                break
    if area is not None:
        attrs["area_sq_miles"] = area

    for field, keys in (("huc", _HUC_KEYS), ("basin_code", _BASIN_CODE_KEYS)):
        for key in keys:
            code = _short_code(values.get(key))
            if code is not None:
                attrs[field] = code
                break

    return attrs


def parse_geojson_boundary(geojson: dict):
    """
    Extract a MultiPolygon GEOSGeometry from a GeoJSON dict.
    Accepts Feature, FeatureCollection (first feature), or raw geometry.

    Raises ``ValueError`` with a specific, plain-language reason when no valid
    polygon can be extracted, so the wizard can tell the operator exactly what
    was wrong (empty collection vs. wrong geometry type vs. unreadable
    coordinates) instead of one generic failure.

    **Validity repair (ISS-122).** An invalid polygon (most often a
    self-intersecting ring) stored straight into the database breaks spatial
    queries downstream — ``ST_Intersects``/``ST_Within`` and friends can raise
    or silently return the wrong answer against an invalid geometry. Until
    this was added here, the wizard's upload path stored whatever the file
    contained, invalid or not, while
    ``core/management/commands/seed_merced_base.py`` repaired its own fixture
    with ``buffer(0)`` before saving. The same uploaded file therefore behaved
    differently depending on which of the two loading paths it went through.
    ``buffer(0)`` is applied here — the same GEOS self-repair trick the Merced
    seeder uses — so every caller of this function gets the same, valid
    geometry regardless of which path called it. srid stays 4326 throughout.
    """
    if not isinstance(geojson, dict):
        raise ValueError(
            "That file isn't a GeoJSON object — expected a Feature, "
            "FeatureCollection, or geometry."
        )

    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError(
                "The GeoJSON FeatureCollection is empty — it has no features to "
                "use as a boundary."
            )
        geom_dict = features[0].get("geometry")
    elif gtype == "Feature":
        geom_dict = geojson.get("geometry")
    else:
        geom_dict = geojson  # raw geometry

    if geom_dict is None:
        raise ValueError(
            "No geometry found in the file. Provide a GeoJSON Feature or "
            "FeatureCollection whose feature has Polygon or MultiPolygon geometry."
        )

    geom_type = geom_dict.get("type", "")
    if geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            f"The boundary geometry is a {geom_type or 'unknown type'}, but a "
            "Polygon or MultiPolygon is required — upload an area outline (your "
            "district), not a point or line."
        )

    try:
        geos = GEOSGeometry(json.dumps(geom_dict), srid=4326)
    except Exception:
        logger.exception("GEOSGeometry parse failed")
        raise ValueError(
            "The geometry couldn't be read as a valid polygon. Check the "
            "coordinates are WGS84 longitude/latitude pairs (EPSG:4326)."
        )

    if isinstance(geos, Polygon):
        geos = MultiPolygon(geos, srid=4326)
    elif isinstance(geos, MultiPolygon):
        pass
    else:
        raise ValueError(
            f"The geometry parsed as {geos.geom_type}, but a Polygon or "
            "MultiPolygon is required."
        )

    if not geos.valid:
        # Repair self-intersections rather than store an invalid geometry that
        # would break spatial queries downstream — mirrors
        # seed_merced_base.py:85-90.
        geos = geos.buffer(0)
        if geos.geom_type == "Polygon":
            geos = MultiPolygon(geos)
        geos.srid = 4326

    return geos


def boundary_from_geojson_text(raw_text, *, fallback_name):
    """Parse uploaded GeoJSON text into (name, geometry, attrs).

    Shared by the setup wizard's upload branch (``setup/views.py``) and the
    ``import_boundary`` management command (ISS-122) — before this, the
    wizard held the only code able to build a ``Boundary`` from an operator's
    own file, so a headless deployment had no equivalent. Both callers now go
    through this one implementation, so an upload behaves identically whether
    it came in through a browser or `import_boundary --file`.

    ``raw_text`` is the file's raw bytes, exactly as read from disk or from
    the upload — decoding it to text and then parsing it as JSON are both
    done here, in that order, matching what the wizard's upload view used to
    do inline before this function existed. ``UnicodeDecodeError``,
    ``json.JSONDecodeError`` and ``ValueError`` (raised by
    ``parse_geojson_boundary`` for a structurally bad GeoJSON document) all
    propagate uncaught — each caller carries its own operator-facing wording
    for these, so this function deliberately raises the bare exceptions
    rather than choosing text for either audience.

    The name follows the same precedence the wizard has always used: the
    GeoJSON document's own top-level ``name``, then the first feature's
    ``name`` property, then the caller's ``fallback_name`` (the wizard passes
    the uploaded filename; the command passes ``--name`` or the file's stem).
    """
    decoded = raw_text.decode("utf-8")
    geojson = json.loads(decoded)
    geom = parse_geojson_boundary(geojson)
    properties = feature_properties(geojson)
    name = (
        geojson.get("name")
        or properties.get("name")
        or fallback_name
    )
    return name or "Uploaded Boundary", geom, boundary_attrs_from_properties(properties)


NO_POLYGON_SENTENCE = (
    "That file holds no polygon, only points or lines. The boundary must be an "
    f"area outline, in {THREE_FORMATS}."
)


def _two_dimensional(coordinates):
    """``coordinates`` with every position cut to longitude and latitude.

    GDAL reads a KML position as (lon, lat, altitude), and ``Boundary.geometry``
    is a 2D column, so the altitude is dropped before GEOS ever sees it.
    """
    if coordinates and isinstance(coordinates[0], (int, float)):
        return list(coordinates[:2])
    return [_two_dimensional(part) for part in coordinates]


def _feature_name(properties) -> str:
    """The feature's own name, whatever the case of its key (KML writes ``Name``)."""
    if not isinstance(properties, dict):
        return ""
    value = _normalise_property_keys(properties).get("name")
    return value.strip() if isinstance(value, str) else ""


def _polygons_of(geom_dict):
    """The Polygon parts of one feature geometry, 2D, each repaired if invalid."""
    flat = dict(geom_dict, coordinates=_two_dimensional(geom_dict.get("coordinates") or []))
    try:
        geos = GEOSGeometry(json.dumps(flat), srid=4326)
    except (GDALException, GEOSException, ValueError, TypeError):
        logger.exception("GEOSGeometry parse failed")
        raise ValueError(
            "A polygon in the file could not be read. Check that the file opens "
            "in a GIS program, then upload it again."
        )
    parts = [geos] if isinstance(geos, Polygon) else list(geos)
    repaired = []
    for part in parts:
        if not part.valid:
            part = part.buffer(0)
        repaired.append(part)
    return parts, repaired


def _within_longitude_latitude(geom) -> bool:
    xmin, ymin, xmax, ymax = geom.extent
    return -180 <= xmin <= xmax <= 180 and -90 <= ymin <= ymax <= 90


def boundary_from_upload(uploaded_file, *, fallback_name):
    """Build a boundary from an uploaded map file: (name, geometry, attrs, polygon_count).

    The Setup Wizard's one door for a file (150-03, ISS-200). A GeoJSON file
    (``.geojson`` / ``.json``) goes through ``boundary_from_geojson_text``
    exactly as it always has, so its name, geometry, attrs and error sentences
    are unchanged; its ``polygon_count`` is the number of polygons in the
    boundary it gives.

    A zipped shapefile or a KML is read by ``core.geofiles.features_from_upload``
    (the bulk importer's own readers, with their size and archive guards).
    Every Polygon and MultiPolygon is kept and every point and line dropped;
    the reader has already reprojected a layer whose .prj names another
    projection to EPSG:4326. The boundary is the dissolved union of every
    polygon, one MultiPolygon in srid 4326, repaired with ``buffer(0)`` as
    ``parse_geojson_boundary`` repairs; ``polygon_count`` is the number of
    polygons combined. The name is the first polygon feature's name, else
    ``fallback_name``; attrs come from that feature's properties.

    Raises ``ValueError`` (plain words) or ``ImportError`` (the archive
    guards' own sentence); the GeoJSON path also lets ``UnicodeDecodeError``
    and ``json.JSONDecodeError`` through for the caller to word.
    """
    if extension(getattr(uploaded_file, "name", "")) in GEOJSON_EXTENSIONS:
        check_upload_size(uploaded_file)
        name, geom, attrs = boundary_from_geojson_text(
            uploaded_file.read(), fallback_name=fallback_name,
        )
        return name, geom, attrs, geom.num_geom

    features = features_from_upload(uploaded_file)

    first_properties = None
    polygon_count = 0
    parts = []
    for feature in features:
        geom_dict = feature.get("geometry")
        if not isinstance(geom_dict, dict):
            continue
        if geom_dict.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        originals, repaired = _polygons_of(geom_dict)
        polygon_count += len(originals)
        parts.extend(repaired)
        if first_properties is None:
            first_properties = feature.get("properties") or {}

    if not parts:
        raise ValueError(NO_POLYGON_SENTENCE)

    try:
        union = GeometryCollection(*parts, srid=4326).unary_union
    except GEOSException:
        logger.exception("Polygon union failed")
        raise ValueError(
            "The polygons in the file could not be combined into one boundary. "
            "Check that the file opens in a GIS program, then upload it again."
        )

    if union.empty or union.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(NO_POLYGON_SENTENCE)
    if union.geom_type == "Polygon":
        union = MultiPolygon(union, srid=4326)
    if not union.valid:
        union = union.buffer(0)
        if union.geom_type == "Polygon":
            union = MultiPolygon(union)
    union.srid = 4326

    if not _within_longitude_latitude(union):
        raise ValueError(
            "The coordinates in this file are not longitude and latitude, and "
            "the file does not say which projection they are in. For a "
            "shapefile, include its .prj file in the zip."
        )

    name = _feature_name(first_properties) or fallback_name
    attrs = boundary_attrs_from_properties(first_properties)
    return name or "Uploaded Boundary", union, attrs, polygon_count


def parse_extent_bounds(north, south, east, west):
    """Parse and range-check four typed extent corners (ISS-178).

    Returns ``(north, south, east, west)`` as floats, or raises ``ValueError``
    with a plain-language reason, the same contract ``parse_geojson_boundary``
    gives the upload card, so the wizard's typed-extent form can render a form
    error instead of a 500 on a bad or out-of-range value.
    """
    try:
        north = float(north)
        south = float(south)
        east = float(east)
        west = float(west)
    except (TypeError, ValueError):
        raise ValueError(
            "North, south, east and west must all be numbers, in decimal degrees."
        )

    for label, value in (("North", north), ("South", south)):
        if not math.isfinite(value) or not -90 <= value <= 90:
            raise ValueError(f"{label} must be a latitude between -90 and 90 degrees.")
    for label, value in (("East", east), ("West", west)):
        if not math.isfinite(value) or not -180 <= value <= 180:
            raise ValueError(f"{label} must be a longitude between -180 and 180 degrees.")
    if north <= south:
        raise ValueError("North must be greater than south.")
    if east <= west:
        raise ValueError("East must be greater than west.")

    return north, south, east, west


def boundary_from_extent(*, north, south, east, west, name):
    """Build a rectangle ``Boundary`` geometry from four typed corners (ISS-178).

    Goes through ``parse_geojson_boundary``, the same validity-repair and
    SRID-4326 path ``boundary_from_geojson_text`` (the upload card) uses, so
    a typed extent and an uploaded file give a ``Boundary.geometry`` with
    identical guarantees. The caller is expected to have already validated
    the four corners with ``parse_extent_bounds``; this function does not
    re-check their ranges.
    """
    polygon = Polygon.from_bbox((west, south, east, north))
    geom = parse_geojson_boundary(json.loads(polygon.geojson))
    return name or "Typed extent", geom, {}
