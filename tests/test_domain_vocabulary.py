# SPDX-License-Identifier: AGPL-3.0-or-later
"""The boundary gate: no screen may explain the water to a water professional.

``core/domain_vocabulary.py`` is the list — water and hydrology words found
being explained somewhere in this repository. This file is what makes the list
bite, and it is the mirror image of ``tests/test_operator_vocabulary.py``: that
gate says *define the infrastructure term before you use it*; this one says
*never define the water term at all*. `DESIGN.md` copy rule 11 is the full
statement of the boundary.

**Why a gate and not a copy pass.** ISS-129's real defect was never the strings.
It was that three tests in ``tests/test_drinking_readability.py`` *mandated* a
physical description for all 22 EPA facility codes, so every correction made by
hand was reverted by the suite on the next run. A rewrite with no rule and no
guard behind it is the same defect scheduled to recur. The rule is written down
in ``DESIGN.md`` and ``CLAUDE.md``; this is the half that cannot be argued with.

**What this gate proves, and what it does not.** That a term from the list sits
inside a *definitional construction* — the "A/An <thing>" noun-phrase opening,
an appositive after a dash or colon, or a copular "X is a …". It cannot read a
sentence and judge whether a district engineer would find it patronising, and it
cannot see a water explanation written in a shape none of those three cover. It
under-reaches on purpose, in the same way and for the same reason
``core/operator_vocabulary.py`` leaves a loose pattern out: a gate that cries
wolf is a gate nobody reads.

**The offence is the definition, never the term.** "Well" appears on nearly
every screen in the drinking module and belongs there. A gate on term *presence*
would be unfixable noise, would be switched off within a week, and would earn
exactly the fate of the tests it replaces.

**What 118-02 did to the numbers, and what it deliberately left alone.** The
gate opened at six surfaces carrying 49 flagged locations. One surface —
``drinking/glossary.py::FACILITY_TYPE_PLAIN``, 22 entries — was deleted whole
rather than swept, so it is now a *deletion guard* below rather than a baseline.
``SHORTHAND`` walked 7 → **strict 0**: every value in it is now a decoding and
nothing more. The other four surfaces walked 28 → 18, and **stopped there on
purpose**. All 18 survivors are enumerated in ``118-01-EVIDENCE.md`` Part two as
false positives or recorded judgment calls — a page heading, an agency-name
expansion, a worked example, a sentence about a number the platform computed.
Rewording those to reach a cosmetic zero would be the gate bending the product
rather than measuring it. The per-surface table sits with ``BASELINE``.

**One measured gap this sweep found and could not close.** ``_scannable_prose``
strips ``{% %}`` before scanning, so the ``text="…"`` argument of every
``{% include "partials/_explainer_popout.html" %}`` is **invisible to this gate**
— and 118-02 found water definitions living in exactly there, on the accounting
dashboard and the water-balances explainer, none of which any baseline ever
counted. They were corrected by hand and ``templates/partials/_explainer_popout.html``
now carries the rule in its own usage comment, which is the only guard that
surface has. Stripping template syntax is still right — it removed 20 of 32
flags on the template surface — but it is a real blind spot, not a rounding
error.

**Why the fixture controls exist.** A scorer that never fails is not a
measurement. One plants a water definition and demands it be reported. The other
proves the scanner stays silent on all three legitimate constructions — an
agency-name expansion, an EPA code expansion, and a platform-concept definition.
The second is the one that matters most: a gate with false positives on
legitimate copy gets deleted rather than obeyed. Both run against strings, never
against the real files, so they keep proving the scanner works after 118-02
takes the surfaces themselves clean.

Every test calls ``scan()``. A control that exercises a different code path from
the gate proves nothing.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from core.domain_vocabulary import COMPILED, TERMS_BY_SLUG, mask_allowed
from tests.test_drinking_readability import template_prose

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"


# -- The definitional constructions ------------------------------------------
#
# Three shapes, and between them they cover how this codebase actually writes a
# definition. Each was read off real strings in the repository, not invented:
#
#   opening      "A drilled well. …"            FACILITY_TYPE_PLAIN, all 22
#                "A borehole used to draw …"    config/views.py::glossary
#   appositive   "Nitrate — a contaminant …"    drinking/glossary.py::SHORTHAND
#                "… — the pipes out to …"       drinking/glossary.py::SHORTHAND
#   copular      "A well is a hole …"           free prose
#
# The copular shape deliberately requires an article after the verb. Without it
# the pattern reports "the well is at 300 feet", which is a fact about a row of
# data and not the platform explaining anything.

_WORD = r"[\w'’-]+[\s-]+"

#: Where a sentence can begin. ``>`` and ``"`` are in the list because template
#: prose starts immediately after a tag or an attribute quote —
#: ``<p class="page-description">A drilled well.</p>`` is one sentence beginning
#: at a ``>``, and without it the gate reads the whole template as mid-sentence
#: and reports nothing.
_SENTENCE_START = r"""(?:\A|(?<=[.!?])\s|(?<=\n)|(?<=>)|(?<=")|(?<=“))"""


def _constructions(pattern: str) -> tuple:
    """The three definitional shapes, built around one term's regex."""
    return (
        ("opening", re.compile(
            rf"{_SENTENCE_START}\s*(?:An?|The)\s+(?:{_WORD}){{0,5}}(?:{pattern})",
            re.IGNORECASE)),
        ("appositive", re.compile(
            rf"(?:—|--|:)\s*(?:an?|the)?\s*(?:{_WORD}){{0,5}}(?:{pattern})",
            re.IGNORECASE)),
        ("copular", re.compile(
            rf"(?:{pattern})\s*(?:—|--|:)"
            rf"|(?:{pattern})\s+(?:is|are|means)\s+(?:an?|the)\b",
            re.IGNORECASE)),
    )


CONSTRUCTIONS: dict = {
    slug: tuple(
        (shape, compiled)
        for pattern in TERMS_BY_SLUG[slug].patterns
        for shape, compiled in _constructions(pattern)
    )
    for slug in COMPILED
}


@dataclass(frozen=True)
class Offence:
    """One water term caught being defined."""

    slug: str
    label: str
    shape: str
    quote: str

    def __str__(self) -> str:
        return f"{self.label} ({self.shape}): …{self.quote}…"


def scan(text: str) -> list:
    """Every water term this string defines.

    Legitimate proper names are blanked first — otherwise "SGMA — Sustainable
    Groundwater Management Act" reports itself as a groundwater lecture. See
    ``core.domain_vocabulary.mask_allowed``.
    """
    masked = mask_allowed(text or "")
    offences = []

    for slug, shapes in CONSTRUCTIONS.items():
        for shape, pattern in shapes:
            match = pattern.search(masked)
            if match:
                start = max(0, match.start() - 10)
                offences.append(Offence(
                    slug=slug,
                    label=TERMS_BY_SLUG[slug].label,
                    shape=shape,
                    quote=" ".join(masked[start:match.end() + 30].split()),
                ))
                break

    return sorted(offences, key=lambda offence: offence.slug)


# -- The surfaces ------------------------------------------------------------
#
# Reader-facing prose only, per ISS-089's recorded scope decision. Code comments
# and docstrings are not copy and are not scanned.


def _drinking_glossary_entries(name: str) -> list:
    """``(key, string)`` for a dictionary in ``drinking/glossary.py``.

    Read through the module rather than by parsing, because the dictionary is
    what actually renders: ``SHORTHAND`` into the onboarding builder's
    abbreviation legend. The shape of this helper follows
    ``_glossary_strings()`` in ``tests/test_drinking_readability.py``, which
    pins the same dictionary.

    It took a ``name`` argument because there used to be two. See
    ``test_the_facility_description_dictionary_stays_deleted`` below.
    """
    from drinking import glossary

    return sorted(getattr(glossary, name).items())


def _platform_glossary_entries() -> list:
    """``(term, definition)`` for the 36 entries ``/help/glossary/`` serves.

    Parsed out of ``config/views.py`` with ``ast`` rather than by calling the
    view, so the gate needs no request, no database and no login — and so a
    definition is read exactly as it is written in the source.
    """
    tree = ast.parse((REPO_ROOT / "config" / "views.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "glossary":
            for statement in ast.walk(node):
                if (isinstance(statement, ast.Assign)
                        and isinstance(statement.value, ast.Dict)
                        and any(getattr(target, "id", None) == "terms"
                                for target in statement.targets)):
                    return [
                        (ast.literal_eval(key), ast.literal_eval(value))
                        for key, value in zip(statement.value.keys,
                                              statement.value.values)
                    ]
    raise AssertionError(
        "config/views.py::glossary no longer assigns a `terms` dict literal — "
        "the gate cannot see the platform glossary and is silently scanning "
        "nothing. Fix the reader, do not delete the surface."
    )


#: Django template syntax, stripped before scanning. ``template_prose()`` in
#: ``tests/test_drinking_readability.py`` removes comments, scripts, styles and
#: ``<th>``; it deliberately leaves the tags in, because it also checks casing
#: inside them. This gate cannot survive that: ``{% url 'wells:detail' %}`` puts
#: ``wells`` immediately before a colon, which is the appositive construction
#: exactly, and a URL namespace is not the platform explaining what a well is.
#: Measured before this strip existed, template syntax produced 20 of the 32
#: flags on the template surface — noise that would have got the gate deleted.
_TEMPLATE_SYNTAX = (
    re.compile(r"\{%.*?%\}", re.S),
    re.compile(r"\{\{.*?\}\}", re.S),
    #: Inline handlers (``onclick="…{% url … %}…"``) survive the tag strip as
    #: bare JavaScript. They are code, not copy.
    re.compile(r"\son[a-z]+\s*=\s*\"[^\"]*\"", re.S),
    #: Inline ``style="…"``. A design token name is not a sentence:
    #: ``var(--reservoir-400)`` reads as an appositive definition of a
    #: reservoir, and the colour ramp is named after the palette, not the water.
    re.compile(r"\sstyle\s*=\s*\"[^\"]*\"", re.S),
)


def _scannable_prose(path: Path) -> str:
    """A template reduced to the words a reader actually sees."""
    text = template_prose(path)
    for pattern in _TEMPLATE_SYNTAX:
        text = pattern.sub(" ", text)
    return text


#: Every prose-bearing template. ``page-description`` and ``text-secondary`` are
#: the two classes this codebase uses for reader-facing body copy, and the same
#: pair DISCOVERY.md counted 132 templates by.
_PROSE_MARKERS = ("page-description", "text-secondary")

HELP_PAGES: tuple = tuple(sorted((TEMPLATES / "help").glob("*.html")))


def _prose_templates() -> list:
    """Prose-bearing templates outside ``templates/help/``.

    The Help explainer pages are their own surface below, so they are excluded
    here rather than counted twice.
    """
    help_pages = set(HELP_PAGES)
    return sorted(
        path for path in TEMPLATES.rglob("*.html")
        if path not in help_pages
        and any(marker in path.read_text() for marker in _PROSE_MARKERS)
    )


#: ``help_text="…"`` and ``help_text='…'`` on models and forms. Migrations are
#: excluded: they are a frozen historical record, not copy anyone can edit.
_HELP_TEXT = re.compile(r"""help_text\s*=\s*(?:_\()?\s*(["'])(.*?)\1""", re.S)


def _help_text_strings() -> list:
    """``(path, line, string)`` for every ``help_text=`` outside migrations."""
    found = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if "migrations" in relative.parts or relative.parts[0] in {".venv", "tests"}:
            continue
        source = path.read_text()
        for match in _HELP_TEXT.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            found.append((str(relative), line, match.group(2)))
    return found


def _scan_surface(name: str) -> list:
    """``(location, string, offences)`` for every flagged string on a surface."""
    flagged = []

    if name == "drinking/glossary.py::SHORTHAND":
        entries = [(key, value)
                   for key, value in _drinking_glossary_entries("SHORTHAND")]
    elif name == "config/views.py::glossary":
        entries = _platform_glossary_entries()
    elif name == "templates/help/*.html":
        entries = [(str(path.relative_to(REPO_ROOT)), _scannable_prose(path))
                   for path in HELP_PAGES]
    elif name == "templates/**/*.html":
        entries = [(str(path.relative_to(REPO_ROOT)), _scannable_prose(path))
                   for path in _prose_templates()]
    elif name == "help_text=":
        entries = [(f"{path}:{line}", string)
                   for path, line, string in _help_text_strings()]
    else:  # pragma: no cover - a typo in SURFACES, not a runtime path
        raise AssertionError(f"unknown surface: {name}")

    for location, string in entries:
        offences = scan(string)
        if offences:
            flagged.append((location, string, offences))
    return flagged


SURFACES: tuple = (
    "drinking/glossary.py::SHORTHAND",
    "config/views.py::glossary",
    "templates/help/*.html",
    "templates/**/*.html",
    "help_text=",
)


# -- The ratchet -------------------------------------------------------------

#: **The walk-down, per surface. 118-01 measured these red; 118-02 swept them.**
#: Every number in the "after" column below was re-measured on 2026-08-06 in a
#: container rebuilt from the working tree, and the strings behind the 118-01
#: column are listed verbatim in ``118-01-EVIDENCE.md``.
#:
#: ==============================================  ======  =====  ==============
#: Surface                                         118-01  now    kind
#: ==============================================  ======  =====  ==============
#: ``drinking/glossary.py::FACILITY_TYPE_PLAIN``        14  gone   deleted whole
#: ``drinking/glossary.py::SHORTHAND``                   7      0  reading
#: ``config/views.py::glossary``                         8      2  ceiling
#: ``templates/help/*.html``                             2      2  ceiling
#: ``templates/**/*.html``                              14     10  ceiling
#: ``help_text=``                                        4      4  ceiling
#: ==============================================  ======  =====  ==============
#:
#: **Only one surface reaches a strict zero, and that is the honest outcome, not
#: an unfinished sweep.** All 18 locations still flagged are enumerated in
#: ``118-01-EVIDENCE.md`` Part two as false positives or recorded judgment calls,
#: and 118-02's instructions forbid changing them. Rewording legitimate copy to
#: reach a cosmetic zero would be the gate bending the product instead of
#: measuring it — the exact failure that made the three mandating tests in
#: ``tests/test_drinking_readability.py`` a defect rather than a guard.
#:
#: **Reading versus ceiling.** ``SHORTHAND`` and the platform glossary are
#: strings that exist in order to define something, so a flag on them is a real
#: finding and the number is a reading — ``SHORTHAND`` is now a **strict 0**.
#: The two template surfaces and ``help_text=`` are free prose, where the same
#: constructions occur innocently ("— set up your watershed" is a heading, not a
#: lecture), so those are ceilings. The platform glossary is recorded as a
#: ceiling **now** rather than a reading, because its two survivors are the
#: Apportionment worked example and the Effective Precipitation entry, both of
#: which ``118-01-EVIDENCE.md`` records as legitimate. The operator gate has the
#: same distinction in its own history: ``DEPLOY.md`` sat at "25 — a ceiling,
#: never a reading" until Phase 114 measured it at 24.
#:
#: The gate is deliberately NOT ``xfail``. It bites the moment a count climbs.
#: Lowering a baseline is the only legitimate edit. Raising one is a silently
#: weakened gate.
BASELINE: dict = {
    # Reading — strict, and it stays strict. Every value in this dictionary is a
    # decoding: "GAC" -> "Granular activated carbon." and nothing after it.
    "drinking/glossary.py::SHORTHAND": 0,
    # Ceilings — every survivor is named in 118-01-EVIDENCE.md Part two.
    #   glossary   : Apportionment (worked example), Effective Precipitation
    #   help pages : methods.html (shared-well worked example),
    #                water_balances.html (unmetered-diversions fact, a USGS
    #                publication title, a statement of platform behaviour)
    #   templates  : the 10 enumerated false positives — headings, page
    #                descriptions, computed-number explanations, agency-name
    #                expansions
    #   help_text= : 3 false positives naming a relation or a foreign key, plus
    #                core/forms.py:160, which explains what a SETTING means
    "config/views.py::glossary": 2,
    "templates/help/*.html": 2,
    "templates/**/*.html": 10,
    "help_text=": 4,
}


def test_the_facility_description_dictionary_stays_deleted():
    """``FACILITY_TYPE_PLAIN`` was a whole surface. It is not coming back.

    118-01 measured it at 14 flags of 22 entries, and read the other 8 by eye as
    the same defect in a shape none of the three constructions cover — so the
    disposition was the whole dictionary, not 14 rewrites. It gave all 22 EPA
    facility codes a sentence saying what the thing physically is ("A drilled
    well. Water comes up out of the ground here."), stacked directly under a
    panel heading that already rendered EPA's own label from
    ``FACILITY_TYPE_CHOICES``. Its only added content was the water lecture.

    This is a guard and not a leftover. **The mechanism that made ISS-129 recur
    was a refill, not an edit**: three tests in
    ``tests/test_drinking_readability.py`` mandated the descriptions, so hand
    corrections were reverted by the suite on the next run. A dictionary with
    this name reappearing — or the accessor, or a stub returning ``""`` — is that
    mechanism restarting. There is no baseline to lower here and no surface to
    scan; the correct count is that the names do not exist.
    """
    from drinking import glossary

    resurrected = [
        name for name in ("FACILITY_TYPE_PLAIN", "facility_type_plain")
        if hasattr(glossary, name)
    ]
    assert resurrected == [], (
        f"drinking/glossary.py has regrown {resurrected}. That dictionary gave "
        "every EPA facility code a sentence describing what the thing physically "
        "is, to a reader who is a water district engineer, and the facility panel "
        "heading already carries EPA's own label. Deleted by ISS-129 on "
        "2026-08-06 — DESIGN.md copy rule 11. Do not restore it, and do not "
        "leave a stub with a live name."
    )


def test_no_surface_gains_a_water_definition():
    climbed = []
    for surface in SURFACES:
        count = len(_scan_surface(surface))
        baseline = BASELINE[surface]
        if count > baseline:
            climbed.append(f"{surface}: {baseline} -> {count}")

    assert not climbed, (
        "these surfaces gained a definition of a water term. The reader is a "
        "water district engineer; explain the software and the data "
        "conventions, never the water (DESIGN.md copy rule 11). Expand a code "
        "and stop. Lowering a baseline is the only legitimate edit to "
        "BASELINE: " + "; ".join(climbed)
    )


# -- The controls ------------------------------------------------------------

PLANTED_WATER_DEFINITION = """\
<p class="page-description">A drilled well. Water comes up out of the ground
here.</p>
"""

#: All three legitimate constructions, each in the exact shape the repository
#: writes it. This control is the important one: it proves the carve-out holds,
#: and a red run here means the gate would fire on correct copy.
AGENCY_NAME_EXPANSION = "SGMA — Sustainable Groundwater Management Act"
EPA_CODE_EXPANSION = "GAC — granular activated carbon"
PLATFORM_CONCEPT = (
    "An Allocation Ceiling is the total volume assigned to a zone for a "
    "reporting period."
)


def test_the_gate_reports_a_planted_water_definition():
    slugs = {offence.slug for offence in scan(PLANTED_WATER_DEFINITION)}

    assert "well" in slugs, (
        "the scanner missed 'A drilled well.' — the exact string ISS-129 was "
        f"filed over. It reported {sorted(slugs)}"
    )


def test_the_gate_stays_silent_on_all_three_legitimate_constructions():
    agency = scan(AGENCY_NAME_EXPANSION)
    assert not agency, (
        "expanding an agency's own name was reported as a water lecture: "
        f"{[str(offence) for offence in agency]}. Agency and program names are "
        "filing conventions and stay explainable forever (DESIGN.md rule 11)."
    )

    code = scan(EPA_CODE_EXPANSION)
    assert not code, (
        "expanding a code inside EPA's own data was reported: "
        f"{[str(offence) for offence in code]}. Expanding the code is the "
        "correct half of the rule; only the description after it is the defect."
    )

    platform = scan(PLATFORM_CONCEPT)
    assert not platform, (
        "defining one of this platform's own coined concepts was reported: "
        f"{[str(offence) for offence in platform]}. The operator cannot know "
        "these — they are software, and the platform owes a definition."
    )
