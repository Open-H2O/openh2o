# SPDX-License-Identifier: AGPL-3.0-or-later
"""The struck sentence shapes a machine can see may only go down.

Since 2026-10-09 the shapes struck in review are fixed everywhere. DESIGN.md copy rule 15 names seven. ``scripts/writing_shapes.py``
counts the four a pattern can find: an em dash or a double hyphen between two
words, the filler words (actually, genuinely, really, simply), a heading made
of two clauses joined by ", and what", and a heading ending in ", by what". It
reads every template, the .html pages and the .txt emails (including the words
passed into included partials, ``source_label``, ``module_nouns`` and four
filters), every application Python file except the few whose strings never
reach a screen (``NOT_SCREEN_PYTHON``), and the public guides.

``BASELINE`` held each file's count from 2026-10-09 and was the to-do list for
the writing work; it reached zero on 2026-10-18. ``EXCEPTIONS`` now holds each
line a shape still matches on purpose, with its reason, and a line is excused
only for the shapes its entry names. A file may not gain a shape, and an entry
whose line has gone fails as well, so the list always states the truth.

Before it was installed the scanner was run against the history: the About
page at the commit before d247786 counts no paired heading, and at d247786 it
counts three ("What OpenH2O is, and who it is for"; "What it owes to the
Groundwater Accounting Platform, and what is its own"; "Who made it, and where
the code is"), the headings that started this work. The stand-in shape ("that platform",
"both are") was replayed the same way on 2026-10-10: About counts 0 at
3cbe34c, 2 at 017c89d and at fbe4f47 (the two versions struck for it)
and 0 after the approved sentence went in.

The "district reader" and "California" shapes joined on 2026-10-11 (150.4-01),
so that OpenH2O reads nationally and for any reader, not only a district. Replayed against f4b18da first: templates caught 48 of the recount's
49 district-reader lines and 3 of its 4 generic-California lines (the misses
sit inside ``<script>``).

"No" put where "not" belongs ("sends no email") joined on 2026-10-20
(151.2-01). Replayed first against 72 struck and 767 approved sentences: it hits
the three struck for it, one of the 39 account sentences approved that morning
(the same "sends no email"), and 25 approved sentences of the same shape that
were approved before the shape was struck. The product counted 51 such lines
(templates 16, screen Python 2, guides 33). They wait in ``BASELINE`` until
they are taken up page by page; the check stops new ones.

On 2026-10-20 (151.3-01, ISS-261) the guard stopped reading Python by an
allow-list of 15 files and started reading every application file. The 172
files it had not read carried 102 hits: 4 on a screen, held in ``BASELINE``
with the 1 hit a filter's words carried; 57 on strings no product page prints
(help text only the Django admin shows, start-up errors, the module records),
held line by line in ``EXCEPTIONS``; and 41 in the four files of
``NOT_SCREEN_PYTHON``. The measure, file by file, is
``.planning/phases/151.3-language-review-first-pass/151.3-01-ISS261-MEASURE.md``.

The other three shapes (a phrase posing as a statement, a thing acting like a
person, a slogan) need a reader and are not counted here.

**Kill switch:** ``OPENH2O_WRITING_SHAPES_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_WRITING_SHAPES_CHECK", "1") == "0",
    reason="OPENH2O_WRITING_SHAPES_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "writing_shapes.py"


def _load():
    if not SCRIPT.exists():
        pytest.fail(f"{SCRIPT} is missing; update SCRIPT if it moved.")
    spec = importlib.util.spec_from_file_location("writing_shapes_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shapes = _load()

#: The guard reached zero on 2026-10-18 (150.1-03). What is left on the screens
#: is held line by line in EXCEPTIONS below; BASELINE keeps only what still
#: waits on a ruling. The "no for not" lines counted on 2026-10-20 were all
#: reworded the same day on the owner's approval (the saved ledger words with
#: parcels migration 0014). Lower an entry when its file loses a shape; never
#: raise one. The five below are on a screen and were outside the guard's reach
#: until 2026-10-20 (ISS-261); the language review fixes each in the segment
#: that holds its page.
BASELINE: dict = {
    "accounting/calculation.py": {"em dash": 2},
    "accounting/engine_run.py": {"negation frame": 1},
    "drinking/provenance.py": {"California": 1},
    "templates/drinking/partials/_onboard_review.html": {"no for not": 1},
}

_REPORTS = (
    "Reports is off by default and marked Under development (2026-10-12); its "
    "words are rewritten when Reports is built, as 150.1-02 left its screens."
)
_APPROVED = (
    "approved word for word on {}; its 'none' or 'not' is the fact the "
    "sentence states, and it stays as approved (ruling 2026-10-18)."
)
_DEVELOPER = (
    "an Http404 message, shown only on a server running with DEBUG on; the "
    "public 404 page never prints it."
)
#: Strings in a screen file that no product page prints (ISS-261, 2026-10-20).
_ADMIN_HELP = (
    "help text on a column no OpenH2O form shows; only the Django admin's "
    "change form prints it, and the admin is outside the product's pages."
)
_NOWHERE_HELP = (
    "help text on a column no form shows, on a model the Django admin does not "
    "register; nothing prints it."
)
_ADMIN_CHECK = (
    "a SampleResult model check that no OpenH2O form or importer runs; only the "
    "Django admin's change form does."
)
_SYNC_LOG = (
    "stored in a sync log's error_message, which no page prints; only the "
    "Django admin shows it."
)
_START_UP = (
    "printed in the start-up error when OPENH2O_MODULES leaves out a required "
    "module, read in a terminal."
)
_MODULE_RECORD = (
    "a SCHEMA_EXCEPTIONS record read by tests/test_composition_rule.py; no page "
    "prints it."
)

#: Each line a shape still matches, kept on purpose: (file, a fragment of the
#: line as the scanner reads it, the shapes it is excused for, why). A line is
#: excused only for the shapes named, so a new shape in the same line still
#: fails, and an entry whose line is gone or no longer carries its shape fails
#: too, the way an unused CALIFORNIA_NAMES entry does.
EXCEPTIONS: tuple = (
    # The four lines that name a real thing, not the reader (150.1-03 plan).
    ("templates/about.html", "A groundwater agency, an irrigation district or a grower",
     ("district reader",), "a list of the kinds of organization that use OpenH2O."),
    ("templates/drinking/partials/_empty_drinking.html", "opens on that system",
     ("stand-in",), "the water system the sentence has just named."),
    ("templates/drinking/partials/_onboard_result.html", "EPA no longer has that system",
     ("stand-in",), "the water system the person looked up."),
    ("templates/surface/partials/_diversion_import_preview.html", "USE is California's total-use figure",
     ("California",), "names the state's own figure in the state's diversion file."),
    # Stored data.
    ("accounting/ledger_words.py", "Incidental recharge \u2014 deep percolation",
     ("em dash",), "LEGACY_INCIDENTAL_RECHARGE_WORDS matches the description older "
     "ledger rows were written with; it is never printed as new copy."),
    # Approved word for word, and kept (2026-10-18 09:34).
    ("templates/drinking/partials/_onboard_review.html", "not for the agency that regulates it",
     ("negation frame",), _APPROVED.format("2026-10-13")),
    ("templates/drinking/partials/_onboard_review.html", "None of this system's facilities",
     ("negation frame",), _APPROVED.format("2026-10-13")),
    ("templates/surface/diversion_import.html", "rather than the application number",
     ("negation frame",), _APPROVED.format("2026-10-14")),
    ("templates/surface/partials/_detail_pane.html", "none of the canal's use areas",
     ("negation frame",), _APPROVED.format("2026-10-13")),
    ("health/checks.py", "none of the canal's use areas",
     ("negation frame",), _APPROVED.format("2026-10-16")),
    ("health/checks.py", ", not a public domain name",
     ("negation frame",), _APPROVED.format("2026-10-16")),
    ("templates/help/budgets_allocations.html", "When none of the zones an account",
     ("negation frame",), _APPROVED.format("2026-10-19")),
    # Developer messages.
    ("config/views.py", "It is hidden rather than rewritten", ("negation frame",), _DEVELOPER),
    ("infrastructure/views.py", "runs none of the modules", ("negation frame",), _DEVELOPER),
    # Reports.
    ("templates/reporting/partials/_handoff.html", "given your agency", ("district reader",), _REPORTS),
    ("templates/reporting/partials/_openet_prefill.html", "Nothing was written to the water-use ledger",
     ("em dash",), _REPORTS),
    ("templates/reporting/partials/_report_actions.html", "A check, not a filing",
     ("negation frame",), _REPORTS),
    ("templates/reporting/partials/_report_detail_pane.html", "that system does not currently accept",
     ("stand-in",), _REPORTS),
    ("templates/reporting/partials/_report_detail_pane.html", "instead of typing them",
     ("negation frame",), _REPORTS),
    ("templates/reporting/partials/_report_detail_pane.html", "not what you pumped or diverted",
     ("em dash",), _REPORTS),
    ("templates/reporting/partials/_status_section.html", "your agency's own progress",
     ("district reader",), _REPORTS),
    ("templates/reporting/partials/_status_section.html", "the agency recorded filing",
     ("district reader",), _REPORTS),
    ("templates/reporting/partials/_status_section.html", "your agency's sign-off",
     ("district reader",), _REPORTS),
    ("templates/reporting/report_list.html", "Nothing here is submitted to the state",
     ("em dash",), _REPORTS),
    ("templates/reporting/report_prefill.html", "Prepare with OpenET", ("em dash",), _REPORTS),
    ("reporting/validators.py", "No GEARS Correspondence ID on file", ("em dash",), _REPORTS),
    ("reporting/validators.py", "the GEARS upload would be empty", ("em dash",), _REPORTS),
    ("reporting/validators.py", "GEARS by-well requires metered", ("em dash",), _REPORTS),
    ("reporting/validators.py", "have no well registration ID", ("em dash",), _REPORTS),
    ("reporting/validators.py", "duplicate parcel-month reading", ("em dash",), _REPORTS),
    ("reporting/validators.py", "well(s) have a hand-set parcel split", ("em dash",), _REPORTS),
    ("reporting/validators.py", "metered parcel(s) have no well link", ("em dash",), _REPORTS),
    ("reporting/validators.py", "GEARS by-ET requires", ("em dash",), _REPORTS),
    ("reporting/validators.py", "the CalWATRS form would have nothing", ("em dash",), _REPORTS),
    ("reporting/validators.py", "duplicate POD-month record", ("em dash",), _REPORTS),
    ("reporting/validators.py", "their rows are withheld from the CalWATRS file", ("em dash",), _REPORTS),
    ("reporting/validators.py", "point(s) of diversion have a hand-set parcel split", ("em dash",), _REPORTS),
    ("reporting/validators.py", "reported gross as the state requires",
     ("em dash", "negation frame"), _REPORTS),
    ("reporting/validators.py", "will only contain wells with readings", ("em dash",), _REPORTS),
    ("reporting/validators.py", "leaves their Area blank", ("em dash", "negation frame"), _REPORTS),
    ("reporting/validators.py", "will only contain the diversions you entered", ("em dash",), _REPORTS),
    ("reporting/views.py", "can't be generated", ("em dash",), _REPORTS),
    # Strings in a screen file that no product page prints (ISS-261, 2026-10-20).
    ("accounting/models.py", "Surplus banked (acre-feet, positive). The pr",
     ("em dash",), _ADMIN_HELP),
    ("accounting/models.py", "148-02 (Q1, an over-delivery is nobody's cre",
     ("em dash", "filler"), _ADMIN_HELP),
    ("accounting/models.py", "148-04: the SiteConfig.over_delivery_treatme",
     ("em dash", "no for not"), _ADMIN_HELP),
    ("accounting/models.py", "148-04: the amount this run actually credite",
     ("em dash", "filler"), _ADMIN_HELP),
    ("accounting/models.py", "148-04: True when over_delivery_credited_af",
     ("em dash", "negation frame"), _ADMIN_HELP),
    ("accounting/models.py", "Net consumptive use = gross ET − effective p",
     ("em dash",), _ADMIN_HELP),
    ("accounting/models.py", "How the ET − precip − surface residual was r",
     ("em dash",), _ADMIN_HELP),
    ("accounting/models.py", "148-02 Task 4 (Q2): the estimated field's pu",
     ("em dash", "double hyphen"), _ADMIN_HELP),
    ("accounting/models.py", "148-02 Task 4 (Q2): gw_extracted_af minus fi",
     ("double hyphen",), _ADMIN_HELP),
    ("accounting/models.py", "sha256[:12] of the ordered enabled steps + c",
     ("em dash",), _ADMIN_HELP),
    ("accounting/models.py", "The months to calculate, oldest first, each",
     ("filler",), _NOWHERE_HELP),
    ("core/modules.py", "core owns AUTH_USER_MODEL; disabling it is a",
     ("negation frame",), _START_UP),
    ("core/modules.py", "Move the join to the optional side — a wells",
     ("em dash", "negation frame"), _MODULE_RECORD),
    ("core/modules.py", "A wells.WellMeasurement link table plus a da",
     ("em dash",), _MODULE_RECORD),
    ("core/modules.py", "The surface-water counterpart of the arrow a",
     ("negation frame",), _MODULE_RECORD),
    ("core/modules.py", "A parcels.ParcelMeasurement link table plus",
     ("em dash",), _MODULE_RECORD),
    ("core/modules.py", "A wells.WellDatastream link table, which als",
     ("negation frame",), _MODULE_RECORD),
    ("core/modules.py", "The same Thing slot as the arrow above, for",
     ("negation frame",), _MODULE_RECORD),
    ("core/modules.py", "A datasync.StationDatastream link table, wit",
     ("em dash",), _MODULE_RECORD),
    ("core/modules.py", "Move the ParcelZone model itself into parcel",
     ("em dash",), _MODULE_RECORD),
    ("core/modules.py", "A drinking-water facility very often IS a we",
     ("em dash", "district reader", "negation frame", "no for not"), _MODULE_RECORD),
    ("core/modules.py", "A wells.WellFacility link table plus a data",
     ("em dash", "negation frame"), _MODULE_RECORD),
    ("core/modules.py", "Same entanglement as ParcelLedger.water_type",
     ("em dash", "negation frame"), _MODULE_RECORD),
    ("core/modules.py", "A wells.WellDeliveryAccount link table plus",
     ("negation frame",), _MODULE_RECORD),
    ("datasync/adapters/base.py", " fetched but 0 staged — all records dropped",
     ("em dash",), _SYNC_LOG),
    ("drinking/models.py", "EPA WATER_SYSTEM.population_served_count — t",
     ("em dash",), _ADMIN_HELP),
    ("drinking/models.py", "EPA WATER_SYSTEM.service_connections_count —",
     ("em dash",), _ADMIN_HELP),
    ("drinking/models.py", "The ADMINISTRATOR'S MAILING state, NOT the p",
     ("em dash", "negation frame"), _ADMIN_HELP),
    ("drinking/models.py", "State-assigned facility ID — the segment DDW",
     ("em dash",), _ADMIN_HELP),
    ("drinking/models.py", "Entered on this deployment's facility form r",
     ("negation frame",), _ADMIN_HELP),
    ("drinking/models.py", "Primary Station Code, the composite {pwsid}_",
     ("em dash",), _ADMIN_HELP),
    ("drinking/models.py", "DDW's four-digit analyte code. NULL when no",
     ("em dash",), _ADMIN_HELP),
    ("drinking/models.py", "1 to 12. Null means the year was reported as",
     ("double hyphen", "negation frame"), _ADMIN_HELP),
    ("drinking/models.py", "The non-detect flag does not apply to a pres",
     ("em dash",), _ADMIN_CHECK),
    ("reporting/models.py", "The geography.Boundary representing this age",
     ("district reader",), _REPORTS),
    ("reporting/models.py", "Legal name of the agency as it appears on st",
     ("district reader",), _REPORTS),
    ("reporting/models.py", "Correspondence ID mailed by SWRCB to bind th",
     ("district reader",), _REPORTS),
    ("reporting/models.py", "User-edited OpenET pre-fill values, keyed by",
     ("district reader",), _REPORTS),
    ("standards/models.py", "The SensorThings Sensor — the instrument/pro",
     ("em dash",), _ADMIN_HELP),
    ("surface/models.py", "CalWATRS PIN mailed by SWRCB for this water",
     ("district reader",), _ADMIN_HELP),
)


def _unexcused():
    """``({rel: {shape: n}}, [stale exception, ...])`` after EXCEPTIONS are taken out."""
    out, used = {}, set()
    for files in shapes.surfaces().values():
        for rel in files:
            runs, headings = shapes.file_text(rel, (REPO_ROOT / rel).read_text())
            counts = shapes.count(runs, headings)
            for run in runs:
                excused = set()
                for i, (erel, fragment, kept, _reason) in enumerate(EXCEPTIONS):
                    if erel == rel and fragment in run:
                        run_counts = shapes.count([run], [])
                        if all(run_counts[shape] for shape in kept):
                            used.add(i)
                            excused.update(kept)
                for shape in excused:
                    counts[shape] -= shapes.count([run], [])[shape]
            counts = {k: v for k, v in counts.items() if v}
            if counts:
                out[rel] = counts
    stale = [f"{e[0]}: {e[1]!r} {e[2]}" for i, e in enumerate(EXCEPTIONS) if i not in used]
    return out, stale


_ADVICE = (
    "An em dash or double hyphen becomes a colon, a comma, a full stop or "
    "parentheses. A filler word comes out. A heading in two clauses becomes one "
    "plain question or one plain statement (DESIGN.md copy rule 15). A district "
    "reader is rewritten as a whole sentence about the thing itself (\"the land "
    "your records cover\"), not by putting an actor in front of the old words; a "
    "general \"California\" says the general thing (DESIGN.md copy rule 11). "
    "\"X can instead ...\" names the choices instead. \"No\" on the object "
    "becomes \"not\" on the verb (\"does not send email\")."
)


def test_no_file_gains_a_shape():
    gained = [
        f"{rel} {shape}: {BASELINE.get(rel, {}).get(shape, 0)} -> {n}"
        for rel, counts in _unexcused()[0].items()
        for shape, n in counts.items()
        if n > BASELINE.get(rel, {}).get(shape, 0)
    ]
    assert not gained, (
        "these files gained a sentence shape struck in review. " + _ADVICE
        + " Never raise BASELINE or add an EXCEPTIONS entry to pass: " + "; ".join(gained)
    )


def test_every_baseline_is_tight():
    """A count with slack would let a shape come back where one was removed."""
    now = _unexcused()[0]
    slack = [
        f"{rel} {shape}: baseline {ceiling}, now {now.get(rel, {}).get(shape, 0)}"
        for rel, counts in BASELINE.items()
        for shape, ceiling in counts.items()
        if now.get(rel, {}).get(shape, 0) < ceiling
    ]
    assert not slack, (
        "these files lost a shape. Lower (or delete) their BASELINE entry to "
        "the new count: " + "; ".join(slack)
    )


def test_every_exception_still_matches_its_line():
    """An exception whose line is gone, or no longer carries its shape, would hide a new one."""
    stale = _unexcused()[1]
    assert not stale, "these EXCEPTIONS entries match no line carrying their shape: " + "; ".join(stale)


def test_every_exception_gives_a_reason():
    assert all(len(reason) > 20 for *_rest, reason in EXCEPTIONS)


def test_every_not_screen_file_exists_and_gives_a_reason():
    """A file the scanner skips has to be there, and has to say why it is skipped."""
    for rel, reason in shapes.NOT_SCREEN_PYTHON:
        assert (REPO_ROOT / rel).exists(), f"NOT_SCREEN_PYTHON names a missing file: {rel}"
        assert len(reason) > 20, rel


def test_every_baseline_file_is_still_read():
    """An entry for a file the scanner no longer reads would never fail."""
    read = {rel for files in shapes.surfaces().values() for rel in files}
    missing = sorted(set(BASELINE) - read)
    assert not missing, f"BASELINE names files the scanner does not read: {missing}"


# -- The controls ------------------------------------------------------------

def _template(source: str) -> dict:
    return shapes.count_file("templates/planted.html", source)


def test_a_planted_paired_heading_is_caught():
    assert _template("<h2>What X is, and what Y is</h2>")["paired heading"] == 1


def test_a_planted_trailing_heading_is_caught():
    assert _template("<h3>How the month ends, by what the field has</h3>")["trailing heading"] == 1


def test_a_page_title_block_is_read_as_a_heading():
    source = "{% block page_title %}Who made it, and where the code is{% endblock %}"
    assert _template(source)["paired heading"] == 1


def test_the_three_about_headings_that_started_this_work_are_caught():
    source = (
        "<h2>What OpenH2O is, and who it is for</h2>"
        "<h2>What it owes to the Groundwater Accounting Platform, and what is its own</h2>"
        "<h2>Who made it, and where the code is</h2>"
    )
    assert _template(source)["paired heading"] == 3


def test_a_planted_em_dash_is_caught_on_every_surface():
    assert _template("<p>Readings are flagged &mdash; check the meter.</p>")["em dash"] == 1
    python = 'MESSAGE = "No rows to import — upload the file again."\n'
    assert shapes.count_file("planted.py", python)["em dash"] == 1
    guide = "The setting is read once\n— at start-up — and kept.\n"
    assert shapes.count_file("planted.md", guide)["em dash"] == 2


def test_a_stand_in_for_a_name_is_caught():
    """The two lines struck on About on 2026-10-10, as they read."""
    source = (
        "<p>OpenH2O was written from scratch in Python and does not use any of "
        "that platform's code.</p>"
        "<td>Both are released under the GNU Affero General Public License.</td>"
    )
    assert _template(source)["stand-in"] == 2


def test_a_planted_double_hyphen_and_filler_word_are_caught():
    counts = _template("<p>It is simply the total -- nothing more.</p>")
    assert (counts["double hyphen"], counts["filler"]) == (1, 1)


def test_the_words_passed_into_an_included_partial_are_read():
    source = '{% include "partials/_explainer_popout.html" with text="The total — as stored." %}'
    assert _template(source)["em dash"] == 1


def test_text_no_reader_sees_stays_silent():
    template = (
        "{# What came through the meter — a comment, really #}"
        "{% comment %}it simply sits here — not copy{% endcomment %}"
        "<!-- — --><script>var a = 'x — y';</script><style>/* — */</style>"
        '{{ value|default:"—" }}<td>—</td>'
        "<p>This page says what it is, and who it is for.</p>"
    )
    assert set(_template(template).values()) == {0}
    python = (
        '"""A docstring — not on a screen, really."""\n'
        'logger.info("synced — %s rows", n)\n'
    )
    assert set(shapes.count_file("planted.py", python).values()) == {0}
    guide = "```\nmake up  # really — a shell comment\n```\n| Code | Unit |\n|---|---|\n| x | — |\n"
    assert set(shapes.count_file("planted.md", guide).values()) == {0}


# -- District reader and California (150.4-01) --------------------------------

def test_a_planted_district_reader_is_caught_on_every_surface():
    """The sentences the 2026-10-11 approval replaced, as they read."""
    template = (
        "<td>A district can reorder those steps or switch any of them off.</td>"
        "<td>75 percent unless the district changes it.</td>"
        "<p>Give the Setup Wizard your district&rsquo;s boundary.</p>"
        '<input placeholder="District name">'
    )
    assert _template(template)["district reader"] == 4
    python = 'HELP = "These agency-wide settings apply to the whole agency."\n'
    assert shapes.count_file("planted.py", python)["district reader"] == 2
    guide = "Ask your agency for an account.\n"
    assert shapes.count_file("planted.md", guide)["district reader"] == 1


def test_the_approved_replacements_carry_no_district_reader():
    approved = (
        "<td>An administrator can reorder those steps or switch any of them off.</td>"
        "<td>75 percent unless an administrator changes it.</td>"
        "<td>An administrator or operator sets an allocation ceiling on Allocations.</td>"
        "<p>The Setup Wizard needs a boundary, which is the outline of the land your records cover.</p>"
        "<p>OpenH2O is for anyone who keeps water records, anywhere in the United States: "
        "engineers and managers at water agencies and districts, growers, ditch tenders "
        "and drinking-water system operators.</p>"
    )
    assert _template(approved)["district reader"] == 0


def test_a_district_or_agency_in_the_water_world_is_not_a_reader():
    entity = (
        "<p>The regulating agency was recorded from the file.</p>"
        "<p>State classification and regulating agency. OpenH2O fills a blank regulating agency from the Regulating Agency column of an imported lab file.</p>"
        "<p>not for the agency that regulates it.</p>"
        "<p>Pick an area, such as the land an irrigation district serves.</p>"
        "<p>the local agency responsible for managing groundwater under SGMA.</p>"
    )
    assert _template(entity)["district reader"] == 0


def test_a_planted_generic_california_is_caught_on_every_surface():
    assert _template("<p>Decimal degrees inside California.</p>")["California"] == 1
    python = 'MESSAGE = "outside the expected California range."\n'
    assert shapes.count_file("planted.py", python)["California"] == 1
    guide = "a platform a California water agency can stand up\n"
    assert shapes.count_file("planted.md", guide)["California"] == 1


def test_a_california_proper_name_is_not_counted():
    names = (
        "<p>California Data Exchange Center, real-time data.</p>"
        "<p>California's 2014 law under which GSAs manage groundwater basins.</p>"
        "<p>ELAP is California's Environmental Laboratory Accreditation Program.</p>"
    )
    assert _template(names)["California"] == 0


def _every_text_read():
    texts = []
    for files in shapes.surfaces().values():
        for rel in files:
            source = (REPO_ROOT / rel).read_text()
            if rel.endswith(".html"):
                texts.extend(shapes.template_text(source)[0])
            elif rel.endswith(".py"):
                texts.extend(shapes.python_strings(source))
            else:
                texts.extend(shapes.guide_text(source)[0])
    return "\n".join(texts)


def test_every_kept_name_and_phrase_is_still_used():
    """A kept name no page uses any more would let a generic one through later."""
    text = _every_text_read()
    stale = [
        name for name, _ in shapes.CALIFORNIA_NAMES + shapes.DISTRICT_ENTITY
        if not re.search(name, text, re.I)
    ]
    assert not stale, (
        "these kept names match nothing the scanner reads; take them out of "
        "CALIFORNIA_NAMES or DISTRICT_ENTITY in scripts/writing_shapes.py: "
        + "; ".join(stale)
    )


# -- The three shapes added on 2026-10-17 ---------------------------------------

def test_brents_struck_readme_line_is_caught():
    struck = "**A new installation holds none of your records.** It starts empty.\n"
    counts = shapes.count_file("docs/planted.md", struck)
    assert counts["bold verdict"] == 1
    assert counts["negation frame"] == 1


def test_a_planted_reassurance_is_caught():
    assert _template("<p>The refusal to start is deliberate.</p>")["reassurance"] == 1


def test_a_planted_negation_frame_is_caught():
    assert _template("<p>The site sends mail through a provider instead of its own server.</p>")[
        "negation frame"] == 1


def test_an_approved_sentence_is_not_a_bold_verdict():
    approved = "The demonstration uses a real California basin.\n"
    assert shapes.count_file("docs/planted.md", approved)["bold verdict"] == 0


def test_a_planted_can_instead_is_caught():
    struck = "<td>An administrator can instead let it expire at the end of the water year.</td>"
    assert _template(struck)["can instead"] == 1


# -- "No" put where "not" belongs (151.2-01) ------------------------------------

def test_the_three_struck_no_sentences_are_caught():
    struck = (
        "<p>The water accounting is sample data made up for the demonstration, and it "
        "names no real water district.</p>"
        "<td>This setting changes no figure.</td>"
        "<p>This site sends no email. Ask an administrator to set a temporary password for you.</p>"
    )
    assert _template(struck)["no for not"] == 3


def test_the_approved_account_sentences_carry_no_for_not():
    """The New cells of the 2026-10-20 account rows that hold "no" or "not", rows 11 to 37."""
    approved = (
        "<p>This page sets a temporary password for jane@example.com. Their current password "
        "stops working when you click Set temporary password. OpenH2O will ask them to choose a "
        "new password the next time they sign in. OpenH2O does not email the person about the "
        "change.</p>"
        "<p>The person signs in with their email address and the starting password you set here. "
        "OpenH2O will ask them to choose a new password the first time they sign in. OpenH2O does "
        "not email them.</p>"
        "<p>The link works once and expires in three days. If you did not ask for this, you can "
        "ignore this email. Your password has not changed.</p>"
    )
    assert _template(approved)["no for not"] == 0
    python = (
        'A = "ensure_superuser: skipped. .env does not set both DJANGO_SUPERUSER_EMAIL and '
        'DJANGO_SUPERUSER_PASSWORD."\n'
        'B = "change_email: changed jane@example.com to jane.doe@example.org. The password did not change."\n'
        'C = "change_email: no account has the email address jane@example.com."\n'
    )
    assert shapes.count_file("planted.py", python)["no for not"] == 0


def test_no_in_plain_english_is_not_counted():
    plain = (
        "<p>There is no map for this facility.</p>"
        "<p>This file has no map features.</p>"
        "<p>No one has signed in yet.</p>"
        "<p>The station no longer publishes.</p>"
        "<p>A use area with no meter is estimated.</p>"
        "<p>Automatic HTTPS with almost no setup</p>"
        "<p>Run docker image prune to remove images no container uses.</p>"
    )
    assert _template(plain)["no for not"] == 0


def test_a_planted_no_for_not_is_caught_on_every_surface():
    assert _template("<p>The import adds no result.</p>")["no for not"] == 1
    python = 'MESSAGE = "The import adds no result."\n'
    assert shapes.count_file("planted.py", python)["no for not"] == 1
    guide = "The import adds no result.\n"
    assert shapes.count_file("planted.md", guide)["no for not"] == 1


# -- Every screen surface (151.3-01, ISS-261) ---------------------------------

def _package(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "__init__.py").touch()
    path.write_text(source)


def test_a_new_application_file_is_read_and_a_not_screen_one_is_not(tmp_path):
    """The Python surface is every application file, so a new importer is read the day it lands."""
    planted = 'MESSAGE = "Row 4 was skipped \u2014 the date is blank."\n'
    _package(tmp_path, "newapp/importer.py", planted)
    _package(tmp_path, "newapp/models.py", 'x = Field(help_text="The total \u2014 as stored.")\n')
    _package(tmp_path, "newapp/management/commands/run.py", planted)
    _package(tmp_path, "newapp/migrations/0001_initial.py", planted)
    _package(tmp_path, "core/checks.py", 'W = Warning("Settings are local \u2014 not for real records.")\n')
    (tmp_path / "templates").mkdir()
    read = shapes.surfaces(tmp_path)["screen python"]
    assert "newapp/importer.py" in read and "newapp/models.py" in read
    assert "core/checks.py" not in read
    assert not [rel for rel in read if "/management/" in rel or "/migrations/" in rel]
    assert shapes.measured(tmp_path) == {
        "newapp/importer.py": {"em dash": 1}, "newapp/models.py": {"em dash": 1}}


def test_the_words_a_filter_or_source_label_prints_are_read():
    assert _template('<td>{{ right.source|default:"Not stated \u2014 ask" }}</td>')["em dash"] == 1
    assert _template("<td>{{ x|blank:'None on file \u2014 yet' }}</td>")["em dash"] == 1
    assert _template('{{ ok|yesno:"Yes,No,Not really known" }}')["filler"] == 1
    assert _template('{% source_label "GAMA" detail="EPA sends no coordinates" %}')["no for not"] == 1
    nouns = '{% module_nouns "wells:wells" "parcels:your district\'s use areas" %}'
    assert _template(nouns)["district reader"] == 1


def test_an_email_template_is_read_line_by_line():
    email = (
        "{% autoescape off %}Someone asked to reset the password for {{ email }}.\n\n"
        "{{ password_reset_url }}\n\n"
        "The link works once \u2014 and then it simply expires.{% endautoescape %}\n"
    )
    runs, _ = shapes.file_text("templates/account/email/planted.txt", email)
    assert runs == ["Someone asked to reset the password for X .", "X",
                    "The link works once \u2014 and then it simply expires."]
    counts = shapes.count_file("templates/account/email/planted.txt", email)
    assert (counts["em dash"], counts["filler"]) == (1, 1)


def test_the_emails_are_on_the_template_surface():
    read = shapes.surfaces()["templates"]
    assert "templates/account/email/password_reset_key_message.txt" in read
    assert "templates/account/messages/password_changed.txt" in read
