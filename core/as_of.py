# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the records as they stood on a past day, with no change to any calculation.

:func:`reading_as_of` opens one transaction and, for each table that feeds a
printed figure, creates a temporary table of the SAME NAME filled with the rows
as they stood at the moment asked for. Postgres searches temporary tables
before the real ones, so every existing query (``account_balance``,
``ParcelLedger.objects.current()``, a page's own SQL) reads the past as it is
written today. There is no second code path for the arithmetic because there is
no second code path. The block then sets the transaction read-only, which
refuses a write to any table that was not rebuilt, and it always rolls back, so
nothing done inside it is kept.

**THE RULE** (one select per table, :func:`_select_sql`): look at each row's
FIRST change-history event after the moment. A ``before_update`` or a
``delete`` carries the row exactly as it stood. An ``insert`` means the row did
not exist yet. A row with no event after the moment is the live row as it is.
Either way ``created_at``, where the table has one, must be at or before the
moment. Reading the latest event at or before the moment looks equivalent and is
not: it brings back a row whose only record is an old insert and whose live row
is long gone, and it drops a row whose only event is a delete.

A column the event table does not copy comes from the live row (a shape from the
live table; ``updated_at`` falls back to the event's own time).

Nothing here imports a project model at module scope: the tables are optional
modules' (``tests/test_composition_rule.py``), so they are named by label and
found through :func:`core.changes.event_models`, which leaves a switched-off
module out.
"""

import datetime as dt
import re
from collections import Counter
from contextlib import contextmanager

from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from core.changes import event_models

# The tables that move a printed figure, as labels. A switched-off module's
# table is not in ``event_models()`` and is skipped.
AS_OF_TABLES = (
    "parcels.ParcelLedger",
    "accounting.CalculationRun",
    "parcels.Parcel",
    "accounting.WaterAccountParcel",
    "accounting.AllocationPlan",
    "accounting.AccountCredit",
    "geography.ParcelZone",
    "parcels.FallowPeriod",
    "surface.DiversionRecord",
    "wells.WellIrrigatedParcel",
    "parcels.ParcelIrrigationMethod",
    "surface.PointOfDiversionParcel",
    "accounting.PeriodStatement",
)

# Columns a calculation is NOT compared on: its row id and creation time change
# with every re-run, the breakdown is a printout of the figures, and the use
# area and month are the key.
_RUN_KEY = ("parcel_id", "period")
_RUN_LEFT_OUT = ("id", "created_at", "breakdown") + _RUN_KEY

# A ledger row is the same record when use area, date, source and water type
# match; it has changed when its amount or description differ.
_LEDGER_KEY = ("parcel_id", "effective_date", "source_type", "water_type_id")
_LEDGER_FIGURES = ("amount_acre_feet", "description")

DATE_UNREADABLE = "OpenH2O could not read that date. This page shows today's records."
DATE_IN_FUTURE = "That date is in the future. This page shows today's records."

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_as_of(text, today=None):
    """Read the date box: ``(day, error_sentence)``.

    Empty is ``(None, "")`` (show today, say nothing). A real date today or
    earlier is ``(day, "")``. Anything else is ``(None, sentence)``, and the
    page shows today under that sentence.
    """
    text = (text or "").strip()
    if not text:
        return None, ""
    today = today or timezone.localdate()
    try:
        if not _ISO_DATE.fullmatch(text):
            raise ValueError(text)
        day = dt.date.fromisoformat(text)
    except ValueError:
        return None, DATE_UNREADABLE
    if day > today:
        return None, DATE_IN_FUTURE
    return day, ""


def moment_after(day):
    """The start of the day after ``day`` in the site's time zone."""
    return timezone.make_aware(
        dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min),
        timezone.get_current_timezone(),
    )


def _live_columns(cursor, table):
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
        [table],
    )
    return [row[0] for row in cursor.fetchall()]


