# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-01: the canal split keeps a field's own record and divides the remainder.

Brent's rule (2026-09-28): a field with its own recorded delivery keeps it; the
split divides only the REMAINDER of the headgate total among the served fields
that have none. Every split row carries ``divided_from_headgate=True``; an own
row (typed on the ledger form, or imported) is the same table with the flag
False, and the split never edits or deletes it.

Also here: ISS-222 (a short split never gives a field more than its cap when
efficiencies are mixed, so the kernel water-fills) and ISS-221 (caps round DOWN
and the rounding residual never lands above a cap).

Every expected figure is a literal worked out by hand, never recomputed with
the kernel's own formula.
"""

import importlib
from datetime import date
from decimal import Decimal

import pytest

from accounting.allocation_math import allocate_by_demand
from accounting.models import CalculationRun
from parcels.models import ParcelLedger
from surface.models import UnallocatedDelivery
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

EFF = Decimal("0.75")
JAN = date(2024, 1, 1)  # inside the ReportingPeriodFactory default WY 2023-2024
FEB = date(2024, 2, 1)


def _run(parcel, period, net_demand):
    """A minimal CalculationRun carrying a known net consumptive use (the demand)."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(net_demand)),
        net_consumptive_use_af=Decimal(str(net_demand)),
        final_af=Decimal("0"),
    )


def _own(parcel, amount, month=JAN):
    """A field's own recorded delivery: a surface_diversion row, flag left False."""
    return ParcelLedgerFactory(
        parcel=parcel,
        effective_date=month,
        source_type="surface_diversion",
        amount_acre_feet=Decimal(str(amount)),
        description="Reading at the field turnout",
    )


def _split_rows():
    return ParcelLedger.objects.filter(
        source_type="surface_diversion", divided_from_headgate=True
    )


def _split_by_parcel(month=JAN):
    return {
        r.parcel_id: r.amount_acre_feet
        for r in _split_rows().filter(effective_date=month)
    }


def _one_pod_three_fields():
    """One headgate serving A, B and C; A will carry an own record."""
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    c = ParcelFactory(parcel_number="APN-C")
    for p in (a, b, c):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=p)
    _run(a, "2024-01", 50)
    _run(b, "2024-01", 30)
    _run(c, "2024-01", 60)
    return rp, pod, a, b, c


# (a) -----------------------------------------------------------------------


def test_own_record_is_kept_and_the_remainder_is_split_by_demand():
    rp, pod, a, b, c = _one_pod_three_fields()
    own = _own(a, "-40")
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    kept = ParcelLedger.objects.get(pk=own.pk)  # same row, not recreated
    assert kept.amount_acre_feet == Decimal("-40.0000")
    assert kept.divided_from_headgate is False
    # 100 - 40 = 60 AF left for B and C, by demand 30:60. Caps (40 and 80) sum to
    # 120, so the 60 AF is short and the whole of it is handed out.
    assert _split_by_parcel() == {b.pk: Decimal("-20.0000"), c.pk: Decimal("-40.0000")}
    assert not _split_rows().filter(parcel=a).exists()  # own field gets no split row


# (b) -----------------------------------------------------------------------


def test_rerunning_the_split_leaves_the_own_row_and_the_split_rows_identical():
    rp, pod, a, b, c = _one_pod_three_fields()
    own = _own(a, "-40")
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )

    def snapshot():
        return sorted(
            (r.parcel_id, r.amount_acre_feet, r.description, r.effective_date,
             r.divided_from_headgate)
            for r in ParcelLedger.objects.filter(source_type="surface_diversion")
        )

    allocate_district_delivery(pod, rp, efficiency=EFF)
    first = snapshot()
    allocate_district_delivery(pod, rp, efficiency=EFF)
    second = snapshot()

    assert first == second
    assert len(second) == 3  # the own row and two split rows, not five
    assert ParcelLedger.objects.get(pk=own.pk).amount_acre_feet == Decimal("-40.0000")


