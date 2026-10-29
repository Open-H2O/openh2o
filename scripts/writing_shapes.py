# SPDX-License-Identifier: AGPL-3.0-or-later
"""Count the sentence shapes struck in review that a machine can see.

Since 2026-10-09 the shapes struck in review are fixed everywhere. Seven shapes are named in DESIGN.md copy rule 15. Four of
them can be found by pattern, and this script counts those four:

- an em dash between two words, and a double hyphen used as one;
- the filler words actually, genuinely, really and simply;
- a heading made of two clauses joined by ", and what" (or who, how, where,
  why, when, which);
- a heading that ends in a trailing clause, ", by what" or ", by which";
- a stand-in the reader has to resolve ("that platform", "both are", "the
  former") where the name itself should be repeated;
- a district reader: a phrase that assumes whoever reads the page is a water
  district or agency ("your district", "a district can", "unless the
  district", "agency-wide");
- "California" said where a general statement works, outside the proper
  names in ``CALIFORNIA_NAMES``;
- "no" put on the object where "not" belongs on the verb ("sends no email"
  for "does not send email").

A phrase posing as a statement, a thing acting like a person and a slogan need
a reader. This script does not try to find them.

It reads three surfaces:

1. Every template under ``templates/``, the ``.html`` pages and the ``.txt``
   emails and messages, with comments and ``<style>`` removed, a
   ``{{ }}`` figure read as one word, and the text a reader sees in ``title``,
   ``placeholder``, ``aria-label`` and ``alt`` attributes kept. Words passed to
   a tag or filter that puts them on screen are read too: an included
   partial's ``text=`` and the like, ``{% source_label ... detail="..." %}``,
   the nouns of ``{% module_nouns %}``, and the argument of the ``default``,
   ``default_if_none``, ``blank`` and ``yesno`` filters.
   A ``<script>`` is read only for the string literals it passes to a call or
   assignment that puts words on screen (``textContent =``, ``innerHTML =``,
   ``alert(``, ``toast(``, ``setHTML(`` and the others in ``_JS_PROPERTY`` and
   ``_JS_CALL``) and for the markup a popup function returns; a sentence built
   from a variable alone is listed by ``script_words`` as unreadable.
2. String literals in every application Python file: each top-level package
   except ``tests``, outside its ``migrations``, ``management``, ``settings``
   and ``tests`` folders, less the files in ``NOT_SCREEN_PYTHON``, whose
   strings never reach a screen. Docstrings and strings passed to a logger are
   not read. A new importer or model is read the day it is added.
3. The public guides in ``GUIDES``, outside fenced code blocks.

It runs on the host with the standard library only, so it can be pointed at
an old version of a file. Usage::

    python3 scripts/writing_shapes.py                 # every surface, per file
    python3 scripts/writing_shapes.py --totals        # one line per surface
    python3 scripts/writing_shapes.py --as templates/about.html old_about.html
"""

from __future__ import annotations

import ast
import html
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"

#: Folders inside an application package whose strings are read in a
#: terminal or by the tests, never on a screen: management commands,
#: migrations, settings and an app's own tests.
NOT_APPLICATION_PARTS: tuple = ("migrations", "management", "settings", "tests")

#: Application Python files whose strings never reach a screen, each with its
#: reason. Every other application file is read. A file that puts even one
#: string on a screen stays read, and its terminal-only strings are listed in
#: the test's EXCEPTIONS, line by line. Measured 2026-10-20.
NOT_SCREEN_PYTHON: tuple = (
    ("core/checks.py", "Django system checks, printed by manage.py check and at start-up in a "
     "terminal or the container log; no view imports them."),
    ("core/domain_vocabulary.py", "the term list tests/test_domain_vocabulary.py checks the "
     "pages against; no view or template imports it."),
    ("core/operator_vocabulary.py", "the term list tests/test_operator_vocabulary.py checks the "
     "operator documents against; no view or template imports it."),
    ("core/water_vocabulary.py", "reads DESIGN.md's vocabulary table for "
     "tests/test_water_vocabulary.py; no view imports it."),
)

#: The public guides. Dated records in ``docs/`` (audits, proposals, ledgers)
#: say what was true on their date and are not guides, so they are not here.
GUIDES: tuple = (
    "CONTRIBUTING.md",
    "DEPLOY.md",
    "README.md",
    "SECURITY.md",
    "docs/AI-OPERATOR-GUIDE.md",
    "docs/DATA-IMPORT.md",
    "docs/DATA-STANDARDS.md",
    "docs/INSTALL-WITHOUT-DOCKER.md",
    "docs/README.md",
    "docs/ROADMAP.md",
    "docs/earth-engine-tier-setup.md",
    "docs/water-budget-terms.md",
)

