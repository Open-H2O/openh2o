# SPDX-License-Identifier: AGPL-3.0-or-later
"""One orchestrator for the calculation: every month in order, with a record (149-01).

The calculation used to be a sequence only the demonstration build knew: crop
water use for a month, then the canal division, then the groundwater / no-supply
residual against what the canal division left. A screen, the nightly schedule,
a saved diversion record and the command line all now run the SAME sequence
through this module, one month at a time, oldest first:

  1. ``run_calculations`` for the month (never ``--force``);
  2. only when the ``surface`` module is on, ``allocate_district_delivery`` for
     every active point of diversion that has a record in the month or serves
     fields;
  3. ``run_calculations`` again, against the canal rows step 2 wrote.

Each month is ONE ``transaction.atomic()`` block, so a month that raises changes
nothing and the months before it stay. A run stops at the first month that
raises; later months are not attempted.

Every run is a :class:`accounting.models.CalculationRequest`. It carries who
asked, the months, a status (queued, running, succeeded, finished_with_notes,
failed) and an outcome written for a person. ``months_done`` counts the months
committed so far so a screen can say "month 3 of 12".

**One run at a time.** The worker holds a session-level Postgres advisory lock
(:data:`ADVISORY_LOCK_KEY`). A worker that cannot take it exits and leaves its
request queued; the worker that holds it runs every queued request, oldest
first, releases the lock, then looks at the queue again and takes the lock
again if anything arrived in the meantime (the release race). Two queued
requests whose months overlap are merged before running: the oldest is kept,
the months are united, and the other one is given the kept one's result when it
finishes, so a screen still polling it sees how it ended.

**Never ``--force``.** A finalized period is refused up front, naming the
period, and the database lock refuses anything that gets past that. Nothing here
opens :func:`accounting.locks.override`. A technician who deliberately means to
overwrite a filed figure uses ``run_calculations --force``.

**Who did it.** The change history records the person through pghistory's
context, the way the web request does (``pghistory.middleware.HistoryMiddleware``
records the key ``user``). ``manage.py`` already wraps the subprocess in
``core.history.command_context``, so the command name is there too; this module
adds ``user`` around each request's run.

Words a person reads (``outcome``, ``notes``) are plain sentences. The
traceback and the exception text go in ``error_detail`` for an administrator.
"""

import datetime as dt
import io
import logging
import re
import traceback
from collections import defaultdict
from decimal import Decimal

import pghistory
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from accounting.locks import finalized_message, lock_error_message
from accounting.models import CalculationPlan, CalculationRequest, ReportingPeriod
from core.modules import is_enabled

logger = logging.getLogger(__name__)

#: The fixed key of the advisory lock that makes the calculation one-at-a-time
#: (the seven bytes "OH:CALC"; any constant would do, this one is greppable).
ADVISORY_LOCK_KEY = int.from_bytes(b"OH:CALC", "big")

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

#: How many lines of the traceback are kept in ``error_detail``.
TRACEBACK_TAIL_LINES = 20

#: The names of the request's statuses a run has finished with.
FINISHED_STATUSES = ("succeeded", "finished_with_notes", "failed")


# --------------------------------------------------------------------------
# Month helpers
# --------------------------------------------------------------------------


def month_label(month):
    """``"2026-08"`` (or a date) as ``"August 2026"``."""
    first = month_date(month)
    return f"{first:%B %Y}"


def month_date(month):
    """``"YYYY-MM"`` as the first day of that month; a date passes through."""
    if isinstance(month, dt.date):
        return month.replace(day=1)
    year, mon = month.split("-")
    return dt.date(int(year), int(mon), 1)


def month_text(first):
    return f"{first.year:04d}-{first.month:02d}"


def months_in_span(start, end):
    """Every ``"YYYY-MM"`` from ``start`` to ``end`` inclusive, ascending."""
    out = []
    year, mon = start.year, start.month
    while (year, mon) <= (end.year, end.month):
        out.append(f"{year:04d}-{mon:02d}")
        year, mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return out


def _range_label(months):
    if len(months) == 1:
        return month_label(months[0])
    return f"{month_label(months[0])} through {month_label(months[-1])}"


# --------------------------------------------------------------------------
# Which months have crop water use data
# --------------------------------------------------------------------------


