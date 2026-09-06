# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vocabulary gate: every screen names each water quantity once, the same way.

``DESIGN.md`` copy rule 12 is the definitions table, ``core/water_vocabulary.py``
reads it, and this file is what makes it bite. It is the third gate in a family:
``tests/test_operator_vocabulary.py`` says *define the infrastructure term
before you use it*; ``tests/test_domain_vocabulary.py`` says *never define the
water term at all*; this one says *call each quantity by its one name*.

**Why a gate and not a copy pass.** Phase 135 traced all 106 rendered figures
and found not one wrong number. What it found was a correct number under a
label naming something else (ISS-153: banked recharge water headed "Consumptive
Use"), two screens naming the same rows differently (ISS-155: a canal delivery
is a "debit" on one page and a "supply" on the next), and a budget subtracting a
quantity nobody manages against it (ISS-151). Each survived months of green
runs because nothing compared the words on one screen with the words on
another. A sweep with no rule behind it is the same defect scheduled to recur.

**What this gate proves, and what it does not.** That a phrase the table
forbids appears, as visible text, inside the scope the table gives it. It
cannot judge whether a sentence uses the RIGHT word; it can only hold the
wrong ones at zero. It scans template source, so it reaches every arm of every
``{% if %}`` and every HTMX partial a GET never renders, and it cannot see text
that arrives from the database (ISS-089's recorded scope).

**Two measured differences from the domain gate, each for a reason.**

1. **It reads the ``text="…"`` and ``title="…"`` arguments of ``{% include %}``
   tags before stripping template syntax.** The domain gate strips ``{% %}``
   first, and 118-02 recorded that as a real blind spot: an explainer popout's
   whole body lives inside an include argument. The Remaining popout on the
   dashboard, one of the four sites Phase 136 measured red, lives exactly there.
   It also keeps ``<th>`` text, where ISS-153's heading lives; ``template_prose``
   in ``tests/test_drinking_readability.py`` removes ``<th>`` on purpose for its
   own casing check, so it is deliberately not imported here.
2. **The baseline is a strict zero for every rule.** The domain gate carries
   ceilings because its constructions occur innocently in free prose. These
   phrases do not: each is wrong wherever it appears inside its scope, so there
   is no legitimate survivor to enumerate and nothing to ratchet down from.

**The red run is on record.** Against the v2.15 templates (tag ``d12d778``,
byte-identical to the working tree when the gate was first run) the ratchet
named four sites; the verbatim output is in
``.planning/phases/136-one-vocabulary-of-water-use/136-01-EVIDENCE.md``.

Every test calls ``scan()``. A control that exercises a different code path
from the gate proves nothing.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from core.water_vocabulary import NO_GATED_PHRASE, load_rules

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_MD = REPO_ROOT / "DESIGN.md"
TEMPLATES = REPO_ROOT / "templates"

RULES = load_rules(DESIGN_MD)


# -- Reducing a template to the words a reader sees --------------------------

_COMMENT_BLOCK = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)
_COMMENT_INLINE = re.compile(r"\{#.*?#\}", re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.S | re.I)
_VARIABLE = re.compile(r"\{\{.*?\}\}", re.S)
_TAG = re.compile(r"\{%.*?%\}", re.S)
#: The string arguments a popout include carries. Pulled OUT of the tag before
#: the tag is stripped, so the reader's words survive and the syntax does not.
_INCLUDE_TEXT = re.compile(r"""\b(?:text|title)\s*=\s*(["'])(.*?)\1""", re.S)
#: Attributes that are code or styling rather than copy. ``title="…"`` on an
#: HTML element is deliberately NOT here: it is the hover text on a badge, and a
#: reader sees it.
_CODE_ATTRIBUTES = re.compile(
    r"""\s(?:class|style|on[a-z]+|hx-[a-z-]+|href|id|name|for)\s*=\s*(["']).*?\1""",
    re.S,
)
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def visible_text(source: str) -> str:
    """A template's source reduced to what a reader could see.

    Order matters: comments go first so a commented-out include cannot leak its
    arguments; include arguments are harvested before ``{% %}`` is stripped;
    code attributes are dropped before HTML tags are, so an attribute value is
    never mistaken for element text.
    """
    text = _COMMENT_BLOCK.sub(" ", source)
    text = _COMMENT_INLINE.sub(" ", text)
    text = _SCRIPT_STYLE.sub(" ", text)
    harvested = [
        match.group(2)
        for tag in _TAG.finditer(text)
        for match in _INCLUDE_TEXT.finditer(tag.group(0))
    ]
    text = _VARIABLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = _CODE_ATTRIBUTES.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", " ".join([text, *harvested])).strip()


