# SPDX-License-Identifier: AGPL-3.0-or-later
"""seed_merced_details fills the demo's descriptive detail fields.

The structural seeds leave well construction, parcel addresses, CalWATRS PINs,
account contacts, and the meters behind "Certified Meter" wells blank — so detail
pages render hollow sections. This command fills those gaps with deterministic,
fill-only-when-blank mock data, and mints display-only meters that do NOT touch
the accounting engine (which reads ledger meter_reading rows, not Meter objects).
"""
import pytest
from django.core.management import call_command

from accounting.models import WaterAccount
from measurements.models import Meter
from parcels.models import Parcel
from surface.models import WaterRight
from wells.models import Well, WellMeter

from tests.factories import (
    ParcelFactory,
    WaterAccountFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)


@pytest.fixture
def metered_well(db):
    parcel = ParcelFactory(owner_name="Merced Valley Farms LLC", address="")
    well = WellFactory(
        well_registration_id="MER-W-TEST1",
        measurement_method="certified_meter",
        owner_name="",
    )
    WellIrrigatedParcelFactory(well=well, parcel=parcel)
    return well, parcel


@pytest.mark.django_db
def test_fills_well_construction_section(metered_well):
    well, _ = metered_well
    call_command("seed_merced_details")
    well.refresh_from_db()
    # The whole DWR Well Completion Report section is now populated.
    assert well.depth_ft and well.casing_diameter_in
    assert well.casing_material and well.pump_type
    assert well.screen_top_ft and well.screen_bottom_ft
    assert well.tested_yield_gpm and well.capacity_gpm
    assert well.year_pumping_began
    assert well.wcr_number.startswith("E")
    assert well.state_well_number.endswith("M")
    # Screen interval sits inside the bore.
    assert well.screen_bottom_ft <= well.depth_ft
    # Owner is pulled from the irrigated parcel, not invented.
    assert well.owner_name == "Merced Valley Farms LLC"


@pytest.mark.django_db
def test_mints_a_display_meter_for_certified_meter_wells(metered_well):
    well, _ = metered_well
    call_command("seed_merced_details")
    meter = Meter.objects.get(serial_number="MTR-MER-W-TEST1")
    assert meter.status == "active" and meter.manufacturer
    link = WellMeter.objects.get(well=well, meter=meter)
    assert link.is_current is True


@pytest.mark.django_db
def test_no_meter_for_unmetered_wells(db):
    WellFactory(well_registration_id="MER-W-UNMET", measurement_method="et_method")
    call_command("seed_merced_details")
    assert not Meter.objects.exists()
    assert not WellMeter.objects.exists()


@pytest.mark.django_db
def test_fills_parcel_address_pin_and_contact(db):
    ParcelFactory(parcel_number="MER-APN-TEST", address="")
    WaterRightFactory(right_id="MER-WR-TEST", calwatrs_pin="")
    WaterAccountFactory(name="El Nido Irrigation", contact_name="Jane Operator",
                        contact_email="")
    call_command("seed_merced_details")
    assert "CA" in Parcel.objects.get(parcel_number="MER-APN-TEST").address
    assert WaterRight.objects.get(right_id="MER-WR-TEST").calwatrs_pin.startswith("P")
    assert WaterAccount.objects.get(
        name="El Nido Irrigation").contact_email.endswith("@example.com")


@pytest.mark.django_db
def test_idempotent_and_never_clobbers(metered_well):
    well, parcel = metered_well
    parcel.address = "Real address operator typed"
    parcel.save(update_fields=["address"])
    call_command("seed_merced_details")
    well.refresh_from_db()
    depth_first = well.depth_ft
    # Re-run: same deterministic values, no duplicate meter, real data untouched.
    call_command("seed_merced_details")
    well.refresh_from_db()
    parcel.refresh_from_db()
    assert well.depth_ft == depth_first
    assert Meter.objects.filter(serial_number="MTR-MER-W-TEST1").count() == 1
    assert WellMeter.objects.filter(well=well).count() == 1
    assert parcel.address == "Real address operator typed"