def _gross_et_source():
    """The (variable, model) the plan's gross-ET step reads, as ``run_calculations`` does."""
    plan = CalculationPlan.active()
    config = {}
    if plan is not None:
        step = (
            plan.steps.filter(step_type="et_gross", enabled=True)
            .order_by("order")
            .first()
        )
        config = (step.config if step else None) or {}
    return config.get("variable", "ET"), config.get("model", "Ensemble")


def months_with_et_data(first, last):
    """The ``"YYYY-MM"`` months in ``first..last`` that any parcel has gross ET for.

    Reads ``datasync.OpenETCache``, the table the plan's ``et_gross`` step reads
    (``accounting.steps._read_cache_mm``): rows of the plan's variable and model
    whose span touches the range, and the ``et_data`` items that carry an ``et``
    value. A month counts when at least one item is dated in it.
    """
    from datasync.models import OpenETCache

    variable, model = _gross_et_source()
    wanted = set(months_in_span(first, last))
    found = set()
    rows = OpenETCache.objects.filter(
        variable=variable,
        model_name=model,
        start_date__lte=last,
        end_date__gte=first,
    ).values_list("et_data", flat=True)
    for data in rows.iterator():
        for item in data or []:
            if not isinstance(item, dict) or item.get("et") is None:
                continue
            text = str(item.get("date", ""))[:7]
            if text in wanted:
                found.add(text)
        if found == wanted:
            break
    return found


def months_to_run(reporting_period=None, months=None):
    """The months to calculate, ascending, and the notes about the ones left out.

    Pass a ``reporting_period`` (its whole span) or an explicit ``months`` list
    of ``"YYYY-MM"``. The run ends at the last month that has crop water use
    data for any parcel; later months are not a failure, they become ONE note
    naming the first such month, or the range. Returns ``(months, notes)``.
    """
    if months is None:
        if reporting_period is None:
            return [], []
        months = months_in_span(reporting_period.start_date, reporting_period.end_date)
    months = sorted(set(months))
    if not months:
        return [], []

    have = months_with_et_data(month_date(months[0]), month_date(months[-1]))
    to_run = [m for m in months if m <= max(have)] if have else []
    left_out = [m for m in months if m not in to_run]
    notes = []
    if left_out:
        many = len(left_out) > 1
        notes.append(
            f"No crop water use data for {_range_label(left_out)} yet; "
            f"{'they' if many else 'it'} will be calculated when the data arrives."
        )
    return to_run, notes


# --------------------------------------------------------------------------
# One month
# --------------------------------------------------------------------------


def _engine(month, out):
    """``run_calculations`` for one month, never forced, silent."""
    call_command("run_calculations", period=month, stdout=out, stderr=out)


def _points_of_diversion(first):
    """Active points of diversion with a record in the month or fields they serve."""
    from surface.models import DiversionRecord, PointOfDiversion, PointOfDiversionParcel

    ids = set(
        DiversionRecord.objects.filter(month=first).values_list(
            "point_of_diversion_id", flat=True
        )
    )
    ids |= set(
        PointOfDiversionParcel.objects.values_list("point_of_diversion_id", flat=True)
    )
    return list(
        PointOfDiversion.objects.filter(pk__in=ids, status="active").order_by("pk")
    )


def run_month(month, *, request=None):
    """Calculate one month in ONE transaction. Returns the canal notes it raised.

    ``month`` is ``"YYYY-MM"``. Crop water use, then (surface module on) the
    canal division for each point of diversion, then crop water use again. Any
    exception rolls the whole month back and propagates. Returns the raw note
    dicts ``allocate_district_delivery`` filled in (empty when ``surface`` is
    off); :func:`_note_sentences` turns them into sentences.
    """
    first = month_date(month)
    text = month_text(first)
    out = io.StringIO()
    raw = []
    with transaction.atomic():
        _engine(text, out)
        if is_enabled("surface"):
            from surface.services import allocate_district_delivery

            for pod in _points_of_diversion(first):
                allocate_district_delivery(pod, None, months=[first], notes=raw)
            _engine(text, out)
    return raw


def _amount(value):
    return f"{Decimal(value):,.2f}"


