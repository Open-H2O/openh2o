# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the parcel download did, and the sentences the wizard and the command show.

The words were approved word for word on 2026-11-15; only the counts and the plural
forms change. The wizard's result row and
``auto_populate``'s closing lines are built here, so they always say the same thing.

How the counts fit. Every parcel: the parcels that overlap the boundary = saved +
already on file + no number + no outline + repeats of a number. A list: the
different numbers on it = saved + already on file + not found.
"""
from dataclasses import asdict, dataclass, field

IMPORT_USE_AREAS = "Import use areas"


@dataclass
class ParcelDownload:
    #: "every" or "list".
    mode: str = "every"
    found: int = 0
    saved: int = 0
    already: int = 0
    no_number: int = 0
    no_outline: int = 0
    repeat_records: int = 0
    repeat_numbers: int = 0
    listed: int = 0
    not_found: list = field(default_factory=list)
    #: None when the download finished; else "stopped" (the map stopped
    #: responding), "refused" (an error a second try repeats) or "process"
    #: (the download's own process stopped with no word).
    stopped: str | None = None
    #: For a stop: the batch and count, and the map's own words.
    batch: int = 0
    batches: int = 0
    kind: str = ""
    code: object = None
    detail: str = ""
    got: int = 0
    asked: int = 0

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _n(value):
    return f"{value:,}"


def _s(count, one, many):
    return one if count == 1 else many


def saved_lines(o):
    """Rows 15 to 22: what a finished download saved and left out."""
    lines = []
    if o.mode == "list":
        lines.append(
            f"Your list holds {_n(o.listed)} different parcel {_s(o.listed, 'number', 'numbers')}. "
            f"OpenH2O saved {_n(o.saved)} of them as new use areas.")
        if o.already:
            lines.append(_already(o.already))
    elif o.found == 0:
        return [_line(
            "DWR's parcel map has no parcels that overlap this boundary. The map covers "
            "California only. For land outside California, load your parcel outlines with "
            "Import use areas on the Use Areas page.", link=IMPORT_USE_AREAS)]
    elif o.saved == 0:
        lines.append(
            f"OpenH2O did not save any new use areas. {_n(o.already)} "
            f"{_s(o.already, 'parcel was already a use area', 'parcels were already use areas')} "
            "on this site.")
    else:
        lines.append(f"OpenH2O saved {_n(o.saved)} new use {_s(o.saved, 'area', 'areas')}.")
        if o.already:
            lines.append(_already(o.already))
    if o.mode == "every" and (o.no_number or o.no_outline):
        text = (f"OpenH2O left out {_n(o.no_number)} {_s(o.no_number, 'parcel', 'parcels')} "
                "without a parcel number")
        if o.no_outline:
            text += f" and {_n(o.no_outline)} whose outline it cannot read"
        lines.append(text + ".")
    if o.repeat_records and o.saved:
        # Only when this run saved use areas: a run that saved none would say it
        # saved one for each repeated number.
        lines.append(
            f"DWR's map has {_n(o.repeat_records)} duplicate "
            f"{_s(o.repeat_records, 'record', 'records')} of {_n(o.repeat_numbers)} parcel "
            f"{_s(o.repeat_numbers, 'number', 'numbers')}. OpenH2O saved one use area for each "
            "number.")
    if o.mode == "list" and o.not_found:
        count = len(o.not_found)
        lines.append(_line(
            f"{_n(count)} parcel {_s(count, 'number', 'numbers')} on your list "
            f"{_s(count, 'does', 'do')} not match any parcel that overlaps the boundary:",
            numbers=list(o.not_found)))
    return [_line(t) if isinstance(t, str) else t for t in lines]


def _already(count):
    return (f"{_n(count)} other {_s(count, 'parcel was already a use area', 'parcels were already use areas')}"
            " on this site.")


def stopped_lines(o):
    """Rows 23 to 26: the cause of a stop, then how to add the rest."""
    if o.stopped == "refused":
        return [_line(f"DWR's parcel map returned this error: {_sentence(o.detail)} Running the "
                      "step again will return the same error.")]
    if o.stopped == "process":
        first = f"The parcel download stopped after OpenH2O saved {_n(o.saved)} new use areas."
    else:
        first = f"DWR's parcel map stopped responding after OpenH2O saved {_n(o.saved)} new use areas."
    return [_line(first), _line(
        "To add the rest, open the Setup Wizard and choose this boundary under Select an "
        "existing boundary. On Populate, check only Parcel Boundaries and choose your list "
        "again if you used one. OpenH2O saves only the parcels that are not yet on file.")]


def command_stop_reason(o):
    """Rows 31 and 32: the reason the command prints after a stop."""
    if o.stopped == "refused":
        return stopped_lines(o)[0]["text"]
    if o.batch == 0 or (o.kind != "short" and o.code is None):
        # The IDs request, or a batch whose requests themselves failed (no code).
        return f"DWR's parcel map stopped responding after OpenH2O saved {_n(o.saved)} new use areas."
    if o.kind == "short":
        return (f"After 6 attempts, DWR's parcel map had returned only {_n(o.got)} of the "
                f"{_n(o.asked)} parcels OpenH2O asked for in batch {o.batch} of {o.batches}.")
    return (f"DWR's parcel map returned error {o.code} on all 6 attempts at batch {o.batch} of "
            f"{o.batches}: {_sentence(o.detail)}")


COMMAND_RERUN = ("Run the same command again to add the rest. OpenH2O saves only the parcels "
                 "that are not yet on file.")


def batch_line(batch, batches, saved, already, dry_run):
    """Rows 28 and 29."""
    if dry_run:
        return f"Batch {batch} of {batches}: would save {_n(saved)} new use areas"
    return f"Batch {batch} of {batches}: {_n(saved)} new use areas, {_n(already)} already on file"


def plain(line):
    """A line as the command prints it."""
    if line.get("numbers"):
        return line["text"] + " " + ", ".join(line["numbers"]) + "."
    return line["text"]


def _line(text, link=None, numbers=None):
    line = {"text": text}
    if link:
        before, _, after = text.partition(link)
        line.update(link=link, before=before, after=after)
    if numbers is not None:
        line["numbers"] = numbers
    return line


def _sentence(text):
    text = str(text or "").strip()
    return text if text.endswith((".", "!", "?")) else text + "."
