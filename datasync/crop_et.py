# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's crop ET for a month: recorded once, read only from the record, a newer figure shown.

The record (:class:`datasync.models.CropETFigure`) is written in two ways only:

* :func:`record_fetched_months`, called by every writer of crop ET into the cache
  right after it writes, records a month that has no record yet, at the figure
  just fetched and the day it was fetched. It never touches an existing record.
* :func:`accept_newer_figure`, a person's decision with a written reason,
  replaces the record as a recorded correction.

The calculation reads :func:`recorded_mm` and nothing else for crop ET. The
cache is read only through ``accounting.steps._cache_by_date``, the same
"newest row wins" read the calculation used before records existed, so the
record and the newer-figure check agree on which fetch is the newest.

Rain is recorded with the same answer (ruling 208). On a use area with OpenET fields
the record keeps, beside the crop ET, each field's acres inside the use area, crop
ET and rain from that answer (``CropETFigure.fields``, :func:`recorded_fields`), and
the effective rain step reads only those. On a use area with none, each rain writer
records the month's rain once as a record of its own (variable "precip", model
"GRIDMET"). A later answer with other rain changes nothing; accepting a newer crop
ET figure takes that answer's fields, rain included.
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


def today():
    """The site's date, in its time zone. Read through this module so a test can set it."""
    return timezone.localdate()


def this_month():
    """The first day of the month in progress: a month before it has ended."""
    return today().replace(day=1)


def add_months(first, n):
    """The first day of the month ``n`` months after the one starting ``first``."""
    index = first.year * 12 + first.month - 1 + n
    return dt.date(index // 12, index % 12 + 1, 1)


# -- A month waiting for OpenET (rulings 153 to 155, 160, 211) --------------------------------
#
# A use area's month is waiting when the month has ended, the use area lies in at least one
# OpenET field, and the month has no recorded crop ET. A use area in no OpenET field never
# waits (ruling 160): OpenET sends it nothing, and its page says no field is on record. A month
# still in progress never waits and is never named.

#: A waiting month is overdue once this many calendar months have passed since it ended
#: (September is overdue from December 1). Site Health turns yellow then.
OVERDUE_MONTHS = 2


def is_overdue(first, on=None):
    """Whether a waiting month starting ``first`` is still waiting more than two months after it ended."""
    return (on or today()) >= add_months(first, OVERDUE_MONTHS + 1)


def use_areas_with_fields(parcel_ids=None):
    """The ids of the use areas that lie in at least one OpenET field (of ``parcel_ids`` when given)."""
    from datasync.models import OpenETFieldShare

    rows = OpenETFieldShare.objects.all()
    if parcel_ids is not None:
        rows = rows.filter(parcel_id__in=list(parcel_ids))
    return set(rows.values_list("parcel_id", flat=True).distinct())


def waiting_months(parcel_ids, start, end, variable="ET", model="Ensemble"):
    """``{use area id: [first of each waiting month]}`` for the months from ``start`` to ``end``.

    Only use areas that lie in an OpenET field, and only months that have ended. A use area
    with nothing waiting is left out.
    """
    from datasync.models import CropETFigure

    ended = [month_first(m) for m in months_between(start, end) if month_first(m) < this_month()]
    if not ended:
        return {}
    with_fields = use_areas_with_fields(parcel_ids)
    if not with_fields:
        return {}
    recorded = set(
        CropETFigure.objects.current()
        .filter(parcel_id__in=with_fields, variable=variable, model_name=model,
                month__gte=ended[0], month__lte=ended[-1])
        .values_list("parcel_id", "month")
    )
    found = {}
    for pid in with_fields:
        months = [m for m in ended if (pid, m) not in recorded]
        if months:
            found[pid] = months
    return found


def is_waiting(parcel, period):
    """Whether ``parcel``'s month ``period`` ("YYYY-MM") is waiting for OpenET."""
    first = month_first(period)
    return bool(waiting_months([parcel.pk], first, first))


def month_list(firsts):
    """``September 2026``, ``August 2026 and September 2026``, ``July 2026, August 2026 and ...``."""
    labels = [f"{first:%B %Y}" for first in firsts]
    if len(labels) < 2:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


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


#: The key a cached month item holds its depth under, by variable.
CACHE_KEYS = {"precip": "precip"}


def newest_fetched(parcel, period, variable="ET", model="Ensemble"):
    """The month's newest fetched figure, read the way the calculation read the cache; None when none.

    On a use area with OpenET fields, crop ET is the newest answer from its fields (the live
    field months), which the newer figure's band and Accept compare with the record.
    """
    from accounting.steps import _cache_by_date
    from datasync import field_list

    if variable == "ET" and model == "Ensemble" and field_list.has_shares(parcel):
        return field_list.field_share_mm(parcel, period, "et")

    by_date, _rows = _cache_by_date(parcel, period, variable, model, CACHE_KEYS.get(variable, "et"))
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
    from datasync import field_list
    from datasync.models import CropETFigure

    from_fields = variable == "ET" and model == "Ensemble" and field_list.has_shares(parcel)
    note = _fields_note(parcel) if from_fields else ""
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
                fields=fields_received(parcel, period) if from_fields else [],
                fetched_on=newest.fetched_on,
                note=note,
            )
        )
    return written


