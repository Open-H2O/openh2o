# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which water domain each state filing describes, in one place.

A GEARS filing reports groundwater extraction, so it only means anything in a
deployment that runs ``wells``. A CalWATRS filing reports surface diversions, so
it only means anything in a deployment that runs ``surface``. Before v2.4 the
platform said neither out loud, and a deployment with no surface water was still
seeded two CalWATRS templates and still offered a Generate button for them
(measured under Configuration B in 87-02 -- ISS-082).

**This mapping lives here and nowhere else.** The seed command and the generate
form both read it. A second copy could drift, and a drifted copy is worse than
no gate at all: it fails on one surface and passes on the other, which reads as
"we handled that" right up until it does not.

Two ways of naming a filing are in play, and they are different:

* the **report type** (``gears_by_well``) -- what a ``ReportTemplate`` row
  stores, and what the generator branches on;
* the **family** (``gears``) -- what the report list's Generate links pass as
  ``?type=`` and what ``ReportGenerateForm`` matches with ``startswith``.

``REPORT_FAMILY_OWNER`` is derived from ``REPORT_TYPE_OWNER`` rather than
written out a second time, for exactly the drift reason above.

An unknown report type has no owner and is deliberately NOT gated. A deployment
that adds its own ``ReportTemplate`` row is not making a claim about wells or
surface water, and silently hiding it would be a worse answer than leaving it
alone.
"""
from core.modules import is_enabled

#: Report type -> the module whose water that filing describes.
REPORT_TYPE_OWNER: dict = {
    "gears_by_well": "wells",
    "gears_by_et": "wells",
    "calwatrs_a1": "surface",
    "calwatrs_a2": "surface",
}

#: Filing family -> owning module, derived so it cannot drift from the above.
#: Both GEARS types share the ``gears`` family and both CalWATRS types share
#: ``calwatrs``; a family whose types disagreed on their owner would be a
#: contradiction, so building the dict this way would silently pick one. Nothing
#: today can produce that, and ``tests/test_report_type_ownership.py`` pins it.
REPORT_FAMILY_OWNER: dict = {
    report_type.split("_", 1)[0]: owner
    for report_type, owner in REPORT_TYPE_OWNER.items()
}


def owner_of(report_type: str):
    """The module that owns a report type, or None if nothing claims it."""
    return REPORT_TYPE_OWNER.get(report_type)


def report_type_is_available(report_type: str, names=None) -> bool:
    """Whether this deployment can honestly produce this filing.

    True for an unclaimed report type -- see the module docstring.
    """
    owner = owner_of(report_type)
    return owner is None or is_enabled(owner, names)


def report_family_is_available(family: str, names=None) -> bool:
    """The same question asked of a ``?type=`` family (``gears``/``calwatrs``)."""
    owner = REPORT_FAMILY_OWNER.get(family)
    return owner is None or is_enabled(owner, names)


def unavailable_report_types(names=None) -> tuple:
    """Report types whose owning module this deployment does not run.

    Phrased as the *excluded* set rather than the allowed set on purpose: the
    generate form filters with ``.exclude(report_type__in=...)``, so a report
    type nobody has mapped passes through untouched instead of being dropped for
    failing to appear on an allowlist.
    """
    return tuple(
        report_type
        for report_type in REPORT_TYPE_OWNER
        if not report_type_is_available(report_type, names)
    )
