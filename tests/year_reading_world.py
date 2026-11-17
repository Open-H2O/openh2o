# SPDX-License-Identifier: AGPL-3.0-or-later
"""Records that carry every rule a water year's figures are added up by.

Two builders. ``build_world`` is the hand-checked districts of
``tests/ledger_districts.py`` (D1 groundwater with a shared metered well, D2 canal
by shares, D3 mixed with a recharge basin, H3 and H4 with their own canal rows)
over two water years, with the cases those districts lack:

* a use area voided after its runs, still linked to its account and zone;
* an account link removed in the middle of a year, and one removed before both;
* a zone membership that starts in the middle of a year and one that ends in it;
* a use area in two zones (H1, H2), a use area with no runs and a typed
  groundwater row (N1), a fallow month (F3);
* account credits and a zone's carry-over (the year-end rollover) and a credit
  typed directly;
* a zone with no groundwater plan (D2 District);
* two calculation methods in one account (F2's August run stamped otherwise);
* canal records measured four ways (a device, a methodology, an estimate, none);
* an inactive account and a suspended one.

``build_scaled_zones`` and ``add_scaled`` make use areas, accounts and links in two
zones, a few at a time, so a page's number of queries can be compared at two sizes.
"""
import datetime as dt
from decimal import Decimal as D

from django.utils import timezone

from accounting.models import (
    AccountCredit,
    CalculationRun,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
)
from geography.models import ParcelZone
from parcels.models import FallowPeriod, Parcel
from surface.models import DiversionRecord
from tests import ledger_districts as ld

WY25 = "WY 2024-2025"
WY26 = "WY 2025-2026"


def _account(number, parcels, *, status="active", removed=None):
    account = WaterAccount.objects.create(
        name=f"Account {number}", account_number=number, unit_kind="farm_unit", status=status
    )
    for parcel in parcels:
        WaterAccountParcel.objects.create(
            water_account=account, parcel=parcel, removed_date=(removed or {}).get(parcel.parcel_number)
        )
    return account


