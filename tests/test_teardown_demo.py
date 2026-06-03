# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant guard for the ``teardown_demo`` management command (Phase 53-01).

These tests are the SPEC for ``teardown_demo``. They build a compact but
structurally faithful multi-basin world directly via the ORM — a Kaweah slice, a
Demo Valley (Fresno) slice, a Merced slice, and the shared reference data all
three depend on — then run ``teardown_demo`` and assert three things at once:

  * every Kaweah and Demo-Valley object is gone (INV-1, INV-2),
  * Merced is byte-for-byte unchanged (INV-3), and
  * the shared reference data — reporting periods, water types, report
    templates, roles, the singleton SiteConfig — survives (INV-4).

INV-5 proves a second run is a clean no-op. They are written RED-first: until the
command exists, ``call_command("teardown_demo")`` raises ``CommandError`` and
every test fails.

The fixture mirrors the real demos' keying (boundary name + ID prefix: ``KAW-`` /
``DEMO-`` / ``MER-``) at a fraction of the size, so the suite stays fast and
hermetic — no network, no large GeoJSON fixtures.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command

from accounting.models import (
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)
from core.models import Role, SiteConfig
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, ParcelZone, Zone
from measurements.models import Meter, MeterReading, Sensor, SensorMeasurement
from parcels.models import Parcel, ParcelLedger, UsageLocation
from recharge.models import RechargeSite
from reporting.models import ReportTemplate
from surface.models import (
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
    WaterRightType,
)
from wells.models import (
    MonitoringWell,
    Well,
    WellIrrigatedParcel,
    WellMeter,
    WellType,
)


def _box(cx, cy, size=0.05):
    half = size / 2
    ring = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


def _shared_reference():
    """The agency-agnostic rows ALL basins share — the teardown must keep these."""
    gw, _ = WaterType.objects.get_or_create(code="GW", defaults={"name": "Groundwater"})
    sw, _ = WaterType.objects.get_or_create(code="SW", defaults={"name": "Surface Water"})
    prior, _ = ReportingPeriod.objects.get_or_create(
        name="WY 2024-2025",
        defaults={"start_date": date(2024, 10, 1), "end_date": date(2025, 9, 30),
                  "is_finalized": True},
    )
    ReportingPeriod.objects.get_or_create(
        name="WY 2025-2026",
        defaults={"start_date": date(2025, 10, 1), "end_date": date(2026, 9, 30)},
    )
    ReportTemplate.objects.get_or_create(
        report_type="gears_by_well", defaults={"name": "GEARS by Well"})
    Role.objects.get_or_create(name="viewer")
    # SiteConfig is a SINGLETON (its save() refuses a second row). On a real
    # deployment there is exactly one; the teardown must leave it alone.
    if not SiteConfig.objects.exists():
        SiteConfig.objects.create(agency_name="Test Agency GSA")
    return gw, sw, prior


