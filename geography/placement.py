# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spatial-placement toolkit: put operational features ON the real base layer.

WHY this exists. Phase 51 places diversions, wells, and parcels for the Merced
demo. The credibility test — the one a domain expert applies in the first three
seconds — is whether those features sit on the actual rivers and canals or
*float in a field*. (We failed this once already: a recharge basin sized in
fixed degrees "swallowed half a city.") These three pure functions are the guard
that 51-02 routes every feature through, so the rule lives in one tested place.

Three gotchas this module exists to handle correctly, so the next reader does
not reintroduce them:

  1. **Measure distance in metres, not degrees.** A coordinate here is
     EPSG:4326 (lon/lat degrees). ``.distance()`` between two 4326 geometries
     returns DEGREES, and a degree of longitude shrinks with latitude, so a
     degree-distance comparison is silently wrong. Every distance below is
     measured by transforming clones to EPSG:3310 (California Albers, equal
     distance/area, true metres) — the same CRS doctrine as
     ``recharge.geometry``. ``M_PER_DEG_LAT`` is imported from there so the
     cos(lat) conversion cannot drift between the two modules.

  2. **``.project()`` / ``.interpolate()`` are LineString-only.** A
     ``Flowline.geometry`` is a ``MultiLineString``. Calling those linear-
     referencing methods on a Multi* raises. So we iterate the constituent
     parts, compute a candidate on each, and keep the one nearest in true
     metres — never "just the first part."

  3. **The perpendicular offset is an approximation by construction.** It comes
     from a finite-difference local tangent converted through the cos(lat)
     metric, which is why ``place_near_flowline`` is specified to ±15%, not
     survey precision. It is for plausible placement, not surveying.

