# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Composing a DDW PS Code.

A PS Code is the composite ``{pwsid}_{facility_id}_{point_number}`` — the join
key every lab-import row is matched on. ``drinking.importer`` refuses by design
to invent one: a row naming a PS Code the deployment does not carry is a row
error, not an implicit create. So this module is the only place a PS Code comes
into existence, and it is called on the operator's explicit action.

**No model imports, no database.** Kept a pure function so it is testable
without a DB and callable from a view, a management command, or a future
importer path without dragging the ORM along.

Two facts about the real published data shape every rule below. Both were read
off California's own export for CA1010001, not inferred:

**Neither segment is numeric.** Facility segments include ``DST`` (the
distribution system, which EPA sends as an ordinary facility). Point numbers
include ``900``, ``901``, ``902``, ``903`` and ``LCR``. Anything here that
assumed digits — a regex, an ``int()``, a ``type="number"`` input — would drop
every distribution-system row, which is most of a system's regulatory
monitoring.

**The separator is load-bearing.** An underscore inside a segment yields a code
that cannot be split back into three parts, so it is rejected rather than
normalised: quietly mangling it would mint a PS Code that can never match the
state's own file.
"""

import re

#: ``SamplingPoint.ps_code`` is ``max_length=60``. Composing past it raises
#: rather than truncating — a truncated code is a code that silently never
#: matches an import row, which is worse than a refusal at the point of entry.
MAX_PS_CODE_LENGTH = 60

#: Deliberately narrow. Everything observed in the real export is alphanumeric;
#: hyphens are allowed as the one plausible extension. A permissive pattern here
#: would admit values the importer's exact match will later reject anyway, which
#: just moves the failure somewhere harder to explain.
_SEGMENT = re.compile(r"^[A-Z0-9-]+$")


def compose_ps_code(pwsid, facility_id, point_number):
    """Build the ``{pwsid}_{facility_id}_{point_number}`` composite.

    Segments are stripped and upper-cased — DDW publishes fixed-width padded
    fields, and operator input arrives however it arrives, but the stored code
    has to match the state's exactly.

    ``facility_id`` is the **state** facility key (``SystemFacility.facility_id``,
    e.g. ``010`` or ``DST``), never EPA's (``epa_facility_id``, e.g. ``14042``).
    Composing from EPA's id produces ``CA1010001_14042_001`` and misses every
    row of a real file.

    Raises ``ValueError`` for an empty segment, a segment carrying the separator
    or any other unexpected character, or a composite over the column width.
    """
    segments = []
    for label, raw in (
        ("PWSID", pwsid),
        ("facility id", facility_id),
        ("point number", point_number),
    ):
        value = (raw or "").strip().upper()
        if not value:
            raise ValueError(f"The {label} is required to build a PS Code.")
        if "_" in value:
            raise ValueError(
                f"The {label} '{value}' contains an underscore. Underscore "
                "separates the three parts of a PS Code, so one inside a part "
                "would produce a code that cannot be read back."
            )
        if not _SEGMENT.match(value):
            raise ValueError(
                f"The {label} '{value}' has characters a PS Code cannot carry. "
                "Use letters, digits and hyphens — for example 010, DST or LCR."
            )
        segments.append(value)

    composed = "_".join(segments)
    if len(composed) > MAX_PS_CODE_LENGTH:
        raise ValueError(
            f"'{composed}' is {len(composed)} characters, over the "
            f"{MAX_PS_CODE_LENGTH}-character limit for a PS Code."
        )
    return composed
