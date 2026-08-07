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
"""

import json
import logging
import math

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon

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
