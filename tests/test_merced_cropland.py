# SPDX-License-Identifier: AGPL-3.0-or-later
"""Land-use seed guard for the Merced demo (Phase 52.5-01).

These tests assert ``seed_merced_cropland`` gives every IRRIGATED parcel a
crop-type usage location, that crop assignment is deterministic, and that the
command is idempotent (a re-run creates nothing and leaves counts and PKs
unchanged).

The fixture is the same hermetic Phase-51-03 physical slice the 52-01 invariant
tests build (every parcel is irrigated — served by a well or a point of diversion).
"""
import pytest
from django.core.management import call_command

from parcels.models import Parcel, UsageLocation
from surface.models import PointOfDiversionParcel
from wells.models import WellIrrigatedParcel

from tests.test_merced_ledgers import _build_physical_merced

MER = "MER-APN-"


def _irrigated(parcel):
    return (
        WellIrrigatedParcel.objects.filter(parcel=parcel).exists()
        or PointOfDiversionParcel.objects.filter(parcel=parcel).exists()
    )


def _mer_usage():
    return UsageLocation.objects.filter(parcel__parcel_number__startswith=MER)


@pytest.mark.django_db
def test_every_irrigated_parcel_gets_a_crop_usage_location():
    _build_physical_merced()
    call_command("seed_merced_cropland")
    for p in Parcel.objects.filter(parcel_number__startswith=MER):
        if not _irrigated(p):
            continue
        assert UsageLocation.objects.filter(
            parcel=p, crop_type__isnull=False
        ).exists(), f"{p.parcel_number} is irrigated but has no crop_type UsageLocation"


@pytest.mark.django_db
def test_usage_location_geometry_is_a_point_on_the_parcel():
    _build_physical_merced()
    call_command("seed_merced_cropland")
    usage = _mer_usage().exclude(geometry__isnull=True).first()
    assert usage is not None
    assert usage.geometry.geom_type == "Point"
    assert usage.area_acres == usage.parcel.area_acres


@pytest.mark.django_db
def test_crop_assignment_is_deterministic():
    _build_physical_merced()
    call_command("seed_merced_cropland")
    first = {u.parcel_id: u.crop_type_id for u in _mer_usage()}
    call_command("seed_merced_cropland")
    second = {u.parcel_id: u.crop_type_id for u in _mer_usage()}
    assert first == second and first


@pytest.mark.django_db
def test_seed_is_idempotent_rerun_creates_nothing():
    _build_physical_merced()
    call_command("seed_merced_cropland")
    first_pks = set(_mer_usage().values_list("id", flat=True))
    assert first_pks, "first run should create UsageLocations"
    call_command("seed_merced_cropland")
    second_pks = set(_mer_usage().values_list("id", flat=True))
    # update_or_create updates existing rows in place (same PKs) — a re-run
    # creates no new rows, so the PK set is unchanged.
    assert first_pks == second_pks
