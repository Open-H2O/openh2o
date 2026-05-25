from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    RechargeEventFactory,
    RechargeSiteFactory,
    WaterRightFactory,
    WaterRightParcelFactory,
    ZoneFactory,
)


class TestRechargeSiteZoneFK:
    def test_nullable(self):
        site = RechargeSiteFactory(zone=None)
        site.refresh_from_db()
        assert site.zone is None

    def test_set_null_on_delete(self):
        zone = ZoneFactory()
        site = RechargeSiteFactory(zone=zone)
        zone.delete()
        site.refresh_from_db()
        assert site.zone is None


class TestWaterRightParcel:
    def test_unique_together(self):
        wr = WaterRightFactory()
        parcel = ParcelFactory()
        WaterRightParcelFactory(water_right=wr, parcel=parcel)
        with pytest.raises(IntegrityError):
            WaterRightParcelFactory(water_right=wr, parcel=parcel)

    def test_cascade_on_right_delete(self):
        from surface.models import WaterRightParcel

        link = WaterRightParcelFactory()
        link_id = link.id
        link.water_right.delete()
        assert not WaterRightParcel.objects.filter(id=link_id).exists()

    def test_cascade_on_parcel_delete(self):
        from surface.models import WaterRightParcel

        link = WaterRightParcelFactory()
        link_id = link.id
        link.parcel.delete()
        assert not WaterRightParcel.objects.filter(id=link_id).exists()


class TestParcelLedgerSourceType:
    def test_valid_source_types(self):
        from parcels.models import ParcelLedger

        valid_codes = {c[0] for c in ParcelLedger.SOURCE_TYPE_CHOICES}
        expected = {
            "meter_reading", "et_estimate", "manual_entry", "csv_import",
            "surface_diversion", "recharge", "allocation", "adjustment",
        }
        assert valid_codes == expected


class TestRechargeEventOrdering:
    def test_default_ordering(self):
        site = RechargeSiteFactory()
        old = RechargeEventFactory(recharge_site=site, start_date=date(2023, 1, 1))
        new = RechargeEventFactory(recharge_site=site, start_date=date(2024, 6, 1))

        from recharge.models import RechargeEvent

        events = list(RechargeEvent.objects.filter(recharge_site=site))
        assert events[0].pk == new.pk
        assert events[1].pk == old.pk


class TestDiversionRecordUniqueTogether:
    def test_enforced(self):
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod,
            month=date(2024, 3, 1),
            diversion_type="direct_use",
        )
        with pytest.raises(IntegrityError):
            DiversionRecordFactory(
                point_of_diversion=pod,
                month=date(2024, 3, 1),
                diversion_type="direct_use",
            )
