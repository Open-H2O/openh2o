# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-02 Task 2: estimate the delivery of a ditch with no meter, capped at the right.

A point of diversion with fields, a water right, no measuring device in service
and no volume a person typed for the month gets a delivery estimated from what
its fields used, stored as a diversion record marked as an estimate and
provisional. The estimate never goes above what remains of the right's face
value for the water year, and is zero outside the right's direct season.

Every expected figure is a literal worked out by hand, never recomputed with the
estimator's own formula. The worked example used throughout:

    Two fields. Net consumptive use after rain 40 AF and 20 AF, field
    efficiencies 0.80 and 0.60, canal losses 0.01 / 0.12 / 0.02.
      field_need = 40 / 0.80 + 20 / 0.60 = 50 + 33.3333 = 83.3333
      estimate   = 83.3333 / (1 - 0.01 - 0.12 - 0.02) = 83.3333 / 0.85 = 98.0392
"""

from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounting.engine_run import _note_sentences, run_month
from accounting.models import CalculationRun
from parcels.models import ParcelLedger
from surface.diversion_import import commit_rows
from surface.estimate import estimate_month
from surface.models import (
    DiversionRecord,
    IrrigationMethod,
    MeasuringDevice,
    ParcelIrrigationMethod,
    PointOfDiversionDevice,
)
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_calculation_run import _et_cache, _irrigate, _parcel

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)
FEB = date(2024, 2, 1)
MAR = date(2024, 3, 1)
LOSSES = ("0.01", "0.12", "0.02")
ESTIMATE = "estimated_from_use"


def _efficiency(parcel, value):
    """Give a field its own irrigation method at this efficiency."""
    method, _ = IrrigationMethod.objects.get_or_create(
        name=f"Test method {value}",
        defaults={
            "assigned_efficiency": Decimal(value),
            "range_low": Decimal(value),
            "range_high": Decimal(value),
            "source": "test",
        },
    )
    ParcelIrrigationMethod.objects.create(parcel=parcel, method=method)


def _use(parcel, af, period="2024-01"):
    """A CalculationRun carrying a known net consumptive use (use after rain)."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(af)),
        net_consumptive_use_af=Decimal(str(af)),
        final_af=Decimal("0"),
    )


def _ditch(
    *,
    name="Alder Ditch Headgate",
    uses=(40, 20),
    efficiencies=("0.80", "0.60"),
    fractions=LOSSES,
    right=None,
    months=("2024-01",),
):
    """One unmetered point serving one field per entry in ``uses``."""
    rp = ReportingPeriodFactory()
    evaporation, seepage, spill = (Decimal(f) for f in fractions)
    pod = PointOfDiversionFactory(
        name=name,
        water_right=right if right is not None else WaterRightFactory(),
        evaporation_fraction=evaporation,
        seepage_fraction=seepage,
        spill_fraction=spill,
    )
    fields = []
    for use, efficiency in zip(uses, efficiencies):
        parcel = ParcelFactory()
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
        _efficiency(parcel, efficiency)
        for month in months:
            _use(parcel, use, month)
        fields.append(parcel)
    return rp, pod, fields


def _estimate_of(pod, month=JAN):
    return DiversionRecord.objects.get(
        point_of_diversion=pod, method=ESTIMATE, month=month
    )


def _estimates(pod=None):
    qs = DiversionRecord.objects.filter(method=ESTIMATE)
    return qs.filter(point_of_diversion=pod) if pod is not None else qs


def _run(month=JAN):
    notes = []
    estimate_month(month, notes)
    return notes


def _events():
    return apps.get_model("surface", "DiversionRecordEvent").objects.count()


def _sentences(notes):
    return _note_sentences(notes)[1]


# (a) the worked example ------------------------------------------------------


def test_two_fields_are_estimated_from_their_use_and_grossed_up_for_the_canal():
    rp, pod, _fields = _ditch()

    notes = _run()

    record = _estimate_of(pod)
    # 40 / 0.80 = 50.0000 and 20 / 0.60 = 33.3333 -> field_need 83.3333;
    # 83.3333 / 0.85 = 98.0392.
    assert record.volume_acre_feet == Decimal("98.0392")
    assert record.method == ESTIMATE
    assert record.data_state == "provisional"
    assert record.diversion_type == "direct_use"
    assert record.returned_af == Decimal("0")
    assert record.month == JAN
    assert record.reporting_period == rp
    assert record.notes == "Estimated from the fields' crop water use: 98.04 AF."
    assert [n["kind"] for n in notes] == ["estimate_written"]


