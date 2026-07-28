# SPDX-License-Identifier: AGPL-3.0-or-later
"""GSA zones are keyed by NAME, so the Phase 97 rename had to migrate them.

``seed_merced_gsas`` writes with ``update_or_create(name=...)``. On a deployment
seeded before Phase 97 renamed the three GSAs, a plain rename would have CREATED
three new zones and left the three originals behind — still carrying the real
agency names the phase exists to remove, and still holding every ParcelZone,
well, recharge-site and carryover FK that points at them. Six zones, half of
them the defect, on a live public site.

``_rename_forward`` renames the existing row instead, matching on geometry
rather than on a table of the old names — writing those names into the source
to migrate off them would put a real public agency straight back in the repo.
"""
import json

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from core.management.commands.seed_merced_gsas import (
    BASIN_CODE,
    FIXTURE,
    _fixture_geometry,
    Command,
)
from geography.models import Boundary, Zone


def _features():
    with open(FIXTURE) as f:
        return json.load(f)["features"]


def _boundary():
    return Boundary.objects.create(
        name="Merced Subbasin",
        geometry=MultiPolygon(
            Polygon(((-121.0, 36.8), (-120.0, 36.8), (-120.0, 37.6),
                     (-121.0, 37.6), (-121.0, 36.8)))
        ),
    )


def _zone(name, geom, boundary):
    return Zone.objects.create(
        name=name, boundary=boundary, geometry=geom,
        zone_type="management_area", basin_code=BASIN_CODE,
    )


@pytest.mark.django_db
def test_renames_a_stale_zone_forward_and_keeps_its_primary_key():
    """The row is renamed in place, so every FK pointing at it survives."""
    features = _features()
    boundary = _boundary()
    stale = _zone("Some Retired GSA Name", _fixture_geometry(features[0]), boundary)

    Command()._rename_forward(features)

    stale.refresh_from_db()
    assert stale.name == features[0]["properties"]["GSA_Name"]
    assert Zone.objects.filter(zone_type="management_area").count() == 1


@pytest.mark.django_db
def test_reseeding_a_stale_database_lands_three_zones_not_six():
    """The whole point: a pre-rename deployment re-seeds to three, not six."""
    features = _features()
    boundary = _boundary()
    for i, ft in enumerate(features):
        _zone(f"Retired Identity {i}", _fixture_geometry(ft), boundary)

    Command()._rename_forward(features)

    assert sorted(Zone.objects.values_list("name", flat=True)) == sorted(
        ft["properties"]["GSA_Name"] for ft in features
    )
    assert Zone.objects.filter(basin_code=BASIN_CODE).count() == 3


@pytest.mark.django_db
def test_leaves_an_unrelated_zone_alone():
    """A zone whose footprint is not one of the three is never renamed onto them.

    Geometry is the identity proof; a zone somewhere else in the basin must fail
    it outright rather than being claimed by the nearest fixture feature.
    """
    features = _features()
    boundary = _boundary()
    elsewhere = _zone(
        "Neighbouring Agency",
        MultiPolygon(
            Polygon(((-120.05, 36.85), (-120.01, 36.85), (-120.01, 36.89),
                     (-120.05, 36.89), (-120.05, 36.85)))
        ),
        boundary,
    )

    Command()._rename_forward(features)

    elsewhere.refresh_from_db()
    assert elsewhere.name == "Neighbouring Agency"


@pytest.mark.django_db
def test_is_a_no_op_once_every_zone_already_matches():
    """Safe to leave in the seed: post-rename deployments hit nothing."""
    features = _features()
    boundary = _boundary()
    for ft in features:
        _zone(ft["properties"]["GSA_Name"], _fixture_geometry(ft), boundary)
    before = sorted(Zone.objects.values_list("id", "name"))

    Command()._rename_forward(features)

    assert sorted(Zone.objects.values_list("id", "name")) == before


@pytest.mark.django_db
def test_fixture_names_carry_no_real_agency_identity():
    """The committed fixture must never regain the real names, DWR IDs or URLs.

    The tripwire against a future session "restoring" the layer by re-fetching
    it from the SGMA portal, which would return the real agencies.
    """
    features = _features()
    for ft in features:
        props = ft["properties"]
        assert "Merced Subbasin GSA" not in props["GSA_Name"]
        assert "Turner Island" not in props["GSA_Name"]
        assert props["GSA_ID"] >= 9000, "real DWR GSA_IDs are back in the fixture"
        assert props["GSA_URL"] == "", "a real agency URL is back in the fixture"
