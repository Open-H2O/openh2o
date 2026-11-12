# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's crop ET for a month: recorded once, read only from the record, a newer figure shown.

The record (:class:`datasync.models.CropETFigure`) is written in two ways only:

* :func:`record_fetched_months`, called by every writer of crop ET into the cache
  right after it writes, records a month that has no record yet, at the figure
  just fetched and the day it was fetched. It never touches an existing record.
* :func:`accept_newer_figure` and :func:`bring_entry_to_record`, a person's
  decision with a written reason, replace the record and the month's ET estimate
  entry as recorded corrections.

The calculation reads :func:`recorded_mm` and nothing else for crop ET. The
cache is read only through ``accounting.steps._cache_by_date``, the same
"newest row wins" read the calculation used before records existed, so the
record and the newer-figure check agree on which fetch is the newest.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

#: OpenET may revise a month for about this many days after the month ends.
PROVISIONAL_DAYS = 120

#: The smallest difference in depth that counts as a different figure.
DIFFERENT_MM = Decimal("0.01")

#: The sentence for an Accept press when OpenET reports no other figure.
NO_NEWER_SENTENCE = "OpenET reports no other figure for this month. Nothing was changed."

#: The sentence for bringing an entry into line when it already agrees.
ENTRY_AGREES_SENTENCE = "The ET estimate entry already agrees with the recorded figure. Nothing was changed."


@dataclass(frozen=True)
class Fetched:
    """The newest fetched figure of a month: its depth, and the day it was fetched when known."""

    mm: Decimal
    fetched_on: dt.date | None


# -- Months -------------------------------------------------------------------------------


def month_first(period):
    """``"YYYY-MM"`` as the first day of that month."""
    return dt.date(int(period[:4]), int(period[5:7]), 1)


def month_text(day):
    return f"{day.year}-{day.month:02d}"


def months_between(start, end):
    """The ``"YYYY-MM"`` months from ``start``'s to ``end``'s, inclusive."""
    months, day = [], dt.date(start.year, start.month, 1)
    while day <= end:
        months.append(month_text(day))
        day = dt.date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return months


def last_day(first):
    nxt = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def is_provisional(fetched_on, first):
    """Whether a figure fetched on ``fetched_on`` for the month starting ``first`` was provisional."""
    return fetched_on is not None and (fetched_on - last_day(first)).days <= PROVISIONAL_DAYS


def _tidy(value):
    """A depth without the stored column's trailing zeros (91.44, 100.0)."""
    text = f"{Decimal(value):f}"
    if "." in text:
        text = text.rstrip("0")
        if text.endswith("."):
            text += "0"
    return Decimal(text)


def _day(text):
    try:
        return dt.date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


# -- Writing: a fetch -------------------------------------------------------------------


def stamp(items, day):
    """``items`` (cache et_data) with each month item stamped as fetched on ``day``."""
    text = day.isoformat()
    return [{**item, "fetched": text} if isinstance(item, dict) else item for item in items or []]


def months_of(items, key="et"):
    """The ``"YYYY-MM"`` months ``items`` carry a value for."""
    return {
        str(item.get("date", ""))[:7]
        for item in items or []
        if isinstance(item, dict) and item.get(key) is not None and len(str(item.get("date", ""))) >= 7
    }


def newest_fetched(parcel, period, variable="ET", model="Ensemble"):
    """The month's newest fetched figure, read the way the calculation read the cache; None when none."""
    from accounting.steps import _cache_by_date

    by_date, _rows = _cache_by_date(parcel, period, variable, model, "et")
    if not by_date:
        return None
    total = sum((value for value, _pk, _f in by_date.values()), Decimal("0"))
    days = [_day(fetched) for _v, _pk, fetched in by_date.values()]
    fetched_on = None if any(d is None for d in days) else max(days)
    return Fetched(mm=total, fetched_on=fetched_on)


def current_record(parcel, period, variable="ET", model="Ensemble"):
    from datasync.models import CropETFigure

    return (
        CropETFigure.objects.current()
        .filter(parcel=parcel, month=month_first(period), variable=variable, model_name=model)
        .first()
    )


def record_fetched_months(parcel, months, variable="ET", model="Ensemble"):
    """Record each of ``months`` that has no record yet, at its newest fetched figure.

    Called by every crop ET writer right after it writes the cache. A month that
    already has a record is left exactly as it is. Returns the records written.
    """
    from datasync.models import CropETFigure

    written = []
    for period in sorted(months):
        if current_record(parcel, period, variable, model) is not None:
            continue
        newest = newest_fetched(parcel, period, variable, model)
        if newest is None:
            continue
        written.append(
            CropETFigure.objects.create(
                parcel=parcel,
                month=month_first(period),
                variable=variable,
                model_name=model,
                depth_mm=newest.mm,
                fetched_on=newest.fetched_on,
            )
        )
    return written