def test_the_method_reads_in_plain_words():
    label = dict(DiversionRecord.METHOD_CHOICES)[ESTIMATE]
    assert label == "Estimated from the fields' crop water use"


def test_a_field_with_its_own_delivery_record_is_left_out_and_its_record_added_back():
    """Field A has its own 12 AF record; only B's use is estimated, plus the 12.

    B: 20 / 0.60 = 33.3333. field_need = 33.3333 + 12 = 45.3333.
    45.3333 / 0.85 = 53.3333 (53.33329...).
    """
    _rp, pod, fields = _ditch()
    ParcelLedgerFactory(
        parcel=fields[0],
        effective_date=JAN,
        source_type="surface_diversion",
        amount_acre_feet=Decimal("-12"),
        description="Reading at the field turnout",
    )

    _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("53.3333")


# (b) the cap -----------------------------------------------------------------


def test_face_value_less_what_was_used_earlier_this_water_year_caps_the_month():
    """Face value 150 AF, 80 AF used in November: 70.0000 may still be taken.

    The estimate is 98.0392, so 98.0392 - 70.0000 = 28.0392 is above the cap. A
    record from the water year before (August 2023) is not counted.
    """
    right = WaterRightFactory(face_value_acre_feet=Decimal("150"))
    rp, pod, _fields = _ditch(right=right)
    other = PointOfDiversionFactory(water_right=right)
    DiversionRecordFactory(
        point_of_diversion=other, month=date(2023, 11, 15), volume_acre_feet=Decimal("80")
    )
    DiversionRecordFactory(
        point_of_diversion=other, month=date(2023, 8, 15), volume_acre_feet=Decimal("200")
    )

    notes = _run()

    record = _estimate_of(pod)
    assert record.volume_acre_feet == Decimal("70.0000")
    assert record.notes == (
        "Estimated from the fields' crop water use: 98.04 AF. Capped at 70.00 AF, "
        "what remained of the water right this water year."
    )
    capped = [n for n in notes if n["kind"] == "estimate_capped"]
    assert len(capped) == 1
    assert capped[0]["estimate_af"] == Decimal("70.0000")
    assert capped[0]["above_af"] == Decimal("28.0392")
    assert _sentences(notes)[-1] == (
        "Estimated 70.00 AF at Alder Ditch Headgate for January 2024; 28.04 AF of "
        "the fields' use is above what the water right allows this season and is "
        "counted as water use recorded, no supply reported."
    )


def test_the_note_says_groundwater_where_the_fields_have_wells_and_both_where_they_differ():
    right = WaterRightFactory(face_value_acre_feet=Decimal("70"))
    _rp, pod, fields = _ditch(right=right)

    WellIrrigatedParcelFactory(parcel=fields[0])
    mixed = _sentences(_run())[-1]
    WellIrrigatedParcelFactory(parcel=fields[1])
    wells = _sentences(_run())[-1]

    assert mixed.endswith(
        "is counted as groundwater where a field has a well, otherwise as water "
        "use recorded, no supply reported."
    )
    assert wells.endswith("is counted as groundwater.")


def test_an_estimate_at_or_under_what_remains_is_not_capped():
    right = WaterRightFactory(face_value_acre_feet=Decimal("98.0392"))
    _rp, pod, _fields = _ditch(right=right)

    notes = _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("98.0392")
    assert [n["kind"] for n in notes] == ["estimate_written"]


def test_a_right_used_past_its_face_value_leaves_nothing_to_estimate():
    right = WaterRightFactory(face_value_acre_feet=Decimal("50"))
    _rp, pod, _fields = _ditch(right=right)
    DiversionRecordFactory(
        point_of_diversion=pod, month=date(2023, 12, 15), volume_acre_feet=Decimal("60"),
        method="device",
    )

    _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("0.0000")


def test_a_month_outside_the_direct_season_writes_zero_and_a_note():
    right = WaterRightFactory(
        direct_season_start_month=4,
        direct_season_start_day=1,
        direct_season_end_month=9,
        direct_season_end_day=30,
    )
    _rp, pod, _fields = _ditch(right=right)

    notes = _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("0.0000")
    assert _estimate_of(pod).notes == (
        "Estimated from the fields' crop water use: 98.04 AF. Set to 0.00 AF "
        "because this month is outside the water right's direct season."
    )
    capped = [n for n in notes if n["kind"] == "estimate_capped"]
    assert capped[0]["above_af"] == Decimal("98.0392")