def _note_sentences(raw):
    """Plain sentences for what the canal division raised: ``(attention, info)``.

    ``attention`` is what someone has to look at: fields' own delivery records
    adding up to more than the headgate recorded, a contradiction in the data.
    ``info`` is canal water no field's crop water use explains, summed into ONE
    sentence. It is information, not a fault: Site Health's Unallocated
    Delivery card already reports it, and on a district that diverts more than
    its crops use it is true every month, so it must not turn every run yellow.
    """
    attention = []
    unexplained = defaultdict(lambda: Decimal("0"))
    for note in raw:
        if note.get("kind") == "own_over_headgate":
            attention.append(
                f"Fields' own delivery records at {note['pod']} add up to "
                f"{_amount(note['excess_af'])} AF more than the headgate "
                f"recorded for {month_label(note['month'])}."
            )
        elif note.get("kind") == "unallocated":
            unexplained[note["pod"]] += Decimal(note["amount_af"])
    info = []
    if unexplained:
        # Brent's wording, 2026-10-06: the ruled phrase "canal water beyond
        # what the crop could use", the canals named with their amounts,
        # largest first, and what happens to it.
        total = sum(unexplained.values(), Decimal("0"))
        each = ", ".join(
            f"{pod} {_amount(af)}"
            for pod, af in sorted(unexplained.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        info.append(
            f"{_amount(total)} AF of canal water went beyond what the crops "
            f"could use ({each}). No field is charged for it. Site Health "
            f"lists it under Unallocated Delivery."
        )
    return attention, info


# --------------------------------------------------------------------------
# A request
# --------------------------------------------------------------------------


def create_request(trigger="command", *, reporting_period=None, months=None, requested_by=None):
    """Create a queued request for a period's whole span, or for explicit months."""
    if months is None:
        if reporting_period is None:
            raise ValueError("a request needs a reporting period or months")
        months = months_in_span(reporting_period.start_date, reporting_period.end_date)
    months = sorted(set(months))
    return CalculationRequest.objects.create(
        trigger=trigger,
        requested_by=requested_by,
        reporting_period=reporting_period,
        months=months,
    )


def _finalized_period_among(months):
    """A finalized reporting period that any of ``months`` falls in, or None."""
    finalized = list(ReportingPeriod.objects.filter(is_finalized=True))
    for month in months:
        first = month_date(month)
        for period in finalized:
            if period.start_date <= first <= period.end_date:
                return period
    return None


class _Stopped(Exception):
    """The run ends here, with this plain sentence and this operator detail."""

    def __init__(self, sentence, detail=""):
        super().__init__(sentence)
        self.sentence = sentence
        self.detail = detail


def _unexpected(exc, month):
    label = month_label(month)
    tail = "".join(traceback.format_exc().splitlines(keepends=True)[-TRACEBACK_TAIL_LINES:])
    detail = f"{type(exc).__name__}: {exc}\nMonth: {month}\n{tail}"
    return _Stopped(
        f"The calculation stopped at {label} with an error the platform did not "
        f"expect. Nothing in {label} was changed. The details are on Site Health "
        f"for an administrator.",
        detail,
    )


def _explain_failure(exc, month):
    """Map what a month raised to a plain sentence (and operator detail)."""
    locked = lock_error_message(exc)
    if locked is not None:
        return _Stopped(locked, f"{type(exc).__name__}: {exc}\nMonth: {month}")
    text = str(exc)
    if isinstance(exc, ValueError) and "no active CalculationPlan" in text:
        return _Stopped(_NO_PLAN, f"{type(exc).__name__}: {exc}\nMonth: {month}")
    if isinstance(exc, CommandError) and "is finalized" in text:
        period = _finalized_period_among([month])
        if period is not None:
            return _Stopped(finalized_message(period.name), f"CommandError: {exc}")
    return _unexpected(exc, month)


_NO_PLAN = (
    "No calculation method is set up on this site yet, so there is nothing to "
    "calculate with. An administrator can set one up."
)


def _finish(request_obj, status, outcome, notes, *, detail=""):
    request_obj.status = status
    request_obj.outcome = outcome
    request_obj.notes = notes
    request_obj.error_detail = detail
    request_obj.finished_at = timezone.now()
    request_obj.save(
        update_fields=[
            "status", "outcome", "notes", "error_detail", "finished_at", "months",
            "months_done",
        ]
    )


def execute(request_obj):
    """Run one request and write down how it went. Never raises for a calculation fault.

    The caller holds the advisory lock (:func:`run_queue`). Marks the request
    running, refuses a finalized period up front, trims the months to those with
    crop water use data, runs each month atomically and in order, stops at the
    first month that raises, and always writes ``finished_at`` and a Site Health
    record. A failure to write the Site Health record never changes the status.
    """
    request_obj.status = "running"
    request_obj.started_at = timezone.now()
    request_obj.months_done = 0
    request_obj.save(update_fields=["status", "started_at", "months_done"])

    notes = []
    try:
        with pghistory.context(**_attribution(request_obj)):
            _run(request_obj, notes)
    except _Stopped as stop:
        _finish(request_obj, "failed", stop.sentence, notes, detail=stop.detail)
    except Exception as exc:  # the record must say what happened, whatever it was
        logger.exception("calculation request %s stopped", request_obj.pk)
        tail = "".join(
            traceback.format_exc().splitlines(keepends=True)[-TRACEBACK_TAIL_LINES:]
        )
        _finish(
            request_obj,
            "failed",
            "The calculation stopped with an error the platform did not expect. "
            "The details are on Site Health for an administrator.",
            notes,
            detail=f"{type(exc).__name__}: {exc}\n{tail}",
        )
    _record_health()
    return request_obj


def _attribution(request_obj):
    """The change-history context for this run: the person who asked, when known."""
    return {"user": request_obj.requested_by_id} if request_obj.requested_by_id else {}


def _run(request_obj, notes):
    if CalculationPlan.active() is None:
        raise _Stopped(_NO_PLAN)

    requested = list(request_obj.months or [])
    if request_obj.reporting_period_id and request_obj.reporting_period.is_finalized:
        raise _Stopped(finalized_message(request_obj.reporting_period.name))
    period = _finalized_period_among(requested)
    if period is not None:
        raise _Stopped(finalized_message(period.name))

    to_run, skipped = months_to_run(months=requested) if requested else ([], [])
    request_obj.months = to_run
    request_obj.save(update_fields=["months"])

    raw = []
    for index, month in enumerate(to_run):
        try:
            raw.extend(run_month(month, request=request_obj))
        except Exception as exc:
            stop = _explain_failure(exc, month)
            if index == 1:
                stop.sentence += f" {month_label(to_run[0])} was calculated and kept."
            elif index > 1:
                stop.sentence += (
                    f" The {index} earlier months, {month_label(to_run[0])} to "
                    f"{month_label(to_run[index - 1])}, were calculated and kept."
                )
            raise stop from exc
        request_obj.months_done = index + 1
        request_obj.save(update_fields=["months_done"])

    # Months with no crop water use data yet are the normal state of a year in
    # progress (the data arrives a month or two behind), so they are a note,
    # never a reason for the run to read as needing attention.
    attention, info = _note_sentences(raw)
    notes.extend(attention + skipped + info)
    if not to_run:
        outcome = "There was no crop water use data to calculate yet."
    elif len(to_run) == 1:
        outcome = f"Calculated {month_label(to_run[0])}."
    else:
        outcome = (
            f"Calculated {len(to_run)} months, {month_label(to_run[0])} to "
            f"{month_label(to_run[-1])}."
        )
    _finish(
        request_obj,
        "finished_with_notes" if attention else "succeeded",
        outcome,
        notes,
    )


def _record_health():
    """Store the Site Health calculation card's result, so it is current at once.

    Skipped when the health module is off or its check is not there yet; a
    failure here is logged and never touches the request's status.
    """
    try:
        if not is_enabled("health"):
            return
        from health.checks import check_calculation
        from health.models import HealthCheckResult
    except ImportError:
        return
    try:
        result = check_calculation()
        with transaction.atomic():
            HealthCheckResult.objects.create(**result)
    except Exception:
        logger.exception("could not record the calculation's Site Health result")


# --------------------------------------------------------------------------
# The worker: one at a time
# --------------------------------------------------------------------------


def _try_lock():
    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
        return bool(cursor.fetchone()[0])


def _unlock():
    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])