def differing_months(parcels, months):
    """``[(parcel, period, recorded mm, newest mm)]`` where OpenET now reports a different figure."""
    found = []
    for parcel in parcels:
        for period in sorted(months):
            record = current_record(parcel, period)
            if record is None:
                continue
            newer = newer_figure(record)
            if newer is not None:
                found.append((parcel, period, _tidy(record.depth_mm), newer.mm))
    return found


def differing_lines(parcels, months):
    """The lines a fetch prints: the months whose newest figure now differs from the record."""
    found = differing_months(parcels, months)
    if not found:
        return []
    many = len(found) != 1
    lines = [
        f"OpenET now reports a different figure for {len(found)} month{'s' if many else ''}. "
        "Each keeps its recorded figure until a person accepts the newer one on the month's "
        "calculation page:"
    ]
    for parcel, period, recorded, newer in found:
        lines.append(
            f"  {parcel.parcel_number} {month_first(period):%b %Y}: recorded {recorded} mm, "
            f"now {newer} mm"
        )
    return lines


# -- Reading ---------------------------------------------------------------------------------


def recorded_mm(parcel, period, variable="ET", model="Ensemble"):
    """``(depth in mm, 1)`` from the month's record, or ``(Decimal("0"), 0)`` when it has none."""
    record = current_record(parcel, period, variable, model)
    if record is None:
        return Decimal("0"), 0
    return _tidy(record.depth_mm), 1


def newer_figure(record):
    """The month's newest fetched figure when it differs from ``record`` by 0.01 mm or more."""
    newest = newest_fetched(
        record.parcel, month_text(record.month), record.variable, record.model_name
    )
    if newest is None or abs(newest.mm - record.depth_mm) < DIFFERENT_MM:
        return None
    return newest


def acre_feet(mm, acres):
    from accounting.services import et_mm_to_acre_feet

    return abs(et_mm_to_acre_feet(mm, acres or Decimal("0")))


def estimate_words(depth_mm, acres, period, af):
    """The ET estimate entry's description, as the ledger sync writes it."""
    return f"OpenET ET estimate: {depth_mm:.2f}mm over {acres} acres = {af:.4f} AF ({period})"


def current_estimate_entry(parcel, period):
    from parcels.models import ParcelLedger

    first = month_first(period)
    return (
        ParcelLedger.objects.current()
        .filter(
            parcel=parcel,
            source_type="et_estimate",
            effective_date__year=first.year,
            effective_date__month=first.month,
        )
        .order_by("pk")
        .first()
    )


def entry_differs(entry, record):
    """Whether the entry's acre-feet and the record's differ as the pages print them (two places)."""
    recorded = acre_feet(record.depth_mm, record.parcel.area_acres)
    return f"{abs(entry.amount_acre_feet):.2f}" != f"{recorded:.2f}"


# -- A person's decision ------------------------------------------------------------------------


def _checked_reason(reason):
    from core.corrections import REASON_MAX_LENGTH, REASON_MIN_LENGTH, REASON_SENTENCE
    from core.history import clean_note

    text = (reason or "").strip()
    note = clean_note(text) if REASON_MIN_LENGTH <= len(text) <= REASON_MAX_LENGTH else None
    if note is None or not REASON_MIN_LENGTH <= len(note) <= REASON_MAX_LENGTH:
        raise ValueError(REASON_SENTENCE)
    return note


def _entry_changes(record_depth, parcel, period):
    from accounting.services import et_mm_to_acre_feet

    af = et_mm_to_acre_feet(record_depth, parcel.area_acres).quantize(Decimal("0.0001"))
    return {
        "amount_acre_feet": af,
        "description": estimate_words(record_depth, parcel.area_acres, period, abs(af)),
    }