@pytest.mark.parametrize(
    "season, expected",
    [
        # November to March wraps the year end: January is in season.
        ((11, 1, 3, 31), "98.0392"),
        # May to September: January is wholly outside.
        ((5, 1, 9, 30), "0.0000"),
        # A month partly in season counts as in season (Jan 20 to Mar 31).
        ((1, 20, 3, 31), "98.0392"),
        # Season ends on the 1st of the month: still partly in season.
        ((9, 1, 1, 1), "98.0392"),
        # Season ends the last day of December: January is outside.
        ((9, 1, 12, 31), "0.0000"),
    ],
)
def test_the_season_may_wrap_the_year_end(season, expected):
    start_month, start_day, end_month, end_day = season
    right = WaterRightFactory(
        direct_season_start_month=start_month,
        direct_season_start_day=start_day,
        direct_season_end_month=end_month,
        direct_season_end_day=end_day,
    )
    _rp, pod, _fields = _ditch(right=right)

    _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal(expected)


def test_two_points_on_one_right_see_each_others_volume_for_later_months_only():
    """Face value 150 AF, no canal losses, efficiency 1.000, 60 AF of use a month.

    January: nothing earlier this water year, so both points are estimated at 60
    (the second does not see the first's January volume). February: January's 120
    is used, 30 remains, so each is capped at 30 (again neither sees the other's
    February). March: 120 + 60 = 180 used, nothing remains.
    """
    right = WaterRightFactory(face_value_acre_feet=Decimal("150"))
    months = ("2024-01", "2024-02", "2024-03")
    kwargs = dict(
        uses=(60,), efficiencies=("1.000",), fractions=("0", "0", "0"),
        right=right, months=months,
    )
    _rp, first, _f1 = _ditch(name="First Gate", **kwargs)
    _rp, second, _f2 = _ditch(name="Second Gate", **kwargs)

    for month in (JAN, FEB, MAR):
        _run(month)

    assert _estimate_of(first, JAN).volume_acre_feet == Decimal("60.0000")
    assert _estimate_of(second, JAN).volume_acre_feet == Decimal("60.0000")
    assert _estimate_of(first, FEB).volume_acre_feet == Decimal("30.0000")
    assert _estimate_of(second, FEB).volume_acre_feet == Decimal("30.0000")
    assert _estimate_of(first, MAR).volume_acre_feet == Decimal("0.0000")
    assert _estimate_of(second, MAR).volume_acre_feet == Decimal("0.0000")


# (c) who qualifies -----------------------------------------------------------


def _device(pod, *, installed_on=None, removed_on=None):
    device = MeasuringDevice.objects.create(
        nickname="Gate meter", device_type="inline_flow_meter"
    )
    return PointOfDiversionDevice.objects.create(
        point_of_diversion=pod,
        device=device,
        installed_on=installed_on,
        removed_on=removed_on,
    )


def test_a_point_with_a_device_in_service_gets_no_estimate():
    _rp, pod, _fields = _ditch()
    _device(pod, installed_on=date(2023, 6, 1))

    notes = _run()

    assert _estimates(pod).count() == 0
    assert notes == []


def test_a_device_link_with_no_dates_counts_as_in_service():
    _rp, pod, _fields = _ditch()
    _device(pod)

    _run()

    assert _estimates(pod).count() == 0


def test_a_device_removed_before_the_month_does_not_count():
    _rp, pod, _fields = _ditch()
    _device(pod, installed_on=date(2020, 1, 1), removed_on=date(2023, 12, 31))

    _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("98.0392")


def test_a_device_installed_after_the_month_does_not_count_and_one_installed_in_it_does():
    _rp, pod, _fields = _ditch()
    link = _device(pod, installed_on=date(2024, 2, 1))

    _run()
    assert _estimate_of(pod).volume_acre_feet == Decimal("98.0392")

    link.installed_on = date(2024, 1, 31)
    link.save()
    _run()
    assert _estimates(pod).count() == 0