# (c) -----------------------------------------------------------------------


def test_own_records_over_the_headgate_write_no_split_and_report_the_excess():
    rp, pod, a, b, c = _one_pod_three_fields()
    own_a = _own(a, "-70")
    own_b = _own(b, "-50")
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )
    notes = []

    rows = allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    assert rows == []
    assert not _split_rows().exists()
    assert ParcelLedger.objects.get(pk=own_a.pk).amount_acre_feet == Decimal("-70.0000")
    assert ParcelLedger.objects.get(pk=own_b.pk).amount_acre_feet == Decimal("-50.0000")
    assert notes == [
        {
            "kind": "own_over_headgate",
            "pod": pod.name,
            "month": JAN,
            "excess_af": Decimal("20.0000"),
        }
    ]


def test_own_records_over_the_headgate_clear_split_rows_written_earlier():
    rp, pod, a, b, c = _one_pod_three_fields()
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )
    allocate_district_delivery(pod, rp, efficiency=EFF)  # no own record yet
    assert _split_rows().count() == 3
    _own(a, "-70")
    _own(b, "-50")

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert not _split_rows().exists()


# (d) -----------------------------------------------------------------------


def test_short_split_with_mixed_efficiencies_never_exceeds_a_cap():
    """ISS-222: equal demand, efficiencies 0.95 and 0.60, 260 AF short.

    Caps are 100/0.95 = 105.2632 and 100/0.60 = 166.6667. An even demand split
    would hand the 0.95 field 130, well past its cap. It is held at 105.2632 and
    the other field takes the rest.
    """
    got = allocate_by_demand(
        Decimal("260"),
        {"A": Decimal("100"), "B": Decimal("100")},
        {"A": Decimal("0.95"), "B": Decimal("0.60")},
    )

    assert got == {"A": Decimal("105.2632"), "B": Decimal("154.7368")}


# (e) -----------------------------------------------------------------------


def test_residual_never_lands_on_a_field_already_at_its_cap():
    """ISS-221: a capped field takes no rounding residual.

    Demand 40/8/29 at efficiencies 0.6/0.6/0.95 gives caps 66.6667 / 13.3333 /
    30.5263. C's demand share is above its cap, so it is held at
    30.5263 and A and B split the rest. The rounded shares fall 0.0001 short of
    the total, and putting that on the last key (C) would push it to 30.5264,
    above its cap. It goes to A, the field with the most headroom.
    """
    got = allocate_by_demand(
        Decimal("102.7894"),
        {"A": Decimal("40"), "B": Decimal("8"), "C": Decimal("29")},
        {"A": Decimal("0.6"), "B": Decimal("0.6"), "C": Decimal("0.95")},
    )

    assert got == {
        "A": Decimal("60.2193"),
        "B": Decimal("12.0438"),
        "C": Decimal("30.5263"),
    }
    assert got["C"] == Decimal("30.5263")  # exactly its cap, not 30.5264


# (f) -----------------------------------------------------------------------


def test_migration_marks_existing_split_rows_and_leaves_own_rows_alone():
    migration = importlib.import_module(
        "parcels.migrations.0009_parcelledger_divided_from_headgate"
    )
    parcel = ParcelFactory()

    def row(description, source_type="surface_diversion"):
        return ParcelLedgerFactory(
            parcel=parcel,
            effective_date=JAN,
            source_type=source_type,
            description=description,
        )

    by_use = row(
        "Share of 100.00 AF delivered from a canal, divided up from the canal "
        "total in proportion to each field's crop water use after rain"
    )
    legacy = row(
        "Share of 100.00 AF delivered from a canal, split among the use areas "
        "it serves by each one's estimated use for the month"
    )
    fixed = row(
        "Share of 100.00 AF delivered from a canal: 60%, the fixed share on "
        "file, because no use area it serves has an estimated use"
    )
    typed = row("Reading at the field turnout")
    other_source = row(
        "the fixed share on file", source_type="meter_reading"
    )

    marked = migration.mark_existing_split_rows(ParcelLedger)

    assert marked == 3
    flags = {
        r.pk: r.divided_from_headgate
        for r in ParcelLedger.objects.filter(parcel=parcel)
    }
    assert flags == {
        by_use.pk: True,
        legacy.pk: True,
        fixed.pk: True,
        typed.pk: False,
        other_source.pk: False,
    }


