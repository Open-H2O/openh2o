# SPDX-License-Identifier: AGPL-3.0-or-later
"""State the lining of each demonstration point of diversion (150.3-01).

Brent, 2026-10-11 11:50 PDT: "Yes, lets add lined, unlined, and pipe choice to
each point of diversion to help with seepage calcs." Every demonstration point
keeps the platform's default loss basis, so the lining set here also sets its
default seepage share (``PointOfDiversion.apply_lining_default``).

What the sources say, read 2026-10-11:

- Merced Irrigation District's 2020 Agricultural Water Management Plan, Table 2,
  counts 406 miles of unlined canal and 105 of lined canal, and names no canal's
  lining. The 2018 Merced Integrated Regional Water Management Plan lists
  "lining portions of the Main and Le Grand Canals"; the district's 2025
  Atwater Canal Headworks Replacement bid lines the headworks only. No source
  read says any of these canals is lined along its length, so each canal point
  is set to unlined, the district's majority, and its notes say so.
- The two river takes with no canal of their own (the Bottomlands riparian take
  and the Snelling re-diversion) are left not stated: no source describes how
  their water reaches a field, so they keep no seepage share.
- The Merced Falls hydroelectric diversion passes its water through the power
  plant and back to the river, which is a pipe.

Each entry's note is appended to the point's own notes once. Idempotent, keyed
on the demonstration names, and touches no other point.
"""
from django.core.management.base import BaseCommand

from surface.models import PointOfDiversion

_MAJORITY = (
    "Demonstration data: lining set to unlined, Merced Irrigation District's "
    "majority (406 miles of unlined canal against 105 of lined canal, 2020 "
    "Agricultural Water Management Plan, Table 2). No published source read "
    "states this canal's own lining."
)

LINING_BY_POD = {
    "MER-POD-004-DEMO Atwater Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-005-DEMO Le Grand Canal Headgate": (
        "unlined",
        _MAJORITY + " The 2018 Merced Integrated Regional Water Management Plan "
        "lists lining portions of the Le Grand Canal.",
    ),
    "MER-POD-006-DEMO Stevinson Diversion Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-007-DEMO Plainsburg El Nido Canal Headgate": ("unlined", _MAJORITY),
    "MER-POD-008-DEMO Crocker-Huffman River Diversion": (
        "unlined",
        _MAJORITY + " This take feeds Merced Irrigation District's Main Canal; the "
        "2018 Merced Integrated Regional Water Management Plan lists lining "
        "portions of the Main Canal.",
    ),
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


def apply_demo_pod_lining():
    """Set each demonstration point's lining and note; return how many changed."""
    changed = 0
    for name, (lining, note) in LINING_BY_POD.items():
        pod = PointOfDiversion.objects.filter(name=name).first()
        if pod is None:
            continue
        notes = pod.notes or ""
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