def _select_sql(cursor, schema, event, live_columns):
    """THE RULE for one table: the select that yields its rows as they stood at ``%(w)s``."""
    live = f'"{schema}"."{event.pgh_tracked_model._meta.db_table}"'
    etable = f'"{event._meta.db_table}"'
    copied = {f.column for f in event._meta.concrete_fields}
    pieces = []
    for column in live_columns:
        if column in copied:
            pieces.append(f'e."{column}"')
        elif column == "updated_at":
            # History never copies it (a save that changes nothing records nothing).
            pieces.append('e.pgh_created_at AS "updated_at"')
        else:
            pieces.append(f'l."{column}"')  # geometry and the like
    has_created = "created_at" in live_columns
    e_created = 'AND e."created_at" <= %(w)s' if has_created else ""
    l_created = 'AND l."created_at" <= %(w)s' if has_created else ""
    live_list = ", ".join(f'l."{c}"' for c in live_columns)
    return f"""
    WITH first_after AS (
        SELECT DISTINCT ON (pgh_obj_id) pgh_obj_id, pgh_id, pgh_label FROM {etable}
        WHERE pgh_created_at > %(w)s ORDER BY pgh_obj_id, pgh_id)
    SELECT {", ".join(pieces)} FROM {etable} e
        JOIN first_after f USING (pgh_id)
        LEFT JOIN {live} l ON l.id = e.pgh_obj_id
    WHERE f.pgh_label IN ('before_update', 'delete') {e_created}
    UNION ALL
    SELECT {live_list} FROM {live} l
    WHERE NOT EXISTS (SELECT 1 FROM first_after x WHERE x.pgh_obj_id = l.id) {l_created}
    """


class Reading:
    """What a ``reading_as_of`` block hands back: the date, and the two questions a page asks."""

    def __init__(self, day, moment, schema):
        self.day = day
        self.moment = moment
        self._schema = schema

    # -- the two sides of a comparison -----------------------------------------------
    def _table(self, name, live):
        return f'"{self._schema}"."{name}"' if live else f'"{name}"'

    def _rows(self, sql, params):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            names = [c.name for c in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _scope(self, alias, date_column, parcel_ids, start, end):
        clauses, params = [], []
        if parcel_ids is not None:
            clauses.append(f"AND {alias}.parcel_id = ANY(%s)")
            params.append(list(parcel_ids))
        if start is not None:
            clauses.append(f"AND {alias}.{date_column} >= %s")
            params.append(start)
        if end is not None:
            clauses.append(f"AND {alias}.{date_column} <= %s")
            params.append(end)
        return " ".join(clauses), params

    def _ledger(self, live, parcel_ids, start, end):
        ledger = self._table("parcels_parcelledger", live)
        parcel = self._table("parcels_parcel", live)
        scope, params = self._scope("l", "effective_date", parcel_ids, start, end)
        columns = ", ".join(f"l.{c}" for c in _LEDGER_KEY + _LEDGER_FIGURES)
        # The rules of ``.current()``, written against this side's own columns.
        return self._rows(
            f"""SELECT {columns} FROM {ledger} l
            WHERE l.voided_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM {ledger} r WHERE r.replaces_id = l.id)
              AND EXISTS (SELECT 1 FROM {parcel} p WHERE p.id = l.parcel_id AND p.voided_at IS NULL
                          AND NOT EXISTS (SELECT 1 FROM {parcel} q WHERE q.replaces_id = p.id))
              {scope}""",
            params,
        )

    def _runs(self, live, parcel_ids, start, end):
        runs = self._table("accounting_calculationrun", live)
        scope, params = self._scope("c", "period_start", parcel_ids, start, end)
        with connection.cursor() as cursor:
            names = _live_columns(cursor, "accounting_calculationrun")
        columns = ", ".join(f"c.{c}" for c in _RUN_KEY + tuple(n for n in names if n not in _RUN_LEFT_OUT))
        return self._rows(f"SELECT {columns} FROM {runs} c WHERE TRUE {scope}", params), [
            n for n in names if n not in _RUN_LEFT_OUT
        ]

    @staticmethod
    def _bag(rows, key, figures):
        bag = {}
        for row in rows:
            bag.setdefault(tuple(row[k] for k in key), []).append(tuple(str(row[f]) for f in figures))
        return bag

    @staticmethod
    def _differences(then, now):
        """Records that differ. Within a key the removed and added figures pair off, so the key counts the larger."""
        total = 0
        for key in set(then) | set(now):
            removed = Counter(then.get(key, [])) - Counter(now.get(key, []))
            added = Counter(now.get(key, [])) - Counter(then.get(key, []))
            total += max(sum(removed.values()), sum(added.values()))
        return total

    def _other_table(self, label, filters):
        """How many rows of one more table differ between then and now, ``filters`` naming the page's rows.

        Compared as a whole on what a person reads: not the row id or its times (a table the
        engine rewrites gets new ones), not a shape.
        """
        table = apps.get_model(label)._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = %s AND data_type <> 'USER-DEFINED' ORDER BY ordinal_position",
                [table],
            )
            columns = [r[0] for r in cursor.fetchall() if r[0] not in ("id", "created_at", "updated_at")]
        where, params = [], []
        for column, value in filters.items():
            where.append(f'"{column}" = ANY(%s)')
            params.append(list(value) if isinstance(value, (list, tuple, set)) else [value])
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        names = ", ".join(f'"{c}"' for c in columns)
        then, now = (
            self._rows(f"SELECT {names} FROM {self._table(table, live)} {clause}", params)
            for live in (False, True)
        )
        return self._differences(self._bag(then, (), columns), self._bag(now, (), columns))

    def changed_count(self, parcel_ids=None, start=None, end=None, also=()):
        """How many records differ between the rows as they stood and the rows now.

        Compares current rows only, by what a person calls the same record (a
        ledger row by use area, date, source and water type; a calculation by use
        area and month), so a re-run that moved no figure is 0 however many history
        events it wrote. A correction, a void and a new entry are 1 each.
        ``also`` adds the other tables that move a figure this page prints, as
        ``(label, {column: value or values})``, because an allocation moved since would
        otherwise change the page under a line saying nothing changed. A table of a
        module that is switched off is skipped.
        """
        then = self._ledger(False, parcel_ids, start, end)
        now = self._ledger(True, parcel_ids, start, end)
        count = self._differences(
            self._bag(then, _LEDGER_KEY, _LEDGER_FIGURES), self._bag(now, _LEDGER_KEY, _LEDGER_FIGURES)
        )
        runs_then, figures = self._runs(False, parcel_ids, start, end)
        runs_now, _ = self._runs(True, parcel_ids, start, end)
        count += self._differences(
            self._bag(runs_then, _RUN_KEY, figures), self._bag(runs_now, _RUN_KEY, figures)
        )
        running = event_models()
        return count + sum(self._other_table(label, filters) for label, filters in also if label in running)

    def has_records(self, parcel_ids=None, start=None, end=None, also=()):
        """Whether any ledger row or calculation existed in that scope at the moment."""
        for table, alias, date_column in (
            ("parcels_parcelledger", "l", "effective_date"),
            ("accounting_calculationrun", "c", "period_start"),
        ):
            scope, params = self._scope(alias, date_column, parcel_ids, start, end)
            rows = self._rows(f'SELECT 1 FROM "{table}" {alias} WHERE TRUE {scope} LIMIT 1', params)
            if rows:
                return True
        return False


