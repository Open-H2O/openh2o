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


def uses_california_ps_codes(pwsid):
    """True when this PWSID belongs to a California system.

    ``WaterSystem`` stores no primacy agency, so the PWSID decides: California's
    are ``CA`` plus seven digits (``CA2410011``), and any other prefix is
    another state's. The underscore composition ``compose_ps_code`` builds is
    California DDW's format, so only a California system gets it; another
    state's sampling point code is taken exactly as that state's lab file
    writes it. Case-insensitive, outer whitespace ignored.
    """
    return (pwsid or "").strip().upper().startswith("CA")


def compose_ps_code(pwsid, facility_id, point_number):
    """Build California's (DDW's) ``{pwsid}_{facility_id}_{point_number}`` code.

    Used for a system whose PWSID marks it as California's
    (``uses_california_ps_codes``); another state's code is not composed.

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
        ("facility ID", facility_id),
        ("point number", point_number),
    ):
        value = (raw or "").strip().upper()
        if not value:
            raise ValueError(f"Enter the {label}.")
        if "_" in value:
            raise ValueError(
                f"The {label} '{value}' contains an underscore. A PS Code uses "
                "underscores only between its three parts."
            )
        if not _SEGMENT.match(value):
            bad = next(ch for ch in value if not re.match(r"[A-Z0-9-]", ch))
            what = "a space" if bad == " " else f"the character '{bad}'"
            raise ValueError(
                f"The {label} '{value}' contains {what}. A PS Code uses only "
                "letters, digits and hyphens, such as 010, DST or LCR."
            )
        segments.append(value)

    composed = "_".join(segments)
    if len(composed) > MAX_PS_CODE_LENGTH:
        raise ValueError(
            f"The PS Code {composed} has {len(composed)} characters, and "
            f"OpenH2O stores PS Codes of up to {MAX_PS_CODE_LENGTH}. Shorten "
            "the point number."
        )
    return composed