def _build_basin(*, boundary_name, cx, cy, parcel_numbers, acct_number,
                 right_id, well_reg, recharge_name, station_ext, station_source,
                 gw, prior, zone_type="management_area", basin_code=""):
    """One complete demo slice keyed by ``boundary_name`` + the given ID prefixes.

    Touches every model the teardown traverses so the invariants exercise the
    full cascade, not just the headline rows.
    """
    boundary = Boundary.objects.create(name=boundary_name, geometry=_box(cx, cy, 0.2))
    zone = Zone.objects.create(
        name=f"{boundary_name} Zone", boundary=boundary, geometry=_box(cx, cy, 0.1),
        zone_type=zone_type, basin_code=basin_code,
    )
    wrtype, _ = WaterRightType.objects.get_or_create(
        code="POST14", defaults={"name": "Post-1914 Appropriative"})
    welltype, _ = WellType.objects.get_or_create(name="Agricultural")

    parcels = []
    for i, pn in enumerate(parcel_numbers):
        p = Parcel.objects.create(
            parcel_number=pn, owner_name=f"{boundary_name} Owner {i + 1}",
            area_acres=Decimal("80.00"), geometry=_box(cx + i * 0.01, cy, 0.01),
        )
        ParcelZone.objects.create(parcel=p, zone=zone)
        UsageLocation.objects.create(parcel=p, name=f"{pn} field")
        ParcelLedger.objects.create(
            parcel=p, transaction_date=prior.start_date, effective_date=prior.start_date,
            amount_acre_feet=Decimal("100.0000"), water_type=gw,
            source_type="allocation", reporting_period=prior,
        )
        parcels.append(p)

    acct = WaterAccount.objects.create(
        account_number=acct_number, name=f"{boundary_name} District")
    for p in parcels:
        WaterAccountParcel.objects.create(
            water_account=acct, parcel=p, reporting_period=prior)

    AllocationPlan.objects.create(
        name=f"{boundary_name} GW Budget", zone=zone, water_type=gw,
        reporting_period=prior, allocation_acre_feet=Decimal("1000.0000"))

    well = Well.objects.create(
        well_registration_id=well_reg, name=f"{boundary_name} Well",
        well_type=welltype, location=Point(cx, cy))
    WellIrrigatedParcel.objects.create(well=well, parcel=parcels[0], fraction=Decimal("1.0"))
    meter = Meter.objects.create(serial_number=f"{well_reg}-MTR")
    WellMeter.objects.create(well=well, meter=meter)
    MeterReading.objects.create(
        meter=meter, reading_date=datetime(2025, 1, 15, 12, tzinfo=timezone.utc),
        current_value=Decimal("10.0000"))
    MonitoringWell.objects.create(well=well, monitoring_agency=boundary_name)
    sensor = Sensor.objects.create(
        name=f"{boundary_name} Sensor", sensor_type="pressure_transducer",
        well=well, location=Point(cx, cy))
    SensorMeasurement.objects.create(
        sensor=sensor, measurement_date=datetime(2025, 1, 15, 12, tzinfo=timezone.utc),
        value=Decimal("120.0000"), unit="ft_bgs")

    right = WaterRight.objects.create(
        right_id=right_id, right_type=wrtype, holder_name=f"{boundary_name} Holder")
    pod = PointOfDiversion.objects.create(
        water_right=right, name=f"{boundary_name} POD", location=Point(cx, cy))
    PointOfDiversionParcel.objects.create(
        point_of_diversion=pod, parcel=parcels[0], fraction=Decimal("1.0"))
    WaterRightParcel.objects.create(water_right=right, parcel=parcels[0])
    DiversionRecord.objects.create(
        point_of_diversion=pod, month=date(2025, 5, 1),
        volume_acre_feet=Decimal("5.0000"), reporting_period=prior)

    RechargeSite.objects.create(name=recharge_name, location=Point(cx, cy), zone=zone)

    ds, _ = DataSource.objects.get_or_create(
        code=station_source, defaults={"name": station_source.upper()})
    MonitoredStation.objects.create(
        data_source=ds, external_station_id=station_ext,
        station_name=f"{boundary_name} Station", location=Point(cx, cy))


def _build_multi_basin_world():
    """Kaweah + Demo Valley + Merced slices, far enough apart spatially that a
    station-by-geometry sweep of one basin can never catch another's."""
    gw, sw, prior = _shared_reference()
    _build_basin(
        boundary_name="Kaweah Subbasin", cx=-119.2, cy=36.4,
        parcel_numbers=["KAW-APN-001", "KAW-APN-002"], acct_number="KAW-ACCT-001",
        right_id="KAW-WR-001", well_reg="KAW-W-001",
        recharge_name="Kaweah Delta Spreading Grounds",
        station_ext="KAW-ST-1", station_source="cdec", gw=gw, prior=prior)
    _build_basin(
        boundary_name="Demo Valley GSA", cx=-119.8, cy=36.75,
        parcel_numbers=["045-100-010", "045-101-011"], acct_number="DEMO-001",
        right_id="DEMO-A012345", well_reg="WCR-2024000",
        recharge_name="Demo North Spreading Basin",
        station_ext="DEMO-ST-1", station_source="usgs", gw=gw, prior=prior)
    # A Kaweah gauge in the foothills ABOVE the subbasin — outside the boundary
    # polygon, so only the explicit-ID sweep can remove it. Regression guard for
    # the out-of-polygon station bug found on the live Butler teardown.
    cdec = DataSource.objects.get(code="cdec")
    MonitoredStation.objects.create(
        data_source=cdec, external_station_id="TRM",
        station_name="Terminus Dam", location=Point(-118.98, 36.42))
    _build_basin(
        boundary_name="Merced Subbasin", cx=-120.5, cy=37.2,
        parcel_numbers=["MER-APN-001", "MER-APN-002"], acct_number="MER-ACCT-001",
        right_id="MER-WR-001", well_reg="MER-W-001",
        recharge_name="Cressey-Winton Recharge Basin",
        station_ext="MER-ST-1", station_source="cimis", gw=gw, prior=prior,
        zone_type="management_area", basin_code="5-022.04")


