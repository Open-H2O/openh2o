# SPDX-License-Identifier: AGPL-3.0-or-later
"""Acreage-band guard for recharge spreading basins (Phase 50-03).

The named anti-pattern: the Kaweah seed built spreading-basin footprints with
``make_box(size=0.008)``, a fixed-degree box that is ~150-190 acres at Central
Valley latitude — about ten times the size of a real Merced spreading basin
(~18-20 acres). An oversized basin "swallowing half a city" is the most visible
tell that makes a domain expert distrust the whole map.

This test locks the fix in true projected area (EPSG:3310, California Albers
equal-area), NOT raw degrees (which are latitude-dependent and meaningless):

  - ``area_accurate_box`` returns a footprint whose true area matches the
    requested acreage within ±10% across Central Valley latitudes — proving the
    cos(lat) correction works.
  - Every seeded demo spreading basin sits inside a sane band (0 < acres ≤ 50).
  - The retired fixed-degree box would BREACH that band — so if anyone
    re-introduces it, the suite goes red.
"""
import pytest

from recharge.geometry import SQ_M_PER_ACRE, area_accurate_box
from recharge.models import RechargeSite

# Real Central Valley spreading basins run tens of acres; 50 is a generous
# ceiling that still catches the ~156-acre fixed-degree bug by a wide margin.
MAX_BASIN_ACRES = 50


def _true_acres(geom):
    """True footprint area in acres via an equal-area projection (EPSG:3310)."""
    return geom.transform(3310, clone=True).area / SQ_M_PER_ACRE


@pytest.mark.parametrize("lat", [35.0, 36.3, 37.13, 37.34, 38.5])
@pytest.mark.parametrize("acres", [18.0, 20.0, 40.0])
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
    """The retired make_box(0.008) footprint is out of band — proving the guard
    catches a regression to the anti-pattern without a manual edit-and-revert."""
    from core.management.commands.seed_kaweah import make_box

    box = make_box(-120.5, 37.0, size=0.008)
    box.srid = 4326  # make_box does not set one; transform needs a source SRID
    acres = _true_acres(box)
    assert acres > MAX_BASIN_ACRES, (
        f"expected the fixed-degree box to breach the band; it was {acres:.1f} ac"
    )