def test_a_device_that_arrives_takes_an_earlier_estimate_away():
    _rp, pod, _fields = _ditch()
    _run()
    assert _estimates(pod).count() == 1

    _device(pod)
    _run()

    assert _estimates(pod).count() == 0


def test_a_person_entered_record_wins_and_the_estimate_is_deleted():
    _rp, pod, _fields = _ditch()
    _run()
    assert _estimate_of(pod).volume_acre_feet == Decimal("98.0392")
    typed = DiversionRecordFactory(
        point_of_diversion=pod, month=date(2024, 1, 15), volume_acre_feet=Decimal("12")
    )

    notes = _run()

    assert _estimates(pod).count() == 0
    typed.refresh_from_db()
    assert typed.volume_acre_feet == Decimal("12.0000")
    assert typed.method == ""
    assert notes == []


def test_a_record_of_another_method_is_never_touched():
    _rp, pod, _fields = _ditch()
    record = DiversionRecordFactory(
        point_of_diversion=pod, month=JAN, volume_acre_feet=Decimal("33"),
        method="outage_estimate",
    )

    _run()

    record.refresh_from_db()
    assert record.volume_acre_feet == Decimal("33.0000")
    assert record.method == "outage_estimate"
    assert _estimates(pod).count() == 0


def test_a_record_taken_to_storage_does_not_stop_the_estimate():
    _rp, pod, _fields = _ditch()
    DiversionRecordFactory(
        point_of_diversion=pod, month=JAN, volume_acre_feet=Decimal("33"),
        diversion_type="to_storage",
    )

    _run()

    assert _estimate_of(pod).volume_acre_feet == Decimal("98.0392")


def test_a_point_with_no_crop_water_use_for_any_field_writes_nothing():
    _rp, pod, _fields = _ditch(months=())

    notes = _run()

    assert _estimates(pod).count() == 0
    assert notes == []


# (d) re-running --------------------------------------------------------------


def test_running_the_month_again_leaves_the_record_as_it_was():
    _rp, pod, _fields = _ditch(right=WaterRightFactory(face_value_acre_feet=Decimal("70")))
    _run()
    before = _estimate_of(pod)
    snapshot = (
        before.pk, before.month, before.volume_acre_feet, before.returned_af,
        before.method, before.data_state, before.diversion_type, before.notes,
        before.reporting_period_id, before.created_at,
    )
    events = _events()

    _run()
    _run()

    after = _estimate_of(pod)
    assert (
        after.pk, after.month, after.volume_acre_feet, after.returned_af,
        after.method, after.data_state, after.diversion_type, after.notes,
        after.reporting_period_id, after.created_at,
    ) == snapshot
    assert _estimates(pod).count() == 1
    assert _events() == events


def test_a_changed_figure_updates_the_same_record():
    _rp, pod, fields = _ditch()
    _run()
    pk = _estimate_of(pod).pk
    CalculationRun.objects.filter(parcel=fields[0], period="2024-01").update(
        net_consumptive_use_af=Decimal("20")
    )

    _run()

    # 20 / 0.80 = 25.0000, + 33.3333 = 58.3333; / 0.85 = 68.6274 (68.62741...)
    record = _estimate_of(pod)
    assert record.pk == pk
    assert record.volume_acre_feet == Decimal("68.6274")


def test_an_estimate_on_another_day_of_the_month_is_updated_in_place():
    rp, pod, _fields = _ditch()
    stray = DiversionRecordFactory(
        point_of_diversion=pod, month=date(2024, 1, 15), volume_acre_feet=Decimal("1"),
        method=ESTIMATE, reporting_period=rp,
    )

    _run()

    assert _estimates(pod).count() == 1
    stray.refresh_from_db()
    assert stray.month == JAN
    assert stray.volume_acre_feet == Decimal("98.0392")


# (e) no right, a right that is not active ------------------------------------


def test_points_with_no_water_right_get_no_estimate_and_one_listing_note():
    _rp, first, _f1 = _ditch(name="Beta Gate")
    _rp, second, _f2 = _ditch(name="Alpha Gate")
    for pod in (first, second):
        pod.water_right = None
        pod.save()

    notes = _run()

    assert _estimates().count() == 0
    assert _sentences(notes) == [
        "No delivery was estimated for Alpha Gate and Beta Gate: each has no "
        "water right linked."
    ]


