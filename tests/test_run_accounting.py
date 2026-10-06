# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-01 Task 2: one orchestrator and a run record (accounting/engine_run.py).

The calculation for a month is crop water use, the canal division, then crop
water use again. ``run_accounting`` runs that for every month of a period (or
named months), oldest first, one transaction per month, one run at a time, and
leaves a ``CalculationRequest`` saying in words how it went.

Fixture: a three-month period (January to March 2024), three well-irrigated
10-acre fields A, B and C that one canal point of diversion serves, crop water
use data for January and February only (10 acres at 304.8 mm is exactly
10.0000 AF), a 30 AF delivery in January and 25 AF in February, and one
hand-entered 4 AF delivery to field A in January (the field's own record).

Every assertion is a stored value or a literal sentence. Where the
orchestrator must equal "the hand sequence", the test runs the hand sequence
first, takes a snapshot of what it stored, wipes what the calculation wrote,
runs ``run_accounting`` and compares the two snapshots. No test recomputes the
calculation's formulas.

Advisory locks are session-level, so the two-worker test needs no committed
data: a second connection takes the lock and the first sees it refused.
"""
import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import override_settings

from accounting import engine_run
from accounting.engine_run import ADVISORY_LOCK_KEY, create_request, run_queue
from accounting.models import CalculationRequest, CalculationRun, ReportingPeriod
from core.modules import ALL_MODULE_NAMES
from parcels.models import ParcelLedger
from surface.models import UnallocatedDelivery
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_calculation_run import _et_cache, _irrigate, _parcel, _surface_row

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)
FEB = date(2024, 2, 1)
ET_MM = 304.8  # exactly 10.0000 AF over 10 acres

NO_DATA_MARCH = (
    "No crop water use data for March 2024 yet; it will be calculated when "
    "the data arrives."
)

_WITHOUT_SURFACE = tuple(
    n for n in ALL_MODULE_NAMES if n not in ("surface", "recharge")
)


class World:
    """The fixture's rows, by name."""


@pytest.fixture
def world():
    w = World()
    call_command("seed_calculation_plan")
    w.period = ReportingPeriodFactory(
        name="Winter 2024", start_date=date(2024, 1, 1), end_date=date(2024, 3, 31)
    )
    w.fields = []
    for number in ("RA-A", "RA-B", "RA-C"):
        parcel = _parcel(number, acres="10")
        _irrigate(parcel)
        WellIrrigatedParcelFactory(parcel=parcel)
        _et_cache(parcel, period="2024-01", et_mm=ET_MM)
        _et_cache(parcel, period="2024-02", et_mm=ET_MM)
        w.fields.append(parcel)
    w.a, w.b, w.c = w.fields
    w.pod = PointOfDiversionFactory(name="Test Canal Headgate")
    for parcel, fraction in zip(w.fields, ("0.3333", "0.3333", "0.3334")):
        PointOfDiversionParcelFactory(
            point_of_diversion=w.pod, parcel=parcel, fraction=Decimal(fraction)
        )
    DiversionRecordFactory(
        point_of_diversion=w.pod, reporting_period=w.period, month=JAN,
        volume_acre_feet=Decimal("30"),
    )
    DiversionRecordFactory(
        point_of_diversion=w.pod, reporting_period=w.period, month=FEB,
        volume_acre_feet=Decimal("25"),
    )
    # Field A's own recorded delivery for January.
    w.own = _surface_row(w.a, "2024-01", af=4)
    return w


def _quiet():
    return io.StringIO()


def _snapshot():
    """What the calculation stored, with no row ids: ledger, runs, unexplained canal water."""
    ledger = sorted(
        (r.parcel_id, r.effective_date, r.source_type, r.amount_acre_feet)
        for r in ParcelLedger.objects.all()
    )
    runs = sorted(
        (
            r.parcel_id, r.period, r.gross_et_af, r.net_consumptive_use_af,
            r.surface_water_af, r.final_af, r.over_delivery_af,
        )
        for r in CalculationRun.objects.all()
    )
    unexplained = sorted(
        (u.point_of_diversion_id, u.month, u.amount_acre_feet)
        for u in UnallocatedDelivery.objects.all()
    )
    return {"ledger": ledger, "runs": runs, "unexplained": unexplained}


def _hand_sequence(w):
    """Crop water use, the canal division, crop water use again, per month."""
    for first in (JAN, FEB):
        text = f"{first:%Y-%m}"
        call_command("run_calculations", period=text, stdout=_quiet())
        allocate_district_delivery(w.pod, None, months=[first])
        call_command("run_calculations", period=text, stdout=_quiet())


def _run_months(*months):
    args = []
    for month in months:
        args += ["--month", month]
    call_command("run_accounting", *args, stdout=_quiet(), stderr=_quiet())
    return CalculationRequest.objects.order_by("-pk").first()


# --------------------------------------------------------------------------
# (a) equal to the hand sequence
# --------------------------------------------------------------------------


def test_two_months_equal_the_hand_sequence(world):
    keep = set(ParcelLedger.objects.values_list("id", flat=True))

    _hand_sequence(world)
    expected = _snapshot()
    ParcelLedger.objects.exclude(id__in=keep).delete()
    CalculationRun.objects.all().delete()
    UnallocatedDelivery.objects.all().delete()
    assert _snapshot()["runs"] == []  # the wipe left only the fixture

    req = _run_months("2024-01", "2024-02")

    assert _snapshot() == expected
    # The hand sequence is not empty: six runs (three fields, two months), each
    # reading exactly 10.0000 AF of gross crop water use.
    assert len(expected["runs"]) == 6
    assert {r[2] for r in expected["runs"]} == {Decimal("10.0000")}
    # Field A's own January record survived untouched: same row, same amount.
    own = ParcelLedger.objects.get(pk=world.own.pk)
    assert own.amount_acre_feet == Decimal("-4.0000")
    assert own.source_type == "surface_diversion"
    # The record of the run.
    assert req.months == ["2024-01", "2024-02"]
    assert req.months_done == 2
    assert req.outcome == "Calculated 2 months, January 2024 to February 2024."
    assert req.status in ("succeeded", "finished_with_notes")
    assert req.finished_at is not None
    assert req.trigger == "command"


# --------------------------------------------------------------------------
# (b) idempotent
# --------------------------------------------------------------------------


def test_running_again_changes_nothing(world):
    _run_months("2024-01", "2024-02")
    first = _snapshot()

    _run_months("2024-01", "2024-02")

    assert _snapshot() == first
    assert CalculationRequest.objects.count() == 2
    assert len(first["runs"]) == 6


# --------------------------------------------------------------------------
# (c) a finalized period: refused, nothing changes
# --------------------------------------------------------------------------


def test_finalized_period_is_refused_and_nothing_changes(world):
    before = _snapshot()
    ReportingPeriod.objects.filter(pk=world.period.pk).update(is_finalized=True)

    with pytest.raises(CommandError, match="is finalized"):
        call_command(
            "run_accounting", "--period", "Winter 2024", stdout=_quiet(), stderr=_quiet()
        )

    req = CalculationRequest.objects.get()
    assert req.status == "failed"
    assert req.outcome == (
        "Winter 2024 is finalized. An administrator can reopen it on the period page."
    )
    assert req.months_done == 0
    assert _snapshot() == before
    assert CalculationRun.objects.count() == 0


def test_months_inside_a_finalized_period_are_refused_too(world):
    before = _snapshot()
    ReportingPeriod.objects.filter(pk=world.period.pk).update(is_finalized=True)

    req = create_request("command", months=["2024-02"])
    run_queue()

    req.refresh_from_db()
    assert req.status == "failed"
    assert req.outcome.startswith("Winter 2024 is finalized.")
    assert _snapshot() == before


# --------------------------------------------------------------------------
# (d) a month that raises: earlier months kept, that month unchanged
# --------------------------------------------------------------------------


def test_a_failing_month_keeps_the_earlier_month_and_changes_nothing_in_itself(
    world, monkeypatch
):
    import surface.services as services

    real = services.allocate_district_delivery

    def explode_in_february(pod, reporting_period, **kwargs):
        if kwargs.get("months") == [FEB]:
            raise RuntimeError("boom")
        return real(pod, reporting_period, **kwargs)

    monkeypatch.setattr(services, "allocate_district_delivery", explode_in_february)
    req = create_request("command", months=["2024-01", "2024-02"])

    run_queue()

    req.refresh_from_db()
    assert req.status == "failed"
    assert req.months_done == 1
    assert req.outcome == (
        "The calculation stopped at February 2024 with an error the platform did "
        "not expect. Nothing in February 2024 was changed. The details are on "
        "Site Health for an administrator. January 2024 was calculated and kept."
    )
    assert req.error_detail.startswith("RuntimeError: boom\nMonth: 2024-02\n")
    # January is there; February is exactly as the fixture left it.
    assert set(CalculationRun.objects.values_list("period", flat=True)) == {"2024-01"}
    assert CalculationRun.objects.count() == 3
    assert not ParcelLedger.objects.filter(
        effective_date=FEB, source_type__in=("calculated", "surface_diversion")
    ).exists()


# --------------------------------------------------------------------------
# (e) a month with no crop water use data is a note
# --------------------------------------------------------------------------


def test_a_month_without_data_becomes_one_note(world):
    # A year in progress always has months whose data has not arrived; that is
    # a note, not a reason for the run (or Site Health) to read as a problem.
    req = _run_months_for_period("Winter 2024")

    assert req.status == "succeeded"
    assert req.months == ["2024-01", "2024-02"]
    assert req.outcome == "Calculated 2 months, January 2024 to February 2024."
    assert req.notes[0] == NO_DATA_MARCH
    assert not CalculationRun.objects.filter(period="2024-03").exists()


def test_months_with_no_data_at_all_are_a_note_and_not_a_failure(world):
    req = _run_months("2024-03")

    assert req.status == "succeeded"
    assert req.months == []
    assert req.outcome == "There was no crop water use data to calculate yet."
    assert req.notes == [NO_DATA_MARCH]
    assert CalculationRun.objects.count() == 0


def test_months_to_run_names_a_range_when_several_months_are_left_out(world):
    months, notes = engine_run.months_to_run(
        months=["2024-01", "2024-02", "2024-03", "2024-04"]
    )

    assert months == ["2024-01", "2024-02"]
    assert notes == [
        "No crop water use data for March 2024 through April 2024 yet; they "
        "will be calculated when the data arrives."
    ]


def _run_months_for_period(name):
    call_command("run_accounting", "--period", name, stdout=_quiet(), stderr=_quiet())
    return CalculationRequest.objects.order_by("-pk").first()


# --------------------------------------------------------------------------
# (f) one at a time
# --------------------------------------------------------------------------


def test_a_second_worker_leaves_its_request_queued_until_the_lock_is_free(world):
    req = create_request("command", months=["2024-01", "2024-02"])
    other = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
            assert cursor.fetchone()[0] is True

        assert run_queue() == []
        req.refresh_from_db()
        assert req.status == "queued"
        assert req.started_at is None
        assert CalculationRun.objects.count() == 0

        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
            assert cursor.fetchone()[0] is True
    finally:
        other.close()

    assert run_queue() == [req.pk]
    req.refresh_from_db()
    assert req.status in ("succeeded", "finished_with_notes")
    assert req.months_done == 2
    assert CalculationRun.objects.count() == 6


def test_the_lock_is_released_after_a_run(world):
    create_request("command", months=["2024-01"])
    run_queue()

    other = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
            assert cursor.fetchone()[0] is True
    finally:
        other.close()


def test_two_queued_requests_for_the_same_months_run_once(world):
    first = create_request("screen", months=["2024-01", "2024-02"])
    second = create_request("diversion_saved", months=["2024-02"])

    ran = run_queue()

    assert ran == [first.pk, second.pk]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.trigger == "screen"
    assert first.months == ["2024-01", "2024-02"]
    assert second.status == first.status
    assert second.outcome == first.outcome == (
        "Calculated 2 months, January 2024 to February 2024."
    )
    assert second.finished_at == first.finished_at
    assert CalculationRun.objects.count() == 6


def test_requests_for_different_months_run_separately_oldest_first(world):
    jan = create_request("command", months=["2024-01"])
    feb = create_request("command", months=["2024-02"])

    assert run_queue() == [jan.pk, feb.pk]

    jan.refresh_from_db()
    feb.refresh_from_db()
    assert jan.outcome == "Calculated January 2024."
    assert feb.outcome == "Calculated February 2024."
    assert jan.finished_at <= feb.started_at


# --------------------------------------------------------------------------
# (g) surface off: crop water use only
# --------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_with_surface_switched_off_only_crop_water_use_runs(world):
    req = _run_months("2024-01", "2024-02")

    assert req.status == "succeeded"
    assert req.notes == []
    assert req.outcome == "Calculated 2 months, January 2024 to February 2024."
    assert CalculationRun.objects.count() == 6
    # No canal division: field A's own record is the only surface row.
    surface = ParcelLedger.objects.filter(source_type="surface_diversion")
    assert list(surface.values_list("pk", flat=True)) == [world.own.pk]


# --------------------------------------------------------------------------
# The change history names the person; Site Health is kept current
# --------------------------------------------------------------------------


def test_the_person_who_asked_is_recorded_on_every_change(world):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        username="operator", password="x", is_active=True
    )
    create_request("screen", months=["2024-01"], requested_by=user)

    run_queue()

    run = CalculationRun.objects.filter(period="2024-01").first()
    events = list(run.events.all())
    assert events
    assert {e.pgh_context.metadata["user"] for e in events} == {user.pk}