@dataclass(frozen=True)
class Hit:
    """One forbidden phrase found where the table says it may not appear."""

    location: str
    phrase: str
    term: str
    quote: str

    def __str__(self) -> str:
        return f"{self.location}: `{self.phrase}` (the term is {self.term}) …{self.quote}…"


def scan(text: str, location: str, rules=RULES) -> list:
    """Every hit in ``text``, which a reader sees at ``location``.

    ``location`` is a repo-relative path such as
    ``templates/surface/partials/_diversion_records.html`` or a surface name
    such as ``config/views.py::glossary``; each rule applies only inside its
    own scope, and an ``anywhere`` rule applies to every location. ``text`` is
    template SOURCE for a template location and a plain string for the other
    surfaces, and the reduction to visible words happens here so every caller,
    the controls included, goes through the same path.
    """
    words = visible_text(text) if location.startswith("templates/") else text
    hits = []
    for rule in rules:
        if not rule.applies_to(location):
            continue
        for match in rule.pattern.finditer(words):
            start = max(0, match.start() - 25)
            hits.append(Hit(
                location=location,
                phrase=rule.phrase,
                term=rule.term,
                quote=words[start:match.end() + 25],
            ))
    return hits


# -- The surfaces ------------------------------------------------------------


def _templates() -> list:
    return sorted(TEMPLATES.rglob("*.html"))


def _platform_glossary_entries() -> list:
    """``(term, definition)`` for every entry ``/help/glossary/`` serves.

    Read out of ``config/views.py`` with ``ast`` so the gate needs no request
    and no database. The same reading the domain gate does; copied rather than
    imported because a test module's private helper is not an interface.
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
        "config/views.py::glossary no longer assigns a `terms` dict literal, so "
        "the gate cannot see the platform glossary and would silently scan "
        "nothing. Fix the reader, do not delete the surface."
    )


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


def scan_repository(rules=RULES) -> list:
    """Every hit across all three surfaces, in a stable order."""
    hits = []
    for path in _templates():
        hits.extend(scan(path.read_text(encoding="utf-8"),
                         str(path.relative_to(REPO_ROOT)), rules))
    for term, definition in _platform_glossary_entries():
        hits.extend(scan(definition, f"config/views.py::glossary[{term}]", rules))
    for path, line, string in _help_text_strings():
        hits.extend(scan(string, f"{path}:{line} help_text", rules))
    return hits


# -- The ratchet -------------------------------------------------------------

#: **Strict zero for every rule, and it stays strict.** This differs from the
#: domain gate's ceilings on purpose: a definitional construction can occur
#: innocently in free prose, so that gate enumerates its survivors. A forbidden
#: phrase cannot occur innocently inside its scope. There is no legitimate
#: survivor to list, so there is nothing to ratchet down from and nothing to
#: raise. Observed RED at four sites against the v2.15 templates on 2026-09-06
#: before any template changed; green after the 136-01 sweep.
BASELINE: dict = {str(rule): 0 for rule in RULES}


def test_no_screen_uses_a_phrase_the_vocabulary_forbids():
    hits = scan_repository()
    by_rule = {}
    for hit in hits:
        by_rule.setdefault((hit.phrase, hit.term), []).append(hit)

    assert not hits, (
        f"{len(hits)} site(s) call a water quantity by a name DESIGN.md copy "
        "rule 12 forbids. Name each quantity once and the same way on every "
        "screen; the table between the vocabulary markers in DESIGN.md is the "
        "one list of names. Sites:\n  "
        + "\n  ".join(str(hit) for hit in hits)
    )


def test_every_rule_scopes_a_directory_that_exists():
    """A rule scoped to a typo'd path would silently scan nothing."""
    missing = [
        str(rule) for rule in RULES
        if rule.scope is not None and not (REPO_ROOT / rule.scope).is_dir()
    ]
    assert not missing, (
        "these DESIGN.md rule 12 entries name a template directory that does "
        "not exist, so the gate scans nothing for them: " + "; ".join(missing)
    )


def test_the_table_gates_the_four_sites_phase_136_measured():
    """The four phrases the red run named must stay in the table.

    A row quietly rewritten to `no gated phrase` would leave the gate green
    over the exact defect it was built for. Order is not asserted; presence is.
    """
    gated = {(rule.phrase, rule.scope) for rule in RULES}
    for expected in (
        ("Consumptive Use", "templates/surface/"),
        ("Surplus", "templates/parcels/"),
        ("debits", "templates/accounting/"),
        ("Allocation minus estimated consumptive use", None),
    ):
        assert expected in gated, (
            f"DESIGN.md rule 12 no longer gates {expected[0]!r} "
            f"{'anywhere' if expected[1] is None else 'in ' + expected[1]}. That "
            "phrase was one of the four Phase 136 measured red; restore the entry."
        )


