import factory
from datetime import date
from decimal import Decimal

from django.contrib.gis.geos import MultiPolygon, Point, Polygon


def _box(cx=-119.5, cy=36.5, size=0.01):
    half = size / 2
    ring = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


class BoundaryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "geography.Boundary"

    name = factory.Sequence(lambda n: f"Boundary {n}")
    geometry = factory.LazyFunction(_box)


class ZoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "geography.Zone"

    name = factory.Sequence(lambda n: f"Zone {n}")
    boundary = factory.SubFactory(BoundaryFactory)
    geometry = factory.LazyFunction(_box)
    zone_type = "management_area"


class ParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "parcels.Parcel"

    parcel_number = factory.Sequence(lambda n: f"APN-{n:06d}")
    owner_name = "Test Owner"
    area_acres = Decimal("80.00")
    geometry = factory.LazyFunction(_box)
    status = "active"


class ParcelZoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "geography.ParcelZone"

    parcel = factory.SubFactory(ParcelFactory)
    zone = factory.SubFactory(ZoneFactory)


class WellTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "wells.WellType"

    name = factory.Sequence(lambda n: f"WellType {n}")


class WellFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "wells.Well"

    name = factory.Sequence(lambda n: f"Well {n}")
    well_type = factory.SubFactory(WellTypeFactory)
    location = factory.LazyFunction(lambda: Point(-119.5, 36.5))
    status = "active"


class WellIrrigatedParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "wells.WellIrrigatedParcel"

    well = factory.SubFactory(WellFactory)
    parcel = factory.SubFactory(ParcelFactory)
    fraction = Decimal("1.0000")


class WaterTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.WaterType"

    name = factory.Sequence(lambda n: f"Water Type {n}")
    code = factory.Sequence(lambda n: f"WT{n}")


class ReportingPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.ReportingPeriod"

    name = factory.Sequence(lambda n: f"WY {2020 + n}")
    start_date = factory.LazyAttribute(lambda o: date(2023, 10, 1))
    end_date = factory.LazyAttribute(lambda o: date(2024, 9, 30))


class WaterAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.WaterAccount"

    name = factory.Sequence(lambda n: f"Account {n}")
    account_number = factory.Sequence(lambda n: f"ACCT-{n:04d}")
    status = "active"


class WaterAccountParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.WaterAccountParcel"

    water_account = factory.SubFactory(WaterAccountFactory)
    parcel = factory.SubFactory(ParcelFactory)


class ParcelLedgerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "parcels.ParcelLedger"

    parcel = factory.SubFactory(ParcelFactory)
    transaction_date = factory.LazyFunction(date.today)
    effective_date = factory.LazyFunction(date.today)
    amount_acre_feet = Decimal("10.0000")
    source_type = "manual_entry"


class WaterRightTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.WaterRightType"

    name = factory.Sequence(lambda n: f"Right Type {n}")
    code = factory.Sequence(lambda n: f"RT{n}")


class WaterRightFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.WaterRight"

    right_id = factory.Sequence(lambda n: f"WR-{n:06d}")
    right_type = factory.SubFactory(WaterRightTypeFactory)
    holder_name = "Test Holder"
    status = "active"


class WaterRightParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.WaterRightParcel"

    water_right = factory.SubFactory(WaterRightFactory)
    parcel = factory.SubFactory(ParcelFactory)


class PointOfDiversionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.PointOfDiversion"

    water_right = factory.SubFactory(WaterRightFactory)
    name = factory.Sequence(lambda n: f"POD {n}")
    location = factory.LazyFunction(lambda: Point(-119.5, 36.5))
    status = "active"


class PointOfDiversionParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.PointOfDiversionParcel"

    point_of_diversion = factory.SubFactory(PointOfDiversionFactory)
    parcel = factory.SubFactory(ParcelFactory)
    fraction = Decimal("1.0000")


class DiversionRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "surface.DiversionRecord"

    point_of_diversion = factory.SubFactory(PointOfDiversionFactory)
    month = factory.LazyFunction(lambda: date(2024, 1, 1))
    volume_acre_feet = Decimal("50.0000")
    diversion_type = "direct_use"


class AllocationPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.AllocationPlan"

    name = factory.Sequence(lambda n: f"Allocation {n}")
    zone = factory.SubFactory(ZoneFactory)
    water_type = factory.SubFactory(WaterTypeFactory)
    reporting_period = factory.SubFactory(ReportingPeriodFactory)
    allocation_acre_feet = Decimal("100.0000")


class RechargeSiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "recharge.RechargeSite"

    name = factory.Sequence(lambda n: f"Recharge Site {n}")
    site_type = "spreading_basin"
    location = factory.LazyFunction(lambda: Point(-119.5, 36.5))
    status = "active"


class RechargeEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "recharge.RechargeEvent"

    recharge_site = factory.SubFactory(RechargeSiteFactory)
    start_date = factory.LazyFunction(lambda: date(2024, 1, 1))
    volume_acre_feet = Decimal("100.0000")
