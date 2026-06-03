# SPDX-License-Identifier: AGPL-3.0-or-later
"""Area-accurate geometry helpers for recharge facilities.

The naive ``make_box(size=0.008)`` in the Kaweah seed builds a basin footprint
from a fixed number of DEGREES. At Central Valley latitude (~37 N) that is a
~0.5-mile square ≈ 150-190 acres — roughly ten times too large for a real
Merced Irrigation District spreading basin (~18-20 acres). Two things make a
fixed-degree box wrong:

  1. It encodes *size in degrees*, not on the ground, so the same number means
     a different acreage everywhere.
  2. A degree of longitude shrinks with latitude (the cos(lat) compression), so
     a "square" in degrees is a rectangle on the ground.

``area_accurate_box`` instead takes a TARGET ACREAGE, converts it to a side
length in true ground metres, and converts that back to degrees per-axis with
the longitude corrected for latitude. Measured in an equal-area projection
(EPSG:3310, California Albers) the footprint matches the requested acreage to
within ~1-2%. This is the guard against the "recharge basin swallowing half a
city" anti-pattern.
"""
import math

from django.contrib.gis.geos import MultiPolygon, Polygon

# US survey acre. Matches the divisor the sizing test transforms area through.
SQ_M_PER_ACRE = 4046.8564224
# Metres per degree of latitude (very nearly constant; the WGS84 mean).
M_PER_DEG_LAT = 111_320.0


def area_accurate_box(cx, cy, acres, srid=4326):
    """Return a square ``MultiPolygon`` centred on (cx, cy) of ~``acres`` acres.

    ``cx`` / ``cy`` are longitude / latitude in degrees. The box is sized in
    true ground metres, then converted back to degrees per axis so longitude is
    corrected for the cos(latitude) compression. Transformed to an equal-area
    projection the footprint matches ``acres`` to within a couple of percent —
    not a fixed degree size that balloons with latitude.
    """
    side_m = math.sqrt(acres * SQ_M_PER_ACRE)
    half_m = side_m / 2.0
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(cy))
    half_lat = half_m / M_PER_DEG_LAT
    half_lon = half_m / m_per_deg_lon
    ring = [
        (cx - half_lon, cy - half_lat),
        (cx + half_lon, cy - half_lat),
        (cx + half_lon, cy + half_lat),
        (cx - half_lon, cy + half_lat),
        (cx - half_lon, cy - half_lat),
    ]
    return MultiPolygon(Polygon(ring), srid=srid)
