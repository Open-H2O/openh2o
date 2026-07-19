# SPDX-License-Identifier: AGPL-3.0-or-later
import factory
from datetime import date
from decimal import Decimal

from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon

from parcels.models import NON_POSITIVE_SOURCE_TYPES


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


def _line(cx=-119.5, cy=36.5, size=0.01):
    half = size / 2
    return MultiLineString(
        LineString((cx - half, cy - half), (cx + half, cy + half))
    )


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


class FlowlineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "geography.Flowline"

    name = factory.Sequence(lambda n: f"Flowline {n}")
    boundary = factory.SubFactory(BoundaryFactory)
    feature_type = "Stream/River"
    stream_order = 3
    geometry = factory.LazyFunction(_line)


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


class CropTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "parcels.CropType"

    name = factory.Sequence(lambda n: f"Crop {n}")
    code = factory.Sequence(lambda n: f"CR{n}")


class UsageLocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "parcels.UsageLocation"

    parcel = factory.SubFactory(ParcelFactory)
    name = factory.Sequence(lambda n: f"Usage {n}")
    crop_type = factory.SubFactory(CropTypeFactory)
    area_acres = Decimal("40.00")


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
    source_type = "manual_entry"

    # The default amount's SIGN follows source_type, because the ledger's sign
    # rule is now enforced by check constraints (math eval 2026-07-18): usage
    # rows debit and must be <= 0, supply rows credit and must be > 0. A flat
    # positive default silently built usage rows production never writes — every
    # real meter_reading and surface_diversion row in the live demo is negative.
    # Magnitude stays 10 either way, so magnitude-based assertions are unchanged.
    # An explicit amount_acre_feet passed by a test still wins over this.
    amount_acre_feet = factory.LazyAttribute(
        lambda o: (
            Decimal("-10.0000")
            if o.source_type in NON_POSITIVE_SOURCE_TYPES
            else Decimal("10.0000")
        )
    )


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


# -- drinking (Phase 78) -----------------------------------------------------


class WaterSystemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.WaterSystem"

    pwsid = factory.Sequence(lambda n: f"CA19{n:05d}")
    name = factory.Sequence(lambda n: f"Water System {n}")
    activity_status = "A"
    pws_type = "CWS"
    state_classification = "C"
    primary_source_code = "GW"


class SystemFacilityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.SystemFacility"

    system = factory.SubFactory(WaterSystemFactory)
    facility_id = factory.Sequence(lambda n: f"F{n:04d}")
    name = factory.Sequence(lambda n: f"Facility {n}")
    facility_type = "WL"
    activity_status = "A"
    is_source = True
    water_type = "GW"
    availability = "P"


class SamplingPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.SamplingPoint"

    ps_code = factory.Sequence(lambda n: f"CA1900001_F{n:04d}_001")
    name = factory.Sequence(lambda n: f"Sampling Point {n}")
    facility = factory.SubFactory(SystemFacilityFactory)
    point_type = "source"


class AnalyteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.Analyte"

    # ddw_code stays NULL by default: the reference data dictionary publishes
    # no code list, so a factory default would be a fabricated code.
    ddw_code = None
    name = factory.Sequence(lambda n: f"Analyte {n}")


class RegulatoryLimitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.RegulatoryLimit"

    analyte = factory.SubFactory(AnalyteFactory)
    limit_type = "mcl"
    value = Decimal("0.010000")
    unit = "mg/L"
    jurisdiction = "federal"
    effective_start = factory.LazyFunction(lambda: date(2000, 1, 1))
    effective_end = None


class SampleEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.SampleEvent"

    sampling_point = factory.SubFactory(SamplingPointFactory)
    sample_date = factory.LazyFunction(lambda: date(2024, 6, 1))
    sample_type = "routine"


class SampleResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "drinking.SampleResult"

    event = factory.SubFactory(SampleEventFactory)
    analyte = factory.SubFactory(AnalyteFactory)
    result_kind = "numeric"
    result_value = Decimal("0.001000")
    unit = "mg/L"
    less_than_rl = False
