# SPDX-License-Identifier: AGPL-3.0-or-later
"""The change history is append-only: the database refuses to update or delete
a recorded change, however the statement arrives.

The lock is on the event tables (``core/history.py`` ``track_changes``). The
table that says who made a change (``pghistory_context``) is not locked, because
pghistory updates it when a nested context adds a note.
"""

import datetime
import decimal
import uuid

import pghistory
import pghistory.models as pghistory_models
import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction

from core.changes import event_models
from core.history import change_note
from geography.models import Zone, ZoneEvent

from .factories import ZoneFactory

pytestmark = pytest.mark.django_db

LABELS = sorted(event_models())


def _filler(field):
    """A value for a required column; only the database sees it."""
    kind = field.get_internal_type()
    if field.choices:
        return field.choices[0][0]
    if kind in {"CharField", "TextField", "SlugField", "EmailField", "URLField"}:
        return "x"
    if kind == "BooleanField":
        return False
    if kind == "DecimalField":
        return decimal.Decimal("0")
    if kind in {"FloatField"}:
        return 0.0
    if kind == "DateField":
        return datetime.date(2020, 1, 1)
    if kind == "DateTimeField":
        return datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    if kind == "TimeField":
        return datetime.time(0, 0)
    if kind == "UUIDField":
        return uuid.uuid4()
    if kind == "JSONField":
        return {}
    if kind == "DurationField":
        return datetime.timedelta(0)
    return 1


def _event_row(event_model):
    """One recorded event on ``event_model``: an insert, which is allowed."""
    values = {}
    for field in event_model._meta.concrete_fields:
        if field.primary_key and field.get_internal_type() == "AutoField":
            continue
        if field.name in {"pgh_created_at", "pgh_label", "pgh_context"}:
            continue
        if field.null or field.has_default():
            continue
        values[field.attname] = _filler(field)
    values["pgh_label"] = "insert"
    values["pgh_obj_id"] = 1
    return event_model.objects.create(**values)


def _refused(sql, params):
    """True when the statement raises a database error in its own savepoint."""
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    except DatabaseError:
        return True
    return False


@pytest.mark.parametrize("label", LABELS)
def test_an_event_table_refuses_an_update_and_a_delete(label):
    event_model = event_models()[label]
    table = event_model._meta.db_table
    row = _event_row(event_model)

    assert _refused(
        f'UPDATE "{table}" SET pgh_label = pgh_label WHERE pgh_id = %s', [row.pgh_id]
    )
    assert _refused(f'DELETE FROM "{table}" WHERE pgh_id = %s', [row.pgh_id])
    assert event_model.objects.filter(pgh_id=row.pgh_id).count() == 1


def test_the_orm_cannot_change_or_remove_a_recorded_change_either():
    zone = ZoneFactory()
    event = ZoneEvent.objects.get(pgh_obj_id=zone.id)
    with pytest.raises(DatabaseError), transaction.atomic():
        ZoneEvent.objects.filter(pgh_id=event.pgh_id).update(name="Rewritten")
    with pytest.raises(DatabaseError), transaction.atomic():
        event.delete()
    assert ZoneEvent.objects.filter(pgh_id=event.pgh_id).count() == 1


def test_every_event_table_carries_the_trigger_in_the_database():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND t.tgname LIKE %s",
            ["%append_only%"],
        )
        locked = {name for (name,) in cursor.fetchall()}
    tables = {m._meta.db_table for m in event_models().values()}
    assert tables
    assert tables <= locked


def test_recording_still_works():
    zone = ZoneFactory(name="Before")
    zone.name = "After"
    zone.save()
    labels = list(
        ZoneEvent.objects.filter(pgh_obj_id=zone.id)
        .order_by("pgh_id")
        .values_list("pgh_label", flat=True)
    )
    assert labels == ["insert", "before_update", "update"]
    zone_id = zone.id
    zone.delete()
    assert ZoneEvent.objects.filter(pgh_obj_id=zone_id, pgh_label="delete").count() == 1


def test_the_note_still_saves_inside_an_open_context():
    with pghistory.context(command="a-command"):
        with change_note("Board asked for it"):
            zone = ZoneFactory()
    event = ZoneEvent.objects.get(pgh_obj_id=zone.id)
    assert event.pgh_context.metadata["note"] == "Board asked for it"
    assert event.pgh_context.metadata["command"] == "a-command"


def test_the_context_table_is_not_locked():
    with pghistory.context(command="x"):
        ZoneFactory()
    context = pghistory_models.Context.objects.get()
    pghistory_models.Context.objects.filter(id=context.id).update(metadata={"a": 1})
    assert pghistory_models.Context.objects.get(id=context.id).metadata == {"a": 1}


def test_the_golden_build_still_empties_every_event_table_and_the_context():
    for model in event_models().values():
        _event_row(model)
    with pghistory.context(command="test"):
        ZoneFactory()
    call_command("clear_change_history", "--golden-build")
    for model in event_models().values():
        assert model.objects.count() == 0
    assert pghistory_models.Context.objects.count() == 0


def test_the_list_of_doors_is_every_tracked_event_table():
    from core.demonstration import history_lock_uris

    expected = {
        f"{model._meta.app_label}.{model.__name__}:append_only"
        for model in event_models().values()
    }
    assert set(history_lock_uris()) == expected
    assert len(history_lock_uris()) == len(event_models())


def test_forgetting_a_context_deletes_its_events_and_only_its_events():
    with pghistory.context(command="mine") as mine:
        ZoneFactory(name="Mine")
    with pghistory.context(command="theirs"):
        ZoneFactory(name="Theirs")
    from core.demonstration import forget_events

    # The context closes first, as the load and the removal do; only the
    # demonstration's own clean-up goes through the door.
    forget_events(mine.id)
    assert list(Zone.objects.order_by("name").values_list("name", flat=True)) == [
        "Mine",
        "Theirs",
    ]
    assert ZoneEvent.objects.filter(name="Mine").count() == 0
    assert ZoneEvent.objects.filter(name="Theirs").count() == 1
    assert not pghistory_models.Context.objects.filter(id=mine.id).exists()
    # The door shut behind it.
    row = ZoneEvent.objects.get(name="Theirs")
    assert _refused(
        f'DELETE FROM "{ZoneEvent._meta.db_table}" WHERE pgh_id = %s', [row.pgh_id]
    )
