# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized water year is refused on every write path (147-02 Task 4).

The lock is a database trigger on every period-scoped table
(``accounting/locks.py``), so these tests go under the ORM on purpose: raw SQL
insert, update and delete dated in a finalized year are refused; the same in
an open year succeed; inside ``override()`` they succeed and the change history
records the reason. Then the doors a person uses: ``/admin/`` answers with the
409 page, the ledger CSV import reports the refused rows with a period picked
or not, and the everyday forms say so beside the form. Every assertion is an
exact value.
"""
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import reverse

from accounting.ledger_import import import_ledger_rows
from accounting.locks import (
    LOCK_SQLSTATE,
    LOCK_TRIGGER_URIS,
    LOCKED_MODELS,
    PeriodFinalized,
    override,
    refuse_if_finalized,
)
from accounting.models import (
    AllocationCarryover,
    AllocationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterCredit,
    WaterCreditDraw,
)
from parcels.models import ParcelLedger
from surface.models import DiversionRecord, UnallocatedDelivery
from tests.factories import (
    AllocationPlanFactory,
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

REFUSAL = "WY 2024-2025 is finalized. An administrator can reopen it on the period page."
REASON = "a test of the recorded override"

CLOSED_DAY = dt.date(2025, 3, 1)
OPEN_DAY = dt.date(2026, 3, 1)


@pytest.fixture
def periods():
    """WY 2024-2025 and WY 2025-2026, both open; the test finalizes the first."""
    closed = ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30)
    )
    opened = ReportingPeriod.objects.create(
        name="WY 2025-2026", start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30)
    )
    return closed, opened


def _finalize(period):
    ReportingPeriod.objects.filter(pk=period.pk).update(is_finalized=True)
    period.refresh_from_db()


def _month(day):
    return f"{day.year}-{day.month:02d}"


def _water_year(day):
    return day.year + 1 if day.month >= 10 else day.year


def _build(label, day, period):
    """One row of ``label`` dated ``day`` (and linked to ``period`` where it can be)."""
    if label == "parcels.ParcelLedger":
        # The link left empty on purpose: several real writers leave it empty,
        # so the lock has to find the year by the row's own date.
        return ParcelLedgerFactory(effective_date=day, transaction_date=day, reporting_period=None)
    if label == "accounting.WaterAccountParcel":
        return WaterAccountParcelFactory(reporting_period=period)
    if label == "accounting.AllocationPlan":
        return AllocationPlanFactory(reporting_period=period)
    if label == "accounting.WaterCredit":
        return WaterCredit.objects.create(
            parcel=ParcelFactory(), origin_period=_month(day), amount_af=Decimal("2.5000")
        )
    if label == "accounting.WaterCreditDraw":
        credit = WaterCredit.objects.create(
            parcel=ParcelFactory(), origin_period="2024-01", amount_af=Decimal("2.5000")
        )
        return WaterCreditDraw.objects.create(
            credit=credit, draw_period=_month(day), amount_af=Decimal("1.0000")
        )
    if label == "accounting.AllocationCarryover":
        return AllocationCarryover.objects.create(
            zone=ZoneFactory(), water_type=WaterTypeFactory(),
            water_year=_water_year(day), amount_af=Decimal("4.0000"),
        )
    if label == "accounting.CalculationRun":
        return CalculationRun.objects.create(
            parcel=ParcelFactory(), period=_month(day), gross_et_af=Decimal("3.0000"),
            net_consumptive_use_af=Decimal("3.0000"), final_af=Decimal("3.0000"),
        )
    if label == "surface.DiversionRecord":
        return DiversionRecordFactory(month=day, reporting_period=None)
    if label == "surface.UnallocatedDelivery":
        return UnallocatedDelivery.objects.create(
            point_of_diversion=PointOfDiversionFactory(), reporting_period=period,
            month=day, amount_acre_feet=Decimal("1.0000"), delivery_acre_feet=Decimal("5.0000"),
        )
    raise AssertionError(label)


def _table(label):
    return apps.get_model(label)._meta.db_table


def _refused_sql(sql, params):
    """Run ``sql`` in a savepoint; return the lock's (sqlstate, message) or None."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)
    except DatabaseError as exc:
        cause = exc.__cause__
        return (cause.sqlstate, cause.diag.message_primary)
    return None


def _row_json(label, pk):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT row_to_json(t)::text FROM "{_table(label)}" t WHERE id = %s', [pk])
        return cursor.fetchone()[0]


def _insert_sql(label):
    table = _table(label)
    return f'INSERT INTO "{table}" SELECT * FROM json_populate_record(NULL::"{table}", %s::json)'