def fields_received(parcel, period):
    """Each OpenET field's part of the month as OpenET's newest answer holds it, for a record.

    ``[{"field_id", "acres", "et_mm", "pr_mm"}]``: the field's acres inside the use area and its
    crop ET and rain in millimetres, as full-precision strings (rain None when the answer has
    none), in the order the use area's shares were made. Read from the same rows as
    :func:`newest_fetched`, so the list is the answer the record's figure comes from.
    """
    from datasync.models import OpenETFieldMonth, OpenETFieldShare

    shares = list(OpenETFieldShare.objects.filter(parcel=parcel).select_related("field").order_by("pk"))
    rows = {
        row.field_id: row
        for row in OpenETFieldMonth.objects.filter(
            field_id__in=[s.field_id for s in shares], month=month_first(period)
        )
    }
    out = []
    for share in shares:
        row = rows.get(share.field_id)
        out.append({
            "field_id": share.field.field_id,
            "acres": str(share.overlap_acres),
            "et_mm": None if row is None or row.et_mm is None else str(row.et_mm),
            "pr_mm": None if row is None or row.pr_mm is None else str(row.pr_mm),
        })
    return out


def recorded_fields(parcel, period):
    """The OpenET fields the month's record was made from, or None when it has none.

    ``[(field number, acres, crop ET mm or None, rain mm or None)]`` in the record's order, as
    Decimals. None when the month has no record or its record holds no fields (a use area with
    no OpenET field when it was recorded).
    """
    record = current_record(parcel, period)
    if record is None or not record.fields:
        return None
    return [
        (
            item["field_id"],
            Decimal(item["acres"]),
            None if item.get("et_mm") is None else Decimal(item["et_mm"]),
            None if item.get("pr_mm") is None else Decimal(item["pr_mm"]),
        )
        for item in record.fields
    ]


#: The same function under the name the field-list route reads in its own words.
record_received_months = record_fetched_months


def _fields_note(parcel):
    """``From OpenET's fields: 21106403648 (176.60 acres); ...``, the fields a figure is made from."""
    from datasync.models import OpenETFieldShare

    shares = OpenETFieldShare.objects.filter(parcel=parcel).order_by("field__field_id")
    parts = [f"{share.field.field_id} ({share.overlap_acres:.2f} acres)" for share in shares.select_related("field")]
    return "From OpenET's fields: " + "; ".join(parts)


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


@dataclass(frozen=True)
class RecordedMonth:
    """One use area-month's recorded crop ET in acre-feet, as the reports read it."""

    parcel_id: int
    parcel_number: str
    area_acres: Decimal
    month: dt.date
    acre_feet: Decimal


def recorded_acre_feet(start, end):
    """Every current record (ET, Ensemble) whose month starts in ``start``..``end``, in acre-feet.

    One query. The figure is the record's depth over the use area's acres, rounded to
    four places and positive: ``et_mm_to_acre_feet(_tidy(depth), acres)``. A use area with no acres has no
    figure and is left out. Ordered by use area number, then month.
    """
    from accounting.services import et_mm_to_acre_feet
    from datasync.models import CropETFigure

    rows = (
        CropETFigure.objects.current()
        .filter(
            variable="ET",
            model_name="Ensemble",
            month__gte=start,
            month__lte=end,
            parcel__voided_at__isnull=True,
            parcel__replaced_by__isnull=True,
        )
        .exclude(parcel__area_acres__isnull=True)
        .exclude(parcel__area_acres=0)
        .order_by("parcel__parcel_number", "month")
        .values_list("parcel_id", "parcel__parcel_number", "parcel__area_acres", "month", "depth_mm")
    )
    return [
        RecordedMonth(
            parcel_id=pid,
            parcel_number=number,
            area_acres=acres,
            month=month,
            acre_feet=abs(et_mm_to_acre_feet(_tidy(depth), acres).quantize(Decimal("0.0001"))),
        )
        for pid, number, acres, month, depth in rows
    ]


