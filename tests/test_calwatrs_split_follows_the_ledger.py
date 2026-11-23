# SPDX-License-Identifier: AGPL-3.0-or-later
"""The CalWATRS file divides each point's water in each month the way the ledger divided it.

A decision of 2026-10-25 set how canal water divides among use areas: by the shares the district
entered, by acreage where it entered none, by crop ET only at a point the district set to divide by
crop ET. The use area pages follow it. The CalWATRS file kept an older rule: where no shares are
entered, each use area's crop ET summed over the year. The file now follows the same division.

So for each point and month, a use area's Source Fraction is its part of what the ledger put on the
point's use areas that month: the rows the point divided, plus a use area's own recorded delivery
(this point's part of it, when more than one point serves the use area). A month with nothing on
the ledger uses the ledger's own rule, the shares entered, else acreage. Crop ET never feeds the
file's split directly. The point's monthly total is the diversion record, as before.

Every ledger here is written by the product itself (``allocate_district_delivery`` or the year's
calculation), never by hand, so the tests measure what a district would file.
"""
import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun
from datasync import crop_et
from datasync.models import CropETFigure, OpenETFieldMonth
from parcels.models import ParcelLedger
from reporting.generators import build_shared_supply_comparison, generate_calwatrs_csv
from reporting.services import build_openet_prefill
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_waiting_for_openet import APR, ET_MM, _drop_month, _run_year, world  # noqa: F401

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)
FEB = date(2024, 2, 1)
MAR = date(2026, 3, 1)


# -- helpers ------------------------------------------------------------------------------------


def _file(period, template="a1"):
    """The file's data rows as dicts: point name, month, use (Combined / SW Only), fraction, volume."""
    text = generate_calwatrs_csv(period, template).getvalue()
    rows = list(csv.reader(io.StringIO(text)))
    start = next(i for i, r in enumerate(rows) if r and r[0] == "Water Right ID") + 1
    return [
        {
            "pod": r[2],
            "month": r[6],
            "use": r[10],
            "fraction": Decimal(r[3]),
            "volume": Decimal(r[7]),
        }
        for r in rows[start:]
    ]


def _fractions(rows, pod, month):
    """``{use: fraction}`` for one point and month. Each test gives the two use areas different uses."""
    return {r["use"]: r["fraction"] for r in rows if r["pod"] == pod.name and r["month"] == month}


def _totals(rows):
    """``{(pod name, month): volume}`` summed over the point's rows."""
    out = defaultdict(Decimal)
    for r in rows:
        out[(r["pod"], r["month"])] += r["volume"]
    return dict(out)


def _point(name, **kwargs):
    return PointOfDiversionFactory(
        name=name,
        evaporation_fraction=Decimal("0"),
        seepage_fraction=Decimal("0"),
        spill_fraction=Decimal("0"),
        **kwargs,
    )


def _two_use_areas(acres_combined="30", acres_sw="10"):
    """Use area C has a well (its rows read "Combined"); use area S has none ("SW Only")."""
    c = ParcelFactory(area_acres=Decimal(acres_combined))
    s = ParcelFactory(area_acres=Decimal(acres_sw))
    WellIrrigatedParcelFactory(parcel=c)
    return c, s


def _crop_et_run(parcel, net, period="2024-01"):
    """The calculation's crop ET less rain for a use area-month: the signal the old file split by."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(net),
        net_consumptive_use_af=Decimal(net),
        final_af=Decimal("0"),
    )


def _record(pod, period, month, af):
    return DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=period,
        month=month,
        volume_acre_feet=Decimal(af),
        diversion_type="direct_use",
    )


def _own_delivery(parcel, period, month, af):
    """A use area's own recorded canal delivery (typed on the ledger form), never divided."""
    return ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=month,
        effective_date=month,
        amount_acre_feet=-Decimal(af),
        source_type="surface_diversion",
        reporting_period=period,
    )


def _ledger_split(pod, month):
    """The ledger's own split of the point's water that month, by use area, normalized."""
    rows = ParcelLedger.objects.current().filter(
        effective_date__year=month.year,
        effective_date__month=month.month,
        divided_from_headgate=True,
        divided_from_point_pk=pod.pk,
    )
    by_parcel = defaultdict(Decimal)
    for r in rows:
        by_parcel[r.parcel_id] += abs(r.amount_acre_feet)
    total = sum(by_parcel.values(), Decimal("0"))
    return {pk: (v / total).quantize(Decimal("0.0001")) for pk, v in by_parcel.items()}


# -- (a) shares entered ---------------------------------------------------------------------------