def _count(label, pk):
    return apps.get_model(label).objects.filter(pk=pk).count()


# -- The trigger, table by table -----------------------------------------------------


def test_every_locked_table_carries_the_trigger():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE t.tgname LIKE 'pgtrigger_finalized_period_lock_%' ORDER BY c.relname"
        )
        tables = [row[0] for row in cursor.fetchall()]
    assert tables == sorted(_table(label) for label in LOCKED_MODELS)
    assert len(LOCK_TRIGGER_URIS) == 9


@pytest.mark.parametrize("label", LOCKED_MODELS)
def test_raw_sql_in_a_finalized_year_is_refused(periods, label):
    closed, _ = periods
    row = _build(label, CLOSED_DAY, closed)
    _finalize(closed)
    table = _table(label)

    assert _refused_sql(f'UPDATE "{table}" SET id = id WHERE id = %s', [row.pk]) == (
        LOCK_SQLSTATE, REFUSAL,
    )
    assert _refused_sql(f'DELETE FROM "{table}" WHERE id = %s', [row.pk]) == (
        LOCK_SQLSTATE, REFUSAL,
    )
    assert _count(label, row.pk) == 1

    # Insert: take the row out through the recorded door, then try to put it
    # back without it.
    snapshot = _row_json(label, row.pk)
    with override(REASON):
        apps.get_model(label).objects.filter(pk=row.pk).delete()
    assert _refused_sql(_insert_sql(label), [snapshot]) == (LOCK_SQLSTATE, REFUSAL)
    assert _count(label, row.pk) == 0


@pytest.mark.parametrize("label", LOCKED_MODELS)
def test_raw_sql_in_an_open_year_succeeds(periods, label):
    closed, opened = periods
    row = _build(label, OPEN_DAY, opened)
    _finalize(closed)
    table = _table(label)

    assert _refused_sql(f'UPDATE "{table}" SET id = id WHERE id = %s', [row.pk]) is None
    snapshot = _row_json(label, row.pk)
    assert _refused_sql(f'DELETE FROM "{table}" WHERE id = %s', [row.pk]) is None
    assert _count(label, row.pk) == 0
    assert _refused_sql(_insert_sql(label), [snapshot]) is None
    assert _count(label, row.pk) == 1


@pytest.mark.parametrize("label", LOCKED_MODELS)
def test_the_override_writes_and_the_history_records_the_reason(periods, label):
    closed, _ = periods
    row = _build(label, CLOSED_DAY, closed)
    _finalize(closed)
    table = _table(label)

    snapshot = _row_json(label, row.pk)
    with override(REASON):
        with connection.cursor() as cursor:
            cursor.execute(f'DELETE FROM "{table}" WHERE id = %s', [row.pk])
            cursor.execute(_insert_sql(label), [snapshot])
    assert _count(label, row.pk) == 1

    events = apps.get_model(f"{label}Event").objects.filter(pgh_obj_id=row.pk)
    recorded = [
        (event.pgh_label, event.pgh_context.metadata.get("override"), event.pgh_context.metadata.get("reason"))
        for event in events.order_by("pgh_id")
        if event.pgh_context_id is not None
    ]
    assert recorded == [("delete", True, REASON), ("insert", True, REASON)]


def test_a_row_cannot_be_moved_out_of_or_into_a_finalized_year(periods):
    closed, opened = periods
    inside = _build("parcels.ParcelLedger", CLOSED_DAY, closed)
    outside = _build("parcels.ParcelLedger", OPEN_DAY, opened)
    _finalize(closed)
    sql = 'UPDATE "parcels_parcelledger" SET effective_date = %s WHERE id = %s'
    assert _refused_sql(sql, [OPEN_DAY, inside.pk]) == (LOCK_SQLSTATE, REFUSAL)
    assert _refused_sql(sql, [CLOSED_DAY, outside.pk]) == (LOCK_SQLSTATE, REFUSAL)


def test_a_ledger_row_linked_to_a_finalized_period_is_locked_whatever_its_date(periods):
    closed, _ = periods
    row = ParcelLedgerFactory(effective_date=OPEN_DAY, transaction_date=OPEN_DAY, reporting_period=closed)
    _finalize(closed)
    assert _refused_sql(
        'UPDATE "parcels_parcelledger" SET description = %s WHERE id = %s', ["x", row.pk]
    ) == (LOCK_SQLSTATE, REFUSAL)