# (g) -----------------------------------------------------------------------


def test_a_capped_share_consumes_exactly_the_demand_at_four_decimals():
    """Demand 10.0001 at 0.75 is 13.33346666... AF, a cap of 13.3335.

    13.3335 * 0.75 = 10.000125, which is 10.0001 at the ledger's four decimals:
    the field's consumed canal water equals its demand, neither over nor under.
    (A cap rounded down, 13.3334, would consume 10.0000, 0.0001 short.)
    """
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("10.0001")}, Decimal("0.75"))

    assert got == {"A": Decimal("13.3335")}
    assert (got["A"] * Decimal("0.75")).quantize(Decimal("0.0001")) == Decimal("10.0001")


def test_a_difference_under_the_ledgers_resolution_is_no_canal_water_beyond_use():
    """ISS-221 at the source, MER-APN-001 December 2025 on the demonstration.

    The chain carries 1.381020383 AF of crop use after rain; the canal share,
    sized from the stored 1.3811, consumes 1.5875 * 0.870 = 1.3811. The 0.00008
    between them is two roundings disagreeing, not water: the step leaves 0.
    A real 0.0002 AF is kept.
    """
    from accounting.steps import subtract_surface_water
    from core.models import SiteConfig

    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Test Agency"})
    config.default_irrigation_efficiency = Decimal("0.870")
    config.save()
    field = ParcelFactory(parcel_number="APN-ROUND")
    ParcelLedgerFactory(
        parcel=field, effective_date=date(2025, 12, 15),
        source_type="surface_diversion", amount_acre_feet=Decimal("-1.5875"),
    )
    step = {"apply_efficiency": True}

    out, record = subtract_surface_water(
        Decimal("1.381020383999398644677165355"), field, "2025-12", {}, step
    )
    assert out == Decimal("0")
    assert record["detail"]["below_ledger_precision_af"] == (
        "-0.000079616000601355322834645"
    )

    out, record = subtract_surface_water(Decimal("1.3809"), field, "2025-12", {}, step)
    assert out == Decimal("-0.0002")
    assert "below_ledger_precision_af" not in record["detail"]


# further cases ---------------------------------------------------------------


def test_months_narrows_the_split_to_the_months_given():
    rp, pod, a, b, c = _one_pod_three_fields()
    _run(a, "2024-02", 50)
    _run(b, "2024-02", 30)
    _run(c, "2024-02", 60)
    for month in (JAN, FEB):
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=rp, month=month,
            volume_acre_feet=Decimal("90"),
        )
    allocate_district_delivery(pod, rp, efficiency=EFF, months=[JAN])
    assert _split_rows().filter(effective_date=FEB).count() == 0
    assert _split_rows().filter(effective_date=JAN).count() == 3

    # Now February alone: January's rows are neither deleted nor rewritten.
    january_pks = set(_split_rows().filter(effective_date=JAN).values_list("pk", flat=True))
    allocate_district_delivery(pod, rp, efficiency=EFF, months=[FEB])

    assert set(
        _split_rows().filter(effective_date=JAN).values_list("pk", flat=True)
    ) == january_pks
    assert _split_rows().filter(effective_date=FEB).count() == 3