def test_a_shares_entered_are_the_rows_in_every_month():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas()
    pod = _point("Shares Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c, fraction=Decimal("0.6"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s, fraction=Decimal("0.4"))
    _crop_et_run(c, "10")  # crop ET says S is thirstier; the shares win
    _crop_et_run(s, "30")
    _record(pod, rp, JAN, "100")
    _record(pod, rp, FEB, "50")
    allocate_district_delivery(pod, rp)

    rows = _file(rp)
    for month in ("2024-01", "2024-02"):
        assert _fractions(rows, pod, month) == {"Combined": Decimal("0.6"), "SW Only": Decimal("0.4")}
    assert _totals(rows) == {(pod.name, "2024-01"): Decimal("100"), (pod.name, "2024-02"): Decimal("50")}


# -- (b) no shares entered: acreage, not crop ET ----------------------------------------------------


def test_b_no_shares_entered_divides_by_acreage_not_crop_et():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="30", acres_sw="10")
    pod = _point("Acreage Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s)
    _crop_et_run(c, "10")
    _crop_et_run(s, "30")
    _record(pod, rp, JAN, "100")
    allocate_district_delivery(pod, rp)

    rows = _file(rp)
    # The ledger gave C 75 AF and S 25 AF by acreage; the old file wrote 25 and 75 by crop ET.
    assert _fractions(rows, pod, "2024-01") == {"Combined": Decimal("0.75"), "SW Only": Decimal("0.25")}
    assert _totals(rows) == {(pod.name, "2024-01"): Decimal("100")}


# -- (c) and (d) a point set to divide by crop ET ----------------------------------------------------


def _thirstier_in_march(world):  # noqa: F811
    """WAIT-2's March crop ET is three times WAIT-1's; every other month they match."""
    OpenETFieldMonth.objects.filter(field__shares__parcel=world.u2, month=MAR).update(et_mm=ET_MM * 3)
    CropETFigure.objects.filter(parcel=world.u2, month=MAR).delete()
    crop_et.record_received_months(world.u2, [crop_et.month_text(MAR)])


def _crop_et_canal(world):  # noqa: F811
    """A crop ET point serving WAIT-1 (with a well: "Combined") and WAIT-2 ("SW Only"), no shares entered."""
    pod = _point("Need Canal", division_method="crop_need")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=world.u1)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=world.u2)
    for month in (MAR, APR):
        _record(pod, world.period, month, "20")
    return pod


def test_c_a_crop_et_point_files_the_months_crop_et_split(world):  # noqa: F811
    _thirstier_in_march(world)
    pod = _crop_et_canal(world)
    _run_year(world)

    rows = _file(world.period)
    ledger = _ledger_split(pod, MAR)
    assert ledger == {world.u1.pk: Decimal("0.25"), world.u2.pk: Decimal("0.75")}
    assert _fractions(rows, pod, "2026-03") == {"Combined": Decimal("0.25"), "SW Only": Decimal("0.75")}
    assert _totals(rows)[(pod.name, "2026-03")] == Decimal("20")


def test_d_a_waiting_month_files_the_shares_and_moves_no_other_month(world):  # noqa: F811
    _thirstier_in_march(world)
    pod = _crop_et_canal(world)
    _run_year(world)
    march_before = _fractions(_file(world.period), pod, "2026-03")

    _drop_month(world.u1, APR)
    _run_year(world)
    rows = _file(world.period)

    # WAIT-1 waits in April: the ledger divides April by acreage (10 and 10 acres, no shares entered).
    assert _fractions(rows, pod, "2026-04") == {"Combined": Decimal("0.5"), "SW Only": Decimal("0.5")}
    # March's rows stay where the ledger put them. The old year sum moved them when April went missing.
    assert _fractions(rows, pod, "2026-03") == march_before == {
        "Combined": Decimal("0.25"),
        "SW Only": Decimal("0.75"),
    }
    assert _totals(rows)[(pod.name, "2026-04")] == Decimal("20")


# -- (e) a month the ledger has not divided yet -------------------------------------------------------