All functions are deterministic (no randomness): re-running the 51-02 seed
reproduces identical placements.
"""
import math

from django.contrib.gis.geos import Point

# Share the latitude conversion with recharge.geometry so the two cannot drift.
#
# Module scope is correct here and is NOT an ISS-072 defect, so do not "finish the
# job" by moving it. `recharge/geometry.py` imports `math` and
# `django.contrib.gis.geos` and defines no models, so this import succeeds whether
# or not `recharge` is in INSTALLED_APPS — the app_label RuntimeError that makes
# the other recharge imports load-bearing only fires for `recharge.models`.
# Relocating the constant into `geography` would be domain restructuring, which the
# v2.3 milestone explicitly forbids.
from recharge.geometry import M_PER_DEG_LAT

# California Albers — equal distance/area, metre units. The CRS we measure in.
MEASURE_SRID = 3310


def _m_per_deg_lon(lat):
    """Metres per degree of longitude at ``lat`` (the cos(lat) compression)."""
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def _to_measure(geom):
    """A clone of ``geom`` reprojected to EPSG:3310 (true metres)."""
    return geom.transform(MEASURE_SRID, clone=True)


def _parts(geom):
    """The LineString parts of ``geom`` (a MultiLineString OR a LineString).

    Each part is returned with the parent's SRID applied — a constituent pulled
    out of a MultiLineString does not always carry one, and ``.project`` /
    ``.transform`` need it set. Zero-length / single-vertex parts are dropped so
    callers never feed a degenerate part into linear referencing.
    """
    srid = geom.srid or 4326
    raw = list(geom) if geom.geom_type == "MultiLineString" else [geom]
    parts = []
    for part in raw:
        if part.empty or part.num_points < 2:
            continue
        if part.srid is None:
            part.srid = srid
        parts.append(part)
    return parts


def _nearest_part_point(point, geom):
    """Point on ``geom`` closest to ``point``, plus the part it landed on.

    Iterates the parts (MultiLineString-safe), takes each part's closest point
    via ``project``/``interpolate``, and keeps the candidate with the smallest
    TRUE-METRE distance to ``point``. Returns ``(None, None)`` if ``geom`` has
    no usable line part (degenerate geometry) so callers can fall back sanely.
    """
    point_m = _to_measure(point)
    best_pt = best_part = None
    best_d = None
    for part in _parts(geom):
        along = part.project(point)  # distance along the part (degrees)
        cand = part.interpolate(along)  # the point on the part
        cand.srid = point.srid or 4326
        d = _to_measure(cand).distance(point_m)
        if best_d is None or d < best_d:
            best_d, best_pt, best_part = d, cand, part
    return best_pt, best_part


def nearest_flowline(point, flowlines, feature_type=None):
    """Return the ``Flowline`` closest to ``point``, or ``None`` if none qualify.

    ``point`` is a GEOS ``Point`` (srid 4326). ``flowlines`` is any iterable /
    QuerySet of ``Flowline``. Distance is the minimum true-metre distance
    (EPSG:3310) from ``point`` to each flowline's geometry. When ``feature_type``
    is given, only flowlines of exactly that type are considered — so asking for
    the nearest river never returns a nearer canal. Empty candidate set (or all
    filtered out) returns ``None``; 51-02 turns that into a clear
    "base layer not seeded" error.
    """
    point_m = _to_measure(point)
    best = None
    best_d = None
    for flowline in flowlines:
        if feature_type is not None and flowline.feature_type != feature_type:
            continue
        d = _to_measure(flowline.geometry).distance(point_m)
        if best_d is None or d < best_d:
            best_d, best = d, flowline
    return best


def snap_to_flowline(point, flowline):
    """Return the point ON ``flowline.geometry`` closest to ``point`` (srid 4326).

    MultiLineString-safe: it snaps onto the nearest constituent part, not the
    first one. The returned point's true-metre distance to the geometry is ~0
    (well under a metre, allowing for projection/float epsilon). If the geometry
    is degenerate (no usable line part) the input ``point`` is returned unchanged
    rather than raising.
    """
    snapped, _ = _nearest_part_point(point, flowline.geometry)
    return snapped if snapped is not None else point


def place_near_flowline(flowline, offset_m, along=0.5, side=1):
    """A point ``offset_m`` true metres off ``flowline.geometry`` (srid 4326).

    Places a feature a plausible distance off a river/canal: at fractional
    position ``along`` (0..1) of the representative part, offset perpendicular to
    the local channel direction. ``side`` (+1 / -1) chooses the bank, so callers
    can fan parcels onto both sides. Deterministic: same args -> same point.

    The perpendicular comes from a finite-difference local tangent converted
    through the cos(lat) metric, so the realized offset is approximate (the
    toolkit's tests allow ±15%); the point is always strictly off the line,
    never on it. Returns a representative vertex (or ``None`` for a truly empty
    geometry) if no usable line part exists, rather than raising.
    """
    parts = _parts(flowline.geometry)
    if not parts:
        return None
    # Representative part = the longest in true metres (the main channel),
    # so the result is deterministic and uses the dominant geometry.
    part = max(parts, key=lambda p: _to_measure(p).length)
    length = part.length  # in degrees (linear-referencing units)
    along = min(max(along, 0.0), 1.0)
    here = along * length
    base = part.interpolate(here)
    base.srid = part.srid or 4326

    # Local tangent from two interpolated points a small delta apart.
    delta = length * 1e-2
    d1 = max(0.0, here - delta / 2.0)
    d2 = min(length, here + delta / 2.0)
    p1 = part.interpolate(d1)
    p2 = part.interpolate(d2)

    # Convert the tangent into a local metre-space (east, north) before rotating
    # 90°, so the perpendicular is true-perpendicular on the ground, not in
    # latitude-distorted degree space.
    lat = base.y
    m_per_deg_lon = _m_per_deg_lon(lat)
    tx_m = (p2.x - p1.x) * m_per_deg_lon
    ty_m = (p2.y - p1.y) * M_PER_DEG_LAT
    norm = math.hypot(tx_m, ty_m)
    if norm == 0:
        # Degenerate tangent (coincident vertices): offset due east as a
        # sane, deterministic fallback rather than raising.
        ux, uy = 1.0, 0.0
    else:
        ux, uy = tx_m / norm, ty_m / norm
    # Rotate the unit tangent 90°; ``side`` picks which bank.
    perp_x, perp_y = -uy * side, ux * side

    # Metre offset -> degrees, longitude corrected for latitude.
    off_lon = (perp_x * offset_m) / m_per_deg_lon
    off_lat = (perp_y * offset_m) / M_PER_DEG_LAT
    return Point(base.x + off_lon, base.y + off_lat, srid=base.srid)
