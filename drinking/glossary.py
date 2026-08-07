# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The key to EPA's shorthand, so a federal record shown verbatim can be read.

**Why this exists.** The onboarding screens were reviewed on 2026-07-20 and the
verdict was that they do not read to a human: "It's just a bunch of random
letters and acronyms." That was correct. The screens showed ``DST``, ``LCR``,
``WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3`` and expected the reader to already
know the vocabulary.

**Abbreviations inside facility names** (``RAW``, ``GAC``, ``IX``, ``STBY``) are
**EPA's data**, not ours. Rewriting them would be falsifying the federal record,
so the name is always shown verbatim and the shorthand is expanded *alongside*
it in a legend. ``shorthand_in_use`` returns only the terms that actually appear
in the names on screen, because a full 20-row glossary on every page is just
another wall to scroll past.

**Expand the code and stop — every entry here is a decoding, never a
description (BLOCKING).** The reader is a water district operator, and telling
that reader what granular activated carbon *does* explains treatment to the
person who runs the treatment. ``GAC`` → "Granular activated carbon." is the
whole job. Brent ruled on 2026-08-06 that this holds with **no exception for a
clause about the filing**, so ``LCR`` is "Lead and Copper Rule." and nothing
more. The rule is `DESIGN.md` copy rule 11; the guard is
``tests/test_domain_vocabulary.py``.

**What used to be here, and must not come back.** A second dictionary,
``FACILITY_TYPE_PLAIN``, gave all 22 EPA facility codes a sentence saying what
the thing physically is — "A drilled well. Water comes up out of the ground
here." It was deleted whole on 2026-08-06 (ISS-129), not trimmed:
``FACILITY_TYPE_CHOICES`` in ``drinking/models.py`` already carries EPA's own
label for every code, and the facility panel already renders it as the heading,
so the dictionary's only added content was the water lecture. Three tests in
``tests/test_drinking_readability.py`` had *mandated* those descriptions, which
is why every correction made by hand was reverted by the suite on the next run;
they went in the same change.

Nothing here is a regulatory determination — never a statement about compliance.
"""

import re

#: Abbreviations that appear inside EPA's own facility and sampling-point names.
#: Order matters only for readability; lookup is by key.
#:
#: **Every value is a decoding and nothing more (ISS-129, 2026-08-06).** Each of
#: these used to carry a clause after the expansion — what the filter removes,
#: what the contaminant is, where the samples are taken — and every one of those
#: clauses explained treatment, chemistry or sampling practice to the person who
#: does it for a living. A status code's meaning stays, because what the state's
#: own flag signifies is a data convention this platform owes the reader; a
#: description of the water, the equipment or the sampling never does.
SHORTHAND = {
    "RAW": "Untreated water.",
    "STBY": "Standby. A source held in reserve, not normally running.",
    "INAC": "Inactive — not currently in service.",
    "INACTIVE": "Not currently in service.",
    "DESTROYED": "The facility has been decommissioned or destroyed.",
    "BLENDED": "Water from more than one source, mixed together.",
    "EFFLUENT": "Effluent.",
    "GAC": "Granular activated carbon.",
    "IX": "Ion exchange.",
    "NO3": "Nitrate.",
    "NITRATE": "Nitrate.",
    "CL2": "Chlorine.",
    "DBCP": "1,2-dibromo-3-chloropropane.",
    "TCP": "1,2,3-trichloropropane.",
    "PFOA": "Perfluorooctanoic acid.",
    "PFHXS": "Perfluorohexanesulfonic acid.",
    "LCR": "Lead and Copper Rule.",
    "DBPR": "Disinfection Byproducts Rule.",
    "DST": "Distribution system.",
}

#: Split a name into candidate tokens. EPA separates with spaces, hyphens,
#: underscores, ampersands, commas and parentheses, often several at once
#: ("WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3").
_TOKENS = re.compile(r"[^A-Za-z0-9]+")


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
