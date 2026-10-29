# SPDX-License-Identifier: AGPL-3.0-or-later
"""A use area is fallow for dated months, and a fallowed field takes no canal share.

* A fallow period has a start month and an end month. Either may be empty: no
  start means "from the start of the records", no end means "still fallow". The
  end month is inclusive.
* Saving a period asks for the months it covers (or uncovers) to be calculated
  again, refuses a period that touches a finalized water year, and refuses two
  periods of one use area that overlap.
* The calculation counts crop ET as 0 in a fallow month and reads the satellite
  figure in every other month.
* The canal division leaves a fallow field out of the fields it divides the
  water among. When every field is fallow, nothing is divided and the water is
  recorded as unallocated, with the fallow fields named in the note.

Every expected figure is a literal worked by hand.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRequest, CalculationRun, ReportingPeriod
from parcels.models import Parcel, ParcelLedger
from surface.models import UnallocatedDelivery
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

User = get_user_model()

JAN = dt.date(2024, 1, 1)
FEB = dt.date(2024, 2, 1)
MAR = dt.date(2024, 3, 1)
EFF = D("0.75")


def fallow_model():
    return apps.get_model("parcels", "FallowPeriod")


def make_period(parcel, start=None, end=None):
    return fallow_model().objects.create(parcel=parcel, start_month=start, end_month=end)


def operator_client():
    user, _ = User.objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    return client


def add_url(parcel):
    return reverse("parcels:fallow_period_add", args=[parcel.pk])


def end_url(parcel):
    return reverse("parcels:fallow_period_end_edit", args=[parcel.pk])


def post_add(client, parcel, start, end=""):
    return client.post(add_url(parcel), {"start_month": start, "end_month": end})


def post_end(client, parcel, end):
    return client.post(end_url(parcel), {"end_month": end})


@pytest.fixture
def ref():
    ld.seed_reference()


def gross_et(parcel, period):
    return CalculationRun.objects.get(parcel=parcel, period=period).gross_et_af


def pumped(parcel, period):
    return CalculationRun.objects.get(parcel=parcel, period=period).gw_extracted_af


# ------------------------------------------------------------------ the model
def test_a_period_is_fallow_in_every_month_from_its_start_to_its_end_inclusive():
    field = ParcelFactory()
    make_period(field, dt.date(2024, 3, 1), dt.date(2024, 5, 1))
    assert field.is_fallow_in(dt.date(2024, 2, 1)) is False
    assert field.is_fallow_in(dt.date(2024, 3, 1)) is True
    assert field.is_fallow_in(dt.date(2024, 5, 1)) is True
    assert field.is_fallow_in(dt.date(2024, 6, 1)) is False


def test_an_empty_end_means_still_fallow_and_an_empty_start_means_from_the_start():
    open_ended = ParcelFactory()
    make_period(open_ended, dt.date(2024, 3, 1), None)
    assert open_ended.is_fallow_in(dt.date(2024, 2, 1)) is False
    assert open_ended.is_fallow_in(dt.date(2040, 1, 1)) is True
    from_the_start = ParcelFactory()
    make_period(from_the_start, None, dt.date(2024, 3, 1))
    assert from_the_start.is_fallow_in(dt.date(1999, 1, 1)) is True
    assert from_the_start.is_fallow_in(dt.date(2024, 4, 1)) is False
    never = ParcelFactory()
    assert never.is_fallow_in(dt.date(2024, 3, 1)) is False
    assert never.fallow_now is False


def test_any_day_in_the_month_asks_about_that_month():
    field = ParcelFactory()
    make_period(field, dt.date(2024, 3, 1), dt.date(2024, 3, 1))
    assert field.is_fallow_in(dt.date(2024, 3, 17)) is True
    assert field.is_fallow_in(dt.date(2024, 4, 2)) is False


def test_fallow_now_reads_today():
    field = ParcelFactory()
    today = dt.date.today().replace(day=1)
    make_period(field, today, None)
    assert field.fallow_now is True


def test_the_database_refuses_an_end_before_the_start():
    field = ParcelFactory()
    backwards = fallow_model()(parcel=field, start_month=dt.date(2024, 5, 1), end_month=dt.date(2024, 3, 1))
    with pytest.raises(IntegrityError), transaction.atomic():
        fallow_model().objects.bulk_create([backwards])


def test_the_save_path_refuses_an_end_before_the_start():
    from django.core.exceptions import ValidationError

    field = ParcelFactory()
    with pytest.raises(ValidationError):
        make_period(field, dt.date(2024, 5, 1), dt.date(2024, 3, 1))


def test_the_save_path_refuses_two_periods_that_overlap():
    from django.core.exceptions import ValidationError

    field = ParcelFactory()
    make_period(field, dt.date(2024, 3, 1), dt.date(2024, 6, 1))
    with pytest.raises(ValidationError):
        make_period(field, dt.date(2024, 6, 1), None)
    make_period(field, dt.date(2024, 7, 1), None)
    other = ParcelFactory()
    make_period(other, dt.date(2024, 3, 1), None)


# ------------------------------------------------------------------ (a)
def test_a_period_from_august_leaves_july_alone_and_counts_no_crop_et_in_august(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])
    assert pumped(f4, "2025-07") == D("37.5000")
    assert gross_et(f4, "2025-08") == D("5.0000")

    response = post_add(operator_client(), f4, "2025-08-14")
    assert response.status_code == 200
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])

    assert pumped(f4, "2025-07") == D("37.5000")
    assert gross_et(f4, "2025-07") == D("30.0000")
    assert gross_et(f4, "2025-08") == D("0.0000")
    assert pumped(f4, "2025-08") == D("0.0000")
    # the satellite figure is still kept with the month's calculation
    first = CalculationRun.objects.get(parcel=f4, period="2025-08").breakdown[0]
    assert first["detail"]["fallow"] is True
    assert first["detail"]["satellite_et_af"] == "5.0000"


# ------------------------------------------------------------------ (b)
def test_an_end_month_counts_the_satellite_crop_et_again_the_month_after(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 8, 1), dt.date(2025, 8, 1))
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    assert gross_et(f4, "2025-07") == D("30.0000")
    assert gross_et(f4, "2025-08") == D("0.0000")
    assert gross_et(f4, "2025-09") == D("5.0000")


def test_ending_an_open_period_from_the_page_restores_the_months_after_it(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 8, 1), None)
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    assert gross_et(f4, "2025-09") == D("0.0000")

    response = post_end(operator_client(), f4, "2025-08-20")
    assert response.status_code == 200
    period = fallow_model().objects.get(parcel=f4)
    assert period.end_month == dt.date(2025, 8, 1)
    assert gross_et(f4, "2025-08") == D("0.0000")
    assert gross_et(f4, "2025-09") == D("5.0000")


# ------------------------------------------------------------------ (c)
def finalize(name):
    ReportingPeriod.objects.filter(name=name).update(is_finalized=True)


def test_a_period_touching_a_finalized_year_is_refused_and_nothing_changes(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    ld.run_months(["2025-08"])
    finalize("WY 2024-2025")
    requests_before = CalculationRequest.objects.count()

    response = post_add(operator_client(), f4, "2025-08-01", "2025-11-30")
    body = response.content.decode()

    assert "WY 2024-2025 is finalized. An administrator can reopen it on the water year page." in body
    assert 'role="alert"' in body
    assert fallow_model().objects.count() == 0
    assert CalculationRequest.objects.count() == requests_before
    assert gross_et(f4, "2025-08") == D("5.0000")


def test_an_open_period_starting_before_a_finalized_year_ends_is_refused(ref):
    d1 = ld.build_d1()
    finalize("WY 2024-2025")
    response = post_add(operator_client(), d1["F4"], "2025-09-01")
    assert "WY 2024-2025 is finalized." in response.content.decode()
    assert fallow_model().objects.count() == 0


def test_a_period_after_a_finalized_year_is_accepted(ref):
    d1 = ld.build_d1()
    finalize("WY 2024-2025")
    response = post_add(operator_client(), d1["F4"], "2025-10-01")
    assert "is finalized" not in response.content.decode()
    assert fallow_model().objects.filter(parcel=d1["F4"]).count() == 1


def test_ending_a_period_does_not_touch_the_finalized_year_it_began_in(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 8, 1), None)
    finalize("WY 2024-2025")
    response = post_end(operator_client(), f4, "2025-09-10")
    assert "is finalized" not in response.content.decode()
    # only the months after September change, and they are in WY 2025-2026
    assert fallow_model().objects.get(parcel=f4).end_month == dt.date(2025, 9, 1)


def test_ending_a_period_inside_a_finalized_year_is_refused_when_later_months_are_finalized(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 1, 1), None)
    finalize("WY 2024-2025")
    response = post_end(operator_client(), f4, "2025-03-05")
    assert "WY 2024-2025 is finalized." in response.content.decode()
    assert fallow_model().objects.get(parcel=f4).end_month is None


# ------------------------------------------------------------------ (d)
@pytest.mark.django_db(transaction=True)
def test_migrating_forward_from_the_old_column_keeps_the_mark_as_an_open_period():
    executor = MigrationExecutor(connection)
    executor.migrate([("parcels", "0020_change_history_lock_and_labels")])
    try:
        old = executor.loader.project_state(
            [("parcels", "0020_change_history_lock_and_labels")]
        ).apps
        OldParcel = old.get_model("parcels", "Parcel")
        marked = OldParcel.objects.create(parcel_number="MIG-A", fallow=True)
        plain = OldParcel.objects.create(parcel_number="MIG-B", fallow=False)

        executor = MigrationExecutor(connection)
        leaf = [n for n in executor.loader.graph.leaf_nodes() if n[0] == "parcels"]
        executor.migrate(leaf)

        new = executor.loader.project_state(leaf).apps
        Period = new.get_model("parcels", "FallowPeriod")
        assert [
            (p.start_month, p.end_month) for p in Period.objects.filter(parcel_id=marked.pk)
        ] == [(None, None)]
        assert Period.objects.filter(parcel_id=plain.pk).count() == 0
        assert not any(
            f.name == "fallow" for f in new.get_model("parcels", "Parcel")._meta.get_fields()
        )
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate([n for n in executor.loader.graph.leaf_nodes() if n[0] == "parcels"])
        Parcel.objects.filter(parcel_number__in=("MIG-A", "MIG-B")).delete()


# ------------------------------------------------------------------ (e)
def last_request():
    return CalculationRequest.objects.order_by("-pk").first()


def test_saving_an_open_period_requests_the_calculated_months_it_covers(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    before = CalculationRequest.objects.count()

    response = post_add(operator_client(), f4, "2025-08-20")

    assert CalculationRequest.objects.count() == before + 1
    assert last_request().months == ["2025-08", "2025-09"]
    assert "OpenH2O is recalculating August 2025 through September 2025." in response.content.decode()


def test_saving_a_closed_period_requests_only_its_own_months(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    response = post_add(operator_client(), f4, "2025-08-20", "2025-08-05")
    assert last_request().months == ["2025-08"]
    assert "OpenH2O is recalculating August 2025." in response.content.decode()


def test_ending_an_open_period_requests_the_months_it_uncovers(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 7, 1), None)
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    response = post_end(operator_client(), f4, "2025-07-31")
    assert last_request().months == ["2025-08", "2025-09"]
    assert "OpenH2O is recalculating August 2025 through September 2025." in response.content.decode()


def test_the_existing_recalculation_sentence_is_unchanged():
    from accounting.engine_run import recalculation_sentence

    assert recalculation_sentence(["2026-03"]) == (
        "OpenH2O is recalculating the fields this water serves for March 2026."
    )
    assert recalculation_sentence(["2026-03", "2026-04", "2026-05"]) == (
        "OpenH2O is recalculating the fields this water serves for March 2026 through May 2026."
    )
    assert recalculation_sentence(["2026-03", "2026-05", "2026-06"]) == (
        "OpenH2O is recalculating the fields this water serves for "
        "March 2026, May 2026 and June 2026."
    )


# ------------------------------------------------------------------ the form's other refusals
def test_two_periods_that_overlap_are_refused_with_a_sentence(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    make_period(f4, dt.date(2025, 10, 1), dt.date(2025, 12, 1))
    response = post_add(operator_client(), f4, "2025-12-15", "2026-02-01")
    assert (
        "This period overlaps the fallow period from October 2025 to December 2025."
        in response.content.decode()
    )
    assert fallow_model().objects.filter(parcel=f4).count() == 1


def test_a_start_month_is_required_and_an_end_before_the_start_is_refused(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    client = operator_client()
    missing = post_add(client, f4, "")
    assert "Pick a day in the start month." in missing.content.decode()
    backwards = post_add(client, f4, "2025-11-01", "2025-10-01")
    assert "The end month cannot be before the start month." in backwards.content.decode()
    assert fallow_model().objects.count() == 0


def test_the_start_and_end_are_stored_as_the_first_of_their_months(ref):
    d1 = ld.build_d1()
    f4 = d1["F4"]
    post_add(operator_client(), f4, "2025-10-17", "2025-12-29")
    period = fallow_model().objects.get(parcel=f4)
    assert (period.start_month, period.end_month) == (dt.date(2025, 10, 1), dt.date(2025, 12, 1))
    assert period.created_by is not None


# ------------------------------------------------------------------ the Fallow row
def row_text(parcel):
    client = operator_client()
    return client.get(reverse("parcels:detail", args=[parcel.pk])).content.decode()


def test_the_row_for_a_use_area_with_no_period_reads_not_fallow():
    field = ParcelFactory()
    body = row_text(field)
    assert "Not fallow" in body
    assert "Add fallow period" in body
    assert "End fallow period" not in body
    assert (
        "Mark the months a use area grows nothing. In a fallow month OpenH2O counts crop ET as 0. "
        "Without the mark it counts the satellite crop ET, whether or not a crop is on record."
    ) in body


def test_the_row_for_an_open_period_offers_to_end_it_and_not_to_add_one():
    field = ParcelFactory()
    make_period(field, dt.date(2026, 3, 1), None)
    body = row_text(field)
    assert "Fallow from March 2026" in body
    assert "crop ET is counted as 0 from March 2026 in this use area&#x27;s calculation" in body or (
        "crop ET is counted as 0 from March 2026 in this use area's calculation" in body
    )
    assert "End fallow period" in body
    assert "Add fallow period" not in body


def test_the_row_for_a_closed_period_lists_the_earlier_ones_underneath():
    field = ParcelFactory()
    make_period(field, dt.date(2025, 11, 1), dt.date(2025, 12, 1))
    make_period(field, dt.date(2026, 3, 1), dt.date(2026, 6, 1))
    body = row_text(field)
    assert "Fallow from March 2026 to June 2026" in body
    assert "from March 2026 through June 2026 in this use area" in body
    assert "Earlier: November 2025 to December 2025" in body
    assert "Add fallow period" in body
    assert "End fallow period" not in body


def test_the_migrated_mark_reads_fallow_and_an_earlier_one_reads_fallow_until():
    field = ParcelFactory()
    make_period(field, None, None)
    body = row_text(field)
    assert "crop ET is counted as 0 in this use area" in body
    assert "Fallow from" not in body
    closed = ParcelFactory()
    make_period(closed, None, dt.date(2026, 6, 1))
    make_period(closed, dt.date(2026, 9, 1), None)
    assert "Earlier: fallow until June 2026" in row_text(closed)


def test_there_is_no_edit_or_delete_control_for_a_period_and_no_pencil_on_the_row():
    field = ParcelFactory()
    make_period(field, dt.date(2026, 3, 1), None)
    body = row_text(field)
    assert 'title="Edit Fallow"' not in body
    assert "Delete fallow" not in body


def test_the_add_form_carries_the_approved_words():
    field = ParcelFactory()
    body = operator_client().get(add_url(field)).content.decode()
    for words in (
        "Add a fallow period",
        "Start month (pick any day in it)",
        "Choose the first full month with no crop. If the crop came out partway through a month, "
        "start with the next month. The satellite crop ET for the partial month already shows the lower use.",
        "End month (optional, pick any day in it)",
        "Leave this blank while the use area stays fallow. The use area is fallow in its end month too.",
        "Save",
        "Cancel",
    ):
        assert words in body


def test_the_end_form_asks_for_an_end_month_only():
    field = ParcelFactory()
    make_period(field, dt.date(2026, 3, 1), None)
    body = operator_client().get(end_url(field)).content.decode()
    assert "End month (pick any day in it)" in body
    assert "optional" not in body.split('id="id_end_month"')[0].rsplit("<form", 1)[-1]
    assert 'name="start_month"' not in body
    assert 'name="end_month"' in body


# ------------------------------------------------------------------ the canal division
def one_pod_three_fields(division_method="shares", fractions=("1.0000", "1.0000", "1.0000")):
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory(
        evaporation_fraction=D("0"), seepage_fraction=D("0"), spill_fraction=D("0"),
        division_method=division_method,
    )
    fields = [ParcelFactory(parcel_number=f"APN-{n}") for n in "ABC"]
    for field, fraction in zip(fields, fractions):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=field, fraction=D(fraction))
    return rp, pod, fields


def split_by_parcel(month):
    return {
        r.parcel.parcel_number: r.amount_acre_feet
        for r in ParcelLedger.objects.filter(
            source_type="surface_diversion", divided_from_headgate=True, effective_date=month
        )
    }


def record(pod, rp, month, af, kind="direct_use"):
    return DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=month,
        volume_acre_feet=D(str(af)), diversion_type=kind,
    )


# (i)
def test_three_fields_with_equal_shares_and_the_third_fallow_divide_15_15_and_0():
    rp, pod, (a, b, c) = one_pod_three_fields()
    make_period(c, MAR, MAR)
    record(pod, rp, MAR, "30.0000")
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert split_by_parcel(MAR) == {"APN-A": D("-15.0000"), "APN-B": D("-15.0000")}


def test_a_field_is_divided_normally_in_a_month_outside_its_fallow_period():
    rp, pod, (a, b, c) = one_pod_three_fields(fractions=("0.2500", "0.2500", "0.5000"))
    make_period(c, MAR, MAR)
    record(pod, rp, FEB, "30.0000")
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert split_by_parcel(FEB) == {
        "APN-A": D("-7.5000"), "APN-B": D("-7.5000"), "APN-C": D("-15.0000"),
    }


# (j)
def test_when_every_field_is_fallow_nothing_is_divided_and_the_note_names_them():
    rp, pod, fields = one_pod_three_fields()
    for field in fields:
        make_period(field, MAR, None)
    record(pod, rp, MAR, "30.0000")
    notes = []

    rows = allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)

    assert rows == []
    assert split_by_parcel(MAR) == {}
    left = UnallocatedDelivery.objects.get(point_of_diversion=pod, month=MAR)
    assert left.amount_acre_feet == D("30.0000")
    assert notes == [
        {
            "kind": "unallocated",
            "pod": pod.name,
            "month": MAR,
            "amount_af": D("30.0000"),
            "fallow_parcels": ["APN-A", "APN-B", "APN-C"],
        }
    ]


def test_the_crop_need_division_also_leaves_the_fallow_field_out():
    rp, pod, (a, b, c) = one_pod_three_fields(division_method="crop_need")
    make_period(c, MAR, None)
    record(pod, rp, MAR, "30.0000")
    allocate_district_delivery(pod, rp, efficiency=EFF)
    # no field has calculated demand yet, so the fallback shares divide it
    assert split_by_parcel(MAR) == {"APN-A": D("-15.0000"), "APN-B": D("-15.0000")}


def test_a_fallow_field_with_its_own_record_keeps_it_and_is_not_named():
    rp, pod, (a, b, c) = one_pod_three_fields()
    make_period(c, MAR, MAR)
    ParcelLedger.objects.create(
        parcel=c, transaction_date=MAR, effective_date=MAR, amount_acre_feet=D("-4.0000"),
        source_type="surface_diversion", description="Reading at the field turnout",
        reporting_period=rp,
    )
    record(pod, rp, MAR, "30.0000")
    notes = []
    allocate_district_delivery(pod, rp, efficiency=EFF, notes=notes)
    assert split_by_parcel(MAR) == {"APN-A": D("-13.0000"), "APN-B": D("-13.0000")}
    assert notes == []


# (l)
def test_a_to_storage_record_in_a_fallow_month_is_still_left_out_of_the_division():
    rp, pod, (a, b, c) = one_pod_three_fields()
    make_period(c, MAR, MAR)
    record(pod, rp, MAR, "30.0000")
    record(pod, rp, MAR, "20.0000", kind="to_storage")
    allocate_district_delivery(pod, rp, efficiency=EFF)
    assert split_by_parcel(MAR) == {"APN-A": D("-15.0000"), "APN-B": D("-15.0000")}


# (k)
def d2_with_months(*months_af):
    """D2 with extra typed records, and 30.48 mm of ET in each of those months (the engine skips a month with none)."""
    d2 = ld.build_d2()
    for month, af in months_af:
        ld.typed_record(d2["P2"], month, af)
        for key in ("G1", "G2", "G3"):
            if month != ld.AUG:
                ld.add_et(d2[key], {f"{month.year}-{month.month:02d}": "30.48"})
    return d2


def split_amount(parcel, month):
    row = ParcelLedger.objects.filter(
        parcel=parcel, source_type="surface_diversion", effective_date=month,
        divided_from_headgate=True,
    ).first()
    return row.amount_acre_feet if row else None


def test_marking_a_field_fallow_from_a_month_redivides_that_open_month_and_later_ones(ref):
    d2 = d2_with_months((ld.AUG, "100.0000"), (ld.SEP, "100.0000"))
    g1, g2, g3 = d2["G1"], d2["G2"], d2["G3"]
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    # losses 0.01 + 0.10 + 0.04 take 15 AF; 85 AF is divided 0.5 / 0.3 / 0.2
    assert split_amount(g3, ld.JUL) == D("-17.0000")
    assert split_amount(g3, ld.AUG) == D("-17.0000")
    assert split_amount(g3, ld.SEP) == D("-17.0000")

    response = post_add(operator_client(), g3, "2025-08-10")
    assert response.status_code == 200

    # August and September: 85 AF over shares 0.5 and 0.3, so 53.125 and 31.875
    assert split_amount(g1, ld.AUG) == D("-53.1250")
    assert split_amount(g2, ld.AUG) == D("-31.8750")
    assert split_amount(g3, ld.AUG) is None
    assert split_amount(g3, ld.SEP) is None
    # July is before the period and keeps its three-way split
    assert split_amount(g1, ld.JUL) == D("-42.5000")
    assert split_amount(g3, ld.JUL) == D("-17.0000")


def test_a_finalized_year_keeps_its_division_when_a_later_period_is_saved(ref):
    d2 = d2_with_months((ld.AUG, "100.0000"), (dt.date(2025, 10, 1), "30.0000"))
    g1, g2, g3 = d2["G1"], d2["G2"], d2["G3"]
    for month in ("2025-07", "2025-08", "2025-09", "2025-10"):
        ld.run_months([month])
    finalize("WY 2024-2025")
    assert split_amount(g3, dt.date(2025, 10, 1)) == D("-5.1000")

    response = post_add(operator_client(), g3, "2025-10-01")
    assert "is finalized" not in response.content.decode()

    # October: 30 AF less 15 percent in losses is 25.5 AF over shares 0.5 and 0.3
    assert split_amount(g1, dt.date(2025, 10, 1)) == D("-15.9375")
    assert split_amount(g2, dt.date(2025, 10, 1)) == D("-9.5625")
    assert split_amount(g3, dt.date(2025, 10, 1)) is None
    # the finalized year was not touched
    assert split_amount(g3, ld.AUG) == D("-17.0000")
    assert split_amount(g1, ld.AUG) == D("-42.5000")


def test_a_requested_month_redivides_every_turnout_serving_the_field(ref):
    d2 = ld.build_d2()
    g1, g3 = d2["G1"], d2["G3"]
    other = ld.make_point("D2 Second headgate", -120.51, 37.16, None, "0", "0", "0", [(g3, "1.0"), (g1, "1.0")])
    ld.typed_record(other, ld.JUL, "40.0000")
    ld.run_months(["2025-07"])
    rows = ParcelLedger.objects.filter(
        parcel=g3, source_type="surface_diversion", effective_date=ld.JUL, divided_from_headgate=True
    )
    # one share from each of the two turnouts
    assert rows.count() == 2
    make_period(g3, ld.JUL, ld.JUL)
    from accounting.engine_run import request_for_months

    request_for_months("ledger_saved", ["2025-07"])
    assert rows.count() == 0
    # the other field of the second turnout takes the whole of that turnout's water
    assert ParcelLedger.objects.filter(
        parcel=g1, source_type="surface_diversion", effective_date=ld.JUL,
        divided_from_headgate=True, divided_from_point_pk=other.pk,
    ).get().amount_acre_feet == D("-40.0000")


# ------------------------------------------------------------------ (m)
def page_world(period_months, record_months=(JAN, FEB, MAR)):
    rp, pod, (a, b, c) = one_pod_three_fields()
    for month in record_months:
        record(pod, rp, month, "30.0000")
        CalculationRun.objects.get_or_create(
            parcel=c, period=f"{month.year}-{month.month:02d}",
            defaults={"gross_et_af": D("0"), "net_consumptive_use_af": D("0"), "final_af": D("0")},
        )
    for start, end in period_months:
        make_period(c, start, end)
    return rp, pod, a, b, c


def field_page(parcel, rp):
    client = operator_client()
    return client.get(reverse("parcels:detail", args=[parcel.pk]), {"period": rp.pk}).content.decode()


def test_the_field_page_says_a_single_fallow_month_took_no_share():
    rp, pod, a, b, c = page_world([(FEB, FEB)])
    body = field_page(c, rp)
    assert (
        "This use area was fallow in February 2024, so OpenH2O gave it no share of the canal water "
        "that month. Record any water spread on it to recharge as To Storage."
    ) in body
    assert "budget-breakdown-group--under" in body


def test_the_field_page_names_a_run_of_months_once():
    rp, pod, a, b, c = page_world([(JAN, MAR)])
    body = field_page(c, rp)
    assert (
        "This use area was fallow from January 2024 to March 2024, so OpenH2O gave it no share of "
        "the canal water in those months. Record any water spread on it to recharge as To Storage."
    ) in body


def test_the_field_page_names_months_that_are_not_in_one_run():
    rp, pod, a, b, c = page_world([(JAN, JAN), (MAR, MAR)])
    body = field_page(c, rp)
    assert (
        "This use area was fallow in January 2024 and March 2024, so OpenH2O gave it no share of "
        "the canal water in those months."
    ) in body


def test_the_field_page_names_three_separate_months_with_commas():
    rp, pod, a, b, c = page_world(
        [(JAN, JAN), (MAR, MAR), (dt.date(2024, 5, 1), dt.date(2024, 5, 1))],
        record_months=(JAN, MAR, dt.date(2024, 5, 1)),
    )
    body = field_page(c, rp)
    assert "was fallow in January 2024, March 2024 and May 2024, so OpenH2O" in body


def test_the_field_page_says_nothing_for_a_fallow_month_with_no_canal_water():
    rp, pod, a, b, c = page_world([(JAN, MAR)], record_months=())
    assert "gave it no share of the canal water" not in field_page(c, rp)


def test_the_field_page_says_nothing_for_a_fallow_month_when_the_field_has_its_own_record():
    rp, pod, a, b, c = page_world([(FEB, FEB)])
    ParcelLedger.objects.create(
        parcel=c, transaction_date=FEB, effective_date=FEB, amount_acre_feet=D("-4.0000"),
        source_type="surface_diversion", description="Reading at the field turnout",
        reporting_period=rp,
    )
    assert "gave it no share of the canal water" not in field_page(c, rp)


def test_the_field_page_says_nothing_for_a_to_storage_record_alone():
    rp, pod, (a, b, c) = one_pod_three_fields()
    record(pod, rp, FEB, "30.0000", kind="to_storage")
    CalculationRun.objects.create(
        parcel=c, period="2024-02", gross_et_af=D("0"), net_consumptive_use_af=D("0"), final_af=D("0"))
    make_period(c, FEB, FEB)
    assert "gave it no share of the canal water" not in field_page(c, rp)


def test_the_turnout_page_names_the_fallow_use_area_under_its_month():
    rp, pod, a, b, c = page_world([(FEB, FEB)])
    body = operator_client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert (
        "Use area APN-C was fallow in February 2024, so OpenH2O gave it no share of this month&#x27;s water."
        in body
    ) or "Use area APN-C was fallow in February 2024, so OpenH2O gave it no share of this month's water." in body
    assert body.count("was fallow in") == 1


def test_the_turnout_page_has_one_line_for_each_fallow_use_area():
    rp, pod, (a, b, c) = one_pod_three_fields()
    record(pod, rp, FEB, "30.0000")
    make_period(b, FEB, FEB)
    make_period(c, FEB, FEB)
    body = operator_client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "Use area APN-B was fallow in February 2024" in body
    assert "Use area APN-C was fallow in February 2024" in body
    assert "Use area APN-A was fallow" not in body


def test_the_turnout_page_has_no_line_for_a_month_with_no_fallow_use_area():
    rp, pod, (a, b, c) = one_pod_three_fields()
    record(pod, rp, FEB, "30.0000")
    make_period(c, MAR, MAR)
    body = operator_client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "was fallow in" not in body


def test_the_turnout_page_has_no_line_for_a_to_storage_month():
    rp, pod, (a, b, c) = one_pod_three_fields()
    record(pod, rp, FEB, "30.0000", kind="to_storage")
    make_period(c, FEB, FEB)
    body = operator_client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "was fallow in" not in body