# -- The controls ------------------------------------------------------------

PLANTED_HEADING = """\
<table class="data-table text-sm">
  <thead>
    <tr>
      <th>Month</th>
      <th class="th-right">Consumptive Use (AF)</th>
    </tr>
  </thead>
</table>
"""

#: The blind spot 118-02 recorded: the whole sentence is an include argument.
PLANTED_POPOUT = """\
<th class="th-right">Remaining (AF){% include "partials/_explainer_popout.html" with title="Remaining" text="Allocation minus estimated consumptive use. A negative number means the account is over budget." link=budgets_help_url %}</th>
"""

CSS_TOKEN_ONLY = """\
<td class="td-num text-surplus">12.00</td>
"""

CORRECT_NET_POPOUT = """\
<th class="th-right">Net (AF){% include "partials/_explainer_popout.html" with title="Net" text="Supplies minus estimated consumptive use for this account" link=wb_help_url %}</th>
"""

EMPTY_TABLE = """\
### 12. One vocabulary of water

<!-- vocabulary: begin -->
| Term | Means | Computed as | Never called |
|---|---|---|---|
<!-- vocabulary: end -->
"""

COMMENTED_OUT = """\
{% comment %}
  The footer used to read: credits and debits and net AF.
{% endcomment %}
<td>All entries</td>
"""


def test_the_gate_reports_a_planted_heading_in_a_surface_template():
    hits = scan(PLANTED_HEADING, "templates/surface/partials/_planted.html")
    phrases = {hit.phrase for hit in hits}

    assert "Consumptive Use" in phrases, (
        "the scanner missed a <th>Consumptive Use (AF)</th> under templates/surface/, "
        f"the exact heading ISS-153 was filed over. It reported {sorted(phrases)}"
    )


def test_the_gate_reads_inside_an_include_argument():
    hits = scan(PLANTED_POPOUT, "templates/accounting/partials/_planted.html")
    phrases = {hit.phrase for hit in hits}

    assert "Allocation minus estimated consumptive use" in phrases, (
        "the scanner cannot see the text= argument of an explainer popout, which "
        "is the blind spot 118-02 recorded for the domain gate and the site the "
        f"dashboard's Remaining column lived in. It reported {sorted(phrases)}"
    )


def test_the_gate_stays_silent_on_a_css_token():
    hits = scan(CSS_TOKEN_ONLY, "templates/parcels/partials/_planted.html")

    assert not hits, (
        "a class attribute carrying text-surplus was reported as the badge word: "
        f"{[str(hit) for hit in hits]}. Phrases are case-sensitive and word-bounded, "
        "and class= is stripped before scanning."
    )


def test_the_gate_stays_silent_on_correct_copy():
    hits = scan(CORRECT_NET_POPOUT, "templates/accounting/partials/_planted.html")

    assert not hits, (
        "the dashboard's Net popout, which is correct copy, was reported: "
        f"{[str(hit) for hit in hits]}. A gate with false positives on correct "
        "copy gets deleted rather than obeyed."
    )


def test_the_gate_stays_silent_on_a_phrase_outside_its_scope():
    """The dashboard's own `Consumptive Use (AF)` headers are the platform's
    headline term and stay. Only a surface template may not carry the phrase."""
    hits = scan(PLANTED_HEADING, "templates/accounting/partials/_planted.html")

    assert not hits, (
        "a phrase scoped to templates/surface/ was reported under "
        f"templates/accounting/: {[str(hit) for hit in hits]}"
    )


def test_the_gate_stays_silent_on_a_commented_out_phrase():
    hits = scan(COMMENTED_OUT, "templates/accounting/partials/_planted.html")

    assert not hits, (
        "a phrase inside a {% comment %} block was reported; comments are not "
        f"copy: {[str(hit) for hit in hits]}"
    )


def test_an_empty_table_fails_loudly():
    import pytest

    with pytest.raises(AssertionError, match="no rows"):
        load_rules(EMPTY_TABLE)


def test_a_row_with_no_readable_entry_fails_loudly():
    import pytest

    row = "| **Thing** | means | `x` | never the other thing |\n"
    with pytest.raises(AssertionError, match=NO_GATED_PHRASE):
        load_rules(EMPTY_TABLE.replace("<!-- vocabulary: end -->", row + "<!-- vocabulary: end -->"))