#: Between two words of one run of text. A lone dash standing for "no value"
#: is a glyph, not a sentence, and is not counted.
EM_DASH = re.compile(r"[^\s—][^\S\n]*—[^\S\n]*(?=[^\s—])")
DOUBLE_HYPHEN = re.compile(r"\w[^\S\n]+--[^\S\n]+(?=\w)")
FILLER = re.compile(r"\b(?:actually|genuinely|really|simply)\b", re.I)
PAIRED_HEADING = re.compile(r",\s+and\s+(?:what|who|how|where|why|when|which)\b", re.I)
TRAILING_HEADING = re.compile(r",\s+by\s+(?:what|which)\b", re.I)
#: A stand-in for a name the reader has to resolve: "that platform", "both
#: are", "the former". "That platform's code" and "Both are released
#: under..." were struck on About (2026-10-10): name the thing again instead. Replayed before installing: it flags both struck
#: lines in About's history. Some hits are plain English ("two reasons, and
#: both are good ones"), so a hit is a line to read, not an automatic fault.
STAND_IN = re.compile(
    r"\b(?:that|those|said) (?:platform|system|software|project|tool|method|code|program"
    r"|agency|page)s?\b|\bboth (?:are|were|use|run|have)\b|\bthe (?:former|latter)\b", re.I)

#: A phrase that puts the reader in a water district or agency. OpenH2O is
#: meant to be used nationally, and some of its users are growers or ditch
#: tenders rather than districts (2026-10-11). Rewrite the whole sentence about
#: the thing itself ("the land your records cover", approved 2026-10-18); an
#: actor put in front of the old words ("An administrator can instead ...") was
#: struck on 2026-10-18 18:35. A district or
#: agency that is a real thing in the water world, and not the reader, does not
#: match: "the regulating agency", "the primacy agency", "a GSA" under SGMA, "an
#: irrigation district" as one kind of supplier, "the agency that regulates it".
#: Replayed against f4b18da before it was installed.
DISTRICT_READER = re.compile(
    r"\b(?:your|our|this) (?:district|agency|gsa)\b"
    r"|\b(?:an?|the) (?:water |groundwater )?(?:district|agency)\b(?!\s+that\s+regulates)"
    r"|\bagency[- ](?:wide|default|boundary)\b"
    r"|\bdistrict (?:name|water balance|total)\b"
    r"|\b(?:one|another) (?:district|agency)\b|\bagency-drawn\b|\bper-agency\b"
    r"|\bthe whole agency\b|\bfor districts and agencies\b|@district\.gov|\bmy[- ]gsa\b",
    re.I)

#: Phrases where "the agency" is the regulating agency of a water system, read
#: out of a lab file, and not the reader. Removed before DISTRICT_READER counts.
DISTRICT_ENTITY: tuple = (
    (r"a groundwater agency's published table", "names the efficiency table's publisher, not the reader (2026-10-12)"),
    (r"records the agency on the water system", "the lab file's regulating agency, not the reader (2026-10-15)"),
    (r"a groundwater agency's or a county's", "a local registry's keeper, not the reader (2026-10-11)"),
    (r"one organization: a district, an agency, a farm or a ditch company", "the kinds of organization a site serves, not the reader (2026-10-11)"),
    (r"A water agency or district running OpenH2O", "who needs Earth Engine's paid license, not the reader (2026-10-17)"),
)
_DISTRICT_KEPT = re.compile("|".join(f"(?:{phrase})" for phrase, _ in DISTRICT_ENTITY), re.I)


def district_reader_count(text: str) -> int:
    """Each phrase in ``text`` that assumes the reader is a district or agency."""
    return len(DISTRICT_READER.findall(_DISTRICT_KEPT.sub(" ", text)))

