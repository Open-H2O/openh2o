# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water words this platform may name but may never define.

The mirror image of ``core/operator_vocabulary.py``, and the two must not be
confused for one another. That list says *you must define an infrastructure term
before you use it*, because the operator never signed up to learn what DNS is.
This one says *you must not define a water term at all*, because the operator has
spent thirty years on groundwater and irrigation and there is no more expert
audience alive on what a well is.

The boundary is `DESIGN.md` copy rule 11: **explain the software and the data
conventions; never explain the water.**

**Where this list came from, and what that means.** Every term below was found
being explained to a reader somewhere in this repository — in
``drinking/glossary.py``'s two dictionaries, or in the 36 definitions
``config/views.py::glossary`` serves to ``/help/glossary/``. It is a list of
terms **found being explained here**, not a hydrology dictionary and not a claim
about the domain. A water word absent from this list is absent because nothing
in this codebase was caught defining it, which is a statement about the
codebase.

**What a record claims, and what it does not.** A record claims that this word
belongs to the reader's domain rather than to ours, so a sentence that *defines*
it is talking down to the person reading it. It claims nothing about the word
appearing: "well" is on nearly every screen in the drinking module and belongs
there. Naming a well is the platform doing its job. Saying what a well *is* is
the defect. ``tests/test_domain_vocabulary.py`` is what draws that line, and it
draws it on definitional constructions — never on the bare presence of a term.

**The carve-out is load-bearing and is exported, not commented.** ``ALLOWED``
below holds the three things that stay explainable forever: agency and program
names, codes inside data this platform did not author, and this platform's own
coined concepts. Every multi-word entry whose own text contains a term from
``TERMS`` is masked out of the prose before scanning — otherwise "SGMA —
Sustainable Groundwater Management Act" reports itself as a groundwater lecture,
the gate becomes noise, and it is switched off within a week. A gate with false
positives on legitimate copy gets deleted rather than obeyed.

