# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized water year is closed to change, on every path.

The period page promises that finalizing "locks this water year's allocations
and ledger against further edits". Before this module that was true only for
``run_calculations`` and the ledger CSV command. It is now enforced in the
database, by a BEFORE row trigger on every period-scoped table, so a form,
``/admin/``, an import, ``bulk_create``, ``QuerySet.update()``, a management
command and raw SQL are all refused alike.

**What is locked.** A row belongs to a finalized year when its own date falls
inside a finalized ``ReportingPeriod`` (or, for the tables that carry one, its
``reporting_period`` link points at a finalized period). The date, not only the
link, because several ledger writers leave the link empty (the engine's gross
ET rows, the OpenET sync, a personal recharge credit). The trigger checks the
row as it was (update and delete) and as it would become (insert and update),
so a row can neither be changed inside a finalized year nor moved into or out
of one.

**The one door through.** :func:`override` is a recorded exception: it opens a
change-history context carrying ``override=True`` and the reason, and inside it
switches off ONLY the lock triggers (``pgtrigger.ignore``), so the history
triggers go on recording every overriding write, with its reason. The history
context sits outside the ignore on purpose (django-pghistory issue #237). The
demonstration seeds and ``run_calculations --force`` use it, and so does an
administrator's correction or void inside a finalized year, with the reason the
administrator typed, and the recalculation that correction starts (a
``CalculationRequest`` carrying an ``override_reason``). Inside the door
:func:`override_open` is true and the Python-side checks below stand aside the
same way the database lock does; nothing else opens it.

**Refusals a person sees** are in plain words and never a 500. The write paths
a person reaches check first with :func:`refuse_if_finalized` and show the
message beside the form; :class:`FinalizedPeriodMiddleware` turns anything
that reaches the database anyway into the 409 page.

Each trigger's SQL is written out in full for its own table by
:func:`finalized_period_lock` (no shared SQL function), so no app gains a
migration dependency on another. Nothing here imports a model at module
scope: ``parcels`` and ``surface`` import this file from their ``models.py``.
"""

from contextlib import contextmanager
from contextvars import ContextVar

import pghistory
import pgtrigger
from django.conf import settings

#: The trigger's name on every locked table.
LOCK_TRIGGER_NAME = "finalized_period_lock"

#: The SQLSTATE the lock raises. A class of its own ("OH"), so psycopg and
#: Django report it as a plain DatabaseError: nothing that catches
#: IntegrityError (a duplicate row) can mistake it for something else.
LOCK_SQLSTATE = "OH409"

#: The sentence after the period's name, in the database and in Python alike.
REOPEN_SENTENCE = "is finalized. An administrator can reopen it on the water year page."

#: Every locked table, as ``app_label.ModelName``. The every-path test is
#: parametrized over this tuple, and :data:`LOCK_TRIGGER_URIS` is built from it.
LOCKED_MODELS = (
    "parcels.ParcelLedger",
    "accounting.WaterAccountParcel",
    "accounting.AllocationPlan",
    "accounting.WaterCredit",
    "accounting.WaterCreditDraw",
    "accounting.AllocationCarryover",
    "accounting.AccountCredit",
    "accounting.CalculationRun",
    "surface.DiversionRecord",
    "surface.UnallocatedDelivery",
    "measurements.MeterReading",
    "measurements.WaterMeasurement",
    "recharge.RechargeEvent",
    "recharge.RechargeMeasurement",
    "surface.CanalMonthLoss",
    "parcels.FallowPeriod",
    "datasync.TypedReading",
    "drinking.SystemProduction",
    "drinking.SampleResult",
)

#: What :func:`override` switches off: the lock triggers and nothing else.
LOCK_TRIGGER_URIS = tuple(f"{label}:{LOCK_TRIGGER_NAME}" for label in LOCKED_MODELS)

#: SQL: the month the site's water year starts in, read from the one site row
#: each time the trigger runs, so changing the setting needs no new trigger.
#: October when there is no site row. A period is in the water year its END
#: month falls in (``accounting.services.water_year_periods``), and
#: AllocationCarryover is keyed on that label. ``accounting.carryover_math``
#: holds the same rule in Python.
WATER_YEAR_START_MONTH_SQL = (
    "COALESCE((SELECT s.water_year_start_month FROM core_siteconfig s "
    "ORDER BY s.id LIMIT 1), 10)"
)


def _month_text_to_date(column):
    """SQL: a ``YYYY-MM`` text column as the first day of that month, or NULL."""
    return (
        f"CASE WHEN {{row}}.\"{column}\" ~ '^[0-9]{{{{4}}}}-[0-9]{{{{2}}}}$' "
        f"THEN to_date({{row}}.\"{column}\" || '-01', 'YYYY-MM-DD') END"
    )


def _finalized_match(*, date_sql=None, period_column=None, water_year_column=None):
    """SQL: the WHERE test for "this row sits in finalized period p".

    Each argument is a template with ``{row}`` standing for NEW or OLD.
    """
    tests = []
    if date_sql:
        tests.append(f"({date_sql}) BETWEEN p.start_date AND p.end_date")
    if period_column:
        tests.append(f'p.id = {{row}}."{period_column}"')
    if water_year_column:
        tests.append(
            "(EXTRACT(YEAR FROM p.end_date)::int + CASE WHEN "
            f"{WATER_YEAR_START_MONTH_SQL} > 1 AND "
            f"EXTRACT(MONTH FROM p.end_date) >= {WATER_YEAR_START_MONTH_SQL} "
            f'THEN 1 ELSE 0 END) = {{row}}."{water_year_column}"'
        )
    return " OR ".join(tests)


def finalized_span_lock(*, start_column, end_column):
    """The lock for a row that covers a span of months (a fallow period).

    ``start_column`` and ``end_column`` are each the first day of a month; an
    empty start reaches back without end and an empty end means the span is
    still running. A row is refused when it covers any month of a finalized
    year, on insert and delete; an update is refused when the row covers such
    a month before or after it, unless the one change is its end month and the
    months it covers in that year stay the same. So a running period that began in a finalized year can
    still be ended (the months it stops covering come after the year), and
    nothing else about it can change.
    """

    def clipped(row):
        start = f'GREATEST(COALESCE({row}."{start_column}", p.start_date), p.start_date)'
        end = (
            f'LEAST(COALESCE(({row}."{end_column}" + INTERVAL \'1 month\' '
            f"- INTERVAL '1 day')::date, p.end_date), p.end_date)"
        )
        return start, end

    def covers(row):
        start, end = clipped(row)
        return f"({start} <= {end})"

    old_start, old_end = clipped("OLD")
    new_start, new_end = clipped("NEW")
    raise_sql = (
        "IF locked_name IS NOT NULL THEN "
        f"RAISE EXCEPTION USING ERRCODE = '{LOCK_SQLSTATE}', "
        f"MESSAGE = locked_name || ' {REOPEN_SENTENCE}', "
        "DETAIL = TG_TABLE_NAME; "
        "END IF; "
    )
    pick = "SELECT p.name INTO locked_name FROM accounting_reportingperiod p WHERE p.is_finalized AND "
    func = (
        "IF TG_OP = 'INSERT' THEN "
        f"{pick}{covers('NEW')} ORDER BY p.start_date LIMIT 1; {raise_sql}"
        "ELSIF TG_OP = 'DELETE' THEN "
        f"{pick}{covers('OLD')} ORDER BY p.start_date LIMIT 1; {raise_sql}"
        "ELSE "
        f"{pick}({covers('OLD')} OR {covers('NEW')}) AND ("
        f"(to_jsonb(OLD) - '{end_column}') IS DISTINCT FROM (to_jsonb(NEW) - '{end_column}') "
        f'OR OLD."{end_column}" IS NOT DISTINCT FROM NEW."{end_column}" '
        f"OR NOT ({covers('OLD')} AND {covers('NEW')}) "
        f"OR {old_start} IS DISTINCT FROM {new_start} OR {old_end} IS DISTINCT FROM {new_end}"
        f") ORDER BY p.start_date LIMIT 1; {raise_sql}"
        "END IF; "
        "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; "
        "RETURN NEW;"
    )
    return pgtrigger.Trigger(
        name=LOCK_TRIGGER_NAME,
        when=pgtrigger.Before,
        operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
        declare=[("locked_name", "text")],
        func=func,
    )


def _sql_literal(text):
    return "'" + str(text).replace("'", "''") + "'"


def finalized_period_lock(*, date_column=None, month_text_column=None,
                          fallback_month_text_column=None, period_column=None,
                          water_year_column=None, datetime_column=None,
                          year_month_columns=None, fallback_date_column=None,
                          date_subquery=None):
    """The BEFORE INSERT/UPDATE/DELETE row trigger that locks one table.

    Name the row's date one way: ``date_column`` (a date), ``datetime_column``
    (a timestamp, read as the site's calendar day), ``month_text_column``
    (``YYYY-MM`` text), ``year_month_columns`` (``(year, month)`` integers; an
    empty month means January), ``date_subquery`` (an SQL template with
    ``{row}``, for a table whose date is on another row) or
    ``water_year_column`` (a water-year label). A ``fallback_month_text_column``
    or a ``fallback_date_column`` is read when ``date_column`` is empty.
    ``period_column`` is the ``reporting_period`` link, tested as well.
    """
    if date_column and fallback_month_text_column:
        date_sql = (
            f'COALESCE({{row}}."{date_column}", '
            f"{_month_text_to_date(fallback_month_text_column)})"
        )
    elif date_column and fallback_date_column:
        date_sql = f'COALESCE({{row}}."{date_column}", {{row}}."{fallback_date_column}")'
    elif date_column:
        date_sql = f'{{row}}."{date_column}"'
    elif datetime_column:
        # The one limit: the zone is read from settings when the trigger is
        # declared, so the migration records it. A site that changes TIME_ZONE
        # after migrating keeps the old zone in the trigger until the migration
        # is regenerated.
        zone = _sql_literal(settings.TIME_ZONE)
        date_sql = f'({{row}}."{datetime_column}" AT TIME ZONE {zone})::date'
    elif year_month_columns:
        year, month = year_month_columns
        date_sql = (
            f'make_date({{row}}."{year}", CASE WHEN {{row}}."{month}" BETWEEN 1 AND 12 '
            f'THEN {{row}}."{month}" ELSE 1 END, 1)'
        )
    elif date_subquery:
        date_sql = date_subquery
    elif month_text_column:
        date_sql = _month_text_to_date(month_text_column)
    else:
        date_sql = None
    match = _finalized_match(
        date_sql=date_sql,
        period_column=period_column,
        water_year_column=water_year_column,
    )

    def check(row):
        where = match.format(row=row)
        return (
            "SELECT p.name INTO locked_name FROM accounting_reportingperiod p "
            f"WHERE p.is_finalized AND ({where}) ORDER BY p.start_date LIMIT 1; "
            "IF locked_name IS NOT NULL THEN "
            f"RAISE EXCEPTION USING ERRCODE = '{LOCK_SQLSTATE}', "
            f"MESSAGE = locked_name || ' {REOPEN_SENTENCE}', "
            "DETAIL = TG_TABLE_NAME; "
            "END IF; "
        )

    func = (
        f"IF TG_OP IN ('UPDATE', 'DELETE') THEN {check('OLD')}END IF; "
        f"IF TG_OP IN ('INSERT', 'UPDATE') THEN {check('NEW')}END IF; "
        "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; "
        "RETURN NEW;"
    )
    return pgtrigger.Trigger(
        name=LOCK_TRIGGER_NAME,
        when=pgtrigger.Before,
        operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
        declare=[("locked_name", "text")],
        func=func,
    )


# -- Python-side checks ----------------------------------------------------------


class PeriodFinalized(Exception):
    """A write into a finalized period, refused before it reached the database."""

    def __init__(self, period, what=""):
        self.period = period
        self.what = what
        super().__init__(finalized_message(period.name))


def finalized_message(period_name):
    """The one refusal sentence: "<period> is finalized. An administrator ..."."""
    return f"{period_name} {REOPEN_SENTENCE}"


def period_for(date):
    """The reporting period whose dates contain ``date``, or None."""
    from accounting.models import ReportingPeriod

    if date is None:
        return None
    return ReportingPeriod.objects.filter(
        start_date__lte=date, end_date__gte=date
    ).first()


def refuse_if_finalized(date, what=""):
    """Raise :class:`PeriodFinalized` when ``date`` is inside a finalized period.

    Returns without raising inside :func:`override`: the database lock is off
    there too.
    """
    if override_open():
        return
    period = period_for(date)
    if period is not None and period.is_finalized:
        raise PeriodFinalized(period, what)


def refuse_if_period_finalized(period, what=""):
    """Raise :class:`PeriodFinalized` when ``period`` itself is finalized.

    Returns without raising inside :func:`override`, as :func:`refuse_if_finalized` does.
    """
    if override_open():
        return
    if period is not None and period.is_finalized:
        raise PeriodFinalized(period, what)


def finalized_spans():
    """``[(start, end, name), ...]`` of the finalized years: ONE query for a whole file.

    An import checks every row against this list, so the preview and the commit
    refuse the same rows without a query per row. Empty inside :func:`override`,
    where the database lock is off too.
    """
    from accounting.models import ReportingPeriod

    if override_open():
        return []
    return list(
        ReportingPeriod.objects.filter(is_finalized=True).values_list(
            "start_date", "end_date", "name"
        )
    )


def finalized_span_message(day, spans):
    """The refusal sentence when ``day`` is inside one of ``spans``, else None."""
    if day is None:
        return None
    for start, end, name in spans:
        if start <= day <= end:
            return finalized_message(name)
    return None


#: True while a thread is inside :func:`override`.
_OVERRIDE_OPEN = ContextVar("finalized_period_override_open", default=False)


def override_open():
    """Whether the caller is inside :func:`override`, the one recorded door."""
    return _OVERRIDE_OPEN.get()


@contextmanager
def override(reason):
    """Write into a finalized period, recorded with ``reason``.

    Every change made inside carries ``override=True`` and the reason in the
    change history. Only the lock triggers are switched off; the history
    triggers keep recording. :func:`override_open` is true inside, so the
    Python-side checks stand aside the same way.
    """
    with pghistory.context(override=True, reason=reason):
        with pgtrigger.ignore(*LOCK_TRIGGER_URIS):
            token = _OVERRIDE_OPEN.set(True)
            try:
                yield
            finally:
                _OVERRIDE_OPEN.reset(token)


def lock_error_message(exc):
    """The plain-words message when ``exc`` is the lock's refusal, else None.

    Walks the exception chain, because Django wraps psycopg's error in its own
    ``DatabaseError`` with the original as ``__cause__``.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, PeriodFinalized):
            return str(exc)
        if getattr(exc, "sqlstate", None) == LOCK_SQLSTATE:
            diag = getattr(exc, "diag", None)
            return getattr(diag, "message_primary", None) or str(exc)
        exc = exc.__cause__
    return None


class FinalizedPeriodMiddleware:
    """The backstop: a refused write that reached the database shows the 409 page.

    Every write path a person uses checks first and answers beside its own
    form. Anything that does not (``/admin/``, a path added later) still
    reaches the trigger, and this turns its error into a page in plain words
    instead of a 500.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        message = lock_error_message(exception)
        if message is None:
            return None
        return finalized_response(request, message)


def finalized_response(request, message):
    """The 409 page for a refused write into a finalized period."""
    from django.shortcuts import render

    return render(
        request,
        "409_period_finalized.html",
        {"finalized_message": message},
        status=409,
    )


#: The reason every demonstration seed records on its writes into the
#: finalized demonstration year.
SEED_REASON = "demonstration seed"

#: The reason the demonstration teardown records on the rows it removes.
TEARDOWN_REASON = "demonstration teardown"


def overriding(reason):
    """Decorate a command's ``handle`` to run it through :func:`override`.

    Every override site is this decorator (or ``demonstration_seed``) on a
    ``handle``, or a direct ``with override(...)``; a search for those three
    names lists them all.
    """
    from functools import wraps

    def decorator(handle):
        @wraps(handle)
        def wrapped(self, *args, **options):
            with override(reason):
                return handle(self, *args, **options)

        return wrapped

    return decorator


#: The demonstration's prior water year (WY 2024-2025) is finalized on purpose,
#: and the seeds that write its figures wear this decorator.
demonstration_seed = overriding(SEED_REASON)
