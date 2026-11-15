# SPDX-License-Identifier: AGPL-3.0-or-later
"""State the lining of each demonstration point of diversion.

Each point of diversion is stated as lined, unlined or pipe, to help with
seepage calculations. Every demonstration point
keeps the platform's default loss basis, so the lining set here also sets its
default seepage share (``PointOfDiversion.apply_lining_default``).

What the sources say, read 2026-10-11:

- One irrigation district's 2020 agricultural water management plan counts 406
  miles of unlined canal and 105 of lined canal (Table 2), and names no single
  canal's lining. A search result for a 2018 regional water plan mentioned
  lining portions of two canals, and a 2025 headworks replacement bid lines one
  headworks; neither says a canal is lined along its length, and the 2018 plan
  itself was never read. Each canal point is set to unlined, the majority, and
  its note says the lining is an assumption.
- The Bottomlands riparian take and the Snelling re-diversion are left not
  stated. The re-diversion serves no use area in the demonstration.
- The Merced Falls hydroelectric diversion passes its water through the power
  plant and back to the river, which the demonstration takes as a pipe.

Notes name no district. A re-run takes out every note an earlier version of
this command wrote (``_RETIRED_NOTE``, ``_RETIRED_NOTES``) and appends the
current note to the point's own notes once. Idempotent, keyed on the
demonstration names, and touches no other point.
"""
import re

from django.core.management.base import BaseCommand

from surface.models import PointOfDiversion

# The notes, word for word as approved. Each says the lining is an assumption
# for the demonstration and, for the canals, the one figure behind it.
_UNLINED = (
    "The lining below is an assumption for the demonstration. An irrigation "
    "district in the area reports 406 miles of canal unlined and 105 miles lined "
    "in its 2020 agricultural water management plan."
)
_RIVER_TAKE = (
    "This river take's lining is not stated in the demonstration, so its "
    "seepage share is zero."
)
_RE_DIVERSION = (
    "This re-diversion does not serve a use area in the demonstration, so the "
    "lining is not stated."
)
_PIPE = (
    "Pipe is an assumption for the demonstration, because this diversion's "
    "water passes through the power plant and back to the river."
)

LINING_BY_POD = {
    "MER-POD-004-DEMO Atwater Canal Headgate": ("unlined", _UNLINED),
    "MER-POD-005-DEMO Le Grand Canal Headgate": ("unlined", _UNLINED),
    "MER-POD-006-DEMO Stevinson Diversion Canal Headgate": ("unlined", _UNLINED),
    "MER-POD-007-DEMO Plainsburg El Nido Canal Headgate": ("unlined", _UNLINED),
    "MER-POD-008-DEMO Crocker-Huffman River Diversion": ("unlined", _UNLINED),
    "MER-POD-009-DEMO Bottomlands Riparian Take": (None, _RIVER_TAKE),
    "MER-POD-010-DEMO Merced Falls Hydroelectric Diversion": ("pipe", _PIPE),
    "MER-POD-011-DEMO Snelling Re-Diversion": (None, _RE_DIVERSION),
    "MER-BPOD-001 El Nido Canal Recharge Intake": ("unlined", _UNLINED),
}

# Every note an earlier version of this command wrote, so a re-run takes it out
# and a point ends with one current note. The first build (2026-10-11 16:40 PDT)
# named a real district in a paragraph opening with the comma form below,
# matched by prefix so this file never has to spell the banned name. The five
# notes that replaced it (2026-10-11 to 2026-11-14) are matched whole.
_RETIRED_NOTE = re.compile(r"Demonstration data: lining set to unlined, [^\n]*")
_MAJORITY_150_3 = (
    "Demonstration data: lining set to unlined. A published water management "
    "plan for this area counts 406 miles of unlined canal against 105 of lined "
    "canal, and no published source read states this canal's own lining."
)
_RETIRED_NOTES = (
    _MAJORITY_150_3,
    _MAJORITY_150_3 + " A regional water plan from 2018 lists lining portions of this canal.",
    "Demonstration data: lining not stated. This riparian take draws from the "
    "Merced River with no canal of its own, and no published source describes "
    "how its water reaches the fields, so it carries no seepage share.",
    "Demonstration data: lining set to pipe. A hydroelectric diversion passes "
    "its water through the power plant and back to the river.",
    "Demonstration data: lining not stated. This re-diversion takes from the "
    "Merced River with no canal of its own, and no published source describes "
    "how its water reaches the fields, so it carries no seepage share.",
)


def _without_retired(notes):
    """The notes with every paragraph an earlier version of this command wrote taken out."""
    parts = [_RETIRED_NOTE.sub("", part).strip() for part in notes.split("\n\n")]
    return "\n\n".join(part for part in parts if part and part not in _RETIRED_NOTES)


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