def accept_newer_figure(record, *, user, reason):
    """Replace ``record`` with OpenET's newer figure, and the month's ET estimate entry with it.

    Both are recorded corrections carrying ``reason``: the old record and entry stay,
    struck. Raises ``core.corrections.AlreadyVoided`` / ``AlreadyReplaced``, ``ValueError``
    (the reason sentence, or :data:`NO_NEWER_SENTENCE`) or
    ``accounting.locks.PeriodFinalized`` before anything is written. Inside a finalized
    year it goes through only inside ``accounting.locks.override``. Returns the months
    to recalculate; the caller starts them.
    """
    from accounting.locks import refuse_if_finalized
    from core import corrections
    from core.history import change_note
    from datasync.models import CropETFigure

    note = None
    with transaction.atomic():
        locked = CropETFigure.objects.select_for_update().get(pk=record.pk)
        if locked.voided_at is not None:
            raise corrections.AlreadyVoided("This record is already voided.")
        if locked.replaced_at is not None or CropETFigure.objects.filter(replaces=locked).exists():
            raise corrections.AlreadyReplaced(corrections.ALREADY_REPLACED_SENTENCE)
        note = _checked_reason(reason)
        newer = newer_figure(locked)
        if newer is None:
            raise ValueError(NO_NEWER_SENTENCE)
        refuse_if_finalized(locked.month)
        period = month_text(locked.month)
        with change_note(note):
            CropETFigure.objects.filter(pk=locked.pk).update(replaced_at=timezone.now())
            CropETFigure.objects.create(
                parcel_id=locked.parcel_id,
                month=locked.month,
                variable=locked.variable,
                model_name=locked.model_name,
                depth_mm=newer.mm,
                fetched_on=newer.fetched_on,
                replaces=locked,
                change_reason=note,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
        entry = current_estimate_entry(locked.parcel, period)
        if entry is not None:
            corrections.correct(
                entry, user=user, reason=note,
                changes=_entry_changes(newer.mm, locked.parcel, period),
                recorded_figure=True,
            )
    return [period]


def bring_entry_to_record(record, *, user, reason):
    """Replace the month's ET estimate entry with one at the recorded figure, as a correction."""
    from core import corrections

    period = month_text(record.month)
    with transaction.atomic():
        note = _checked_reason(reason)
        entry = current_estimate_entry(record.parcel, period)
        if entry is None or not entry_differs(entry, record):
            raise ValueError(ENTRY_AGREES_SENTENCE)
        corrections.correct(
            entry, user=user, reason=note,
            changes=_entry_changes(_tidy(record.depth_mm), record.parcel, period),
            recorded_figure=True,
        )
    return [period]


# -- What the month's page shows ----------------------------------------------------------------
#
# The month's calculation page shows the record inside its own Crop ET figure: the figure's
# value, one caption, and the figure's breakdown rows (templates/accounting/partials/
# _crop_et_segment.html). Every word the page prints about the record is made here.


def _af(mm, acres):
    return f"{acre_feet(mm, acres):,.2f}"


def _day_words(day):
    return f"{day:%b} {day.day}, {day.year}"


def _fetched(day):
    return f"fetched {_day_words(day)}" if day is not None else "fetch date not recorded"


def caption(record):
    """``OpenET satellite estimate, fetched Aug 6, 2025, provisional`` (a label, so no full stop)."""
    words = f"OpenET satellite estimate, {_fetched(record.fetched_on)}"
    if is_provisional(record.fetched_on, record.month):
        words += ", provisional"
    return words


def _replaced_words(earlier, by):
    """``Replaced Sep 30, 2025 by J. Lopez: the reason.``, the site's line under a replaced record."""
    day = timezone.localtime(earlier.replaced_at or by.created_at, timezone.get_default_timezone())
    reason = (by.change_reason or "").strip()
    if reason and reason[-1] not in ".!?":
        reason += "."
    head = f"Replaced {_day_words(day)} by {_who(by.created_by)}"
    return f"{head}: {reason}" if reason else f"{head}."


def page_context(parcel, period):
    """What the month's page shows about its crop ET; None when nothing is recorded.

    ``rows`` are the Crop ET figure's breakdown rows, in order: a newer figure OpenET now
    reports, the ledger's ET estimate entry when it differs from the record, then each
    earlier figure an acceptance replaced, struck, with the line that says who, when and why.
    A row with an ``action`` gets the three-dot menu when the person may correct records.
    """
    from datasync.models import CropETFigure

    record = current_record(parcel, period)
    if record is None:
        return None
    acres = parcel.area_acres
    rows = []
    newer = newer_figure(record)
    if newer is not None:
        rows.append({
            "label": "Newer figure",
            "note": f"{_fetched(newer.fetched_on)}, not used",
            "figure": _af(newer.mm, acres),
            "action": "accept",
            "item": "Accept newer figure",
        })
    entry = current_estimate_entry(parcel, period)
    if entry is not None and entry_differs(entry, record):
        rows.append({
            "label": "Ledger entry",
            "note": "differs from the recorded figure",
            "figure": f"{abs(entry.amount_acre_feet):,.2f}",
            "action": "entry",
            "item": "Bring to the recorded figure",
        })
    later = record
    while later.replaces_id:
        earlier = CropETFigure.objects.get(pk=later.replaces_id)
        rows.append({
            "label": "Earlier figure",
            "note": _fetched(earlier.fetched_on),
            "figure": _af(earlier.depth_mm, acres),
            "struck": True,
            "line": _replaced_words(earlier, later),
        })
        later = earlier
    return {
        "record": record,
        "figure": _af(record.depth_mm, acres),
        "caption": caption(record),
        "rows": rows,
    }


def _who(user):
    if user is None:
        return "a former user"
    first, last = user.first_name.strip(), user.last_name.strip()
    if first and last:
        return f"{first[0]}. {last}"
    return user.get_full_name().strip() or user.email or user.get_username()
