# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a canal's water is divided among its fields, worked by hand.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A headgate month is divided by the shares the district entered; by acreage
  where it entered none; by crop need only where the district chose that.
* Water that reaches the fields after canal losses is all booked to them.
* A field served by two points with no record and no meter gets no canal water
  from either: nothing is made up from its crop need.
* Re-dividing a month clears what the point wrote that month on every field,
  including a field no longer linked.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from parcels.models import ParcelLedger
from surface.models import PointOfDiversionParcel, UnallocatedDelivery

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

Z = D("0.0001")


def split_rows(parcel, month):
    """Magnitude of the headgate-divided delivery on one field in one month."""
    rows = ParcelLedger.objects.filter(
        parcel=parcel, source_type="surface_diversion", divided_from_headgate=True,
        effective_date__year=month.year, effective_date__month=month.month,
    )
    return sum((abs(r.amount_acre_feet) for r in rows), D("0")).quantize(Z)


def undivided(point):
    return sum((u.amount_acre_feet for u in UnallocatedDelivery.objects.filter(point_of_diversion=point)), D("0")).quantize(Z)


@pytest.fixture
def d2():
    ld.seed_reference()
    return ld.build_d2()


@pytest.fixture
def d3():
    ld.seed_reference()
    return ld.build_d3()


# ------------------------------------------------------------------ F-05
def test_d2_july_divided_by_the_shares_entered(d2):
    ld.run_months(["2025-07"])
    assert split_rows(d2["G1"], ld.JUL) == D("42.5000")
    assert split_rows(d2["G2"], ld.JUL) == D("25.5000")
    assert split_rows(d2["G3"], ld.JUL) == D("17.0000")
    assert undivided(d2["P2"]) == D("0.0000")


def test_d2_surface_used_is_what_reached_the_fields(d2):
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])
    row = ld.zone_budget(d2["dist"], "WY 2024-2025", "SW")
    # July: 100 AF typed less 15% canal losses = 85. August has no record, so it adds nothing.
    assert row["used"] == D("85.0000")
    assert row["remaining"] == D("115.0000")


def test_d3_july_divided_by_the_shares_entered(d3):
    ld.run_months(["2025-07"])
    assert split_rows(d3["H1"], ld.JUL) == D("53.2800")
    assert split_rows(d3["H2"], ld.JUL) == D("35.5200")
    assert undivided(d3["P3"]) == D("0.0000")


def test_a_winter_flood_through_the_canal_is_all_booked_to_the_fields():
    ld.seed_reference()
    d3 = ld.build_d3(jan_flood=True)
    jan = dt.date(2025, 1, 1)
    ld.run_months(["2025-01"])
    assert split_rows(d3["H1"], jan) == D("31.0800")
    assert split_rows(d3["H2"], jan) == D("20.7200")
    assert undivided(d3["P3"]) == D("0.0000")


def test_crop_need_method_still_gives_the_old_division(d2):
    d2["P2"].division_method = "crop_need"
    d2["P2"].save()
    ld.run_months(["2025-07"])
    assert split_rows(d2["G1"], ld.JUL) == D("40.0000")
    assert split_rows(d2["G2"], ld.JUL) == D("30.0000")
    assert split_rows(d2["G3"], ld.JUL) == D("12.0000")
    assert undivided(d2["P2"]) == D("3.0000")


def test_acreage_divides_where_no_share_was_entered(d2):
    # 100, 100 and 50 acres: shares 0.4, 0.4, 0.2 of the 85 AF that reaches the fields.
    PointOfDiversionParcel.objects.filter(point_of_diversion=d2["P2"]).update(fraction=D("1.0"))
    ld.run_months(["2025-07"])
    assert split_rows(d2["G1"], ld.JUL) == D("34.0000")
    assert split_rows(d2["G2"], ld.JUL) == D("34.0000")
    assert split_rows(d2["G3"], ld.JUL) == D("17.0000")
    assert undivided(d2["P2"]) == D("0.0000")


# ------------------------------------------------------------------ F-14
def two_point_field(fractions):
    """One 100-acre field, ET 30.48 mm (10 AF), on two unmetered points with no losses."""
    ld.seed_reference()
    zone = ld.make_zone("Two points", "custom", -120.6, 37.1, -120.4, 37.3)
    f = ld.add_field("T1", 100, "Alfalfa", None, [zone], -120.55, 37.2, [{"2025-07": 30.48}])
    pa = ld.make_point("Turnout A", -120.5, 37.15, None, "0", "0", "0", [(f, fractions[0])])
    pb = ld.make_point("Turnout B", -120.45, 37.15, None, "0", "0", "0", [(f, fractions[1])])
    return pa, pb


def recorded(point):
    from surface.models import DiversionRecord

    return sum((r.volume_acre_feet for r in DiversionRecord.objects.filter(point_of_diversion=point)), D("0")).quantize(Z)


@pytest.mark.parametrize("fractions", [("1.0", "1.0"), ("0.75", "0.25")])
def test_a_field_on_two_unmetered_points_gets_no_canal_water_from_either(fractions):
    pa, pb = two_point_field(fractions)
    ld.run_months(["2025-07"])
    assert recorded(pa) == D("0.0000")
    assert recorded(pb) == D("0.0000")
    assert ParcelLedger.objects.filter(source_type="surface_diversion").count() == 0


# ------------------------------------------------------------------ F-16
def test_a_field_taken_off_a_point_keeps_nothing_when_the_month_is_re_run(d3):
    ld.run_months(["2025-07"])
    PointOfDiversionParcel.objects.filter(point_of_diversion=d3["P3"], parcel=d3["H2"]).delete()
    ld.run_months(["2025-08"])
    ld.run_months(["2025-09"])
    ld.run_months(["2025-07", "2025-08", "2025-09"])
    july = split_rows(d3["H1"], ld.JUL) + split_rows(d3["H2"], ld.JUL)
    assert july == D("88.8000")
    assert split_rows(d3["H2"], ld.JUL) == D("0.0000")