def _queued():
    return CalculationRequest.objects.filter(status="queued").order_by("requested_at", "pk")


def _merge_overlapping(head, queued):
    """Fold queued requests whose months overlap ``head``'s into it.

    Returns the folded-in requests. ``head`` keeps its own trigger and person
    (the oldest's); its months become the union. The folded ones are marked
    running with ``head``'s start, and are given its result by
    :func:`_mirror` when it ends.
    """
    months = set(head.months or [])
    absorbed = []
    remaining = [r for r in queued if r.pk != head.pk]
    changed = True
    while changed:
        changed = False
        for other in list(remaining):
            if months & set(other.months or []):
                months |= set(other.months or [])
                absorbed.append(other)
                remaining.remove(other)
                changed = True
    if absorbed:
        head.months = sorted(months)
        head.save(update_fields=["months"])
        now = timezone.now()
        for other in absorbed:
            other.status = "running"
            other.started_at = now
            other.save(update_fields=["status", "started_at"])
    return absorbed


def _mirror(head, absorbed):
    """Give each folded-in request the result of the one that ran for it."""
    head.refresh_from_db()
    for other in absorbed:
        other.status = head.status
        other.outcome = head.outcome
        other.notes = head.notes
        other.error_detail = head.error_detail
        other.finished_at = head.finished_at
        other.months = head.months
        other.months_done = head.months_done
        other.save()


