# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized water year's code: taking it, checking it, and the words about it.

(The screen calls it "Changes to this year's records" and the code a "code". The module,
the model fields and the routes keep the older name, because the code is computed from the
parts' names and renaming any of them would flip every stored code to "disagrees".)

``core.fingerprint`` reads the records and returns the digests. This module keeps
the result on the water year (``fingerprint``, ``fingerprint_at``,
``fingerprint_parts``), answers Check, and builds what the page and the
downloaded file print.

Taking one never saves: :func:`take_fingerprint` fills the three fields and the
caller saves the period, inside the transaction that holds its row. A correction
or a void never retakes it; finalizing a reopened year does, and the first code
the year ever had is kept beside the newest.

Check changes no record, so pressing it leaves no Change history behind and
cannot move the code it is checking. (The Figures as filed comparison it may read
keeps its usual entry in the cache.)
"""

import datetime as dt
import textwrap
from dataclasses import dataclass, field

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from accounting.statements import _day, _who, cached_comparison, corrections_since
from core import corrections, fingerprint
from core.fingerprint import short_code


def has_fingerprint(period):
    """Whether the water year page shows the line: finalized, with a code on file."""
    return bool(period.is_finalized and period.fingerprint and period.fingerprint_parts)


# -- Taking ----------------------------------------------------------------------------------


def take_fingerprint(period):
    """Compute the year's fingerprint and set it on ``period`` (not saved).

    A year that already carries a code keeps its earliest one as ``first``.
    """
    computed = fingerprint.compute(period)
    stored = {
        "version": fingerprint.VERSION,
        "parts": computed.parts,
        "columns": computed.columns,
        "water_year": computed.water_year,
    }
    earlier = (period.fingerprint_parts or {}).get("first")
    if earlier:
        stored["first"] = earlier
    elif period.fingerprint:
        stored["first"] = {
            "digest": period.fingerprint,
            "at": period.fingerprint_at.isoformat() if period.fingerprint_at else "",
        }
    period.fingerprint = computed.digest
    period.fingerprint_at = timezone.now()
    period.fingerprint_parts = stored
    return period


FINGERPRINT_FIELDS = ["fingerprint", "fingerprint_at", "fingerprint_parts"]


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
        "first_label": "as filed" if first else "",
    }


# -- Check -----------------------------------------------------------------------------------


#: The parts OpenH2O's calculation writes when it recalculates, read from the code:
#: ``accounting.engine_run.run_month`` runs ``run_calculations`` (the Use ledger rows and the Calculation
#: results; it also clears the retired Water credits and Water credit draws of the parcel-month and can
#: move the carry-over pool), then ``surface.services.allocate_district_delivery`` (Canal losses,
#: Unallocated deliveries, and through canal seepage the carry-over pool and Account credits) and removes
#: Diversion records the retired estimate left in the month.
RECALCULATION_PARTS = frozenset(
    {
        "parcels.ParcelLedger",
        "accounting.CalculationRun",
        "surface.DiversionRecord",
        "surface.UnallocatedDelivery",
        "surface.CanalMonthLoss",
        "accounting.AllocationCarryover",
        "accounting.AccountCredit",
    }
)

#: Parts a correction of one kind writes itself, with no recalculation: correcting or voiding a recharge
#: event takes its credit and its pool deposit back and writes the new row's
#: (``core.corrections._recharge_event_on_correct``, ``accounting.services.create_recharge_ledger_entries``).
KIND_SIDE_EFFECTS = {
    "recharge.RechargeEvent": frozenset({"accounting.AccountCredit", "accounting.AllocationCarryover"})
}

#: The Use areas part reads the use areas that have a ledger row or a calculation in the year. A
#: recalculation writes no use area row, but the first ledger row or result it writes for a use area
#: brings that use area into the part, so the part gains a row. After any correction a growth in the
#: number of rows is the recalculation's doing; a change with the same number of rows is an edit to a
#: use area and is named.
GROWS_WITH_RECALCULATION = frozenset({"parcels.Parcel"})

# The limit of this rule, as the downloaded file says: the code keeps one digest per part, so a correction
# cannot be told apart from an unrecorded change in a part it explains.


@dataclass
class Answer:
    """What Check for changes found. ``state`` is matches, differs, disagrees or unreadable."""

    state: str
    taken: str
    #: Every part that differs, in words (lower case), in the year's order.
    differing: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    #: The unreadable parts the sections switched off on this site explain:
    #: ``([section labels], [part words])`` in the registry's order, or None. The
    #: change history is among the parts when nothing else keeps it from being read.
    switched_off: tuple = None
    #: ``[{"text": ..., "linked": bool}, ...]``, oldest first.
    corrections: list = field(default_factory=list)
    #: The differing parts the corrections since do not explain, in words.
    unexplained: list = field(default_factory=list)
    #: Where the count of corrections leads.
    count_href: str = ""

    @property
    def look_at(self):
        """The parts named after "Look at:": the differing parts no correction explains."""
        return self.unexplained

    @property
    def look_at_words(self):
        return ", ".join(self.unexplained)

    @property
    def unreadable_sentence(self):
        sentences = []
        if self.switched_off:
            labels, parts = self.switched_off
            sentences.append(switched_off_sentence(labels, parts))
        explained = set(self.switched_off[1]) if self.switched_off else set()
        removed = [part for part in self.unreadable if part not in explained]
        if len(removed) == 1:
            sentences.append(
                f"OpenH2O can no longer read the {removed[0]}, because a later "
                "version removed what it was computed from."
            )
        elif removed:
            sentences.append(
                f"OpenH2O can no longer read these parts: {', '.join(removed)}, because a "
                "later version removed what they were computed from."
            )
        return " ".join(sentences)


def _and(words):
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def switched_off_sentence(labels, parts):
    """The answer's sentence for the parts the sections switched off on this site keep from being read."""
    return (
        "Check for changes cannot compare these parts while this site has the "
        f"{_and(labels)} section{'s' if len(labels) > 1 else ''} switched off: {', '.join(parts)}."
    )


def _sections_off(keys):
    """``([section labels], [part keys])`` for the unreadable ``keys`` whose section is switched off.

    A part's section is the module that owns its app (``core.modules``). The change
    history holds the changes to those parts' rows, so it goes with them when it is
    the only other part that cannot be read. ``None`` when no section explains any.
    """
    from core.modules import MODULE_REGISTRY, is_enabled

    owner = {app: spec for spec in MODULE_REGISTRY.values() for app in spec.apps}
    found = {}
    rest = []
    for key in keys:
        spec = owner.get(key.split(".")[0])
        if spec is not None and not is_enabled(spec.name):
            found.setdefault(spec.name, (spec.label, []))[1].append(key)
        else:
            rest.append(key)
    names = [name for name in MODULE_REGISTRY if name in found]
    if not names:
        return None
    labels = [found[name][0] for name in names]
    parts = [key for name in names for key in found[name][1]]
    if rest == [fingerprint.HISTORY]:
        parts.append(fingerprint.HISTORY)
    return labels, parts


def _lower(key):
    return fingerprint.PART_NAMES[key].lower()


def _day_iso(moment):
    """``2025-10-15``: the day the code was taken, in Pacific time as the pages print it."""
    from accounting.statements import _pacific

    return timezone.localtime(moment, _pacific()).date().isoformat()


def check_fingerprint(period):
    """Recompute the year over what its code kept and compare. Changes no record."""
    stored = period.fingerprint_parts
    taken = _day(period.fingerprint_at)
    computed = fingerprint.compute(period, stored)
    differing = [
        key
        for key in fingerprint.PART_KEYS
        if key in computed.parts and computed.parts[key]["digest"] != stored["parts"][key]["digest"]
    ]
    unreadable = [_lower(key) for key in computed.unreadable]
    off = _sections_off(computed.unreadable)
    off = (off[0], [_lower(key) for key in off[1]]) if off else None
    agrees = fingerprint.whole_digest(stored["parts"]) == period.fingerprint
    if differing:
        found, kinds = _corrections(period)
        unexplained = _unexplained(differing, kinds, bool(found), stored, computed)
        return Answer(
            "differs", taken, [_lower(key) for key in differing], unreadable, off, found,
            [_lower(key) for key in unexplained], _count_href(period, found),
        )
    if not agrees:
        return Answer("disagrees", taken, [], unreadable, off)
    if unreadable:
        return Answer("unreadable", taken, [], unreadable, off)
    return Answer("matches", taken)


def _starts_recalculation(model):
    """Whether a correction of the kind stored in ``model`` recalculates anything."""
    return any(
        kind["model"].lower() == model.lower() and corrections.starts_recalculation(kind)
        for kind in corrections.KINDS.values()
    )


def _unexplained(differing, kinds, any_correction, stored, computed):
    """The differing parts, in order, that the corrections since do not explain.

    A part is explained by a correction of its own kind; whatever the kind, Change history and the parts
    a recalculation writes (:data:`RECALCULATION_PARTS`); a recharge event's own side effects; and
    the Use areas part when it only gained rows. With no correction nothing is explained, except that
    Change history is not named beside another part (a direct edit leaves history behind), and is
    named when it is the only part that differs.
    """
    if not any_correction:
        others = [key for key in differing if key != fingerprint.HISTORY]
        return others or list(differing)
    explained = {fingerprint.HISTORY}
    recalculated = False
    for model in kinds:
        explained.add(model)
        explained |= KIND_SIDE_EFFECTS.get(model, frozenset())
        recalculated = recalculated or _starts_recalculation(model)
    if recalculated:
        explained |= RECALCULATION_PARTS
    unexplained = []
    for key in differing:
        if key in explained:
            continue
        if recalculated and key in GROWS_WITH_RECALCULATION and computed.parts[key]["rows"] > stored["parts"][key].get("rows", 0):
            continue
        unexplained.append(key)
    return unexplained


def _count_href(period, found):
    """The Figures as filed card when it lists one of the corrections, else Change history from the day taken."""
    if any(c["linked"] for c in found):
        return "#figures-as-filed"
    return f"{reverse('change_history')}?from={_day_iso(period.fingerprint_at)}"


def _corrections(period):
    """``(corrections, kinds)``: the corrections recorded since the code was taken, each marked linked or
    plain, and the model labels of the kinds they are of."""
    from core.corrections import KINDS

    models = {kind["label"]: kind["model"] for kind in KINDS.values()}
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
    return found, {models[line.kind_label] for line in lines}


# -- The downloaded page ---------------------------------------------------------------------

_WIDTH = 76

#: The width of the label column of the header rows (Finalized, Code, Full code, Taken, First code).
_LABEL = 12

_COVERS = (
    "OpenH2O computed the code from every row below at the moment the code was "
    "issued, including records marked void or replaced, and from every Change "
    "history entry of those rows. Station readings covers only readings entered by "
    "hand. For a use area with a record in the "
    "year, the code reads its number and whether it was voided, not its acres or "
    "other details. For a fallow period it reads the end month only up to the "
    "year's end. Change history of use areas and fallow periods is left out. "
    "Nothing else is covered: links and settings (which zone a use area is in, "
    "which well and meter serve it, which use areas a point of diversion serves, "
    "which accounts are active, account names, site settings), the stored OpenET "
    "figures, and anything a later version of OpenH2O adds. These can "
    "change a figure on the Figures as filed card without changing this code."
)

_STEPS = (
    "Open the water year page for {name} in OpenH2O.",
    "Compare the code on the page with the code on this file. Someone able to change "
    "the records could also change the code on the page; this file catches that. For "
    "a dispute, download this page again and compare the full code.",
    "Press Check for changes. OpenH2O recomputes the code from the records now.",
    "Read the answer. When Check for changes finds a change, the answer begins with the "
    "number of corrections to the year's records recorded since, if any are recorded, and "
    "goes on to name the parts to look at where changes have no correction on record. The "
    "parts the answer names leave out the parts a correction explains, so an unrecorded "
    "change there shows only as the correction: each correction explains its own part and "
    "the change history, and correcting or voiding a meter reading, a ledger entry, a "
    "fallow period or a diversion record, or voiding a use area, also explains the parts a "
    "recalculation writes, because it recalculates the months it moves. \"Can no longer "
    "read\" means a later version removed what a part was computed from. When the answer "
    "names a section that is switched off, Check for changes cannot compare that section's "
    "parts, or the change history, while the section is switched off.",
)

_MEANING = (
    "\"No changes found\" means what the code covers is the same as when it was issued. "
    "It does not show that the records were right. Check for changes runs inside "
    "OpenH2O, so it does not catch a change to the software."
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
    return f"changes-code-{slugify(period.name) or 'water-year'}.txt"


def file_text(period):
    """The one-page text file, ready to send."""
    from core.site_identity import derive_name

    stored = period.fingerprint_parts
    first = _first(period)
    taken = _day(period.fingerprint_at)
    finalized = _day(period.finalized_at)
    if period.finalized_by:
        finalized += f" by {_who(period.finalized_by)}"
    if first:
        taken_line = f"{taken}, when the year was finalized again"
    else:
        taken_line = f"{taken}, when the year was finalized"
    as_filed = ""
    if first:
        label = "As filed"
        as_filed = (
            f"{label:<{_LABEL}}{short_code(first[0])}, issued {first[1]}\n"
            f"{label:<{_LABEL}}{first[0].upper()}\n"
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