#: "California" where it names a real thing and stays, one reason each. Every
#: other "California" is a general statement written for one state, and is
#: counted. ``tests/test_writing_shapes.py`` fails on an entry no surface uses.
CALIFORNIA_NAMES: tuple = (
    (r"California Water Data Consortium", "the organization that oversees the earlier platform"),
    (r"California Water Accounting, Tracking, and Reporting System", "CalWATRS spelled out"),
    (r"California Data Exchange Center", "CDEC spelled out"),
    (r"California Irrigation Management Information System", "CIMIS spelled out"),
    (r"California Nevada River Forecast Center", "CNRFC spelled out"),
    (r"California Department of Water Resources", "DWR spelled out"),
    (r"California.s Environmental Laboratory Accreditation Program", "ELAP spelled out"),
    (r"California's program for accrediting laboratories", "ELAP is a California program"),
    (r"California's 2014 law under which GSAs manage", "SGMA is a California law"),
    (r"In California, the \**Sustainable Groundwater Management Act", "SGMA spelled out (2026-10-17)"),
    (r"California DDW", "DDW is California's Division of Drinking Water"),
    (r"California.s Division of Drinking Water", "DDW spelled out"),
    (r"California Central Valley Groundwater Surface Water Simulation", "C2VSim spelled out"),
    (r"California.s SDWIS format", "the lab file layout is California's Division of Drinking Water's (2026-10-14)"),
    (r"California.s Water Use Reported export", "the State Water Board's published diversion file (2026-10-14)"),
    (r"SDWIS4 file holds every water system in California", "the Division of Drinking Water's file covers the state's systems (2026-10-14)"),
    (r"California.s Electronic\s+Annual\s+Report", "the eAR is California's report (2026-10-14)"),
    (r"open up California's water data", "the Consortium's purpose, in its own terms"),
    (r"so the wizard finds none outside California", "the Setup Wizard's subbasin and parcel sources cover one state (2026-10-18)"),
    (r"California water system", "a PS Code is built from the PWSID only in California's format; another state's code is typed as the lab file has it"),
    (r"California PS Code", "the same: only California's PS Codes begin with the PWSID"),
    (r"California's reporting format", "the state's own format, the approved name for it (2026-10-12: \"California's reporting format, not layout\")"),
)
CALIFORNIA = re.compile(r"\bCalifornia\b")
_CALIFORNIA_KEPT = re.compile("|".join(f"(?:{name})" for name, _ in CALIFORNIA_NAMES))


def california_count(text: str) -> int:
    """Each "California" in ``text`` outside a name in ``CALIFORNIA_NAMES``."""
    return len(CALIFORNIA.findall(_CALIFORNIA_KEPT.sub(" ", text)))


#: Three habits struck in the README on 2026-10-17 ("A new installation holds
#: none of your records."), replayed before they were installed against past
#: review rulings: 222 struck sentences and 1,270 approved ones. A statement of
#: intent or reassurance hit 7 struck and 0 approved; a negation frame hit 18
#: struck (8.1%) and 13 approved (1.0%); a bolded verdict sentence hit the
#: struck README 3 times and nothing approved. A ", so" ending hit 5.9% struck
#: and 3.5% approved, too close to separate, so it is not counted.
REASSURANCE = re.compile(
    r"\b(?:deliberate(?:ly)?|on purpose|intentional(?:ly)?|by design|fully supported"
    r"|nothing has gone wrong|is not a (?:fault|bug|failure))\b", re.I)
NEGATION_FRAME = re.compile(
    r"\b(?:rather than|instead of|none of|nothing (?:has|is|to do)|never (?:makes|has|is))\b"
    r"|, not (?:a |an |the |for |only )|\bnot [a-z]+, but\b", re.I)
#: "can instead" listing the alternatives to a default ("An administrator can
#: instead show it as a separate line ..."), struck 2026-10-18 18:35 ("bad AI
#: grammar"). Replayed before it was installed against 247 struck and 1,321
#: approved sentences: 2 struck, 1 approved (the 2026-10-10 wording of the
#: same sentence, struck in place today). Name the choices, or say what the
#: default is and what else is possible, without an actor and "can instead".
#: The broader "verb + no + noun" check replayed beside it is NO_FOR_NOT below.
CAN_INSTEAD = re.compile(r"\bcan (?:choose )?instead\b", re.I)
#: A paragraph that opens with a whole sentence in bold, announcing a verdict
#: before the facts ("**A new installation holds none of your records.**").
BOLD_VERDICT = re.compile(r"^\*\*[^*]{8,}[.]\*\*")

