# SPDX-License-Identifier: AGPL-3.0-or-later
import factory
from datetime import date
from decimal import Decimal

from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon

from core.modules import is_enabled
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


# `datasync` is schema-resident from Phase 88: demoted it stays in
# INSTALLED_APPS, so these two resolve their `Meta.model` in every valid
# configuration and need no `is_enabled` block (unlike the truly-removable
# `surface` and `recharge` groups further down).
class DataSourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "datasync.DataSource"

    name = factory.Sequence(lambda n: f"Data Source {n}")
    code = factory.Sequence(lambda n: f"DS{n}")


class MonitoredStationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "datasync.MonitoredStation"

    data_source = factory.SubFactory(DataSourceFactory)
    external_station_id = factory.Sequence(lambda n: f"EXT-{n:04d}")
    station_name = factory.Sequence(lambda n: f"Station {n}")
    location = factory.LazyFunction(lambda: Point(-119.5, 36.5))
    is_active = True


class WaterTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.WaterType"

    name = factory.Sequence(lambda n: f"Water Type {n}")
    code = factory.Sequence(lambda n: f"WT{n}")


class ReportingPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounting.ReportingPeriod"
        # The dates below are FIXED, and `reporting_period_no_overlap` is an
        # exclusion constraint — so calling this factory twice with its defaults
        # is not "two periods", it is an IntegrityError. Reusing the row the
        # second time is what the constraint already says the database means
        # (90-01). A caller that passes its own dates still gets its own row,
        # because get_or_create is keyed on the dates it was handed.
        django_get_or_create = ("start_date", "end_date")

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


# -- surface (Phase 87) -------------------------------------------------------
#
# `surface` became an OPTIONAL module in Phase 87, so these definitions are
# guarded for the same reason as the `recharge` and `drinking` blocks below: a
# DjangoModelFactory resolves its `Meta.model` string through the app registry at
# CLASS-DEFINITION time, so an unguarded factory for a dropped module turns
# `import tests.factories` itself into an error — and `tests/droppability/checks.py`
# imports this module, so one unguarded factory takes down every droppability case
# at once rather than one.
#
# The six are self-contained: they SubFactory only into each other, into
# ParcelFactory, and nothing outside the block SubFactories into them (verified
# 2026-07-21 — AllocationPlanFactory below uses zone / water_type /
# reporting_period only).
if is_enabled("surface"):

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


# -- recharge (Phase 82) -----------------------------------------------------
#
# `recharge` became an OPTIONAL module in Phase 82, so these definitions are
# guarded for the same reason as the `drinking` block below: a DjangoModelFactory
# resolves its `Meta.model` string through the app registry at CLASS-DEFINITION
# time, so an unguarded factory for a dropped module turns `import tests.factories`
# itself into an error. That matters more here than it looks —
# `tests/droppability/checks.py` imports this module, so one unguarded factory
# takes down every droppability check at once rather than one.
if is_enabled("recharge"):

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
#
# `drinking` is an OPTIONAL module, so these definitions are guarded. A
# DjangoModelFactory resolves its `Meta.model` string through the app registry at
# CLASS-DEFINITION time, which means an unguarded factory for a dropped module
# turns `import tests.factories` itself into an error — and takes down every test
# that imports it, not just the ones touching that module. The droppability
# harness (tests/droppability/) boots processes without optional modules and is
# what surfaced this.
#
# Phases 82-85: when you flip a module to `required=False`, move its factories
# under the same kind of guard.
if is_enabled("drinking"):

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


# -- reporting (Plan 90-01) ---------------------------------------------------
#
# The state-filing layer had no factories at all until now, which is precisely
# why 89-03 found eight live 500s that three phases of green gates had missed: a
# CalWATRS `ReportSubmission` row OUTLIVES the `surface` module, and nothing in
# this repo could build one to point a reduced deployment at.
#
# **Guarded on `reporting` AND `accounting`, and both halves earn their place.**
# `reporting` is truly removable, so `reporting.ReportSubmission` does not
# resolve without it — the class-definition-time trap the blocks above describe.
# `accounting` is the second half because `ReportSubmission.reporting_period` is
# an FK into `accounting.ReportingPeriod` and `ReportingPeriodFactory` is what
# fills it: a submission is only constructible where the period model is a live
# part of the deployment. Today the requires-closure makes the second check
# redundant (dropping the `parcels`+`accounting` pair drops `reporting` with it),
# and it is written down anyway — checking only `reporting` LOOKS right and would
# break the seven-module case the day that closure changes.
if is_enabled("reporting") and is_enabled("accounting"):
    from django.apps import apps as _django_apps

    _REPORT_TYPE_LABELS = dict(
        _django_apps.get_model("reporting", "ReportTemplate").REPORT_TYPE_CHOICES
    )

    class ReportingProfileFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = "reporting.ReportingProfile"

        legal_entity_name = factory.Sequence(lambda n: f"Test Agency {n}")
        # The state-issued identity fields stay BLANK by default. They are values
        # SWRCB mails to a real agency; a plausible-looking default would be a
        # fabricated Correspondence ID sitting in a test fixture, and the model's
        # own docstring is explicit that OpenH2O only stores what a human
        # supplies. A test that needs one passes it.
        boundary = None

    class ReportTemplateFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = "reporting.ReportTemplate"
            # `report_type` is unique=True, so a second submission in the same
            # test would raise IntegrityError rather than reuse the template that
            # already exists. get_or_create makes the default template a
            # singleton per type, which is what the model's uniqueness already
            # says it is.
            django_get_or_create = ("report_type",)

        report_type = "calwatrs_a1"
        # The human label the model already declares, rather than a second copy
        # of it here — read off the LIVE app registry (the repo's standing rule)
        # instead of importing `reporting.models`, which would be exactly the
        # module-scope import the guard above exists to avoid.
        name = factory.LazyAttribute(lambda o: _REPORT_TYPE_LABELS[o.report_type])
        is_active = True

    class ReportSubmissionFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = "reporting.ReportSubmission"

        # **CalWATRS by default, and that is the whole point of this factory.**
        # `reporting/views.py::calwatrs_worksheet` and `::report_prefill` branch
        # on the report TYPE rather than on module availability, so a CalWATRS row
        # is the exact shape that reached `surface.models.WaterRightType` on a
        # deployment with `surface` dropped and raised `RuntimeError: Model class
        # ... doesn't declare an explicit app_label`. A GEARS submission does not
        # reach that code, so defaulting to one would make Plan 90-02's
        # watched-failing proof impossible while looking identical here.
        report_template = factory.SubFactory(ReportTemplateFactory)
        reporting_period = factory.SubFactory(ReportingPeriodFactory)
        status = "draft"
