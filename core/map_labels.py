# SPDX-License-Identifier: AGPL-3.0-or-later
"""One helper for the map label prefix, shared by every overview map (143-07).

Brent's Task 3 ruling (2026-09-13 14:10 PDT) approved the overview map card
built on Surface Diversions with one change: the map LABEL drops the code
prefix a stored name carries. The demonstration seeds names like
``MER-POD-004-DEMO Atwater Canal Headgate`` and
``MER-BPOD-001 El Nido Canal Recharge Intake`` — the leading token is the
platform's own composed identifier, not a water name, and copy rule 11 (never
explain the water) reads the other way here too: this is software's own
labelling convention leaking onto the map, not something a reader needs.

Two shapes strip, and only two:

  * A LEADING identifier token: one whitespace-delimited word that is all caps,
    digits and hyphens, and carries at least one digit and one hyphen (so a
    real name's first word, however it is capitalised, never matches).
  * A TRAILING parenthetical: ``Halvern Irrigation District (MER-WR-004-DEMO)``
    becomes ``Halvern Irrigation District``.

Both can be present, only one, or neither. A real deployment's names carry
neither pattern, and this function returns them unchanged — never an empty
string, so a name that IS only a code (with nothing left after stripping) is
returned as it came in rather than erased.

Every overview geojson endpoint this plan touches writes the result into
``properties.label``, and ``OH2O.entities.<entity>.labelField`` in
``map-core.js`` reads ``['coalesce', ['get','label'], <existing expression>]``
so an older cached tile or an endpoint this plan does not touch still labels
the way it always has.
"""

import re

#: A leading token is the label's whole first whitespace-delimited word: all
#: caps, digits and hyphens, at least one digit and one hyphen so a real name's
#: first word (however it capitalises) can never match by accident.
_LEADING_CODE = re.compile(r"^(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*-)[A-Z0-9-]+\s+")

#: A trailing parenthetical: "... (MER-WR-004-DEMO)" at the very end of the
#: string, with the space before it consumed too.
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def map_label(name: str) -> str:
    """Strip a leading identifier token and a trailing parenthetical from a
    stored name, for the label a map draws next to its mark.

    Returns ``name`` unchanged when neither pattern applies, and never returns
    an empty string: a name that strips to nothing falls back to the original
    rather than leaving a mark with no label at all.
    """
    if not name:
        return name

    stripped = _TRAILING_PAREN.sub("", _LEADING_CODE.sub("", name))
    stripped = stripped.strip()
    return stripped if stripped else name
