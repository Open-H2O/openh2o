# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-02 Task 1: canal losses come off the top, and seepage goes to the district's pool.

A point of diversion carries three loss shares (evaporation, seepage, spill).
The canal split now takes them off the month's consumed total before anything is
divided, stores what it took on ``surface.CanalMonthLoss``, writes evaporation
and spill off (credited to no one), and deposits seepage to the pool of the zone
the point sits in, as a signed change so a re-run never deposits twice.

Every expected figure is a literal worked out by hand, never recomputed with the
engine's own formula. The worked example used throughout:

    100 AF diverted, 5 AF returned to the stream -> 95.0000 AF consumed.
    Shares 0.01 / 0.12 / 0.02:
      evaporation 95 x 0.01 = 0.9500
      seepage     95 x 0.12 = 11.4000
      spill       95 x 0.02 = 1.9000
      available   95 - 0.95 - 11.4 - 1.9 = 80.7500
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.contrib.gis.geos import Point

from accounting.engine_run import _note_sentences, create_request, run_queue
from accounting.models import AllocationCarryover, CalculationRun, WaterType
from accounting.services import (
    CONVEYANCE_SEEPAGE_POOL,
    deposit_to_basin_pool,
    zone_carryover,
    zone_groundwater_budget,
)
from parcels.models import ParcelLedger
from surface.models import CanalMonthLoss, UnallocatedDelivery
from surface.services import CanalLossesTooLarge, allocate_district_delivery
from tests.factories import (
    AllocationPlanFactory,
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    ZoneFactory,
    _box,
)
from tests.test_calculation_run import _et_cache, _irrigate, _parcel

pytestmark = pytest.mark.django_db

EFF = Decimal("0.75")
JAN = date(2024, 1, 1)
FAR_AWAY = Point(-100.0, 40.0)  # inside no zone the factories build