def _merced_counts():
    return (
        Parcel.objects.filter(parcel_number__startswith="MER-APN-").count(),
        WaterAccount.objects.filter(account_number__startswith="MER-ACCT-").count(),
        ParcelLedger.objects.filter(
            parcel__parcel_number__startswith="MER-APN-").count(),
    )


# --------------------------------------------------------------------------
# INV-1 — Kaweah fully removed
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_inv1_kaweah_fully_removed():
    _build_multi_basin_world()
    boundary = Boundary.objects.get(name="Kaweah Subbasin")
    zone_ids = list(boundary.zones.values_list("id", flat=True))
    parcel_ids = list(Parcel.objects.filter(
        parcel_number__startswith="KAW-APN-").values_list("id", flat=True))
    well_ids = list(Well.objects.filter(
        well_registration_id__startswith="KAW-W-").values_list("id", flat=True))
    pod_ids = list(PointOfDiversion.objects.filter(
        water_right__right_id__startswith="KAW-WR-").values_list("id", flat=True))

    call_command("teardown_demo")

    assert not Boundary.objects.filter(name="Kaweah Subbasin").exists()
    assert Parcel.objects.filter(parcel_number__startswith="KAW-APN-").count() == 0
    assert WaterAccount.objects.filter(account_number__startswith="KAW-ACCT-").count() == 0
    assert Well.objects.filter(well_registration_id__startswith="KAW-W-").count() == 0
    assert WaterRight.objects.filter(right_id__startswith="KAW-WR-").count() == 0
    assert Zone.objects.filter(id__in=zone_ids).count() == 0
    assert ParcelZone.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert ParcelLedger.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert UsageLocation.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert PointOfDiversionParcel.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert WaterRightParcel.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert AllocationPlan.objects.filter(zone_id__in=zone_ids).count() == 0
    assert PointOfDiversion.objects.filter(id__in=pod_ids).count() == 0
    assert DiversionRecord.objects.filter(point_of_diversion_id__in=pod_ids).count() == 0
    assert Sensor.objects.filter(well_id__in=well_ids).count() == 0
    assert SensorMeasurement.objects.filter(sensor__well_id__in=well_ids).count() == 0
    assert MonitoringWell.objects.filter(well_id__in=well_ids).count() == 0
    assert WellMeter.objects.filter(well_id__in=well_ids).count() == 0
    assert not RechargeSite.objects.filter(name="Kaweah Delta Spreading Grounds").exists()
    assert not MonitoredStation.objects.filter(station_name="Kaweah Subbasin Station").exists()
    # The foothill gauge outside the polygon must go too (explicit-ID sweep).
    assert not MonitoredStation.objects.filter(external_station_id="TRM").exists()


# --------------------------------------------------------------------------
# INV-2 — Demo Valley (Fresno) fully removed
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_inv2_fresno_fully_removed():
    _build_multi_basin_world()
    boundary = Boundary.objects.get(name="Demo Valley GSA")
    zone_ids = list(boundary.zones.values_list("id", flat=True))
    parcel_ids = list(Parcel.objects.filter(
        parcel_zones__zone_id__in=zone_ids).values_list("id", flat=True))

    call_command("teardown_demo")

    assert not Boundary.objects.filter(name="Demo Valley GSA").exists()
    assert Parcel.objects.filter(id__in=parcel_ids).count() == 0
    assert WaterAccount.objects.filter(account_number__startswith="DEMO-").count() == 0
    assert WaterRight.objects.filter(right_id__startswith="DEMO-").count() == 0
    assert Zone.objects.filter(id__in=zone_ids).count() == 0
    assert ParcelZone.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert ParcelLedger.objects.filter(parcel_id__in=parcel_ids).count() == 0
    assert AllocationPlan.objects.filter(zone_id__in=zone_ids).count() == 0
    assert not RechargeSite.objects.filter(name="Demo North Spreading Basin").exists()
    assert not MonitoredStation.objects.filter(station_name="Demo Valley GSA Station").exists()