def test_field_served_by_two_points_contributes_to_each_pro_rata_by_recorded_total():
    """F (own 30 AF) is served by P1 (recorded 60 AF) and P2 (recorded 40 AF).

    F's 30 AF counts against P1 as 30 * 60/100 = 18 AF, so P1's remainder for
    its only other field, G, is 60 - 18 = 42 AF.
    """
    rp = ReportingPeriodFactory()
    p1 = PointOfDiversionFactory()
    p2 = PointOfDiversionFactory()
    f = ParcelFactory(parcel_number="APN-F")
    g = ParcelFactory(parcel_number="APN-G")
    for pod in (p1, p2):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=f)
    PointOfDiversionParcelFactory(point_of_diversion=p1, parcel=g)
    _run(g, "2024-01", 100)  # cap 133.3333, so the 42 AF remainder is short
    own = _own(f, "-30")
    DiversionRecordFactory(
        point_of_diversion=p1, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("60"),
    )
    DiversionRecordFactory(
        point_of_diversion=p2, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("40"),
    )

    allocate_district_delivery(p1, rp, efficiency=EFF)

    assert _split_by_parcel() == {g.pk: Decimal("-42.0000")}
    assert ParcelLedger.objects.get(pk=own.pk).amount_acre_feet == Decimal("-30.0000")


def test_field_served_by_two_points_counts_wholly_against_the_one_that_recorded():
    """P2 recorded nothing and P1 recorded 60 AF, so F's 30 AF counts
    30 * 60/60 = 30 against P1 and the remainder for G is 30 AF."""
    rp = ReportingPeriodFactory()
    p1 = PointOfDiversionFactory()
    p2 = PointOfDiversionFactory()
    f = ParcelFactory(parcel_number="APN-F")
    g = ParcelFactory(parcel_number="APN-G")
    for pod in (p1, p2):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=f)
    PointOfDiversionParcelFactory(point_of_diversion=p1, parcel=g)
    _run(g, "2024-01", 100)
    _own(f, "-30")
    DiversionRecordFactory(
        point_of_diversion=p1, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("60"),
    )

    allocate_district_delivery(p1, rp, efficiency=EFF)

    assert _split_by_parcel() == {g.pk: Decimal("-30.0000")}


def test_field_served_by_two_points_splits_evenly_when_neither_recorded_anything():
    """Both points recorded 0 AF, so F's 30 AF counts half (15 AF) against each
    point; against P1's 0 AF headgate that is 15 AF of excess."""
    rp = ReportingPeriodFactory()
    p1 = PointOfDiversionFactory()
    p2 = PointOfDiversionFactory()
    f = ParcelFactory(parcel_number="APN-F")
    for pod in (p1, p2):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=f)
    _own(f, "-30")
    for pod in (p1, p2):
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=rp, month=JAN,
            volume_acre_feet=Decimal("0"),
        )
    notes = []

    allocate_district_delivery(p1, rp, efficiency=EFF, notes=notes)

    assert [n["excess_af"] for n in notes] == [Decimal("15.0000")]


def test_remainder_with_no_field_left_to_take_it_is_unallocated():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory(parcel_number="APN-A")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    _own(a, "-40")
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )
    notes = []

    rows = allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    assert rows == []
    row = UnallocatedDelivery.objects.get(point_of_diversion=pod, month=JAN)
    assert row.amount_acre_feet == Decimal("60.0000")
    assert notes == [
        {
            "kind": "unallocated",
            "pod": pod.name,
            "month": JAN,
            "amount_af": Decimal("60.0000"),
        }
    ]


def test_ample_remainder_reports_the_unallocated_surplus_in_notes():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    _own(a, "-40")
    _run(b, "2024-01", 30)  # cap 40
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )
    notes = []

    allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    # Remainder 60, B takes its cap of 40, the other 20 AF is unexplained.
    assert _split_by_parcel() == {b.pk: Decimal("-40.0000")}
    assert notes == [
        {
            "kind": "unallocated",
            "pod": pod.name,
            "month": JAN,
            "amount_af": Decimal("20.0000"),
        }
    ]