**Pure data.** No Django import, no model import, no settings access. The gate
runs without a database and cannot be broken by an unrelated app change.
"""

import re
from dataclasses import dataclass

#: Where a term was found being explained. Provenance is the point: it is what
#: makes this a measurement of this repository rather than an opinion about
#: hydrology.
#:
#: ``FACILITY_PLAIN`` names a dictionary that **no longer exists** — 118-02
#: deleted it whole on 2026-08-06 (ISS-129). The constant stays because these
#: are historical provenance, not live pointers: a term earned its place on this
#: list by having been caught somewhere, and erasing where would turn a
#: measurement back into an opinion. ``tests/test_domain_vocabulary.py`` no
#: longer scans it as a surface and guards its deletion instead.
FACILITY_PLAIN = "drinking/glossary.py::FACILITY_TYPE_PLAIN"
SHORTHAND = "drinking/glossary.py::SHORTHAND"
PLATFORM_GLOSSARY = "config/views.py::glossary"


@dataclass(frozen=True)
class DomainTerm:
    """One water word the platform may use freely and may never define."""

    #: Stable lowercase identifier, used in failure messages and baselines.
    slug: str
    #: The human name, used verbatim when the gate reports a violation.
    label: str
    #: Case-insensitive regexes matching the term in prose. Word-bounded
    #: without exception — see the pattern-discipline note below.
    patterns: tuple
    #: Which surface in this repository was caught explaining it.
    found_in: tuple


# Pattern discipline
# ------------------
# Word boundaries always, and precise patterns over loose ones — the same rule
# ``core/operator_vocabulary.py`` states, for the same reason. Two exclusions
# here are load-bearing and were each written after a real false positive was
# read out of a scan of this repository:
#
#   * ``per-well`` and ``well number`` / ``well meters``. The GEARS entry reads
#     "the State Water Board reporting format for per-well extraction" — that is
#     the filing subject, not a description of a well. A bare ``\bwells?\b``
#     reports it and the gate immediately looks wrong.
#   * ``surface-diversion``. The CalWATRS entry reads "the State Water Board's
#     surface-diversion reporting system", which names what CalWATRS collects.
#     Same failure mode.
#
# ``water`` on its own is deliberately absent. It appears in the platform's own
# concept names (Water Account), in agency names (State Water Board), and in
# almost every legitimate sentence on every screen. Only the compounds are
# matched: ``surface water``, ``groundwater``, ``water right``, ``water year``.

TERMS: tuple = (
    DomainTerm(
        slug="well",
        label="well",
        # `as well` is the English adverb, not the hole in the ground. Without
        # the exclusion, "counts them as well: each section carries a source"
        # reports as an appositive definition of a well.
        patterns=(r"(?<!per-)(?<!as )\bwells?\b(?!\s+(?:numbers?|meters?|IDs?))",),
        found_in=(FACILITY_PLAIN, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="wellhead",
        label="wellhead",
        patterns=(r"\bwell ?heads?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="borehole",
        label="borehole",
        patterns=(r"\bbore ?holes?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="aquifer",
        label="aquifer",
        patterns=(r"\baquifers?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="groundwater",
        label="groundwater",
        patterns=(r"\bground ?waters?\b",),
        found_in=(SHORTHAND, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="surface_water",
        label="surface water",
        patterns=(r"\bsurface waters?\b",),
        found_in=(FACILITY_PLAIN, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="reservoir",
        label="reservoir",
        patterns=(r"\breservoirs?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="canal",
        label="canal",
        patterns=(r"\bcanals?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="spring",
        label="spring (natural spring)",
        # `\bsprings?\b` unqualified would also match the season. Neither
        # reading appears often enough here for that to matter, and the
        # construction rule means it only reports inside a definition.
        patterns=(r"\bsprings?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="intake",
        label="intake",
        patterns=(r"\bintakes?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="headgate",
        label="headgate",
        patterns=(r"\bhead ?gates?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="diversion",
        label="diversion / diverting water",
        patterns=(r"(?<!surface-)\bdiversions?\b", r"\bdiverts?\b",
                  r"\bdiverted\b", r"\bdiverting\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="point_of_diversion",
        label="point of diversion",
        patterns=(r"\bpoints? of diversion\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="recharge",
        label="recharge / managed aquifer recharge",
        patterns=(r"\brecharges?\b", r"\brecharging\b", r"\brecharged\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="evapotranspiration",
        label="evapotranspiration / evaporation / transpiration",
        patterns=(r"\bevapotranspirations?\b", r"\bevaporation\b",
                  r"\btranspiration\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="consumptive_use",
        label="consumptive use",
        patterns=(r"\bconsumptive use\b", r"\bconsumed by crops\b",
                  r"\bcrop water use\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="watershed",
        label="watershed",
        patterns=(r"\bwatersheds?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="basin",
        label="basin / subbasin / spreading basin",
        patterns=(r"\bsub-?basins?\b", r"\bbasins?\b"),
        found_in=(FACILITY_PLAIN, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="runoff",
        label="runoff",
        patterns=(r"\brun-?offs?\b", r"\brunning off\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="percolation",
        label="percolation",
        patterns=(r"\bpercolat(?:e|es|ed|ing|ion)\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="treatment",
        label="treatment plant / treated water",
        patterns=(r"\btreatment plants?\b", r"\btreated water\b",
                  r"\btreatment steps?\b", r"\bfiltered or treated\b"),
        found_in=(FACILITY_PLAIN, SHORTHAND),
    ),
    DomainTerm(
        slug="distribution_system",
        label="distribution system",
        patterns=(r"\bdistribution systems?\b",),
        found_in=(FACILITY_PLAIN, SHORTHAND),
    ),
    DomainTerm(
        slug="pipes",
        label="pipes / piped water",
        patterns=(r"\bpipes\b", r"\bpiped\b", r"\bone pipe\b"),
        found_in=(FACILITY_PLAIN, SHORTHAND),
    ),
    DomainTerm(
        slug="storage_tank",
        label="storage tank",
        patterns=(r"\bstorage tanks?\b", r"\btanks?\b"),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="cistern",
        label="cistern",
        patterns=(r"\bcisterns?\b",),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="pump_station",
        label="pump station",
        patterns=(r"\bpump stations?\b", r"\bpumping plants?\b"),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="valve_station",
        label="valve station / water pressure",
        patterns=(r"\bvalve stations?\b", r"\bwater pressure\b"),
        found_in=(FACILITY_PLAIN,),
    ),
    DomainTerm(
        slug="chlorine",
        label="chlorine",
        patterns=(r"\bchlorine\b", r"\bchlorinat(?:e|ed|ion)\b"),
        found_in=(SHORTHAND,),
    ),
    DomainTerm(
        slug="nitrate",
        label="nitrate",
        patterns=(r"\bnitrates?\b",),
        found_in=(SHORTHAND,),
    ),
    DomainTerm(
        slug="contaminant",
        label="contaminant / pesticide / solvent",
        patterns=(r"\bcontaminants?\b", r"\bpesticides?\b", r"\bsolvents?\b",
                  r"\bforever chemicals?\b"),
        found_in=(SHORTHAND,),
    ),
    DomainTerm(
        slug="filter",
        label="filter / filtration",
        patterns=(r"\bfilters?\b", r"\bfiltration\b", r"\bfiltering\b"),
        found_in=(SHORTHAND,),
    ),
    DomainTerm(
        slug="customer_tap",
        label="tap (customer tap / sampling tap)",
        patterns=(r"\bcustomer taps?\b", r"\bhousehold taps?\b",
                  r"\btaps?\b(?!\s+(?:into|in\b))"),
        found_in=(FACILITY_PLAIN, SHORTHAND),
    ),
    DomainTerm(
        slug="stream",
        label="stream / river / lake",
        patterns=(r"\bstreams?\b", r"\brivers?\b", r"\blakes?\b",
                  r"\bponds?\b"),
        found_in=(FACILITY_PLAIN, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="rainwater",
        label="rainwater / rainfall",
        patterns=(r"\brain-? ?waters?\b", r"\brainfall\b"),
        found_in=(FACILITY_PLAIN, PLATFORM_GLOSSARY),
    ),
    DomainTerm(
        slug="water_right",
        label="water right",
        patterns=(r"\bwater rights?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="water_year",
        label="water year",
        patterns=(r"\bwater years?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="curtailment",
        label="curtailment",
        patterns=(r"\bcurtailments?\b", r"\bcurtail(?:s|ed|ing)?\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="drought",
        label="drought",
        patterns=(r"\bdroughts?\b",),
        found_in=(PLATFORM_GLOSSARY,),
    ),
    DomainTerm(
        slug="cfs",
        label="cubic feet per second (a rate of flow)",
        patterns=(r"\brate of flow\b", r"\bacre-feet per day\b"),
        found_in=(PLATFORM_GLOSSARY,),
    ),
)


@dataclass(frozen=True)
class AllowedPhrase:
    """One thing the platform may define, forever, and why.

    ``kind`` is the carve-out it belongs to, and the three kinds are the three
    categories `DESIGN.md` rule 11 names:

    ``agency``
        An agency or program name. A filing convention, not hydrology.
    ``code``
        A code or abbreviation inside data the platform did not author — EPA
        facility and sampling-point shorthand, DDW analyte codes. The record is
        shown verbatim, so the reader needs the key to it. Expand the code;
        never describe the thing.
    ``platform``
        This platform's own coined concept. The operator cannot know these:
        they were invented here, and the platform owes a definition.
    """

    text: str
    kind: str


#: The carve-out, exported so a future reader cannot mistake it for incidental
#: omission. Multi-word entries whose own text contains a term from ``TERMS``
#: are masked out of prose before scanning — see ``MASKS`` below. Single-token
#: codes need no mask: a bare expansion ("NO3": "Nitrate.") carries no
#: definitional construction, so the scanner never looks at it.
ALLOWED: tuple = (
    # -- Agency and program names, and their expansions --------------------
    AllowedPhrase("GEARS", "agency"),
    AllowedPhrase("Groundwater Extraction Annual Reporting System", "agency"),
    AllowedPhrase("CalWATRS", "agency"),
    AllowedPhrase("California Water Accounting, Tracking, and Reporting System",
                  "agency"),
    AllowedPhrase("SGMA", "agency"),
    AllowedPhrase("Sustainable Groundwater Management Act", "agency"),
    AllowedPhrase("Sustainable Groundwater Management", "agency"),
    AllowedPhrase("GSA", "agency"),
    AllowedPhrase("Groundwater Sustainability Agency", "agency"),
    AllowedPhrase("GSP", "agency"),
    AllowedPhrase("Groundwater Sustainability Plan", "agency"),
    AllowedPhrase("CDEC", "agency"),
    AllowedPhrase("California Data Exchange Center", "agency"),
    AllowedPhrase("CIMIS", "agency"),
    AllowedPhrase("California Irrigation Management Information System", "agency"),
    AllowedPhrase("USGS", "agency"),
    AllowedPhrase("United States Geological Survey", "agency"),
    AllowedPhrase("OpenET", "agency"),
    AllowedPhrase("EPA", "agency"),
    AllowedPhrase("DDW", "agency"),
    AllowedPhrase("Division of Drinking Water", "agency"),
    AllowedPhrase("SDWIS", "agency"),
    AllowedPhrase("Safe Drinking Water Information System", "agency"),
    AllowedPhrase("GAMA", "agency"),
    AllowedPhrase("Groundwater Ambient Monitoring and Assessment Program", "agency"),
    AllowedPhrase("State Water Board", "agency"),
    AllowedPhrase("Department of Water Resources", "agency"),
    AllowedPhrase("DWR", "agency"),
    AllowedPhrase("Lead and Copper Rule", "agency"),
    AllowedPhrase("Disinfection Byproducts Rule", "agency"),
    # -- Codes inside data this platform did not author ---------------------
    AllowedPhrase("STBY", "code"),
    AllowedPhrase("DST", "code"),
    AllowedPhrase("RAW", "code"),
    AllowedPhrase("GAC", "code"),
    AllowedPhrase("granular activated carbon", "code"),
    AllowedPhrase("IX", "code"),
    AllowedPhrase("ion exchange", "code"),
    AllowedPhrase("NO3", "code"),
    AllowedPhrase("CL2", "code"),
    AllowedPhrase("LCR", "code"),
    AllowedPhrase("DBPR", "code"),
    AllowedPhrase("DBCP", "code"),
    AllowedPhrase("TCP", "code"),
    AllowedPhrase("PFOA", "code"),
    AllowedPhrase("PFHXS", "code"),
    AllowedPhrase("INAC", "code"),
    AllowedPhrase("PS Code", "code"),
    AllowedPhrase("PWSID", "code"),
    AllowedPhrase("ELAP", "code"),
    AllowedPhrase("MCL", "code"),
    # -- This platform's own coined concepts --------------------------------
    AllowedPhrase("Allocation Ceiling", "platform"),
    AllowedPhrase("Allocation", "platform"),
    AllowedPhrase("Apportionment", "platform"),
    AllowedPhrase("Usage", "platform"),
    AllowedPhrase("Closing Balance", "platform"),
    AllowedPhrase("Delivery Settings", "platform"),
    AllowedPhrase("Data Source", "platform"),
    AllowedPhrase("ET-Demand Allocation", "platform"),
    AllowedPhrase("Health Check", "platform"),
    AllowedPhrase("Ledger Entry", "platform"),
    AllowedPhrase("Methodology / Calculation Plan", "platform"),
    AllowedPhrase("Calculation Plan", "platform"),
    AllowedPhrase("Monitoring Station", "platform"),
    AllowedPhrase("Recovery Horizon", "platform"),
    AllowedPhrase("Use Area", "platform"),
    AllowedPhrase("Water Account", "platform"),
    AllowedPhrase("Management Zone", "platform"),
    AllowedPhrase("Effective Precipitation", "platform"),
)


#: Compiled once. Case-insensitive throughout — a screen writes "Well", "well"
#: and "WELL" and all three are the same word to a reader.
COMPILED: dict = {
    term.slug: tuple(re.compile(pattern, re.IGNORECASE) for pattern in term.patterns)
    for term in TERMS
}

TERMS_BY_SLUG: dict = {term.slug: term for term in TERMS}


def _contains_a_term(text: str) -> bool:
    return any(
        pattern.search(text) for patterns in COMPILED.values() for pattern in patterns
    )


#: The allowed phrases that must be blanked out of prose before scanning:
#: exactly those whose own text contains a term from ``TERMS``. Deriving this
#: rather than hand-listing it is deliberate — adding a water term to ``TERMS``
#: later automatically protects "Sustainable Groundwater Management Act" and its
#: siblings, instead of leaving a false positive for someone to discover.
#:
#: Longest first, so "Groundwater Sustainability Agency" is consumed before a
#: shorter overlapping phrase can take a bite out of it.
MASKS: tuple = tuple(
    re.compile(re.escape(phrase.text), re.IGNORECASE)
    for phrase in sorted(ALLOWED, key=lambda p: -len(p.text))
    if _contains_a_term(phrase.text)
)


def mask_allowed(text: str) -> str:
    """Blank every legitimate proper name out of a string, preserving length.

    Replacement is space-for-character so that offsets and line numbers survive:
    a reported position is a position in the real file.
    """
    for pattern in MASKS:
        text = pattern.sub(lambda match: " " * len(match.group(0)), text)
    return text
