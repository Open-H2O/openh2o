# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three small districts, worked by hand, for the ledger tests.

Every input is stated so a person can check each figure with a calculator:
round acre-feet from chosen depths (for 100 acres 30.48 mm of ET is 10 AF; for
50 acres 60.96 mm is 10 AF), no rain anywhere, efficiency 0.75 unless the field
is on "Sprinkler" (0.80), two water years (2024-2025 and 2025-2026), neither
finalized.

* **D1, groundwater only.** One management area "D1 GSA" with fields F1 to F4,
  100 AF of groundwater a year, accounts A (F1, F2) and B (F3, F4). F1 and F2
  share well W1, whose meter reads 45 / 36 / 24 AF in July to September 2025;
  ``build_d1`` enters it on the two fields by acreage as meter-reading rows. F3
  has no crop on record and its own unmetered well; F4 grows corn on Sprinkler.
* **D2, canal only.** A service area "D2 District" (G1, G2, G3; 200 AF of
  surface water), headgate P2 serving them at shares 0.5 / 0.3 / 0.2 with
  losses 0.01 / 0.10 / 0.04, a typed July 2025 record of 100 AF and no August
  record.
* **D3, mixed.** Management area "D3 GSA" (100 AF of groundwater) containing a
  service area "D3 District" (H1, H2; 160 AF of surface water); headgate P3
  serving H1 0.6 and H2 0.4 with losses 0.01 / 0.25 / 0; typed records of 120 /
  60 / 30 AF in July to September 2025; H1 has its own unmetered well W4, H2 has
  none; the district's recharge basin RB takes a 50 AF groundwater event in
  August 2025.