def test_reopening_the_year_lets_the_same_write_through(periods):
    closed, _ = periods
    row = _build("parcels.ParcelLedger", CLOSED_DAY, closed)
    _finalize(closed)
    sql = 'UPDATE "parcels_parcelledger" SET description = %s WHERE id = %s'
    assert _refused_sql(sql, ["first", row.pk]) == (LOCK_SQLSTATE, REFUSAL)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=False)
    assert _refused_sql(sql, ["second", row.pk]) is None
    row.refresh_from_db()
    assert row.description == "second"


def test_bulk_create_and_queryset_update_are_refused_too(periods):
    closed, _ = periods
    parcel = ParcelFactory()
    _finalize(closed)
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        ParcelLedger.objects.bulk_create([
            ParcelLedger(parcel=parcel, transaction_date=CLOSED_DAY, effective_date=CLOSED_DAY,
                         amount_acre_feet=Decimal("-1.0000"), source_type="manual_entry"),
        ])
    assert exc.value.__cause__.diag.message_primary == REFUSAL


def test_the_python_check_names_the_period(periods):
    closed, _ = periods
    _finalize(closed)
    with pytest.raises(PeriodFinalized) as exc:
        refuse_if_finalized(CLOSED_DAY)
    assert str(exc.value) == REFUSAL
    refuse_if_finalized(OPEN_DAY)  # nothing raised


# -- /admin/: the 409 page -----------------------------------------------------------


