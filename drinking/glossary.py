# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Plain-English translations for the drinking-water domain's shorthand.

**Why this exists.** The onboarding screens were reviewed on 2026-07-20 and the
verdict was that they do not read to a human: "It's just a bunch of random
letters and acronyms." That was correct. The screens showed ``DST``, ``LCR``,
``WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3`` and expected the reader to already
know the vocabulary.

Two different kinds of shorthand appear, and they are handled differently:

**Facility type codes** (``WL``, ``TP``, ``DS``) are *ours* to present — they are
a controlled vocabulary in ``drinking/models.py``. The model already carries a
short label ("Well", "Distribution System"); what it lacks is a sentence saying
what the thing physically IS. That is ``FACILITY_TYPE_PLAIN``.

**Abbreviations inside facility names** (``RAW``, ``GAC``, ``IX``, ``STBY``) are
**EPA's data**, not ours. Rewriting them would be falsifying the federal record,
so the name is always shown verbatim and the shorthand is explained *alongside*
it in a legend. ``shorthand_in_use`` returns only the terms that actually appear
in the names on screen, because a full 20-row glossary on every page is just
another wall to scroll past.

Nothing here is a regulatory determination. These are descriptions of equipment
and of what a sample is for — never a statement about compliance.
"""

import re

#: What each facility type physically is, in one sentence a non-specialist can
#: read. Keyed by the same codes as ``FACILITY_TYPE_CHOICES`` in models.py.
FACILITY_TYPE_PLAIN = {
    "WL": "A drilled well. Water comes up out of the ground here.",
    "WH": "The top of a well, where it reaches the surface.",
    "TP": "A treatment plant — where water is filtered or treated before going out.",
    "DS": (
        "The distribution system: the pipes that carry treated water out to "
        "customers. Samples here are taken out in the neighbourhood, not at a well."
    ),
    "CH": "A junction where several sources join into one pipe.",
    "CW": "A tank holding treated water immediately after treatment.",
    "ST": "A storage tank holding treated water before it goes out.",
    "RS": "A reservoir — stored water held in the open.",
    "IN": "An intake, where water is drawn from a river, lake or canal.",
    "SP": "A natural spring, where water reaches the surface on its own.",
    "PF": "A pump station that moves water through the system.",
    "PC": "A valve station that controls water pressure.",
    "TM": "A large main carrying water between parts of the system.",
    "CC": "A connection where this system buys water from another water system.",
    "SS": "A tap built only for taking samples.",
    "CS": "A cistern — a tank storing collected water.",
    "IG": "A buried collector drawing water from alongside a river.",
    "RC": "Rainwater collected from a roof.",
    "SI": "A pond or basin holding surface water.",
    "NN": "Water hauled or delivered rather than piped in.",
    "NP": "Purchased water that arrives other than by pipe.",
    "OT": "A facility the state records only as 'other'.",
}

#: Abbreviations that appear inside EPA's own facility and sampling-point names.
#: Order matters only for readability; lookup is by key.
SHORTHAND = {
    "RAW": "Untreated water — sampled before any treatment.",
    "STBY": "Standby. A source held in reserve, not normally running.",
    "INAC": "Inactive — not currently in service.",
    "INACTIVE": "Not currently in service.",
    "DESTROYED": "The facility has been decommissioned or destroyed.",
    "BLENDED": "Water from more than one source, mixed together.",
    "EFFLUENT": "Water leaving a treatment step.",
    "GAC": "Granular activated carbon — a filter that removes organic chemicals.",
    "IX": "Ion exchange — a filter that removes dissolved minerals such as nitrate.",
    "NO3": "Nitrate.",
    "NITRATE": "Nitrate — a contaminant common in agricultural groundwater.",
    "CL2": "Chlorine.",
    "DBCP": "A banned agricultural pesticide still present in some groundwater.",
    "TCP": "1,2,3-trichloropropane, an industrial solvent.",
    "PFOA": "One of the PFAS 'forever chemicals'.",
    "PFHXS": "One of the PFAS 'forever chemicals'.",
    "LCR": (
        "Lead and Copper Rule — samples taken at customer taps to check for lead."
    ),
    "DBPR": (
        "Disinfection Byproducts Rule — chemicals formed when chlorine reacts "
        "with material in the pipes."
    ),
    "DST": (
        "The state's id for the distribution system — the pipes out to customers."
    ),
}

#: Split a name into candidate tokens. EPA separates with spaces, hyphens,
#: underscores, ampersands, commas and parentheses, often several at once
#: ("WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3").
_TOKENS = re.compile(r"[^A-Za-z0-9]+")


def facility_type_plain(code):
    """One sentence describing what this kind of facility physically is."""
    return FACILITY_TYPE_PLAIN.get((code or "").strip().upper(), "")


def shorthand_in_use(names):
    """The glossary entries actually needed for the names given.

    Returns a sorted list of ``(term, meaning)``. Only terms that genuinely
    appear are returned: a page that lists every abbreviation the domain has is
    a wall, and a wall is what this module exists to remove.
    """
    seen = set()
    for name in names:
        for token in _TOKENS.split((name or "").upper()):
            if token in SHORTHAND:
                seen.add(token)
    return sorted((term, SHORTHAND[term]) for term in seen)