#: "No" put on the object where plain English puts "not" on the verb: "This
#: site sends no email." for "This site does not send email." Struck on
#: 2026-10-18 ("names no real water district", "changes no figure") and on
#: 2026-10-20 ("sends no email"). Replayed on 2026-10-20 before it was
#: installed, against 72 struck and 767 approved sentences: it hits the three
#: struck for it and one of the 39 account sentences approved that morning
#: (the same "sends no email"). Its 25 approved hits are this shape too,
#: approved between 2026-10-10 and 2026-10-18 before it was struck, which is
#: why the 2026-10-18 replay did not separate. The word before "no" has to be
#: the verb, so be, have, "there", a preposition or conjunction, an -ly word
#: and "almost" are skipped, and so is "images" ("remove images no container
#: uses" is a relative clause). "No one", "no longer" and "no more" are plain
#: English. "has no", "with no" and "there is no" are left to a reader.
NO_FOR_NOT = re.compile(r"\b([A-Za-z]+)[^\S\n]+no[^\S\n]+([A-Za-z]+)")
_NOT_THE_VERB = frozenset({
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "there", "with", "of",
    "to", "by", "in", "for", "at", "and", "or", "if", "that", "on", "as", "but", "when",
    "because", "so", "where", "whether", "while", "means", "yes", "almost", "images"})
_NOT_THE_OBJECT = frozenset({
    "one", "longer", "more", "less", "later", "earlier", "sooner", "matter", "other", "fewer"})


def no_for_not_count(text: str) -> int:
    """Each "verb no noun" in ``text`` where "not" belongs on the verb."""
    return sum(
        1 for m in NO_FOR_NOT.finditer(text)
        if not (m.group(1).lower() in _NOT_THE_VERB or m.group(1).lower().endswith("ly")
                or m.group(2).lower() in _NOT_THE_OBJECT))


SHAPES: tuple = ("em dash", "double hyphen", "filler", "paired heading", "trailing heading",
                 "stand-in", "district reader", "California", "reassurance", "negation frame",
                 "bold verdict", "can instead", "no for not")


# -- Templates ----------------------------------------------------------------

_NOT_COPY = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<script.*?</script>", re.S),
    re.compile(r"<style.*?</style>", re.S),
    # A block whose name ends in ``_class`` holds CSS class names (``page_head_class``).
    re.compile(r"\{%\s*block\s+\w+_class\s*%\}.*?\{%\s*endblock\b[^%]*%\}", re.S),
)
_SEEN_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)\"""")
#: Any attribute up to its value so far, to tell which attribute a filter sits in.
_OPEN_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["'][^"']*$""")
#: Tags that sit inside a sentence. Every other tag ends a run of text.
_INLINE = re.compile(
    r"</?(?:a|abbr|b|bdi|cite|code|data|dfn|em|i|kbd|mark|q|s|small|span|strong"
    r"|sub|sup|time|u|var|wbr)\b[^>]*>", re.I)
_TOUCHING = re.compile(r"(</[a-z]+\s*>)(?=<(?:a|abbr|b|bdi|cite|code|data|dfn|em|i|kbd|mark|q|s|small|span|strong|sub|sup|time|u|var)\b)", re.I)
#: An alternative arm of an if or for tag, or a block's start or end, starts a new run of text.
_BRANCH = re.compile(r"\{%\s*(?:elif|else|empty|block|endblock)\b.*?%\}", re.S)
_HEADING_TAG = re.compile(r"<(h[1-6]|summary|legend|caption)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
_TITLE_BLOCK = re.compile(
    r"\{%\s*block\s+(?:title|head_title|page_title|page_heading|heading)\s*%\}(.*?)"
    r"\{%\s*endblock", re.S)
_INCLUDE = re.compile(r"\{%\s*include\b(.*?)%\}", re.S)
#: The include arguments that carry words onto the screen.
_INCLUDE_ARG = re.compile(
    r"""\b(?:text|title|label|link_label|add_label|what)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
#: Words handed to a filter that prints them when the value is empty
#: (``|default:"Not stated"``, ``|blank:"None on file"``, ``|yesno:"Yes,No"``).
_FILTER_WORDS = re.compile(
    r"""\|\s*(?:default|default_if_none|blank|yesno)\s*:\s*(?:"([^"]*)"|'([^']*)')""")
#: ``{% source_label "GAMA" detail="..." %}`` prints its detail beside the label.
_SOURCE_DETAIL = re.compile(
    r"""\{%\s*source_label\b[^%]*?\bdetail\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.S)
#: ``{% module_nouns "wells:wells" "parcels:use areas" %}`` joins the nouns of
#: the switched-on modules into one phrase.
_MODULE_NOUNS = re.compile(r"\{%\s*module_nouns\b(.*?)%\}", re.S)
_MODULE_NOUN = re.compile(r"""(?:"[\w.]+:([^"]*)"|'[\w.]+:([^']*)')""")


def _strip_not_copy(source: str) -> str:
    for pattern in _NOT_COPY:
        source = pattern.sub(" ", source)
    return source