Each builder returns a dict of the objects a test needs by name. Call
``seed_reference()`` first, inside a test that has database access.
"""
import datetime as dt
import io
from decimal import Decimal as D

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command

from accounting.models import AllocationPlan, ReportingPeriod, WaterAccount, WaterAccountParcel, WaterType
from core.models import SiteConfig
from datasync.models import OpenETCache
from geography.models import Boundary, ParcelZone, Zone
from measurements.models import Meter
from parcels.models import CropType, IrrigationMethod, Parcel, ParcelIrrigationMethod, ParcelLedger, UsageLocation
from recharge.models import RechargeEvent, RechargeSite
from surface.models import DiversionRecord, PointOfDiversion, PointOfDiversionParcel, WaterRight, WaterRightType
from wells.models import Well, WellIrrigatedParcel, WellMeter, WellType

TODAY = dt.date.today()
JUL, AUG, SEP = dt.date(2025, 7, 1), dt.date(2025, 8, 1), dt.date(2025, 9, 1)


def sq(lon, lat, half):
    ring = [(lon - half, lat - half), (lon + half, lat - half), (lon + half, lat + half),
            (lon - half, lat + half), (lon - half, lat - half)]
    return MultiPolygon(Polygon(ring), srid=4326)


def box(w, s, e, n):
    ring = [(w, s), (e, s), (e, n), (w, n), (w, s)]
    return MultiPolygon(Polygon(ring), srid=4326)


def seed_reference():
    for cmd in ("seed_water_types", "seed_well_types", "seed_water_right_types",
                "seed_calculation_plan"):
        out = io.StringIO()
        call_command(cmd, stdout=out)
    SiteConfig.objects.create(agency_name="Hand-calculation test district")  # every other field at its default
    IrrigationMethod.objects.create(
        name="Sprinkler", assigned_efficiency=D("0.800"), range_low=D("0.750"), range_high=D("0.850"),
        source="test input", sort_order=99)
    for n in ("Alfalfa", "Tomatoes", "Corn"):
        CropType.objects.create(name=n)
    ReportingPeriod.objects.create(name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    ReportingPeriod.objects.create(name="WY 2025-2026", start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30))
    Boundary.objects.create(name="Test boundary", geometry=box(-120.7, 37.0, -120.2, 37.5))


def wt(code):
    return WaterType.objects.get(code=code)


def period_of(date):
    return ReportingPeriod.objects.filter(start_date__lte=date, end_date__gte=date).first()


# ---------------------------------------------------------------- builders
def make_zone(name, ztype, w, s, e, n, **kw):
    return Zone.objects.create(name=name, boundary=Boundary.objects.first(), zone_type=ztype,
                               geometry=box(w, s, e, n), **kw)


def make_well(name, lon, lat):
    return Well.objects.create(name=name, well_type=WellType.objects.get(name="Production"),
                               location=Point(lon, lat, srid=4326))


def add_et(parcel, months_mm):
    """months_mm: dict 'YYYY-MM' -> mm. One cache row per contiguous run of months, one item per month."""
    keys = sorted(months_mm)
    first = dt.date(int(keys[0][:4]), int(keys[0][5:]), 1)
    ly, lm = int(keys[-1][:4]), int(keys[-1][5:])
    last = (dt.date(ly + (lm == 12), lm % 12 + 1, 1) - dt.timedelta(days=1))
    OpenETCache.objects.create(
        parcel=parcel, geometry=parcel.geometry, start_date=first, end_date=last, variable="ET",
        model_name="Ensemble", origin="fixture",
        et_data=[{"date": f"{k}-01", "et": float(months_mm[k])} for k in keys])


def add_field(number, acres, crop, method, zones, lon, lat, et, well=None, owner=""):
    geom = sq(lon, lat, 0.002)
    p = Parcel.objects.create(parcel_number=number, area_acres=D(str(acres)), area_override=True,
                              geometry=geom, owner_name=owner)
    UsageLocation.objects.create(parcel=p, name=f"{number} use location", area_acres=D(str(acres)),
                                 crop_type=CropType.objects.get(name=crop) if crop else None)
    if method:
        ParcelIrrigationMethod.objects.create(parcel=p, method=IrrigationMethod.objects.get(name=method))
    for z in zones:
        ParcelZone.objects.create(parcel=p, zone=z)
    if well is not None:
        WellIrrigatedParcel.objects.create(well=well, parcel=p)
    for chunk in et:  # list of dicts, each one contiguous window
        add_et(p, chunk)
    return p


def ledger(parcel, date, amount, source, wtype, desc="", divided=False):
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=TODAY, effective_date=date, amount_acre_feet=D(str(amount)),
        source_type=source, water_type=wt(wtype), description=desc or f"{source} (hand-entered test input)",
        reporting_period=period_of(date))


def allocation(zone, code, period_name, af):
    AllocationPlan.objects.create(name=f"{zone.name} {code} {period_name}", zone=zone, water_type=wt(code),
                                  reporting_period=ReportingPeriod.objects.get(name=period_name),
                                  allocation_acre_feet=D(str(af)))


def make_point(name, lon, lat, right, evap, seep, spill, served):
    p = PointOfDiversion.objects.create(
        name=name, location=Point(lon, lat, srid=4326), water_right=right, status="active",
        evaporation_fraction=D(evap), seepage_fraction=D(seep), spill_fraction=D(spill), loss_basis="measured")
    for parcel, frac in served:
        PointOfDiversionParcel.objects.create(point_of_diversion=p, parcel=parcel, fraction=D(frac))
    return p


def typed_record(point, month_first, af):
    return DiversionRecord.objects.create(
        point_of_diversion=point, reporting_period=period_of(month_first), month=month_first,
        volume_acre_feet=D(str(af)), returned_af=D("0"), diversion_type="direct_use")


def log_event(site, start, end, af, code):
    """The recharge view's own sequence: finalized check, event.save(), create_recharge_ledger_entries."""
    from accounting.locks import refuse_if_finalized
    from accounting.services import create_recharge_ledger_entries
    refuse_if_finalized(start)
    ev = RechargeEvent.objects.create(recharge_site=site, start_date=start, end_date=end,
                                      volume_acre_feet=D(str(af)), water_type=wt(code))
    create_recharge_ledger_entries(ev)
    return ev