def test_static_fraction_fallback_divides_the_remainder_among_fields_without_an_own_record():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    c = ParcelFactory(parcel_number="APN-C")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.5"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.3"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=c, fraction=Decimal("0.2"))
    _own(a, "-40")
    # No CalculationRun: no demand signal, so the fixed shares of the two fields
    # without an own record (0.3 : 0.2, normalized to 0.6 : 0.4) split 60 AF.
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert _split_by_parcel() == {b.pk: Decimal("-36.0000"), c.pk: Decimal("-24.0000")}
    assert all(r.divided_from_headgate for r in _split_rows())


# Two points, one field; a deleted record ------------------------------------


def test_recalculating_one_point_keeps_another_points_share_on_a_shared_field():
    rp = ReportingPeriodFactory()
    pod_a = PointOfDiversionFactory()
    pod_b = PointOfDiversionFactory()
    shared = ParcelFactory(parcel_number="APN-SHARED")
    for pod in (pod_a, pod_b):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=shared)
    _run(shared, "2024-01", 30)
    DiversionRecordFactory(
        point_of_diversion=pod_a, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("10"),
    )
    DiversionRecordFactory(
        point_of_diversion=pod_b, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("6"),
    )

    allocate_district_delivery(pod_a, rp, efficiency=EFF)
    allocate_district_delivery(pod_b, rp, efficiency=EFF)
    allocate_district_delivery(pod_a, rp, efficiency=EFF)  # A again, after B

    rows = _split_rows().filter(parcel=shared, effective_date=JAN)
    assert sorted(
        (r.divided_from_point_pk, r.amount_acre_feet) for r in rows
    ) == sorted([(pod_a.pk, Decimal("-10.0000")), (pod_b.pk, Decimal("-6.0000"))])


def test_a_month_asked_for_with_no_record_left_loses_its_split_rows():
    rp, pod, a, b, c = _one_pod_three_fields()
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("70"),
    )
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert _split_rows().filter(effective_date=JAN).count() == 3

    record.delete()  # the diversion record is deleted on its page
    allocate_district_delivery(pod, None, months=[JAN])

    assert not _split_rows().filter(effective_date=JAN).exists()
    assert not UnallocatedDelivery.objects.filter(point_of_diversion=pod).exists()


def test_a_month_is_the_calendar_month_whatever_day_the_record_carries():
    # The demonstration dates diversion records and their rows on the 15th.
    rp, pod, a, b, c = _one_pod_three_fields()
    mid_jan = date(2024, 1, 15)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=mid_jan,
        volume_acre_feet=Decimal("70"),
    )
    _own(a, "-10", month=date(2024, 1, 3))  # typed on the 3rd: still January's

    allocate_district_delivery(pod, None, months=[JAN], efficiency=EFF)

    rows = _split_rows().filter(effective_date=mid_jan)
    # 70 - 10 = 60 AF for B and C by demand 30:60.
    assert {r.parcel_id: r.amount_acre_feet for r in rows} == {
        b.pk: Decimal("-20.0000"), c.pk: Decimal("-40.0000"),
    }

    allocate_district_delivery(pod, None, months=[JAN], efficiency=EFF)
    assert _split_rows().filter(effective_date=mid_jan).count() == 2  # replaced, not doubled


def test_water_taken_to_storage_is_never_divided_among_fields():
    rp, pod, a, b, c = _one_pod_three_fields()
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("70"),
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("85.22"), diversion_type="to_storage",
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    # Only the 70 AF delivered for use: A, B, C by demand 50:30:60 (caps
    # 66.6667, 40, 80 sum past 70, so it is short and all 70 is handed out).
    assert _split_by_parcel() == {
        a.pk: Decimal("-25.0000"), b.pk: Decimal("-15.0000"), c.pk: Decimal("-30.0000"),
    }