def _drain():
    """Run every queued request, oldest first. The caller holds the lock."""
    handled = []
    while True:
        queued = list(_queued())
        if not queued:
            return handled
        head = queued[0]
        absorbed = _merge_overlapping(head, queued)
        execute(head)
        _mirror(head, absorbed)
        handled.append(head.pk)
        handled.extend(r.pk for r in absorbed)


def run_queue():
    """Process the queue under the one-at-a-time lock. Returns the pks it ran.

    A worker that cannot take the lock returns ``[]`` and leaves its request
    queued: the worker holding the lock will run it. After releasing, the
    queue is looked at again and the lock taken again if anything arrived.
    """
    ran = []
    while True:
        if not _try_lock():
            return ran
        try:
            handled = _drain()
        finally:
            _unlock()
        ran.extend(handled)
        if not handled or not _queued().exists():
            return ran


# --------------------------------------------------------------------------
# Starting a run from a screen or a saved record (149-01 Task 3)
# --------------------------------------------------------------------------


def start_calculation(request_obj):
    """Start the worker for ``request_obj`` without making the page wait.

    The worker is ``manage.py run_accounting --request <pk>`` in its own
    process and session, so it outlives the web worker that started it (a
    thread inside gunicorn would die with the worker's recycling). The only
    argument derived from input is an integer primary key. It is launched
    after the surrounding transaction commits, so the new process can see the
    request row.

    With ``settings.OPENH2O_CALCULATION_INLINE`` true (the test suite) the
    queue is run in this process instead, so a test never spawns a process.
    """
    import os
    import subprocess
    import sys

    from django.conf import settings

    if getattr(settings, "OPENH2O_CALCULATION_INLINE", False):
        run_queue()
        return

    pk = int(request_obj.pk)

    def _launch():
        subprocess.Popen(
            [sys.executable, "manage.py", "run_accounting", "--request", str(pk)],
            cwd=settings.BASE_DIR,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ,
        )

    transaction.on_commit(_launch)


def request_for_months(trigger, months, *, requested_by=None):
    """Request and start the calculation of the months a saved record touches.

    Months inside a finalized reporting period are dropped (a finalized year
    is never recalculated). The rest are grouped by the reporting period that
    contains them (or none), one request per group, each started. Returns the
    requests created, each carrying the months it will calculate; an empty
    list when nothing was left to calculate.
    """
    periods = list(ReportingPeriod.objects.order_by("start_date"))
    groups = {}
    for month in sorted({month_text(month_date(m)) for m in months}):
        first = month_date(month)
        period = next(
            (p for p in periods if p.start_date <= first <= p.end_date), None
        )
        if period is not None and period.is_finalized:
            continue
        groups.setdefault(period.pk if period else None, (period, []))[1].append(month)

    created = [
        create_request(
            trigger,
            reporting_period=period,
            months=group,
            requested_by=requested_by,
        )
        for period, group in groups.values()
    ]
    for request_obj in created:
        start_calculation(request_obj)
    return created


def recalculation_sentence(months):
    """The line a saving page shows beneath its success message."""
    months = sorted({month_text(month_date(m)) for m in months})
    consecutive = len(months) > 1 and months == months_in_span(
        month_date(months[0]), month_date(months[-1])
    )
    if len(months) == 1:
        where = month_label(months[0])
    elif consecutive:
        where = f"{month_label(months[0])} through {month_label(months[-1])}"
    else:
        labels = [month_label(m) for m in months]
        where = ", ".join(labels[:-1]) + f" and {labels[-1]}"
    return f"The fields this water serves are being recalculated for {where}."