def recorded_without_acres(start, end):
    """The numbers of use areas with a current record in ``start``..``end`` and no acres on record."""
    from django.db.models import Q

    from datasync.models import CropETFigure

    return set(
        CropETFigure.objects.current()
        .filter(
            variable="ET",
            model_name="Ensemble",
            month__gte=start,
            month__lte=end,
            parcel__voided_at__isnull=True,
            parcel__replaced_by__isnull=True,
        )
        .filter(Q(parcel__area_acres__isnull=True) | Q(parcel__area_acres=0))
        .values_list("parcel__parcel_number", flat=True)
    )


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


# -- A person's decision ------------------------------------------------------------------------


def _checked_reason(reason):
    from core.corrections import REASON_MAX_LENGTH, REASON_MIN_LENGTH, REASON_SENTENCE
    from core.history import clean_note

    text = (reason or "").strip()
    note = clean_note(text) if REASON_MIN_LENGTH <= len(text) <= REASON_MAX_LENGTH else None
    if note is None or not REASON_MIN_LENGTH <= len(note) <= REASON_MAX_LENGTH:
        raise ValueError(REASON_SENTENCE)
    return note


def accept_newer_figure(record, *, user, reason):
    """Replace ``record`` with OpenET's newer figure.

    On a use area with OpenET fields the new record keeps the newer answer's fields, so
    the month's rain comes from the same answer as its crop ET (ruling 208).
    A recorded correction carrying ``reason``: the old record stays,
    struck. Raises ``core.corrections.AlreadyVoided`` / ``AlreadyReplaced``, ``ValueError``
    (the reason sentence, or :data:`NO_NEWER_SENTENCE`) or
    ``accounting.locks.PeriodFinalized`` before anything is written. Inside a finalized
    year it goes through only inside ``accounting.locks.override``. Returns the months
    to recalculate; the caller starts them.
    """
    from accounting.locks import refuse_if_finalized
    from core import corrections
    from core.history import change_note
    from datasync import field_list
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
                # The newer answer's fields, its rain included (ruling 208).
                fields=fields_received(locked.parcel, period) if field_list.has_shares(locked.parcel) else [],
                fetched_on=newer.fetched_on,
                replaces=locked,
                change_reason=note,
                created_by=user if getattr(user, "is_authenticated", False) else None,
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
    sends (its figure, received day, pill and sentences). The band's ``action`` is what its button
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


def _waiting_lines(first):
    """The lines under the waiting month's heading (ruling 212, rows 6 and 6b)."""
    import os

    if not os.environ.get("OPENET_API_KEY", ""):
        return (
            "OpenH2O cannot ask OpenET for crop ET until whoever runs the site sets its OpenET "
            "key. The month is left out of this use area's balance until then. Its meter "
            "readings still count against the groundwater allocation."
        )
    return (
        f"OpenET has not sent crop ET for {first:%B %Y} yet. The month is left out of this use "
        "area's balance until it arrives. Its meter readings still count against the "
        "groundwater allocation."
    )


NO_FIGURE_ENTRIES = "The month's ledger entries are below."


def no_figure_context(parcel, period):
    """The page of a month waiting for OpenET; None otherwise.

    A month is waiting when it has ended, has no recorded crop ET, and the use area lies in an
    OpenET field (or, on the older per-use-area route, OpenET was asked and sent nothing). The
    page names the month and lists the month's ledger supplies as figures, each with the
    site's How measured pills. Nothing is calculated or estimated for the month.
    """
    from accounting.services import (
        groundwater_kind_terms, supply_kind_lines, surface_kind_terms,
    )
    from parcels.models import ParcelLedger

    first = month_first(period)
    if first >= this_month() or current_record(parcel, period) is not None:
        return None
    if not (is_waiting(parcel, period) or asked_and_none_sent(parcel, period)):
        return None
    billable = ParcelLedger.objects.current().filter(
        parcel=parcel, effective_date__year=first.year, effective_date__month=first.month
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
    lines = _waiting_lines(first) + (" " + NO_FIGURE_ENTRIES if supplies else "")
    return {"headline": f"Waiting for OpenET: {first:%B %Y}", "lines": lines, "supplies": supplies}


def _who(user):
    if user is None:
        return "a former user"
    first, last = user.first_name.strip(), user.last_name.strip()
    if first and last:
        return f"{first[0]}. {last}"
    return user.get_full_name().strip() or user.email or user.get_username()
