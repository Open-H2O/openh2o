# SPDX-License-Identifier: AGPL-3.0-or-later
"""State the lining of each demonstration point of diversion (150.3-01).

Brent, 2026-10-11 11:50 PDT: "Yes, lets add lined, unlined, and pipe choice to
each point of diversion to help with seepage calcs." Every demonstration point
keeps the platform's default loss basis, so the lining set here also sets its
default seepage share (``PointOfDiversion.apply_lining_default``).

What the sources say, read 2026-10-11:

- The area's 2020 water management plan counts 406 miles of unlined canal and
  105 of lined canal, and names no canal's lining. A 2018 regional water plan
  lists lining portions of the Main and Le Grand Canals; a 2025 headworks
  replacement bid lines the Atwater headworks only. No source read says any of
  these canals is lined along its length, so each canal point is set to
  unlined, the area's majority, and its notes say so.
- The two river takes with no canal of their own (the Bottomlands riparian take
  and the Snelling re-diversion) are left not stated: no source describes how
  their water reaches a field, so they keep no seepage share.
- The Merced Falls hydroelectric diversion passes its water through the power
  plant and back to the river, which is a pipe.

Notes name no district (Brent 2026-10-11 17:51 PDT: "We arent supposed to be
pointing out individual districts"); the words were approved 18:43 PDT. Each
entry's note replaces any earlier note this command wrote (``_RETIRED_NOTE``)
and is otherwise appended to the point's own notes once. Idempotent, keyed on
the demonstration names, and touches no other point.
"""
import re

from django.core.management.base import BaseCommand

from surface.models import PointOfDiversion

_MAJORITY = (
    "Demonstration data: lining set to unlined. A published water management "
    "plan for this area counts 406 miles of unlined canal against 105 of lined "
    "canal, and no published source read states this canal's own lining."
)
_PARTLY_LINED = " A regional water plan from 2018 lists lining portions of this canal."

LINING_BY_POD = {
    "MER-POD-004-DEMO Atwater Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-005-DEMO Le Grand Canal Headgate": ("unlined", _MAJORITY + _PARTLY_LINED),
    "MER-POD-006-DEMO Stevinson Diversion Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-007-DEMO Plainsburg El Nido Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-008-DEMO Crocker-Huffman River Diversion": ("unlined", _MAJORITY + _PARTLY_LINED),
    "MER-POD-009-DEMO Bottomlands Riparian Take": (
        None,
        "Demonstration data: lining not stated. This riparian take draws from "
        "the Merced River with no canal of its own, and no published source "
        "describes how its water reaches the fields, so it carries no seepage "
        "share.",
    ),
    "MER-POD-010-DEMO Merced Falls Hydroelectric Diversion": (
        "pipe",
        "Demonstration data: lining set to pipe. A hydroelectric diversion "
        "passes its water through the power plant and back to the river.",
    ),
    "MER-POD-011-DEMO Snelling Re-Diversion": (
        None,
        "Demonstration data: lining not stated. This re-diversion takes from "
        "the Merced River with no canal of its own, and no published source "
        "describes how its water reaches the fields, so it carries no seepage "
        "share.",
    ),
    "MER-BPOD-001 El Nido Canal Recharge Intake": ("unlined", _MAJORITY),
}

# Notes an earlier version of this command wrote (150.3-01 as first built,
# 2026-10-11 16:40 PDT) named a real district. Each was one paragraph opening
# with this prefix (a comma where the current note has a full stop), so a re-run
# removes that paragraph before appending the current note. Matched by prefix so
# this file never has to spell the banned name.
_RETIRED_NOTE = re.compile(r"Demonstration data: lining set to unlined, [^\n]*")


def _without_retired(notes):
    """The notes with any retired paragraph this command wrote taken out."""
    if not _RETIRED_NOTE.search(notes):
        return notes
    parts = [_RETIRED_NOTE.sub("", part).strip() for part in notes.split("\n\n")]
    return "\n\n".join(part for part in parts if part)


def apply_demo_pod_lining():
    """Set each demonstration point's lining and note; return how many changed."""
    changed = 0
    for name, (lining, note) in LINING_BY_POD.items():
        pod = PointOfDiversion.objects.filter(name=name).first()
        if pod is None:
            continue
        notes = _without_retired(pod.notes or "")
        if note not in notes:
            notes = f"{notes}\n\n{note}" if notes else note
        if pod.lining == lining and pod.notes == notes:
            continue
        pod.lining = lining
        pod.notes = notes
        pod.save()
        changed += 1
    return changed


class Command(BaseCommand):
    help = "State the lining of each Merced demonstration point of diversion."

    def handle(self, *args, **options):
        changed = apply_demo_pod_lining()
        self.stdout.write(
            self.style.SUCCESS(
                f"  {changed} of {len(LINING_BY_POD)} demonstration points of "
                "diversion given their lining."
            )
        )