def include_arguments(source: str) -> list:
    """The words passed into included partials, comments removed first."""
    found = []
    for tag in _INCLUDE.finditer(_strip_not_copy(source)):
        for match in _INCLUDE_ARG.finditer(tag.group(1)):
            words = html.unescape(match.group(1) if match.group(1) is not None else match.group(2))
            if re.search(r"[A-Za-z]", words):
                found.append(" ".join(words.split()))
    return found


def _unread_attribute(source: str, at: int) -> bool:
    """True when position ``at`` sits inside the value of an attribute no reader sees
    (``autocomplete="{{ x|default:'new-password' }}"``)."""
    tag_start = source.rfind("<", 0, at)
    if tag_start < source.rfind(">", 0, at):
        return False
    opened = _OPEN_ATTR.search(source[tag_start:at])
    return bool(opened) and opened.group(1).lower() not in {"title", "placeholder", "aria-label", "alt"}


def tag_arguments(source: str) -> list:
    """The words passed to the filters and tags above, comments removed first."""
    source = _strip_not_copy(source)
    found = []
    matches = [*_FILTER_WORDS.finditer(source), *_SOURCE_DETAIL.finditer(source)]
    for tag in _MODULE_NOUNS.finditer(source):
        matches.extend(_MODULE_NOUN.finditer(tag.group(1)))
    for match in matches:
        if _unread_attribute(source, match.start()):
            continue
        words = html.unescape(match.group(1) if match.group(1) is not None else match.group(2))
        if re.search(r"[A-Za-z]", words):
            found.append(" ".join(words.split()))
    return found


# -- Words a page script prints -------------------------------------------------

#: Comments and tags that carry no script, blanked in place so a line number survives.
_BLANKED = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"\{%.*?%\}", re.S),
)
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
_VARIABLE = re.compile(r"\{\{.*?\}\}", re.S)
#: A template variable inside a script, kept the same length as it was.
_HOLE = "\x01"
#: A property a script assigns words to.
_JS_PROPERTY = re.compile(
    r"\.(textContent|innerText|innerHTML|outerHTML|title|placeholder|text|alt)\s*(\+?=)(?![=>])")
#: A call whose first argument is words for the screen.
_JS_CALL = re.compile(r"(?<![\w$])(alert|confirm|prompt|toast|showToast|setHTML|setText|setCoordText|showCoordWarning)\s*\(")
#: A call whose second argument is words for the screen.
_JS_ATTRIBUTE = re.compile(
    r"""\.setAttribute\s*\(\s*(['"])(?:aria-label|title|placeholder|alt)\1\s*,""")
_JS_INSERT = re.compile(r"\.insertAdjacentHTML\s*\(\s*[^,()]+,")
#: A function that builds a popup or a fragment hands it back, or keeps it in a variable.
_JS_RETURN = re.compile(r"(?<![\w$.])return\b")
_JS_ASSIGN = re.compile(r"(?<![\w$])[\w$]+\s*\+?=(?![=>])")
#: Variables a script keeps words in before it prints them (``hint = n + ' corners placed'``).
_JS_WORD_NAMES = {"hint", "text", "message", "msg", "caption", "warning", "html", "info", "label"}
_HTML_LITERAL = re.compile(r"<[A-Za-z]")
_ALTERNATIVES = ("||", "&&", "??", "?", ":")
_COMPARISON = re.compile(r"[=!]==?|[<>]=?|\binstanceof\b|\bin\b")