def test_a_finished_run_writes_the_site_health_record(world):
    from health.models import HealthCheckResult

    req = _run_months("2024-01", "2024-02")

    result = HealthCheckResult.objects.get(category="calculation")
    assert result.details["request_id"] == req.pk
    assert result.message.startswith("Last calculated ")


def test_a_site_health_failure_never_changes_the_run_status(world, monkeypatch):
    import health.checks

    def broken():
        raise RuntimeError("health is down")

    monkeypatch.setattr(health.checks, "check_calculation", broken)

    req = _run_months("2024-01", "2024-02")

    assert req.status in ("succeeded", "finished_with_notes")
    assert req.outcome == "Calculated 2 months, January 2024 to February 2024."


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_the_command_runs_a_request_that_already_exists(world):
    req = create_request("screen", months=["2024-01"])

    call_command("run_accounting", request=req.pk, stdout=_quiet(), stderr=_quiet())

    req.refresh_from_db()
    assert req.outcome == "Calculated January 2024."
    assert req.trigger == "screen"


def test_the_command_names_a_missing_period(world):
    with pytest.raises(CommandError, match="There is no reporting period named 'Nope'"):
        call_command("run_accounting", "--period", "Nope", stdout=_quiet())


def test_the_command_has_no_force_option():
    from accounting.management.commands.run_accounting import Command

    parser = Command().create_parser("manage.py", "run_accounting")
    options = {s for action in parser._actions for s in action.option_strings}
    assert "--force" not in options
    assert {"--period", "--month", "--open-periods", "--request", "--trigger"} <= options


def test_open_periods_skips_a_finalized_one(world):
    ReportingPeriodFactory(
        name="Old year", start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
        is_finalized=True,
    )

    call_command("run_accounting", "--open-periods", stdout=_quiet(), stderr=_quiet())

    req = CalculationRequest.objects.get()
    assert req.reporting_period.name == "Winter 2024"


def test_own_records_over_the_headgate_are_the_note_that_needs_attention(world):
    # Field A's own record is raised to 34 AF against a 30 AF January headgate.
    ParcelLedger.objects.filter(pk=world.own.pk).update(
        amount_acre_feet=Decimal("-34")
    )

    req = _run_months("2024-01")

    assert req.status == "finished_with_notes"
    assert req.notes[0] == (
        "Fields' own delivery records at Test Canal Headgate add up to 4.00 AF "
        "more than the headgate recorded for January 2024."
    )