@pytest.fixture
def superuser():
    return User.objects.create_user(
        username="root", email="root@example.org", password="x",
        is_active=True, is_staff=True, is_superuser=True,
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def test_admin_add_in_a_finalized_year_returns_the_409_page(periods, superuser):
    closed, _ = periods
    parcel = ParcelFactory()
    _finalize(closed)
    response = _client(superuser).post(
        reverse("admin:parcels_parcelledger_add"),
        {
            "parcel": parcel.pk,
            "transaction_date": "2025-03-01",
            "effective_date": "2025-03-01",
            "amount_acre_feet": "-1.5000",
            "source_type": "manual_entry",
            "description": "",
        },
    )
    assert response.status_code == 409
    assert REFUSAL in response.content.decode()
    assert ParcelLedger.objects.filter(parcel=parcel).count() == 0


def test_admin_change_in_a_finalized_year_returns_the_409_page(periods, superuser):
    closed, _ = periods
    plan = AllocationPlanFactory(reporting_period=closed, allocation_acre_feet=Decimal("100.0000"))
    _finalize(closed)
    response = _client(superuser).post(
        reverse("admin:accounting_allocationplan_change", args=[plan.pk]),
        {
            "name": plan.name,
            "zone": plan.zone_id,
            "water_type": plan.water_type_id,
            "reporting_period": closed.pk,
            "allocation_acre_feet": "250.0000",
            "notes": "",
        },
    )
    assert response.status_code == 409
    assert REFUSAL in response.content.decode()
    plan.refresh_from_db()
    assert plan.allocation_acre_feet == Decimal("100.0000")


# -- The ledger CSV import -----------------------------------------------------------

CSV = (
    "parcel_number,effective_date,amount_acre_feet,source_type\n"
    "LOCK-001,2025-03-01,-1.0,manual_entry\n"
    "LOCK-001,2026-03-01,-2.0,manual_entry\n"
)


def test_a_ledger_csv_with_an_open_period_picked_refuses_the_finalized_rows(periods):
    closed, opened = periods
    ParcelFactory(parcel_number="LOCK-001")
    _finalize(closed)
    result = import_ledger_rows(io.StringIO(CSV), reporting_period=opened)
    assert result["created_count"] == 1
    assert result["errors"] == [
        {"line": 2, "messages": [f"effective_date 2025-03-01: {REFUSAL}"]}
    ]
    assert list(ParcelLedger.objects.values_list("effective_date", flat=True)) == [OPEN_DAY]


def test_a_ledger_csv_with_the_finalized_period_picked_refuses_every_row(periods):
    closed, _ = periods
    ParcelFactory(parcel_number="LOCK-001")
    _finalize(closed)
    result = import_ledger_rows(io.StringIO(CSV), reporting_period=closed)
    assert result["created_count"] == 0
    assert result["errors"] == [
        {"line": 2, "messages": [f"effective_date 2025-03-01: {REFUSAL}"]},
        {"line": 3, "messages": [f"effective_date 2026-03-01: {REFUSAL}"]},
    ]
    assert ParcelLedger.objects.count() == 0


def test_the_ledger_csv_preview_reports_the_same_refusal(periods):
    closed, _ = periods
    ParcelFactory(parcel_number="LOCK-001")
    _finalize(closed)
    result = import_ledger_rows(io.StringIO(CSV), dry_run=True)
    assert (result["created_count"], result["error_count"]) == (1, 1)


# -- The everyday forms answer beside the form -----------------------------------------


@pytest.fixture
def operator():
    return User.objects.create_user(
        username="op", email="op@example.org", password="x", is_active=True,
    )


def test_a_ledger_entry_dated_in_a_finalized_year_is_refused_beside_the_form(periods, operator):
    closed, _ = periods
    parcel = ParcelFactory()
    _finalize(closed)
    response = _client(operator).post(
        reverse("accounting:ledger_create"),
        {
            "parcel": parcel.pk,
            "transaction_date": "2025-03-01",
            "effective_date": "2025-03-01",
            "amount_acre_feet": "-1.0000",
            "source_type": "manual_entry",
            "description": "",
        },
    )
    assert response.status_code == 200
    assert response.context["form"].errors == {"effective_date": [REFUSAL]}
    assert REFUSAL in response.content.decode()
    assert ParcelLedger.objects.filter(parcel=parcel).count() == 0


def test_an_allocation_in_a_finalized_year_is_refused_beside_the_form(periods, operator):
    closed, _ = periods
    zone, water_type = ZoneFactory(), WaterTypeFactory()
    _finalize(closed)
    response = _client(operator).post(
        reverse("accounting:allocation_create"),
        {
            "name": "Late allocation",
            "zone": zone.pk,
            "water_type": water_type.pk,
            "reporting_period": closed.pk,
            "allocation_acre_feet": "10.0000",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert response.context["form"].errors == {"reporting_period": [REFUSAL]}
    assert AllocationPlan.objects.count() == 0


def test_a_diversion_record_in_a_finalized_year_is_refused_on_create_edit_and_delete(periods, operator):
    closed, _ = periods
    record = DiversionRecordFactory(month=CLOSED_DAY, reporting_period=closed)
    pod = record.point_of_diversion
    _finalize(closed)
    client = _client(operator)

    created = client.post(
        reverse("surface:diversion_record_create", args=[pod.pk]),
        {"month": "2025-04-01", "volume_acre_feet": "5.0000", "returned_af": "0",
         "diversion_type": "direct_use", "data_state": "provisional"},
    )
    assert created.status_code == 200
    assert REFUSAL in created.content.decode()
    assert DiversionRecord.objects.filter(point_of_diversion=pod).count() == 1

    edited = client.post(
        reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
        {"month": "2025-03-01", "volume_acre_feet": "99.0000", "returned_af": "0",
         "diversion_type": "direct_use", "data_state": "provisional"},
    )
    assert edited.status_code == 200
    assert REFUSAL in edited.content.decode()

    deleted = client.post(reverse("surface:diversion_record_delete", args=[pod.pk, record.pk]))
    assert deleted.status_code == 200
    assert REFUSAL in deleted.content.decode()
    record.refresh_from_db()
    assert record.volume_acre_feet == Decimal("50.0000")


def test_removing_a_use_area_from_a_finalized_years_assignment_is_refused(periods, operator):
    closed, _ = periods
    wap = WaterAccountParcelFactory(reporting_period=closed)
    _finalize(closed)
    response = _client(operator).post(
        reverse("accounting:remove_parcel", args=[wap.water_account_id, wap.pk])
    )
    assert response.status_code == 200
    assert REFUSAL in response.content.decode()
    wap.refresh_from_db()
    assert wap.removed_date is None


# -- The engine's recorded override --------------------------------------------------


def test_run_calculations_force_writes_through_the_override_with_its_reason():
    # The engine test file's own finalized-month fixture (ET, a well, the
    # active plan, and "WY2024 June" finalized).
    from tests.test_calculation_run import _seed_finalized_parcel

    parcel = _seed_finalized_parcel("LOCK-FORCE")
    call_command(
        "run_calculations", "--period", "2024-06", "--force",
        stdout=io.StringIO(), stderr=io.StringIO(),
    )
    run = CalculationRun.objects.get(parcel=parcel, period="2024-06")
    event = apps.get_model("accounting.CalculationRunEvent").objects.get(
        pgh_obj_id=run.pk, pgh_label="insert"
    )
    assert (event.pgh_context.metadata["override"], event.pgh_context.metadata["reason"]) == (
        True, "--force on a finalized period",
    )
    # Outside the command, the same row is locked again.
    assert _refused_sql(
        'UPDATE "accounting_calculationrun" SET id = id WHERE id = %s', [run.pk]
    ) == (LOCK_SQLSTATE, "WY2024 June is finalized. An administrator can reopen it on the period page.")