def _blank(match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _string_end(source: str, at: int) -> int:
    """Index just past the string literal that opens at ``at``."""
    quote = source[at]
    i = at + 1
    while i < len(source):
        if source[i] == "\\":
            i += 2
            continue
        if source[i] == quote:
            return i + 1
        if source[i] == "\n" and quote != "`":
            return i
        i += 1
    return len(source)


def _mask_comments(js: str) -> str:
    """The script with its ``//`` and ``/* */`` comments blanked."""
    out = list(js)
    i = 0
    while i < len(js):
        char = js[i]
        if char in "'\"`":
            i = _string_end(js, i)
        elif js.startswith("//", i):
            end = js.find("\n", i)
            end = len(js) if end < 0 else end
            out[i:end] = " " * (end - i)
            i = end
        elif js.startswith("/*", i):
            end = js.find("*/", i + 2)
            end = len(js) if end < 0 else end + 2
            out[i:end] = [" " if c != "\n" else c for c in js[i:end]]
            i = end
        else:
            i += 1
    return "".join(out)


def _expression_end(js: str, start: int, argument: bool) -> int:
    """Index where the expression that begins at ``start`` ends: a ``;`` at depth 0, a closing
    bracket that was never opened, or (for a call argument) the ``,`` that ends the argument."""
    depth = 0
    i = start
    while i < len(js):
        char = js[i]
        if char in "'\"`":
            i = _string_end(js, i)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and (char == ";" or (argument and char == ",")):
            return i
        i += 1
    return len(js)


def _split_top(expr: str, separators: tuple) -> list:
    """``expr`` cut at every separator that sits outside strings and brackets."""
    pieces, depth, last, i = [], 0, 0, 0
    while i < len(expr):
        char = expr[i]
        if char in "'\"`":
            i = _string_end(expr, i)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth == 0:
            for sep in separators:
                if expr.startswith(sep, i):
                    if sep == "?" and (expr[i + 1:i + 2] == "." or expr[i + 1:i + 2] == "?"):
                        continue
                    if sep == "+" and (expr[i + 1:i + 2] == "+" or expr[i - 1:i] == "+"):
                        continue
                    pieces.append(expr[last:i])
                    i += len(sep) - 1
                    last = i + 1
                    break
        i += 1
    pieces.append(expr[last:])
    return pieces


def _is_condition(piece: str) -> bool:
    """True when the piece compares things at depth 0, so its strings are not shown."""
    skeleton, depth, i = [], 0, 0
    while i < len(piece):
        char = piece[i]
        if char in "'\"`":
            i = _string_end(piece, i)
            skeleton.append("\x02")
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth == 0:
            skeleton.append(char)
        i += 1
    return bool(_COMPARISON.search("".join(skeleton)))


def _unescape(literal: str) -> str:
    body = literal[1:-1] if len(literal) > 1 and literal[-1] == literal[0] else literal[1:]
    body = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), body)
    body = re.sub(r"\$\{[^}]*\}", " " + _HOLE + " ", body) if literal[0] == "`" else body
    return re.sub(r"\\(.)", r"\1", body)


def _js_alternatives(expr: str) -> tuple:
    """``(runs of words, held variable words)`` an expression can put on screen.

    The expression is cut at ``?``, ``:``, ``||``, ``&&`` and ``??`` into the values it can take;
    a piece that compares things is a condition and shows nothing. Each value is a chain joined by
    ``+``: a string literal is read, a parenthesised group is read the same way, and anything else
    (a name, a call, a property) is a variable, written ``X`` in the run it sits in."""
    runs, variable = [], False
    for alternative in _split_top(expr, _ALTERNATIVES):
        alternative = alternative.strip()
        if not alternative or _is_condition(alternative):
            continue
        text, literal = [], False
        for operand in _split_top(alternative, ("+",)):
            operand = operand.strip()
            if not operand:
                continue
            if operand[0] in "'\"`" and _string_end(operand, 0) == len(operand):
                text.append(_unescape(operand))
                literal = True
            elif operand[0] == "(" and operand[-1] == ")":
                inner, held = _js_alternatives(operand[1:-1])
                variable = variable or held
                if len(_split_top(operand[1:-1], _ALTERNATIVES)) == 1 and len(inner) == 1:
                    text.append(inner[0])
                    literal = True
                else:
                    runs.extend(inner)
                    text.append(_HOLE)
            else:
                text.append(_HOLE)
                variable = True
        if literal:
            runs.append(" ".join("".join(text).split()))
    return runs, variable


def _script_runs(text: str) -> list:
    return [run for run in _runs(re.sub(_HOLE + "+", " X ", text)) if re.search(r"[A-Za-z]{2}", run.replace("X", ""))]