@contextmanager
def reading_as_of(day=None, *, moment=None):
    """Run the block reading the records as they stood at the end of ``day`` (or at ``moment``).

    Inside, the tables in :data:`AS_OF_TABLES` are temporary copies of the same
    name, the transaction is read-only, and on the way out everything is rolled
    back, with or without an exception. Yields a :class:`Reading`.
    """
    if moment is None:
        moment = moment_after(day)
    events = event_models()
    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_schema()")
                schema = cursor.fetchone()[0]
                for label in AS_OF_TABLES:
                    event = events.get(label)
                    if event is None:
                        continue  # a module that is switched off
                    table = event.pgh_tracked_model._meta.db_table
                    columns = _live_columns(cursor, table)
                    sql = _select_sql(cursor, schema, event, columns)
                    cursor.execute(f'CREATE TEMP TABLE "{table}" ON COMMIT DROP AS {sql}', {"w": moment})
                    for column in ("id", "parcel_id", "replaces_id"):
                        if column in columns:
                            cursor.execute(f'CREATE INDEX ON pg_temp."{table}" ({column})')
                    # With no indexes here the ledger search took 3 s on the demonstration.
                    cursor.execute(f'ANALYZE pg_temp."{table}"')
                cursor.execute("SET LOCAL transaction_read_only = on")
            yield Reading(day, moment, schema)
        finally:
            # Nothing done in a reading is kept, and a failure leaves no trace either.
            transaction.set_rollback(True)
