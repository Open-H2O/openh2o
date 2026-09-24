# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized water year is closed to change, on every path (147-02).

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
demonstration seeds and ``run_calculations --force`` use it; nothing a person
does in the browser does.

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

import pghistory
import pgtrigger

#: The trigger's name on every locked table.
LOCK_TRIGGER_NAME = "finalized_period_lock"

#: The SQLSTATE the lock raises. A class of its own ("OH"), so psycopg and
#: Django report it as a plain DatabaseError: nothing that catches
#: IntegrityError (a duplicate row) can mistake it for something else.
LOCK_SQLSTATE = "OH409"

#: The sentence after the period's name, in the database and in Python alike.
REOPEN_SENTENCE = "is finalized. An administrator can reopen it on the period page."

#: Every locked table, as ``app_label.ModelName``. The every-path test is
#: parametrized over this tuple, and :data:`LOCK_TRIGGER_URIS` is built from it.
LOCKED_MODELS = (
    "parcels.ParcelLedger",
    "accounting.WaterAccountParcel",
    "accounting.AllocationPlan",
    "accounting.WaterCredit",
    "accounting.WaterCreditDraw",
    "accounting.AllocationCarryover",
    "accounting.CalculationRun",
    "surface.DiversionRecord",
    "surface.UnallocatedDelivery",
)

#: What :func:`override` switches off: the lock triggers and nothing else.
LOCK_TRIGGER_URIS = tuple(f"{label}:{LOCK_TRIGGER_NAME}" for label in LOCKED_MODELS)

#: The California water year starts in October: a period is in the water year
#: its END month falls in (``accounting.services.water_year_periods`` with its
#: default ``anchor_month=10``). AllocationCarryover is keyed on that label.
WATER_YEAR_ANCHOR_MONTH = 10


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
            f"EXTRACT(MONTH FROM p.end_date) >= {WATER_YEAR_ANCHOR_MONTH} "
            f'THEN 1 ELSE 0 END) = {{row}}."{water_year_column}"'
        )
    return " OR ".join(tests)


def finalized_period_lock(*, date_column=None, month_text_column=None,
                          fallback_month_text_column=None, period_column=None,
                          water_year_column=None):
    """The BEFORE INSERT/UPDATE/DELETE row trigger that locks one table.

    Name the row's date one way: ``date_column`` (a date), ``month_text_column``
    (``YYYY-MM`` text) or ``water_year_column`` (a water-year label). A
    ``fallback_month_text_column`` is read when ``date_column`` is empty.
    ``period_column`` is the ``reporting_period`` link, tested as well.
    """
    if date_column and fallback_month_text_column:
        date_sql = (
            f'COALESCE({{row}}."{date_column}", '
            f"{_month_text_to_date(fallback_month_text_column)})"
        )
    elif date_column:
        date_sql = f'{{row}}."{date_column}"'
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


def is_finalized_on(date):
    """True when ``date`` falls inside a finalized reporting period."""
    period = period_for(date)
    return bool(period and period.is_finalized)


def refuse_if_finalized(date, what=""):
    """Raise :class:`PeriodFinalized` when ``date`` is inside a finalized period."""
    period = period_for(date)
    if period is not None and period.is_finalized:
        raise PeriodFinalized(period, what)


def refuse_if_period_finalized(period, what=""):
    """Raise :class:`PeriodFinalized` when ``period`` itself is finalized."""
    if period is not None and period.is_finalized:
        raise PeriodFinalized(period, what)


@contextmanager
def override(reason):
    """Write into a finalized period, recorded with ``reason``.

    Every change made inside carries ``override=True`` and the reason in the
    change history. Only the lock triggers are switched off; the history
    triggers keep recording.
    """
    with pghistory.context(override=True, reason=reason):
        with pgtrigger.ignore(*LOCK_TRIGGER_URIS):
            yield


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