def script_words(source: str) -> tuple:
    """``(found, unreadable)`` for the ``<script>`` blocks of a template.

    ``found`` is ``[(line, kind, [run, ...]), ...]``: each string literal a script passes to a call or
    assignment that puts words on screen (``textContent =``, ``innerHTML =``, ``alert(``, ``toast(``
    and the others named above), and each HTML fragment it builds. ``unreadable`` is
    ``[(line, kind, expression), ...]``: a sink whose words are all variables, which nothing here
    can read."""
    for pattern in _BLANKED:
        source = pattern.sub(_blank, source)
    found, unreadable = [], []
    for block in _SCRIPT_BLOCK.finditer(source):
        start = block.start(1)
        js = _VARIABLE.sub(lambda m: _HOLE * len(m.group(0)), block.group(1))
        js = _mask_comments(js)
        seen = set()
        candidates = []
        for pattern, kind in ((_JS_PROPERTY, None), (_JS_CALL, None), (_JS_ATTRIBUTE, "attribute"),
                              (_JS_INSERT, "insertAdjacentHTML")):
            for match in pattern.finditer(js):
                name = kind or match.group(1)
                if pattern is _JS_CALL and js[:match.start()].rstrip().endswith("function"):
                    continue
                is_call = pattern is not _JS_PROPERTY
                candidates.append((match.end(), name, is_call, 2))
        for pattern, name in ((_JS_RETURN, "return"), (_JS_ASSIGN, "assignment")):
            for match in pattern.finditer(js):
                target = re.match(r"[\w$]+", match.group(0))
                mode = 1 if name == "assignment" and target.group(0) in _JS_WORD_NAMES else 0
                candidates.append((match.end(), name, False, mode))
        for at, kind, is_call, certain in sorted(candidates, key=lambda c: (c[0], -c[3])):
            if at in seen:
                continue
            seen.add(at)
            end = _expression_end(js, at, is_call)
            expr = js[at:end]
            runs, variable = _js_alternatives(expr)
            literals = [m for m in _split_top(expr, ("+", "||", "&&", "?", ":")) if m.strip()[:1] in "'\"`"]
            if certain == 0 and not any(_HTML_LITERAL.search(piece) for piece in literals):
                continue
            line = source.count("\n", 0, start + at) + 1
            words = [run for text in runs for run in _script_runs(text)]
            if words:
                found.append((line, kind, words))
            elif variable and certain == 2:
                unreadable.append((line, kind, " ".join(expr.split())))
    return found, unreadable


def script_arguments(source: str) -> list:
    """The words the ``<script>`` blocks of a template put on screen, one run each."""
    return [run for _line, _kind, words in script_words(source)[0] for run in words]


def _runs(source: str) -> list:
    """Template source (comments already gone) as the runs of text it shows."""
    source = " ".join(source.split())
    source = re.sub(r"\{\{.*?\}\}", " X ", source, flags=re.S)
    source = _BRANCH.sub("\n", source)
    source = re.sub(r"\{%.*?%\}", " ", source, flags=re.S)
    attributes = []

    def pull(match):
        attributes.append(match.group(1))
        return ""

    # An attribute's words are a run of their own, after the text; the tag stays whole.
    source = _SEEN_ATTR.sub(pull, source)
    # An inline tag joins its words as the browser does: Open<span>H2O</span> is OpenH2O.
    # Two inline tags touching (</span><b>) are a label and its value, kept apart.
    source = _TOUCHING.sub(r"\1 ", source)
    source = _INLINE.sub("", source)
    source = re.sub(r"<[^>]*>", "\n", source)
    runs = (" ".join(html.unescape(run).split()) for run in [*source.split("\n"), *attributes])
    return [run for run in runs if run]


def template_text(source: str) -> tuple:
    """``(runs, headings)``: every run of text a template shows, and its headings."""
    original = source
    source = _strip_not_copy(source)
    headings = []
    for match in _TITLE_BLOCK.finditer(source):
        headings.append(" ".join(_runs(match.group(1))))
    for match in _HEADING_TAG.finditer(source):
        headings.append(" ".join(_runs(match.group(2))))
    runs = _runs(source) + include_arguments(source) + tag_arguments(source)
    runs += script_arguments(original)
    return runs, [h for h in headings if h]


def email_text(source: str) -> tuple:
    """``(runs, [])`` for a ``.txt`` template: each line of the email is a run."""
    runs = []
    for line in _strip_not_copy(source).splitlines():
        runs.extend(_runs(line))
    return runs + tag_arguments(source), []


# -- Python -------------------------------------------------------------------

_LOGGERS = {"logger", "log", "logging", "LOGGER", "_logger", "_log"}


def python_strings(source: str) -> list:
    """String literals in a Python source, without docstrings or logger arguments."""
    tree = ast.parse(source)
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in _LOGGERS):
            for inner in ast.walk(node):
                skip.add(id(inner))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in skip]


# -- Guides -------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")


_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")


def guide_text(source: str) -> tuple:
    """``(blocks, headings)`` of a Markdown guide, outside fenced code blocks.

    Lines wrapped inside one paragraph or list item are joined, so a dash at
    the end of a line is read between the words on either side of it. A
    table row is split into its cells, so a dash standing alone in a cell (a
    cell with no value) is not read as joining its neighbours.
    """
    blocks, headings, fence = [], [], None
    current: list = []

    def close():
        if current:
            blocks.append(" ".join(current))
            current.clear()

    for line in source.splitlines():
        marker = _FENCE.match(line)
        if marker:
            close()
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1) == fence:
                fence = None
            continue
        if fence is not None:
            continue
        stripped = line.strip()
        while stripped.startswith(">"):
            stripped = stripped[1:].strip()
        if not stripped:
            close()
        elif stripped.startswith("#"):
            close()
            headings.append(stripped.lstrip("#").strip())
            blocks.append(headings[-1])
        elif stripped.startswith("|"):
            close()
            blocks.extend(cell.strip() for cell in stripped.strip("|").split("|"))
        else:
            if _LIST_ITEM.match(stripped):
                close()
            current.append(stripped)
    close()
    return [block for block in blocks if block], headings