def _demand(parcel, net_demand, period="2024-01"):
    """A minimal CalculationRun carrying a known net consumptive use (the demand)."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(net_demand)),
        net_consumptive_use_af=Decimal(str(net_demand)),
        final_af=Decimal("0"),
    )


def _canal(
    *,
    volume="100",
    returned="5",
    fractions=("0.01", "0.12", "0.02"),
    demands=(50, 30, 60),
    name="Plain Canal Headgate",
    location=None,
):
    """One headgate serving fields A, B and C, with a January record."""
    rp = ReportingPeriodFactory()
    evaporation, seepage, spill = (Decimal(f) for f in fractions)
    extra = {"location": location} if location is not None else {}
    pod = PointOfDiversionFactory(
        name=name,
        evaporation_fraction=evaporation,
        seepage_fraction=seepage,
        spill_fraction=spill,
        **extra,
    )
    fields = []
    for number, demand in zip(("APN-A", "APN-B", "APN-C"), demands):
        parcel = ParcelFactory(parcel_number=number)
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
        _demand(parcel, demand)
        fields.append(parcel)
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=rp,
        month=JAN,
        volume_acre_feet=Decimal(volume),
        returned_af=Decimal(returned),
    )
    return rp, pod, fields


def _split_rows():
    return ParcelLedger.objects.filter(
        source_type="surface_diversion", divided_from_headgate=True
    )


def _split_total():
    return -sum((r.amount_acre_feet for r in _split_rows()), Decimal("0"))


def _pool(zone):
    return AllocationCarryover.objects.filter(
        zone=zone, origin=CONVEYANCE_SEEPAGE_POOL
    )


# (a) the four parts ----------------------------------------------------------


def test_the_four_parts_come_off_the_consumed_total():
    rp, pod, fields = _canal()

    allocate_district_delivery(pod, rp, efficiency=EFF)

    loss = CanalMonthLoss.objects.get(point_of_diversion=pod, month=JAN)
    assert loss.diverted_af == Decimal("95.0000")
    assert loss.evaporation_af == Decimal("0.9500")
    assert loss.seepage_af == Decimal("11.4000")
    assert loss.spill_af == Decimal("1.9000")
    assert loss.available_af == Decimal("80.7500")
    assert (
        loss.evaporation_af + loss.seepage_af + loss.spill_af + loss.available_af
        == Decimal("95.0000")
    )


def test_the_fields_share_what_survives_the_canal():
    # Demand 50 / 30 / 60 with caps at 0.75 (66.67 / 40 / 80) is more than the
    # 80.75 AF available, so the whole of it is handed out: not 95, not 100.
    rp, pod, fields = _canal()

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert _split_total() == Decimal("80.7500")
    assert not UnallocatedDelivery.objects.exists()


def test_leftover_canal_water_is_worked_out_against_available():
    # Demand 15 each at 0.75 caps every field at exactly 20.0000, 60 AF between
    # them. Of the 80.75 AF available, 60 is used and 20.75 is beyond what the
    # crops could use. (Against the gross 95 it would be 35.)
    rp, pod, fields = _canal(demands=(15, 15, 15))

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert sorted(-r.amount_acre_feet for r in _split_rows()) == [
        Decimal("20.0000")
    ] * 3
    left = UnallocatedDelivery.objects.get(point_of_diversion=pod)
    assert left.amount_acre_feet == Decimal("20.7500")
    assert left.delivery_acre_feet == Decimal("80.7500")


def test_a_field_own_record_comes_off_available_not_the_gross():
    # Worked example. 100 AF diverted, none returned. Shares 0.01 / 0.04 / 0.05
    # take 1 + 4 + 5 = 10 AF, so 90 AF is available. Field A recorded 40 AF at
    # its own gate: that water already survived the canal, so it comes off the
    # 90, leaving 50 AF for B and C, divided by crop water use 30 : 60.
    #   B 50 x 30/90 = 16.6667     C 50 x 60/90 = 33.3333
    # Taken off the gross 100 instead, the remainder would be 60 and B and C
    # would get 20 and 40.
    rp, pod, (a, b, c) = _canal(returned="0", fractions=("0.01", "0.04", "0.05"))
    ParcelLedgerFactory(
        parcel=a,
        effective_date=JAN,
        source_type="surface_diversion",
        amount_acre_feet=Decimal("-40"),
        description="Reading at the field turnout",
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    shares = {r.parcel_id: r.amount_acre_feet for r in _split_rows()}
    assert shares == {b.pk: Decimal("-16.6667"), c.pk: Decimal("-33.3333")}
    loss = CanalMonthLoss.objects.get(point_of_diversion=pod, month=JAN)
    assert loss.available_af == Decimal("90.0000")


def test_a_re_run_stores_the_same_loss_row():
    rp, pod, fields = _canal()

    allocate_district_delivery(pod, rp, efficiency=EFF)
    first = CanalMonthLoss.objects.values_list(
        "diverted_af", "evaporation_af", "seepage_af", "spill_af", "available_af"
    ).get()
    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert CanalMonthLoss.objects.count() == 1
    assert (
        CanalMonthLoss.objects.values_list(
            "diverted_af", "evaporation_af", "seepage_af", "spill_af", "available_af"
        ).get()
        == first
    )


# (b) the seepage pool --------------------------------------------------------


def test_seepage_lands_in_the_zones_pool_once():
    rp, pod, fields = _canal()
    zone = ZoneFactory()  # the factory's box holds the point's default location

    allocate_district_delivery(pod, rp, efficiency=EFF)
    row = _pool(zone).get()
    assert row.amount_af == Decimal("11.4000")
    assert row.water_year == 2024

    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert _pool(zone).get().amount_af == Decimal("11.4000")

    loss = CanalMonthLoss.objects.get(point_of_diversion=pod, month=JAN)
    assert loss.seepage_zone_id == zone.pk
    assert loss.seepage_water_year == 2024


def test_lowering_the_seepage_share_lowers_the_pool():
    rp, pod, fields = _canal()
    zone = ZoneFactory()
    allocate_district_delivery(pod, rp, efficiency=EFF)

    pod.seepage_fraction = Decimal("0.10")
    pod.save()
    allocate_district_delivery(pod, rp, efficiency=EFF)

    # 95 x 0.10 = 9.5
    assert _pool(zone).get().amount_af == Decimal("9.5000")


def test_seepage_taken_to_zero_removes_the_pool_row():
    rp, pod, fields = _canal()
    zone = ZoneFactory()
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert _pool(zone).exists()

    pod.seepage_fraction = Decimal("0")
    pod.save()
    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert not _pool(zone).exists()
    assert CanalMonthLoss.objects.get().seepage_af == Decimal("0.0000")


def test_a_point_that_moves_zone_takes_its_seepage_with_it():
    rp, pod, fields = _canal()
    first = ZoneFactory()
    second = ZoneFactory(geometry=_box(cx=-118.0))
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert _pool(first).get().amount_af == Decimal("11.4000")

    pod.location = Point(-118.0, 36.5)
    pod.save()
    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert not _pool(first).exists()
    assert _pool(second).get().amount_af == Decimal("11.4000")


def test_a_month_with_no_record_left_gives_its_seepage_back():
    rp, pod, fields = _canal()
    zone = ZoneFactory()
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert _pool(zone).get().amount_af == Decimal("11.4000")

    pod.diversionrecord_set.all().delete()
    allocate_district_delivery(pod, None, months=[JAN], efficiency=EFF)

    assert not CanalMonthLoss.objects.exists()
    assert not _pool(zone).exists()
    assert not _split_rows().exists()


def test_a_dry_run_writes_no_loss_row_and_no_pool():
    rp, pod, fields = _canal()
    zone = ZoneFactory()

    rows = allocate_district_delivery(pod, rp, efficiency=EFF, dry_run=True)

    assert -sum((r.amount_acre_feet for r in rows), Decimal("0")) == Decimal("80.7500")
    assert not CanalMonthLoss.objects.exists()
    assert not _pool(zone).exists()
    assert not _split_rows().exists()


def test_the_zone_of_the_largest_served_field_takes_it_when_no_zone_holds_the_point():
    # The point is inside no zone. Field C has the largest share (crop water use
    # 60 of 140), and C sits in a zone, so that zone's pool takes the seepage.
    rp, pod, (a, b, c) = _canal(location=FAR_AWAY)
    zone = ZoneFactory(geometry=_box(cx=-118.0))
    ParcelZoneFactory(parcel=c, zone=zone)

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert _pool(zone).get().amount_af == Decimal("11.4000")


def test_no_zone_at_all_deposits_nothing_and_says_so_in_words():
    rp, pod, fields = _canal(location=FAR_AWAY)
    ZoneFactory()  # exists, but does not contain the point
    notes = []

    allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    assert not AllocationCarryover.objects.filter(origin=CONVEYANCE_SEEPAGE_POOL).exists()
    loss = CanalMonthLoss.objects.get()
    assert loss.seepage_af == Decimal("11.4000")
    assert loss.seepage_zone_id is None
    assert {
        "kind": "seepage_no_zone",
        "pod": "Plain Canal Headgate",
        "month": JAN,
        "amount_af": Decimal("11.4000"),
    } in notes
    attention, info = _note_sentences(notes)
    assert attention == []
    assert info == [
        "Canal evaporation 0.95 AF and spill 1.90 AF across 1 point this "
        "period, not credited to anyone.",
        "Canal seepage of 11.40 AF at Plain Canal Headgate in January 2024 "
        "has no district zone to go to.",
    ]


def test_the_zones_balance_counts_the_seepage_pool():
    # The figure the dashboard's zone row reads (zone_groundwater_budget): the
    # carry-over is every pool row of the zone-year, so 11.4 AF of seepage adds
    # to a 100 AF allocation.
    rp, pod, fields = _canal()
    zone = ZoneFactory()
    groundwater, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    AllocationPlanFactory(
        zone=zone,
        water_type=groundwater,
        reporting_period=rp,
        allocation_acre_feet=Decimal("100"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert zone_carryover(zone, 2024) == Decimal("11.4000")
    budget = zone_groundwater_budget(zone, rp)
    assert budget["carryover"] == Decimal("11.4000")
    assert budget["available"] == Decimal("111.4000")


# (c) the notes ---------------------------------------------------------------


def test_evaporation_and_spill_are_one_sentence_across_the_points():
    raw = [
        {
            "kind": "canal_losses",
            "pod": "North Canal",
            "month": JAN,
            "evaporation_af": Decimal("0.95"),
            "spill_af": Decimal("1.9"),
        },
        {
            "kind": "canal_losses",
            "pod": "North Canal",
            "month": date(2024, 2, 1),
            "evaporation_af": Decimal("1.05"),
            "spill_af": Decimal("0"),
        },
        {
            "kind": "canal_losses",
            "pod": "South Canal",
            "month": JAN,
            "evaporation_af": Decimal("2"),
            "spill_af": Decimal("0"),
        },
    ]

    attention, info = _note_sentences(raw)

    assert attention == []
    assert info == [
        "Canal evaporation 4.00 AF and spill 1.90 AF across 2 points this "
        "period, not credited to anyone."
    ]


def test_with_no_spill_anywhere_only_evaporation_is_named():
    raw = [
        {
            "kind": "canal_losses",
            "pod": "North Canal",
            "month": JAN,
            "evaporation_af": Decimal("3"),
            "spill_af": Decimal("0"),
        }
    ]

    assert _note_sentences(raw) == (
        [],
        ["Canal evaporation 3.00 AF across 1 point this period, not credited to anyone."],
    )


def test_no_losses_means_no_loss_note():
    rp, pod, fields = _canal(fractions=("0", "0", "0"))
    notes = []

    allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    assert [n for n in notes if n["kind"] == "canal_losses"] == []
    loss = CanalMonthLoss.objects.get()
    assert loss.available_af == loss.diverted_af == Decimal("95.0000")


# (d) shares that leave nothing -----------------------------------------------


def test_shares_that_take_the_whole_refuse_the_month_and_write_nothing():
    rp, pod, fields = _canal(fractions=("0.5", "0.3", "0.2"))
    zone = ZoneFactory()

    with pytest.raises(CanalLossesTooLarge) as caught:
        allocate_district_delivery(pod, rp, efficiency=EFF)

    assert isinstance(caught.value, ValueError)
    assert caught.value.sentence == (
        "In January 2024, evaporation, seepage and spill at Plain Canal "
        "Headgate add up to 100% of the water it diverts, which leaves "
        "nothing for the fields."
    )
    assert not _split_rows().exists()
    assert not CanalMonthLoss.objects.exists()
    assert not _pool(zone).exists()


@pytest.fixture
def engine_world():
    """One canal, one field with crop water use for January, a January delivery."""
    call_command("seed_calculation_plan")
    rp = ReportingPeriodFactory(
        name="Winter 2024", start_date=date(2024, 1, 1), end_date=date(2024, 3, 31)
    )
    parcel = _parcel("CL-A", acres="10")
    _irrigate(parcel)
    _et_cache(parcel, period="2024-01", et_mm=304.8)  # exactly 10.0000 AF
    pod = PointOfDiversionFactory(name="Test Canal Headgate")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=rp,
        month=JAN,
        volume_acre_feet=Decimal("30"),
    )
    return rp, pod, parcel


def test_a_month_that_loses_everything_fails_with_a_named_sentence(engine_world):
    rp, pod, parcel = engine_world
    pod.evaporation_fraction = Decimal("0.5")
    pod.seepage_fraction = Decimal("0.3")
    pod.spill_fraction = Decimal("0.2")
    pod.save()
    zone = ZoneFactory()
    groundwater, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    deposit_to_basin_pool(
        zone, groundwater, 2024, Decimal("3"), origin=CONVEYANCE_SEEPAGE_POOL
    )
    req = create_request("command", months=["2024-01"])

    run_queue()

    req.refresh_from_db()
    assert req.status == "failed"
    assert req.outcome == (
        "In January 2024, evaporation, seepage and spill at Test Canal "
        "Headgate add up to 100% of the water it diverts, which leaves "
        "nothing for the fields. Nothing in January 2024 was changed."
    )
    assert not _split_rows().exists()
    assert not CanalMonthLoss.objects.exists()
    assert not CalculationRun.objects.exists()
    assert _pool(zone).get().amount_af == Decimal("3.0000")


def test_a_run_with_losses_stays_green_and_says_what_was_written_off(engine_world):
    rp, pod, parcel = engine_world
    pod.seepage_fraction = Decimal("0.12")
    pod.spill_fraction = Decimal("0.02")
    pod.save()
    req = create_request("command", months=["2024-01"])

    run_queue()

    req.refresh_from_db()
    # 30 AF x 0.01 = 0.30 evaporation, x 0.02 = 0.60 spill, x 0.12 = 3.60
    # seepage; 30 - 0.30 - 3.60 - 0.60 = 25.50 left for the field
    assert req.status == "succeeded"
    assert (
        "Canal evaporation 0.30 AF and spill 0.60 AF across 1 point this "
        "period, not credited to anyone."
    ) in req.notes
    assert (
        "Canal seepage of 3.60 AF at Test Canal Headgate in January 2024 has "
        "no district zone to go to."
    ) in req.notes
    assert CanalMonthLoss.objects.get().available_af == Decimal("25.5000")


# (e) the description clause (working copy for Brent's checkpoint) --------------


def test_the_split_row_says_the_canal_losses_came_off_first():
    rp, pod, (a, b, c) = _canal(demands=(50, 0, 0))

    allocate_district_delivery(pod, rp, efficiency=EFF)

    row = _split_rows().get(parcel=a)
    assert row.description == (
        "Share of 95.00 AF delivered from Plain Canal Headgate, after 5.00 AF "
        "of the 100.00 AF diverted was returned to the stream, after canal "
        "losses of 15%, divided up from the canal total in proportion to each "
        "field's crop water use after rain"
    )


def test_the_clause_is_absent_when_there_are_no_losses():
    rp, pod, (a, b, c) = _canal(returned="0", fractions=("0", "0", "0"), demands=(50, 0, 0))

    allocate_district_delivery(pod, rp, efficiency=EFF)

    row = _split_rows().get(parcel=a)
    assert row.description == (
        "Share of 100.00 AF delivered from Plain Canal Headgate, divided up "
        "from the canal total in proportion to each field's crop water use "
        "after rain"
    )
    assert "canal losses" not in row.description