def test_e_a_month_not_yet_divided_files_shares_else_acreage():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="30", acres_sw="10")
    pod = _point("Not Yet Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s)
    _crop_et_run(c, "10")
    _crop_et_run(s, "30")
    _record(pod, rp, JAN, "100")  # no calculation has divided it

    rows = _file(rp)
    assert _fractions(rows, pod, "2024-01") == {"Combined": Decimal("0.75"), "SW Only": Decimal("0.25")}
    assert _totals(rows) == {(pod.name, "2024-01"): Decimal("100")}


def test_e_a_month_not_yet_divided_files_the_shares_entered():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="30", acres_sw="10")
    pod = _point("Not Yet Shares Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c, fraction=Decimal("0.2"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s, fraction=Decimal("0.8"))
    _record(pod, rp, JAN, "100")

    assert _fractions(_file(rp), pod, "2024-01") == {"Combined": Decimal("0.2"), "SW Only": Decimal("0.8")}


# -- (f) a use area's own recorded delivery ------------------------------------------------------------


def test_f_a_use_areas_own_delivery_counts_in_its_part():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="10", acres_sw="10")
    pod = _point("Own Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s)
    _own_delivery(c, rp, JAN, "10")
    _record(pod, rp, JAN, "40")
    allocate_district_delivery(pod, rp)

    rows = _file(rp)
    # C's own 10 AF is its part; the 30 AF left was divided to S, the one use area without its own.
    assert _fractions(rows, pod, "2024-01") == {"Combined": Decimal("0.25"), "SW Only": Decimal("0.75")}
    assert _totals(rows) == {(pod.name, "2024-01"): Decimal("40")}


def test_f_an_own_delivery_on_two_points_counts_by_each_points_part():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="10", acres_sw="10")
    north = _point("North Canal")
    south = _point("South Canal")
    PointOfDiversionParcelFactory(point_of_diversion=north, parcel=c)
    PointOfDiversionParcelFactory(point_of_diversion=north, parcel=s)
    PointOfDiversionParcelFactory(point_of_diversion=south, parcel=c)
    _own_delivery(c, rp, JAN, "10")
    _record(north, rp, JAN, "30")
    _record(south, rp, JAN, "10")
    allocate_district_delivery(north, rp)
    allocate_district_delivery(south, rp)

    rows = _file(rp)
    # North recorded 30 of the 40 AF: 7.5 AF of C's own 10 is North's. S was divided the 22.5 AF left.
    assert _fractions(rows, north, "2024-01") == {"Combined": Decimal("0.25"), "SW Only": Decimal("0.75")}
    assert _fractions(rows, south, "2024-01") == {"Combined": Decimal("1")}
    assert _totals(rows) == {(north.name, "2024-01"): Decimal("30"), (south.name, "2024-01"): Decimal("10")}


# -- (h) the Prepare with OpenET page's CalWATRS figures ------------------------------------------------


def test_h_prepare_with_openet_splits_each_month_as_the_file_does():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas(acres_combined="30", acres_sw="10")
    pod = _point("Prefill Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s)
    for parcel, af in ((c, "10"), (s, "30")):
        for month in (JAN, FEB):
            CropETFigure.objects.create(
                parcel=parcel, month=month, variable="ET", model_name="Ensemble",
                depth_mm=Decimal(af) * Decimal("304.8") / parcel.area_acres,
            )
        _crop_et_run(parcel, af, "2024-01")
    _record(pod, rp, JAN, "100")
    _own_delivery(c, rp, FEB, "10")  # February: C's own 10 AF, S divided the 30 AF left
    _record(pod, rp, FEB, "40")
    allocate_district_delivery(pod, rp)

    months = {m["month"]: m["value_af"] for m in build_openet_prefill(rp, "calwatrs")["entities"][0]["months"]}
    # January by acreage, 0.75 and 0.25: 10 x 0.75 + 30 x 0.25 = 15 (the old crop ET split gave 25).
    assert months["2024-01"] == Decimal("15")
    # February as the ledger divided it, 0.25 and 0.75: 10 x 0.25 + 30 x 0.75 = 25.
    assert months["2024-02"] == Decimal("25")


# -- (i) the Shared supply check keeps its crop ET column -----------------------------------------------


def test_i_the_shared_supply_check_still_compares_the_shares_with_crop_et():
    rp = ReportingPeriodFactory()
    c, s = _two_use_areas()
    pod = _point("Check Canal")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c, fraction=Decimal("0.6"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=s, fraction=Decimal("0.4"))
    _crop_et_run(c, "5", "2023-11")
    _crop_et_run(s, "15", "2023-11")

    group = next(g for g in build_shared_supply_comparison(rp) if g["source_name"] == pod.name)
    by_parcel = {r["parcel_id"]: r for r in group["rows"]}
    assert by_parcel[c.pk]["your_weight"] == Decimal("0.6000")
    assert by_parcel[c.pk]["et_weight"] == Decimal("0.2500")
    assert by_parcel[s.pk]["et_weight"] == Decimal("0.7500")