# --------------------------------------------------------------------------
# INV-3 — Merced intact (counts identical before and after)
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_inv3_merced_untouched():
    _build_multi_basin_world()
    before = _merced_counts()
    call_command("teardown_demo")
    after = _merced_counts()

    assert before == after, f"Merced counts changed: {before} != {after}"
    assert before[0] > 0 and before[1] > 0 and before[2] > 0
    assert Boundary.objects.filter(name="Merced Subbasin").exists()
    assert Zone.objects.filter(
        zone_type="management_area", basin_code="5-022.04").exists()
    assert MonitoredStation.objects.filter(station_name="Merced Subbasin Station").exists()
    assert RechargeSite.objects.filter(name="Cressey-Winton Recharge Basin").exists()


# --------------------------------------------------------------------------
# INV-4 — shared reference data intact (the anti-regression for the pitfall)
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_inv4_shared_reference_data_intact():
    _build_multi_basin_world()
    periods_before = set(ReportingPeriod.objects.filter(
        name__startswith="WY ").values_list("name", flat=True))
    watertypes_before = set(WaterType.objects.values_list("code", flat=True))
    templates_before = set(ReportTemplate.objects.values_list("report_type", flat=True))
    roles_before = set(Role.objects.values_list("name", flat=True))
    righttypes_before = set(WaterRightType.objects.values_list("code", flat=True))
    siteconfig_before = SiteConfig.objects.count()

    call_command("teardown_demo")

    assert set(ReportingPeriod.objects.filter(
        name__startswith="WY ").values_list("name", flat=True)) == periods_before
    assert {"WY 2024-2025", "WY 2025-2026"} <= periods_before
    assert set(WaterType.objects.values_list("code", flat=True)) == watertypes_before
    assert set(ReportTemplate.objects.values_list("report_type", flat=True)) == templates_before
    assert set(Role.objects.values_list("name", flat=True)) == roles_before
    assert set(WaterRightType.objects.values_list("code", flat=True)) == righttypes_before
    # The singleton survives — deleting it would break a real deployment.
    assert SiteConfig.objects.count() == siteconfig_before == 1


# --------------------------------------------------------------------------
# INV-5 — idempotent: a second run is a clean no-op, no error
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_inv5_idempotent_second_run_is_clean_noop():
    _build_multi_basin_world()
    call_command("teardown_demo")
    after_first = _merced_counts()

    # Must not raise even though both basins are already absent.
    call_command("teardown_demo")
    after_second = _merced_counts()

    assert not Boundary.objects.filter(name="Kaweah Subbasin").exists()
    assert not Boundary.objects.filter(name="Demo Valley GSA").exists()
    assert Parcel.objects.filter(parcel_number__startswith="KAW-APN-").count() == 0
    assert Parcel.objects.filter(parcel_number__startswith="DEMO-").count() == 0
    assert after_first == after_second
    assert after_second[0] > 0, "Merced must remain after repeated teardown runs"


# --------------------------------------------------------------------------
# Surgical flags — default removes both; each flag spares the other basin
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_kaweah_only_flag_spares_fresno():
    _build_multi_basin_world()
    call_command("teardown_demo", kaweah_only=True)
    assert not Boundary.objects.filter(name="Kaweah Subbasin").exists()
    assert Boundary.objects.filter(name="Demo Valley GSA").exists()
    assert WaterAccount.objects.filter(account_number__startswith="DEMO-").exists()
    assert _merced_counts()[0] > 0


@pytest.mark.django_db
def test_fresno_only_flag_spares_kaweah():
    _build_multi_basin_world()
    call_command("teardown_demo", fresno_only=True)
    assert not Boundary.objects.filter(name="Demo Valley GSA").exists()
    assert Boundary.objects.filter(name="Kaweah Subbasin").exists()
    assert WaterAccount.objects.filter(account_number__startswith="KAW-ACCT-").exists()
    assert _merced_counts()[0] > 0
