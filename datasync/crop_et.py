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


def differs_as_printed(a_mm, b_mm, acres):
    """Whether two depths differ in acre-feet as the pages print them (two decimals).

    A field with no area on file falls back to the depth itself, 0.01 mm apart.
    """
    if not acres:
        return abs(Decimal(a_mm) - Decimal(b_mm)) >= DIFFERENT_MM
    return f"{acre_feet(a_mm, acres):.2f}" != f"{acre_feet(b_mm, acres):.2f}"


def newer_figure(record):
    """The month's newest fetched figure when it differs from ``record`` as the page prints it.

    Two figures that match to the hundredth of an acre-foot are the same figure: a newer one
    that prints the same as the recorded one would show two equal figures and an Accept.
    """
    newest = newest_fetched(
        record.parcel, month_text(record.month), record.variable, record.model_name
    )
    if newest is None or not differs_as_printed(newest.mm, record.depth_mm, record.parcel.area_acres):
        return None
    return newest


def mark_for_day(received_on, first):
    """``"Final"`` or ``"Provisional"`` for a figure received on ``received_on``; None with no day."""
    if received_on is None:
        return None
    return "Provisional" if is_provisional(received_on, first) else "Final"


def mark(record):
    """The recorded figure's pill: Final, Provisional or None.

    Final when OpenET sent the recorded figure more than 120 days after the month ended, or
    has since sent the same figure (as the page prints it) more than 120 days after. With no
    received day and nothing confirming it, no mark.
    """
    own = mark_for_day(record.fetched_on, record.month)
    if own == "Final":
        return own
    newest = newest_fetched(
        record.parcel, month_text(record.month), record.variable, record.model_name
    )
    if (
        newest is not None
        and mark_for_day(newest.fetched_on, record.month) == "Final"
        and not differs_as_printed(newest.mm, record.depth_mm, record.parcel.area_acres)
    ):
        return "Final"
    return own


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
    return f"received {_day_words(day)}" if day is not None else "date received not recorded"


def caption(record):
    """``OpenET satellite estimate, received Aug 6, 2025`` (a label, so no full stop).

    Provisional or Final is the figure's pill (:func:`mark`), not a word in the caption.
    """
    return f"OpenET satellite estimate, {_fetched(record.fetched_on)}"


def _pill(label):
    return {"label": label, "kind": label.lower()} if label else None


NEWER_WORDS = (
    "OpenET now reports a different figure for this month. "
    "OpenH2O calculates the month from the recorded {recorded} AF until a person accepts the newer figure. "
    "Accepting it replaces the recorded figure and recalculates the month at once."
)
ENTRY_READS = "The ledger's ET estimate entry for this month reads {entry} AF."
ENTRY_CALCULATES = "OpenH2O calculates the month from the recorded {recorded} AF."
ENTRY_CORRECTING = "Correcting the entry to {recorded} AF recalculates the month."


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

    ``figure``, ``caption`` and ``pill`` are the Crop ET figure's value, caption and mark.
    ``earlier`` are its struck rows, one per figure an acceptance replaced, each with the
    site's line under a replaced record. ``newer`` is the band for a newer figure OpenET now
    sends (its figure, received day, pill and sentences); ``entry`` the band for an ET
    estimate entry that differs from the record. Each band's ``action`` is what its button
    opens; the view decides who sees the button.
    """
    from datasync.models import CropETFigure

    record = current_record(parcel, period)
    if record is None:
        return None
    acres = parcel.area_acres
    recorded = _af(record.depth_mm, acres)
    newer = newer_figure(record)
    newer_band = None
    if newer is not None:
        newer_band = {
            "figure": _af(newer.mm, acres),
            "received": _fetched(newer.fetched_on),
            "pill": _pill(mark_for_day(newer.fetched_on, record.month)),
            "words": NEWER_WORDS.format(recorded=recorded),
            "button": "Accept the newer figure",
            "action": "accept",
        }
    entry = current_estimate_entry(parcel, period)
    entry_band = None
    if entry is not None and entry_differs(entry, record):
        words = [ENTRY_READS.format(entry=f"{abs(entry.amount_acre_feet):,.2f}")]
        if newer_band is None:
            words.append(ENTRY_CALCULATES.format(recorded=recorded))
        words.append(ENTRY_CORRECTING.format(recorded=recorded))
        entry_band = {
            "words": " ".join(words),
            "button": f"Correct the entry to {recorded} AF",
            "action": "entry",
        }
    earlier_rows = []
    later = record
    while later.replaces_id:
        earlier = CropETFigure.objects.get(pk=later.replaces_id)
        earlier_rows.append({
            "label": "Earlier figure",
            "note": _fetched(earlier.fetched_on),
            "figure": _af(earlier.depth_mm, acres),
            "line": _replaced_words(earlier, later),
        })
        later = earlier
    return {
        "record": record,
        "figure": recorded,
        "caption": caption(record),
        "pill": _pill(mark(record)),
        "earlier": earlier_rows,
        "newer": newer_band,
        "entry": entry_band,
    }


# -- A month OpenET sent nothing for --------------------------------------------------------


def asked_and_none_sent(parcel, period, variable="ET", model="Ensemble"):
    """Whether OpenET was asked about the month and sent no figure for it.

    True when a cached answer covers the whole month and carries no figure for it. A month no
    cached answer covers was never asked about.
    """
    from datasync.models import OpenETCache

    first = month_first(period)
    rows = OpenETCache.objects.filter(
        parcel=parcel, variable=variable, model_name=model,
        start_date__lte=first, end_date__gte=last_day(first),
    )
    return rows.exists() and not any(period in months_of(row.et_data) for row in rows)


NO_FIGURE_LINES = "OpenH2O calculates a month from its crop ET. It has not calculated this month."
NO_FIGURE_ENTRIES = "The month's ledger entries are below."


def no_figure_context(parcel, period):
    """The page of a month OpenET was asked about and sent no crop ET for; None otherwise.

    It names the month and lists the month's ledger supplies as figures, each with the site's
    How measured pills. Nothing is calculated or estimated for the month.
    """
    from accounting.services import (
        billable_ledger, groundwater_kind_terms, supply_kind_lines, surface_kind_terms,
    )
    from parcels.models import ParcelLedger

    if current_record(parcel, period) is not None or not asked_and_none_sent(parcel, period):
        return None
    first = month_first(period)
    billable = billable_ledger(
        ParcelLedger.objects.current().filter(
            parcel=parcel, effective_date__year=first.year, effective_date__month=first.month
        )
    )
    supplies = []
    for label, terms in (
        ("Surface water delivered", surface_kind_terms(billable)),
        ("Groundwater extraction", groundwater_kind_terms(billable)),
    ):
        total = sum((abs(amount) for _kind, amount in terms), Decimal("0"))
        if total:
            supplies.append({
                "label": label,
                "figure": f"{total:,.2f}",
                "title": total,
                "pills": supply_kind_lines([(kind, abs(amount)) for kind, amount in terms]),
            })
    lines = NO_FIGURE_LINES + (" " + NO_FIGURE_ENTRIES if supplies else "")
    return {"headline": f"No crop ET from OpenET for {first:%B %Y}", "lines": lines, "supplies": supplies}


def _who(user):
    if user is None:
        return "a former user"
    first, last = user.first_name.strip(), user.last_name.strip()
    if first and last:
        return f"{first[0]}. {last}"
    return user.get_full_name().strip() or user.email or user.get_username()