# -- Counting -----------------------------------------------------------------

def count(runs: list, headings: list) -> dict:
    """``{shape: n}`` over runs of text and the headings among them."""
    text = "\n".join(runs)
    return {
        "em dash": len(EM_DASH.findall(text)),
        "double hyphen": len(DOUBLE_HYPHEN.findall(text)),
        "filler": len(FILLER.findall(text)),
        "paired heading": sum(1 for h in headings if PAIRED_HEADING.search(h)),
        "trailing heading": sum(1 for h in headings if TRAILING_HEADING.search(h)),
        "stand-in": len(STAND_IN.findall(text)),
        "district reader": district_reader_count(text),
        "California": california_count(text),
        "reassurance": len(REASSURANCE.findall(text)),
        "negation frame": len(NEGATION_FRAME.findall(text)),
        "bold verdict": sum(1 for run in runs if BOLD_VERDICT.match(run)),
        "can instead": len(CAN_INSTEAD.findall(text)),
        "no for not": no_for_not_count(text),
    }


def file_text(rel: str, source: str) -> tuple:
    """``(runs, headings)`` for one file's source, read as the surface its path names."""
    if rel.endswith(".html"):
        return template_text(source)
    if rel.endswith(".txt"):
        return email_text(source)
    if rel.endswith(".py"):
        return python_strings(source), []
    if rel.endswith(".md"):
        return guide_text(source)
    raise ValueError(f"no surface reads {rel}")


def count_file(rel: str, source: str) -> dict:
    """``{shape: n}`` for one file's source, read as the surface its path names."""
    return count(*file_text(rel, source))


def screen_python(root: Path = REPO_ROOT) -> list:
    """Every application Python file outside ``NOT_APPLICATION_PARTS`` and ``NOT_SCREEN_PYTHON``."""
    not_screen = {rel for rel, _reason in NOT_SCREEN_PYTHON}
    found = []
    for package in sorted(p.parent for p in root.glob("*/__init__.py")):
        if package.name == "tests":
            continue
        for path in package.rglob("*.py"):
            rel = path.relative_to(root)
            if set(rel.parts[1:-1]) & set(NOT_APPLICATION_PARTS) or str(rel) in not_screen:
                continue
            found.append(str(rel))
    return sorted(found)


def surfaces(root: Path = REPO_ROOT) -> dict:
    """``{surface: [relative path, ...]}`` for every file this script reads."""
    templates = sorted(
        str(p.relative_to(root)) for pattern in ("*.html", "*.txt")
        for p in (root / "templates").rglob(pattern))
    return {
        "templates": templates,
        "screen python": screen_python(root),
        "guides": [p for p in GUIDES if (root / p).exists()],
    }


def measured(root: Path = REPO_ROOT) -> dict:
    """``{relative path: {shape: n}}`` for every file carrying at least one shape."""
    out = {}
    for files in surfaces(root).values():
        for rel in files:
            counts = {k: v for k, v in count_file(rel, (root / rel).read_text()).items() if v}
            if counts:
                out[rel] = counts
    return out


def main(argv: list) -> int:
    if argv[:1] == ["--as"]:
        rel, path = argv[1], argv[2]
        source = sys.stdin.read() if path == "-" else Path(path).read_text()
        counts = count_file(rel, source)
        print(f"{rel} (read from {path}): " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        if rel.endswith(".html"):
            for heading in template_text(source)[1]:
                if PAIRED_HEADING.search(heading) or TRAILING_HEADING.search(heading):
                    print(f"  heading: {heading}")
        return 0
    found = measured()
    by_file = {rel: surface for surface, files in surfaces().items() for rel in files}
    totals = {surface: dict.fromkeys(SHAPES, 0) for surface in surfaces()}
    for rel, counts in found.items():
        for shape, n in counts.items():
            totals[by_file[rel]][shape] += n
    if "--totals" not in argv:
        for rel, counts in found.items():
            print(f"{rel}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for surface, counts in totals.items():
        print(f"TOTAL {surface}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