def test_a_curtailed_right_gets_no_estimate_and_loses_the_one_it_held():
    right = WaterRightFactory(status="active")
    _rp, pod, _fields = _ditch(name="El Nido Ditch", right=right)
    _run()
    assert _estimates(pod).count() == 1
    right.status = "curtailed"
    right.save()

    notes = _run()

    assert _estimates(pod).count() == 0
    assert _sentences(notes) == [
        "No delivery was estimated for El Nido Ditch: the water right is curtailed."
    ]


def test_points_are_grouped_by_the_status_of_their_right():
    _rp, a, _f1 = _ditch(name="A Gate", right=WaterRightFactory(status="curtailed"))
    _rp, b, _f2 = _ditch(name="B Gate", right=WaterRightFactory(status="curtailed"))
    _rp, c, _f3 = _ditch(name="C Gate", right=WaterRightFactory(status="inactive"))

    notes = _run()

    assert _estimates().count() == 0
    assert _sentences(notes) == [
        "No delivery was estimated for A Gate and B Gate: the water right is curtailed.",
        "No delivery was estimated for C Gate: the water right is inactive.",
    ]


def test_canal_losses_that_leave_nothing_write_nothing_and_say_so():
    _rp, pod, _fields = _ditch(fractions=("0.50", "0.30", "0.20"))

    notes = _run()

    assert _estimates(pod).count() == 0
    assert _sentences(notes) == [
        "No delivery was estimated for Alder Ditch Headgate: its canal losses add "
        "up to the whole of the water diverted."
    ]


def test_the_run_says_once_how_many_points_and_months_were_estimated():
    notes = [
        {"kind": "estimate_written", "pod": "A Gate", "month": JAN},
        {"kind": "estimate_written", "pod": "A Gate", "month": FEB},
        {"kind": "estimate_written", "pod": "B Gate", "month": FEB},
    ]

    attention, info = _note_sentences(notes)

    assert attention == []
    assert info == [
        "Estimated the delivery of 2 points with no meter for 2 months, from the "
        "fields' crop water use. These are estimates, not measurements."
    ]


# (f) a typed volume replaces the estimate ------------------------------------


def _user():
    return get_user_model().objects.create_user(
        username="estimate-operator",
        email="estimate-operator@example.org",
        password="a-good-passw0rd",
        is_active=True,
    )


def _signed_in():
    client = Client()
    client.force_login(_user())
    return client


def test_typing_a_volume_for_an_estimated_month_replaces_the_estimate():
    _rp, pod, _fields = _ditch()
    _run()
    assert _estimates(pod).count() == 1

    response = _signed_in().post(
        reverse("surface:diversion_record_create", args=[pod.pk]),
        {
            "month": "2024-01-15",  # any day; the form keeps the 1st, like the estimate
            "volume_acre_feet": "12",
            "returned_af": "0",
            "diversion_type": "direct_use",
        },
    )

    assert response.status_code == 200
    assert _estimates(pod).count() == 0
    typed = DiversionRecord.objects.get(point_of_diversion=pod, month=JAN)
    assert typed.volume_acre_feet == Decimal("12.0000")
    assert typed.method == ""
    assert "This replaces the estimate for January 2024." in response.content.decode()


def test_a_refused_typed_volume_keeps_the_estimate():
    _rp, pod, _fields = _ditch()
    _run()

    response = _signed_in().post(
        reverse("surface:diversion_record_create", args=[pod.pk]),
        {
            "month": "2024-01-01",
            "volume_acre_feet": "5",
            "returned_af": "9",  # more than the volume: the form refuses it
            "diversion_type": "direct_use",
        },
    )

    assert response.status_code == 200
    assert _estimates(pod).count() == 1
    assert "This replaces the estimate" not in response.content.decode()


def test_editing_a_volume_onto_an_estimated_month_replaces_the_estimate():
    _rp, pod, _fields = _ditch()
    _run()
    moving = DiversionRecordFactory(
        point_of_diversion=pod, month=FEB, volume_acre_feet=Decimal("7")
    )

    response = _signed_in().post(
        reverse("surface:diversion_record_edit", args=[pod.pk, moving.pk]),
        {
            "month": "2024-01-01",
            "volume_acre_feet": "7",
            "returned_af": "0",
            "diversion_type": "direct_use",
        },
    )

    assert response.status_code == 200
    assert _estimates(pod).count() == 0
    moving.refresh_from_db()
    assert moving.month == JAN
    assert "This replaces the estimate for January 2024." in response.content.decode()


