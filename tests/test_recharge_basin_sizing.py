# SPDX-License-Identifier: AGPL-3.0-or-later
"""Acreage-band guard for recharge spreading basins (Phase 50-03).

The named anti-pattern: the Kaweah seed built spreading-basin footprints with
``make_box(size=0.008)``, a fixed-degree box that is ~156 acres at Central
Valley latitude — applied uniformly regardless of a basin's real size, so a
basin that should read as a facility instead "swallows half a city," the most
visible tell that makes a domain expert distrust the whole map.

This test locks the fix in true projected area (EPSG:3310, California Albers
equal-area), NOT raw degrees (which are latitude-dependent and meaningless):

  - ``area_accurate_box`` returns a footprint whose true area matches the
    requested acreage within ±10% across Central Valley latitudes and basin
    sizes — proving the cos(lat) correction works. This is the primary guard:
    any basin built through the helper is correctly sized by construction.
  - Every seeded demo spreading basin sits inside a sane band. Real Central
    Valley spreading basins reach ~120 acres (per domain review), so the band
    ceiling is 130 — comfortably above legitimate basins, still below the
    ~156-acre fixed-degree bug it must catch.
"""
import pytest

from recharge.geometry import SQ_M_PER_ACRE, area_accurate_box
from recharge.models import RechargeSite

# Real Central Valley spreading basins reach ~120 acres; 130 clears legitimate
# basins while still catching the ~156-acre fixed-degree bug. The helper-area
# test above is the tighter guard; this is the gross-oversize backstop.
MAX_BASIN_ACRES = 130


def _true_acres(geom):
    """True footprint area in acres via an equal-area projection (EPSG:3310)."""
    return geom.transform(3310, clone=True).area / SQ_M_PER_ACRE


@pytest.mark.parametrize("lat", [35.0, 36.3, 37.13, 37.34, 38.5])
@pytest.mark.parametrize("acres", [18.0, 40.0, 85.0, 110.0])
def test_area_accurate_box_matches_requested_area(lat, acres):
    """The helper's true area matches the requested acreage within ±10%."""
    box = area_accurate_box(-120.5, lat, acres)
    measured = _true_acres(box)
    assert abs(measured - acres) / acres < 0.10, (
        f"area_accurate_box({acres} ac @ {lat}N) measured {measured:.1f} ac"
    )


@pytest.mark.django_db
def test_seeded_merced_basins_within_band():
    """Every seeded spreading basin has a true area inside the sane band."""
    from django.core.management import call_command

    call_command("seed_merced_recharge")

    basins = RechargeSite.objects.filter(site_type="spreading_basin")
    assert basins.count() >= 2, "expected the two real Merced basins"

    for basin in basins:
        assert basin.geometry is not None, f"{basin.name} has no footprint"
        acres = _true_acres(basin.geometry)
        assert 0 < acres <= MAX_BASIN_ACRES, (
            f"{basin.name} is {acres:.1f} ac — outside the "
            f"0 < acres <= {MAX_BASIN_ACRES} band (the anti-pattern is back?)"
        )


def test_fixed_degree_box_would_breach_the_band():
    """A naive fixed-degree footprint is out of band — proving the guard catches
    a regression to the anti-pattern without a manual edit-and-revert."""
    from django.contrib.gis.geos import MultiPolygon, Polygon

    # The retired seed anti-pattern: a square 0.008 degrees on a side, regardless
    # of latitude. Built inline so this guard owns its own fixture.
    cx, cy, half = -120.5, 37.0, 0.008 / 2
    ring = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    box = MultiPolygon(Polygon(ring))
    box.srid = 4326  # the inline box has no SRID; transform needs a source SRID
    acres = _true_acres(box)
    assert acres > MAX_BASIN_ACRES, (
        f"expected the fixed-degree box to breach the band; it was {acres:.1f} ac"
    )
