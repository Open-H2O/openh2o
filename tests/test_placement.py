# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spatial-placement toolkit (Phase 51-01).

The named anti-pattern this guards: an operational feature (a diversion, a well,
a parcel) that floats in a field instead of sitting on the real river/canal it
belongs to — the same class of credibility bug as the recharge basin that
"swallowed half a city." 51-02 will place every real feature through these three
primitives, so a quiet bug here silently re-floats the entire demo.

Two subtleties make this easy to get wrong, and every test below exists to pin
one of them:

  1. Distance in EPSG:4326 is in DEGREES, not metres, and a degree of longitude
     shrinks with latitude. So every distance assertion measures in EPSG:3310
     (California Albers, true metres) via ``_metres`` — never raw-degree
     ``.distance()``. Fixtures sit at Merced latitude (~37.3 N) so the cos(lat)
     longitude compression is exercised exactly where 51-02 places real data.
  2. GEOS ``.project()`` / ``.interpolate()`` are defined on ``LineString``
     only. A ``Flowline.geometry`` is a ``MultiLineString``, so the snap helper
     must iterate the parts and pick the nearest — ``test_snap_multilinestring_
     picks_nearest_part`` builds a genuine 2-part geometry whose SECOND part is
     the near one, so a "just use the first part" bug fails.

Tests build geometries inline and use UNSAVED ``Flowline`` instances (no DB):
the toolkit is pure geometry, so no database round-trip is needed or wanted.
"""
import math

from django.contrib.gis.geos import LineString, MultiLineString, Point

from geography.models import Flowline
from geography.placement import (
    nearest_flowline,
    place_near_flowline,
    snap_to_flowline,
)

# Merced / Central Valley latitude so the cos(lat) longitude compression is
# real, matching where 51-02 places features.
LAT = 37.3
LON = -120.5
M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat):
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def _metres(a, b):
    """True-metre distance between two srid-4326 geometries via EPSG:3310."""
    return a.transform(3310, clone=True).distance(b.transform(3310, clone=True))


def _ew_line(lon=LON, lat=LAT, length_m=2000.0):
    """A west->east MultiLineString ``length_m`` true metres long at ``lat``."""
    dlon = length_m / _m_per_deg_lon(lat)
    return MultiLineString(
        LineString((lon, lat), (lon + dlon, lat), srid=4326), srid=4326
    )


def _flowline(geom, feature_type="river"):
    """An UNSAVED Flowline carrying ``geom`` — no DB needed for pure geometry."""
    return Flowline(geometry=geom, feature_type=feature_type)


# --------------------------------------------------------------------------
# nearest_flowline
# --------------------------------------------------------------------------
def test_nearest_returns_closest_line():
    near = _flowline(_ew_line(lat=LAT))
    far = _flowline(_ew_line(lat=LAT + 0.5))  # ~55 km north
    point = Point(LON, LAT + 0.001, srid=4326)  # ~111 m north of `near`
    assert nearest_flowline(point, [far, near]) is near


def test_nearest_feature_type_filter_returns_river_not_nearer_canal():
    # The geometrically nearest line is a canal; the river sits ~1.1 km away.
    canal = _flowline(_ew_line(lat=LAT), feature_type="canal")
    river = _flowline(_ew_line(lat=LAT + 0.01), feature_type="river")
    point = Point(LON, LAT, srid=4326)
    result = nearest_flowline(point, [canal, river], feature_type="river")
    assert result is river


def test_nearest_empty_returns_none():
    point = Point(LON, LAT, srid=4326)
    assert nearest_flowline(point, []) is None


# --------------------------------------------------------------------------
# snap_to_flowline
# --------------------------------------------------------------------------
def test_snap_offset_point_lands_on_line():
    line = _ew_line(length_m=2000.0)
    mid_lon = LON + 1000.0 / _m_per_deg_lon(LAT)
    offset_pt = Point(mid_lon, LAT + 200.0 / M_PER_DEG_LAT, srid=4326)  # ~200 m N
    snapped = snap_to_flowline(offset_pt, _flowline(line))
    assert _metres(snapped, line) < 1.0  # lands on the line
    assert _metres(snapped, offset_pt) > 100.0  # and it actually moved


def test_snap_multilinestring_picks_nearest_part():
    # Part 1 is far north; part 2 is the near one. A "first part" bug fails here.
    far = LineString((LON, LAT + 0.02), (LON + 0.01, LAT + 0.02), srid=4326)
    near = LineString((LON, LAT), (LON + 0.01, LAT), srid=4326)
    mls = MultiLineString(far, near, srid=4326)
    point = Point(LON + 0.005, LAT + 0.0005, srid=4326)  # ~55 m above `near`
    snapped = snap_to_flowline(point, _flowline(mls))
    # Snapped onto the near part (lat ~ LAT), not the far part (lat ~ LAT+0.02).
    assert abs(snapped.y - LAT) < abs(snapped.y - (LAT + 0.02))
    assert _metres(snapped, mls) < 1.0


def test_snap_point_already_on_line_returns_itself():
    line = _ew_line(length_m=2000.0)
    on_lon = LON + 800.0 / _m_per_deg_lon(LAT)
    on_pt = Point(on_lon, LAT, srid=4326)
    snapped = snap_to_flowline(on_pt, _flowline(line))
    assert _metres(snapped, on_pt) < 1.0


# --------------------------------------------------------------------------
# place_near_flowline
# --------------------------------------------------------------------------
def test_place_offset_distance_matches_within_tolerance():
    line = _ew_line(length_m=2000.0)
    point = place_near_flowline(_flowline(line), offset_m=300.0)
    dist = _metres(point, line)
    assert 0.85 * 300.0 <= dist <= 1.15 * 300.0  # ±15%
    assert dist > 0  # never on the line


def test_place_sides_are_opposite():
    flow = _flowline(_ew_line(length_m=2000.0))
    left = place_near_flowline(flow, offset_m=300.0, side=1)
    right = place_near_flowline(flow, offset_m=300.0, side=-1)
    midpoint = Point((left.x + right.x) / 2.0, (left.y + right.y) / 2.0, srid=4326)
    # Opposite banks: their midpoint is closer to the line than either point.
    assert _metres(midpoint, flow.geometry) < _metres(left, flow.geometry)
    assert _metres(midpoint, flow.geometry) < _metres(right, flow.geometry)


def test_place_along_picks_opposite_ends():
    flow = _flowline(_ew_line(length_m=2000.0))
    start = place_near_flowline(flow, offset_m=50.0, along=0.0)
    end = place_near_flowline(flow, offset_m=50.0, along=1.0)
    # Same side, opposite ends of a 2 km line -> ~2 km apart.
    assert _metres(start, end) > 1500.0


def test_place_is_deterministic():
    flow = _flowline(_ew_line(length_m=2000.0))
    a = place_near_flowline(flow, offset_m=120.0, along=0.4, side=1)
    b = place_near_flowline(flow, offset_m=120.0, along=0.4, side=1)
    assert a.equals_exact(b, 1e-12)  # no randomness