def test_a_typed_record_for_another_month_leaves_the_estimate_alone():
    _rp, pod, _fields = _ditch()
    _run()

    _signed_in().post(
        reverse("surface:diversion_record_create", args=[pod.pk]),
        {
            "month": "2024-02-01",
            "volume_acre_feet": "12",
            "returned_af": "0",
            "diversion_type": "direct_use",
        },
    )

    assert _estimates(pod).count() == 1


def test_an_imported_volume_replaces_the_estimate_and_is_not_a_duplicate():
    _rp, pod, _fields = _ditch()
    _run()
    built = {
        "errors": [],
        "candidates": [
            {
                "point": pod,
                "month": JAN,
                "diversion_type": "direct_use",
                "volume_acre_feet": Decimal("12.0000"),
                "returned_af": Decimal("0.0000"),
                "max_flow_rate_cfs": None,
                "source_lines": [2],
            }
        ],
    }

    result = commit_rows(built, method="methodology")

    assert result["created"] == 1
    assert result["skipped_duplicates"] == 0
    assert result["replaced_estimates"] == ["January 2024"]
    assert _estimates(pod).count() == 0
    typed = DiversionRecord.objects.get(point_of_diversion=pod, month=JAN)
    assert typed.volume_acre_feet == Decimal("12.0000")
    assert typed.method == "methodology"


# (g) through the month's run -------------------------------------------------


def test_the_estimate_fills_the_fields_exactly_through_the_months_run():
    """engine -> estimate -> split -> engine: each field's share is its use / efficiency.

    Fields of 40 and 20 acres with 304.8 mm of crop water use (exactly 1 ft) use
    40.0000 and 20.0000 AF. At efficiencies 0.80 and 0.60 they can take
    40 / 0.80 = 50.0000 and 20 / 0.60 = 33.3333 AF. The estimate (98.0392) less
    the three losses (0.9804, 11.7647, 1.9608) leaves 83.3333 for the fields.
    """
    call_command("seed_calculation_plan")
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory(
        name="Alder Ditch Headgate",
        evaporation_fraction=Decimal("0.01"),
        seepage_fraction=Decimal("0.12"),
        spill_fraction=Decimal("0.02"),
    )
    fields = []
    for number, acres, efficiency in (("EST-A", "40", "0.80"), ("EST-B", "20", "0.60")):
        parcel = _parcel(number, acres=acres)
        _irrigate(parcel)
        _et_cache(parcel, period="2024-01", et_mm=304.8)
        _efficiency(parcel, efficiency)
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
        fields.append(parcel)

    raw = run_month("2024-01")

    record = _estimate_of(pod)
    assert record.volume_acre_feet == Decimal("98.0392")
    assert record.reporting_period == rp
    shares = {
        row.parcel.parcel_number: -row.amount_acre_feet
        for row in ParcelLedger.objects.filter(
            source_type="surface_diversion", divided_from_headgate=True
        ).select_related("parcel")
    }
    assert abs(shares["EST-A"] - Decimal("50.0000")) <= Decimal("0.0001")
    assert abs(shares["EST-B"] - Decimal("33.3333")) <= Decimal("0.0001")
    assert "estimate_written" in {n["kind"] for n in raw}
    attention, info = _note_sentences(raw)
    assert attention == []
    assert (
        "Estimated the delivery of 1 point with no meter for 1 month, from the "
        "fields' crop water use. These are estimates, not measurements."
    ) in info


# (h) the state's transcription worksheet --------------------------------------


def test_the_calwatrs_worksheet_marks_an_estimated_month():
    """An estimate is never shown as a measurement, on the worksheet too."""
    from tests.factories import ReportSubmissionFactory

    rp, pod, _fields = _ditch()
    DiversionRecord.objects.create(
        point_of_diversion=pod,
        reporting_period=rp,
        month=JAN,
        volume_acre_feet=Decimal("12.5000"),
        diversion_type="direct_use",
        method="estimated_from_use",
        data_state="provisional",
    )
    submission = ReportSubmissionFactory(reporting_period=rp)
    client = Client()
    client.force_login(_user())
    html = client.get(
        reverse("reporting:calwatrs_worksheet", args=[submission.pk])
    ).content.decode()
    assert "12.50" in html
    assert "Estimated</span>" in html
