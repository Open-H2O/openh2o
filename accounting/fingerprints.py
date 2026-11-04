# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized water year's fingerprint: taking it, checking it, and the words about it.

``core.fingerprint`` reads the records and returns the digests. This module keeps
the result on the water year (``fingerprint``, ``fingerprint_at``,
``fingerprint_parts``), answers Check, and builds what the page and the
downloaded file print.

Taking one never saves: :func:`take_fingerprint` fills the three fields and the
caller saves the period, inside the transaction that holds its row. A correction
or a void never retakes it; finalizing a reopened year does, and the first code
the year ever had is kept beside the newest.

Check reads and writes nothing, so pressing it leaves no Change history behind
and cannot move the code it is checking.
"""

import datetime as dt
import textwrap
from dataclasses import dataclass, field

from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from accounting.statements import _day, _who, cached_comparison, corrections_since
from core import fingerprint
from core.fingerprint import short_code

#: The reason the upgrade records under, so Change history says why.
UPGRADE_REASON = "Recorded when OpenH2O began keeping fingerprints."


def has_fingerprint(period):
    """Whether the water year page shows the line: finalized, with a code on file."""
    return bool(period.is_finalized and period.fingerprint and period.fingerprint_parts)


# -- Taking ----------------------------------------------------------------------------------


def take_fingerprint(period, *, at_upgrade=False):
    """Compute the year's fingerprint and set it on ``period`` (not saved).

    A year that already carries a code keeps its earliest one as ``first``.
    """
    computed = fingerprint.compute(period)
    stored = {
        "version": fingerprint.VERSION,
        "parts": computed.parts,
        "columns": computed.columns,
    }
    earlier = (period.fingerprint_parts or {}).get("first")
    if earlier:
        stored["first"] = earlier
    elif period.fingerprint:
        stored["first"] = {"digest": period.fingerprint, "at": period.fingerprint_at.isoformat() if period.fingerprint_at else ""}
    if at_upgrade:
        stored["at_upgrade"] = True
    period.fingerprint = computed.digest
    period.fingerprint_at = timezone.now()
    period.fingerprint_parts = stored
    return period


FINGERPRINT_FIELDS = ["fingerprint", "fingerprint_at", "fingerprint_parts"]


def record_upgrade_fingerprints():
    """Take a fingerprint for each finalized year that has none. Returns the periods.

    The period row is held while its code is taken, so two starts at once (the
    container's boot and a person's command) write one. A year with a code is
    left alone. Nothing is written for an open year.
    """
    from accounting.models import ReportingPeriod

    taken = []
    for pk in ReportingPeriod.objects.filter(is_finalized=True).order_by("start_date").values_list("pk", flat=True):
        with transaction.atomic():
            period = ReportingPeriod.objects.select_for_update().get(pk=pk)
            if not period.is_finalized or period.fingerprint:
                continue
            take_fingerprint(period, at_upgrade=True)
            period.save(update_fields=FINGERPRINT_FIELDS)
            taken.append(period)
    return taken


# -- The line on the page --------------------------------------------------------------------


def _first(period):
    """``(digest, words)`` of the first code a restated year had, or None."""
    first = (period.fingerprint_parts or {}).get("first")
    if not first or not first.get("digest"):
        return None
    when = ""
    if first.get("at"):
        when = _day(dt.datetime.fromisoformat(first["at"]))
    return first["digest"], when


def line_context(period):
    """What `_fingerprint.html` prints, or None when the year shows no line."""
    if not has_fingerprint(period):
        return None
    first = _first(period)
    return {
        "code": short_code(period.fingerprint),
        "taken": _day(period.fingerprint_at),
        "restated": first is not None,
        "first_code": short_code(first[0]) if first else "",
        "first_taken": first[1] if first else "",
    }


# -- Check -----------------------------------------------------------------------------------


@dataclass
class Answer:
    """What Check found. ``state`` is matches, differs, disagrees or unreadable."""

    state: str
    taken: str
    differing: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    #: ``[{"text": ..., "linked": bool}, ...]``, oldest first.
    corrections: list = field(default_factory=list)

    @property
    def unreadable_sentence(self):
        if not self.unreadable:
            return ""
        if len(self.unreadable) == 1:
            return (
                f"OpenH2O can no longer read the {self.unreadable[0]}, because a later "
                "version removed what it was computed from."
            )
        return (
            f"OpenH2O can no longer read these parts: {', '.join(self.unreadable)}, because a "
            "later version removed what they were computed from."
        )


def _lower(key):
    return fingerprint.PART_NAMES[key].lower()


def check_fingerprint(period):
    """Recompute the year over what its fingerprint kept and compare. Writes nothing."""
    stored = period.fingerprint_parts
    taken = _day(period.fingerprint_at)
    computed = fingerprint.compute(period, stored)
    differing = [
        key
        for key in fingerprint.PART_KEYS
        if key in computed.parts and computed.parts[key]["digest"] != stored["parts"][key]["digest"]
    ]
    unreadable = [_lower(key) for key in computed.unreadable]
    agrees = fingerprint.whole_digest(stored["parts"]) == period.fingerprint
    if differing:
        return Answer(
            "differs", taken, [_lower(key) for key in differing], unreadable,
            _corrections(period),
        )
    if not agrees:
        return Answer("disagrees", taken, [], unreadable)
    if unreadable:
        return Answer("unreadable", taken, [], unreadable)
    return Answer("matches", taken)


def _corrections(period):
    """The corrections recorded since the fingerprint was taken, each marked linked or plain."""
    lines = corrections_since(period, period.fingerprint_at, all_records=True)
    listed = set()
    if any(line.use_areas for line in lines):
        comparison = cached_comparison(period)
        if comparison is not None:
            listed = {c.identity for c in comparison.corrections}
    found = []
    for line in lines:
        on = f" of {line.day:%b} {line.day.day}, {line.day.year}" if line.day else ""
        found.append(
            {"text": f"{line.kind_label}{on}, {line.said}", "linked": line.identity in listed}
        )
    return found


# -- The downloaded page ---------------------------------------------------------------------

_WIDTH = 76

_COVERS = (
    "OpenH2O computed the code from every row below as it stood when the code was "
    "taken, records marked void or replaced included, and from every Change history "
    "entry of those rows. For a use area with a record in the year, the code reads its "
    "number and whether it was voided, not its acres or other details. For a fallow "
    "period it reads the end month only up to the year's end. Change history of use "
    "areas and fallow periods is left out. Links and settings (which zone a use area "
    "is in, which well serves it, account names, site settings) are not covered, and "
    "neither is anything a later version of OpenH2O adds."
)

_STEPS = (
    "Open the water year page for {name} in OpenH2O.",
    "Compare the code on the page with the code on this file. Someone able to change "
    "the records could also change the code on the page; this file catches that. For "
    "a dispute, download this page again and compare the full code.",
    "Press Check. OpenH2O recomputes the code from the records now.",
    "Read the answer. \"Does not match\" names the parts that differ and the "
    "corrections recorded since. \"Can no longer read\" means a later version removed "
    "what a part was computed from.",
)

_MEANING = (
    "\"Matches\" means what the code covers is the same as when it was taken. It does "
    "not show that the records were right. Check runs inside OpenH2O, so it does not "
    "catch a change to the software."
)

_KEEPING = (
    "OpenH2O does not send this file anywhere. Keeping it is the organization's choice."
)


def _wrap(text, indent="", first=None):
    return textwrap.fill(
        text, width=_WIDTH, initial_indent=indent if first is None else first, subsequent_indent=indent
    )


def _table(parts):
    """The two-column Part / Rows table of the parts with rows, then the ones with none."""
    shown = [(p["name"], p["rows"]) for key, p in _ordered(parts) if p["rows"] > 0]
    empty = [p["name"] for key, p in _ordered(parts) if p["rows"] == 0]
    cell = lambda name, rows: f"{name:<28}{rows:>5}"  # noqa: E731
    half = (len(shown) + 1) // 2
    left, right = shown[:half], shown[half:]
    lines = [f"  {cell('Part', 'Rows')}    {cell('Part', 'Rows')}"]
    for index, (name, rows) in enumerate(left):
        line = f"  {cell(name, f'{rows:,}')}"
        if index < len(right):
            line += f"    {cell(right[index][0], f'{right[index][1]:,}')}"
        lines.append(line.rstrip())
    out = "\n".join(lines)
    if empty:
        out += "\n\n" + _wrap("No rows in this year: " + ", ".join(empty) + ".", indent="  ")
    return out


def _ordered(parts):
    return [(key, parts[key]) for key in fingerprint.PART_KEYS if key in parts]


def file_name(period):
    return f"fingerprint-{slugify(period.name) or 'water-year'}.txt"


def file_text(period):
    """The one-page text file, ready to send."""
    from core.site_identity import derive_name

    stored = period.fingerprint_parts
    first = _first(period)
    taken = _day(period.fingerprint_at)
    if period.finalized_at:
        finalized = _day(period.finalized_at)
        if period.finalized_by:
            finalized += f" by {_who(period.finalized_by)}"
    else:
        finalized = "date not on record"
    if first:
        taken_line = f"{taken}, when the year was finalized again"
    elif stored.get("at_upgrade"):
        taken_line = f"{taken}, when OpenH2O began keeping fingerprints"
    else:
        taken_line = f"{taken}, when the year was finalized"
    as_filed = ""
    if first:
        as_filed = (
            f"As filed     {short_code(first[0])}, taken {first[1]}\n"
            f"As filed     {first[0].upper()}\n"
        )
    steps = "\n".join(
        _wrap(f"{number}. " + text.format(name=period.name), indent="   ", first="")
        for number, text in enumerate(_STEPS, start=1)
    )
    return render_to_string(
        "accounting/fingerprint.txt",
        {
            "site_name": derive_name() or "OpenH2O",
            "period": period,
            "start": _day(_midday(period.start_date)),
            "end": _day(_midday(period.end_date)),
            "finalized": finalized,
            "code": short_code(period.fingerprint),
            "full_code": period.fingerprint.upper(),
            "taken_line": taken_line,
            "as_filed": as_filed,
            "covers": _wrap(_COVERS),
            "table": _table(stored["parts"]),
            "steps": steps,
            "meaning": _wrap(_MEANING),
            "keeping": _wrap(_KEEPING),
        },
    )


def _midday(day):
    return dt.datetime.combine(day, dt.time(12))