def run_months(months):
    """``run_accounting`` for the listed months as ONE request (one month is the normal case)."""
    args = []
    for m in months:
        args += ["--month", m]
    call_command("run_accounting", *args, stdout=io.StringIO(), stderr=io.StringIO())


# ---------------------------------------------------------------- the three districts
def build_d1():
    gsa = make_zone("D1 GSA", "management_area", -120.6, 37.1, -120.4, 37.3)
    w1 = make_well("W1", -120.545, 37.21)
    m = Meter.objects.create(serial_number="D1-W1-METER", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=w1, meter=m, is_current=True)
    w2 = make_well("W2", -120.505, 37.21)
    w3 = make_well("W3", -120.465, 37.21)
    jas = ("2025-07", "2025-08", "2025-09")
    def et(*mm):
        return [dict(zip(jas, mm))]
    f1 = add_field("F1", 100, "Alfalfa", "Sprinkler", [gsa], -120.55, 37.2, et(60.96, 60.96, 30.48), w1)
    f2 = add_field("F2", 50, "Tomatoes", None, [gsa], -120.53, 37.2, et(121.92, 60.96, 60.96), w1)
    f3 = add_field("F3", 100, None, None, [gsa], -120.51, 37.2, et(60.96, 60.96, 30.48), w2)
    f4 = add_field("F4", 100, "Corn", "Sprinkler", [gsa], -120.49, 37.2, et(91.44, 15.24, 15.24), w3)
    for pr, vals in ((f1, (-30, -24, -16)), (f2, (-15, -12, -8))):
        for mo, v in zip((7, 8, 9), vals):
            ledger(pr, dt.date(2025, mo, 1), v, "meter_reading", "GW", "meter reading entered by acreage share")
    allocation(gsa, "GW", "WY 2024-2025", "100.0000")
    allocation(gsa, "GW", "WY 2025-2026", "100.0000")
    a = WaterAccount.objects.create(name="D1 Account A", account_number="D1-A", unit_kind="farm_unit")
    b = WaterAccount.objects.create(name="D1 Account B", account_number="D1-B", unit_kind="farm_unit")
    for acct, ps in ((a, (f1, f2)), (b, (f3, f4))):
        for pr in ps:
            WaterAccountParcel.objects.create(water_account=acct, parcel=pr)
    return {"gsa": gsa, "F1": f1, "F2": f2, "F3": f3, "F4": f4, "W1": w1}


def build_d2():
    dist = make_zone("D2 District", "custom", -120.6, 37.1, -120.4, 37.3)
    jas = ("2025-07", "2025-08")
    def et(*mm):
        return [dict(zip(jas, mm))]
    g1 = add_field("G1", 100, "Alfalfa", None, [dist], -120.55, 37.2, et(91.44, 45.72))
    g2 = add_field("G2", 100, "Corn", "Sprinkler", [dist], -120.53, 37.2, et(73.152, 36.576))
    g3 = add_field("G3", 50, "Tomatoes", None, [dist], -120.51, 37.2, et(54.864, 36.576))
    right = WaterRight.objects.create(
        right_id="R2", right_type=WaterRightType.objects.get(code="POST14"), holder_name="D2 District",
        face_value_acre_feet=D("500.0000"), direct_season_start_month=4, direct_season_start_day=1,
        direct_season_end_month=10, direct_season_end_day=31)
    p2 = make_point("D2 Headgate", -120.5, 37.15, right, "0.0100", "0.1000", "0.0400",
                    [(g1, "0.5"), (g2, "0.3"), (g3, "0.2")])
    typed_record(p2, dt.date(2025, 7, 1), "100.0000")
    allocation(dist, "SW", "WY 2024-2025", "200.0000")
    return {"dist": dist, "G1": g1, "G2": g2, "G3": g3, "P2": p2}