def build_world():
    """Both water years calculated, a rollover between them, every case above in place."""
    ld.seed_reference()
    d1 = ld.build_d1()
    d2 = ld.build_d2()
    d3 = ld.build_d3()
    ld.add_h3_h4(d3)
    gsa = d1["gsa"]

    # A use area voided after its runs: still linked to account D1-A and to D1 GSA.
    v1 = ld.add_field(
        "V1", 40, "Alfalfa", None, [gsa], -120.57, 37.22,
        [{"2025-07": 76.2, "2025-08": 45.72, "2025-09": 30.48}], ld.make_well("WV", -120.57, 37.22),
    )
    WaterAccountParcel.objects.create(water_account=WaterAccount.objects.get(account_number="D1-A"), parcel=v1)
    # A use area with no runs: no crop ET, one typed groundwater row.
    n1 = ld.add_field("N1", 25, None, None, [gsa], -120.59, 37.24, [])
    ld.ledger(n1, dt.date(2025, 8, 1), -5, "manual_entry", "GW", "typed groundwater use")
    ld.ledger(n1, dt.date(2025, 11, 1), "-2.5", "manual_entry", "GW", "typed groundwater use")

    # The second year: crop ET on four use areas, a meter reading, a canal record.
    for parcel, mm in (
        (d1["F1"], {"2025-10": 30.48, "2025-11": 15.24}),
        (d1["F4"], {"2025-10": 45.72, "2025-11": 22.86}),
        (d3["H1"], {"2025-10": 60.96, "2025-11": 30.48}),
        (d2["G1"], {"2025-10": 38.1, "2025-11": 19.05}),
    ):
        ld.add_et(parcel, mm)
    ld.ledger(d1["F1"], dt.date(2025, 10, 1), -12, "meter_reading", "GW", "meter reading entered by acreage share")
    ld.typed_record(d3["P3"], dt.date(2025, 10, 1), "40.0000")
    ld.allocation(d3["dist"], "SW", WY26, "150.0000")

    ld.run_months(["2025-01", "2025-07", "2025-08", "2025-09"])
    ld.rollover(2025)
    ld.run_months(["2025-10", "2025-11"])

    Parcel.objects.filter(pk=v1.pk).update(voided_at=timezone.now())

    # Accounts beyond D1-A and D1-B.
    _account("D2-C", [d2["G1"], d2["G2"]], removed={"G2": dt.date(2025, 8, 15)})
    _account("D2-D", [d2["G3"]], removed={"G3": dt.date(2024, 6, 1)})
    _account("D3-E", [d3["H1"], d3["H2"], d2["G3"]])
    _account("D3-F", [d3["H3"], d3["H4"]], status="inactive")
    _account("N-G", [n1])
    _account("S-H", [d3["H4"]], status="suspended")

    # Zone memberships with dates.
    ParcelZone.objects.create(parcel=d2["G2"], zone=gsa, start_date=dt.date(2025, 8, 1))
    ParcelZone.objects.filter(parcel=d1["F4"], zone=gsa).update(end_date=dt.date(2025, 8, 15))

    FallowPeriod.objects.create(parcel=d1["F3"], start_month=dt.date(2025, 8, 1), end_month=dt.date(2025, 8, 1))
    CalculationRun.objects.filter(parcel=d1["F2"], period="2025-08").update(config_hash="hand-edited")

    for month, method in (
        (dt.date(2025, 7, 1), "device"),
        (dt.date(2025, 8, 1), "outage_estimate"),
        (dt.date(2025, 10, 1), "methodology"),
    ):
        DiversionRecord.objects.filter(point_of_diversion=d3["P3"], month=month).update(method=method)
    DiversionRecord.objects.filter(point_of_diversion=d2["P2"]).update(method="outage_estimate")

    groundwater = ld.wt("GW")
    for number, year, amount in (("D1-A", 2025, "3.2500"), ("D1-B", 2026, "1.7500"), ("D3-E", 2026, "-0.5000")):
        AccountCredit.objects.create(
            water_account=WaterAccount.objects.get(account_number=number), water_type=groundwater,
            water_year=year, origin="managed_recharge", amount_af=D(amount),
            source_key=f"typed:{number}:{year}", description=f"Typed credit for {number}",
        )
    return {**d1, **d2, **d3, "V1": v1, "N1": n1}


def build_scaled_zones():
    """Two zones (a groundwater plan in one, a surface plan in the other) and one shared metered well."""
    ld.seed_reference()
    east = ld.make_zone("Scaled East", "management_area", -120.6, 37.1, -120.4, 37.3)
    west = ld.make_zone("Scaled West", "custom", -120.6, 37.1, -120.4, 37.3)
    for zone, code in ((east, "GW"), (west, "SW")):
        ld.allocation(zone, code, WY25, "500.0000")
    return {"east": east, "west": west, "well": ld.make_well("Scaled metered", -120.5, 37.2)}


def add_scaled(zones, first, count):
    """Use areas ``first`` to ``first + count - 1``, each with its own active account, then the months calculated."""
    for i in range(first, first + count):
        well = zones["well"] if i % 3 == 0 else (ld.make_well(f"Scaled W{i}", -120.5, 37.2) if i % 3 == 1 else None)
        in_zones = [zones["east"]] if i % 2 else [zones["east"], zones["west"]]
        parcel = ld.add_field(
            f"S{i:03d}", 20 + i, "Alfalfa", None, in_zones, -120.5 + i * 0.001, 37.2,
            [{"2025-07": 30.48 + i, "2025-08": 15.24 + i}], well,
        )
        if i % 3 == 0:
            ld.ledger(parcel, dt.date(2025, 7, 1), -(2 + i), "meter_reading", "GW", "meter reading")
        _account(f"S-{i:03d}", [parcel])
    ld.run_months(["2025-07", "2025-08"])
    return ReportingPeriod.objects.get(name=WY25)


def periods():
    return [ReportingPeriod.objects.get(name=WY25), ReportingPeriod.objects.get(name=WY26)]

