# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link-driven recharge archetype + routing policy (Phase 52.6-01, ISS-053).

The single question that decides whether a unit of recharge becomes a *personal*
(recoverable) groundwater credit or flows to the GSA basin pool is "can this
parcel recover the water itself?" — answered entirely by the parcel's own links
(well / crop / surface). These tests pin the three archetypes (CONJUNCTIVE /
FLOOD_MAR / BASIN) and the personal-vs-pool routing predicate, including the
ISS-053 phantom case: MER-APN-031 is surface-only (a point of diversion, a crop,
no well) and must NEVER receive a personal groundwater credit it cannot pump.
"""
import pytest

from accounting.recharge_policy import (
    BASIN,
    CONJUNCTIVE,
    FLOOD_MAR,
    parcel_recharge_archetype,
    recharge_routes_to_personal,
)
from tests.factories import (
    ParcelFactory,
    PointOfDiversionParcelFactory,
    UsageLocationFactory,
    WellIrrigatedParcelFactory,
)


@pytest.mark.django_db
def test_parcel_with_well_is_conjunctive_and_routes_personal():
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    assert parcel_recharge_archetype(parcel) == CONJUNCTIVE
    assert recharge_routes_to_personal(parcel) is True


@pytest.mark.django_db
def test_parcel_with_crop_and_surface_no_well_is_flood_mar_and_routes_to_pool():
    parcel = ParcelFactory()
    UsageLocationFactory(parcel=parcel)
    PointOfDiversionParcelFactory(parcel=parcel)

    assert parcel_recharge_archetype(parcel) == FLOOD_MAR
    assert recharge_routes_to_personal(parcel) is False


@pytest.mark.django_db
def test_fallow_parcel_no_crop_no_well_is_basin_and_routes_to_pool():
    parcel = ParcelFactory()

    assert parcel_recharge_archetype(parcel) == BASIN
    assert recharge_routes_to_personal(parcel) is False


@pytest.mark.django_db
def test_crop_without_surface_or_well_never_routes_personal():
    # Robustness: a crop alone — no surface, no well — still must not earn a
    # personal credit. Routing keys on has_well only; odd link combinations
    # must never leak a parcel into the personal bucket without a well.
    parcel = ParcelFactory()
    UsageLocationFactory(parcel=parcel)

    assert recharge_routes_to_personal(parcel) is False


@pytest.mark.django_db
def test_mer_apn_031_shape_routes_to_pool_never_personal():
    # ISS-053 phantom case: 1 POD link, 0 wells, has a crop -> FLOOD_MAR.
    # The whole phase exists to make this parcel route to the basin pool.
    parcel = ParcelFactory(parcel_number="MER-APN-031")
    PointOfDiversionParcelFactory(parcel=parcel)
    UsageLocationFactory(parcel=parcel)

    assert parcel_recharge_archetype(parcel) == FLOOD_MAR
    assert recharge_routes_to_personal(parcel) is False


@pytest.mark.django_db
def test_routing_predicate_accepts_both_parcel_and_archetype_string():
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(parcel=parcel)

    # Accepts a bare archetype string (no DB hit needed)...
    assert recharge_routes_to_personal(CONJUNCTIVE) is True
    assert recharge_routes_to_personal(FLOOD_MAR) is False
    assert recharge_routes_to_personal(BASIN) is False

    # ...and a Parcel instance, which it classifies first.
    assert recharge_routes_to_personal(parcel) is True