def build_d3(dry=False, with_event=True, jan_flood=False):
    gsa = make_zone("D3 GSA", "management_area", -120.6, 37.1, -120.3, 37.4)
    dist = make_zone("D3 District", "custom", -120.52, 37.23, -120.47, 37.27)
    w4 = make_well("W4", -120.505, 37.255)
    mm = (109.728, 109.728, 54.864) if dry else (91.44, 91.44, 45.72)
    jas = dict(zip(("2025-07", "2025-08", "2025-09"), mm))
    def et():
        chunks = [dict(jas)]
        if jan_flood:
            chunks.append({"2025-01": 6.096})
        return chunks
    h1 = add_field("H1", 100, "Alfalfa", None, [gsa, dist], -120.5, 37.25, et(), w4)
    h2 = add_field("H2", 100, "Alfalfa", None, [gsa, dist], -120.48, 37.25, et())
    right = WaterRight.objects.create(
        right_id="R3", right_type=WaterRightType.objects.get(code="POST14"), holder_name="D3 District",
        face_value_acre_feet=D("1000.0000"))
    p3 = make_point("D3 Headgate", -120.55, 37.15, right, "0.0100", "0.2500", "0", [(h1, "0.6"), (h2, "0.4")])
    vols = (50, 25, 10) if dry else (120, 60, 30)
    for mo, v in zip((7, 8, 9), vols):
        typed_record(p3, dt.date(2025, mo, 1), f"{v}.0000")
    if jan_flood:
        typed_record(p3, dt.date(2025, 1, 1), "70.0000")
    ga = 60 if dry else 100
    allocation(gsa, "GW", "WY 2024-2025", f"{ga}.0000")
    allocation(gsa, "GW", "WY 2025-2026", f"{ga}.0000")
    allocation(dist, "SW", "WY 2024-2025", "160.0000")
    site = RechargeSite.objects.create(
        name="RB", site_type="spreading_basin", location=Point(-120.4, 37.2, srid=4326),
        geometry=sq(-120.4, 37.2, 0.003), zone=gsa, operator="D3 District", capacity_acre_feet=D("500"),
        notes="dedicated basin run by the district")
    if with_event:
        log_event(site, dt.date(2025, 8, 1), dt.date(2025, 8, 31), "50.0000", "GW")
    return {"gsa": gsa, "dist": dist, "H1": h1, "H2": h2, "P3": p3, "site": site, "w4": w4}


def add_h3_h4(d3):
    gsa = d3["gsa"]
    w5 = make_well("W5", -120.465, 37.255)
    et = [{"2025-01": 6.096}]
    h3 = add_field("H3", 100, "Alfalfa", None, [gsa], -120.46, 37.25, et, w5)
    h4 = add_field("H4", 100, "Alfalfa", None, [gsa], -120.44, 37.25, et)
    for pr in (h3, h4):
        ledger(pr, dt.date(2025, 1, 1), -50, "surface_diversion", "SW",
               "own surface delivery typed on the field ledger (flooded from the canal)")
    d3["H3"], d3["H4"] = h3, h4


# ---------------------------------------------------------------- readers
def zone_budget(zone, period_name, code="GW"):
    """The zone page's own budget row for one zone, period and water type."""
    from geography.views import _zone_budget_row

    alloc = AllocationPlan.objects.get(zone=zone, reporting_period__name=period_name, water_type__code=code)
    parcels = list(ParcelZone.objects.filter(zone=zone).values_list("parcel_id", flat=True))
    return _zone_budget_row(alloc, zone, parcels)


def account_row(account, period_name):
    """The accounts table's own row for one account and period."""
    from accounting.views.common import _account_summary_row

    period = ReportingPeriod.objects.get(name=period_name)
    has_alloc = AllocationPlan.objects.filter(reporting_period=period).exists()
    return _account_summary_row(account, period, has_alloc, WaterType.objects.filter(code__iexact="GW").first())


def rollover(water_year):
    call_command("rollover_allocations", water_year=water_year, stdout=io.StringIO())
