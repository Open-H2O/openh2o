# SPDX-License-Identifier: AGPL-3.0-or-later
"""One name per thing, and "not" on the verb, in the words a reader sees.

``scripts/writing_shapes.py`` counts "no" put on the object ("sends no email")
but skips "no one", "nobody" and "no" after a preposition ("to no field"), so
"Credited to no one" stood beside "Not credited to anyone" on two screens
(Brent's strike, ruling 57). The 151.8-03 sweep measured the screens on
2026-10-31 (``151.8-work/language-sweep-measured.md``): 24 sentences in 13 files
put "no" on the object, 6 sentences named a page by another page's name ("the
field's page", "the canal's headgate page"), 11 places said "Log in" or
"login" where the pair is Sign in and Sign out, 8 buttons and titles said
"New" or "Create" where the majority says "Add", and about 170 sentences
called the use area a "field". Two screens named three settings differently
(Delivery Settings against Settings explained), and the Settings row
"Methodology" opened a page titled "Methodology Settings".

This module keeps those fixed. It reads screen words only: every template and
every application Python file ``writing_shapes`` reads (``surfaces()``,
``template_text()``, ``email_text()``, ``python_strings()``, less
``NOT_SCREEN_PYTHON``), never the guides. The copy rule it keeps is "not" on the
verb (DESIGN.md copy rule 15) and one name per thing (copy rule 4: a control
or a sentence that names a page carries that page's name).

1. **"No" on the object** that ``NO_FOR_NOT`` misses: "no one", "nobody", and a
   preposition before "no". Zero.
2. **Retired page references**: "the field's page", "headgate page". Zero.
3. **Sign in**, in templates: no "Log in", "log in" or "login". Zero.
4. **A new-record page and its button say "Add"**: no page title starting
   "New " or "Create ", no "+ New" button. Zero outside ``EXCEPTIONS``.
5. **"Field" meaning the record** is "use area" (ruling 59, 2026-10-31 17:36).
   ``FIELD_WORD_KEPT`` holds, per file, the uses that mean land outside the
   record or a data field; it may only fall.
6. **Setting names agree**: each heading on the Delivery Settings page is a
   name in the Delivery Settings table on Settings explained.
7. **A Settings row carries its page's name**: the row label is the title of
   the page it opens, or begins it before a colon ("Setup wizard: Boundary").

A test never mandates a domain description (CLAUDE.md). These checks only forbid
retired words and require two screens to agree.

**Kill switch:** ``OPENH2O_SCREEN_WORDS_CHECK=0`` skips this module.
"""
from __future__ import annotations

import functools
import importlib.util
import os
import re
from html import unescape
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import screen_words as words

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_SCREEN_WORDS_CHECK", "1") == "0",
    reason="OPENH2O_SCREEN_WORDS_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "writing_shapes.py"


def _load():
    if not SCRIPT.exists():
        pytest.fail(f"{SCRIPT} is missing; update SCRIPT if it moved.")
    spec = importlib.util.spec_from_file_location("writing_shapes_for_screen_words", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shapes = _load()

#: Per file, how many "field" words stay because they mean land outside the
#: record (the demonstration page's crop-map outlines) or a data field. It was
#: empty when the guard was written, so every file still using "field" for the
#: record failed (222 hits in 36 files); after the sweep only the files below
#: keep the word, each with its reason. A ceiling may fall and never rise; an
#: entry above the file's count fails.
FIELD_WORD_KEPT: dict = {
    # The public records the demonstration was built from: the crop map's field
    # outlines, the basin's canals and fields, and the ET and rainfall estimated
    # on each of them. Land outside the record, measured 2026-10-31.
    "templates/about_demonstration_data.html": 5,
    # "Field outlines": the outlines in the person's own file, before any of
    # them is a use area (the heading Brent approved on the drawing, ruling 70).
    "templates/parcels/use_area_import.html": 1,
}

#: Titles that start "New " or "Create " and are not a new record, one reason
#: each: (template path, the title's first words, reason).
EXCEPTIONS: tuple = (
    ("templates/account/signup.html", "Create account",
     "a person signing up makes their own sign-in, which is not a record an Add page makes; "
     "kept (151.8-03)"),
)


# -- Reading screen words, with line numbers ----------------------------------------

#: Between two words of one source line: whitespace, a tag, a template tag or a quote.
_BETWEEN = r"(?:\s|<[^>]*>|\{\{[^}]*\}\}|\{%[^%]*%\}|\{#[^#]*#\}|[\"'])*"
_QUOTES = r"(?:'|’|&#x27;|&#39;|&rsquo;|&apos;)"


def _flexible(text: str) -> str:
    """A pattern that finds ``text``'s words in source, across tags and line breaks."""
    pieces = []
    for word in text.split():
        if word == "X":
            pieces.append(r"(?:\{\{[^}]*\}\}|X)")
        else:
            pieces.append(re.sub("'", lambda _m: _QUOTES, re.escape(word.replace(chr(0x2019), "'"))))
    return _BETWEEN.join(pieces)


class _Place:
    """Finds the source line of a hit, once per hit, so repeats walk down the file."""

    def __init__(self, source: str, first_line: int = 1):
        self.source = source
        self.used: set = set()
        self.first_line = first_line

    def line(self, run: str, start: int, end: int) -> str:
        before = run[:start].split()[-3:]
        after = run[end:].split()[:2]
        inside = run[start:end]
        for context in (" ".join([*before, inside, *after]), " ".join([*before, inside]), inside):
            try:
                found = [m for m in re.finditer(_flexible(context), self.source, re.S)
                         if m.start() not in self.used]
            except re.error:
                continue
            if found:
                self.used.add(found[0].start())
                where = found[0].start() + found[0].group(0).find(inside.split()[0])
                return str(self.first_line + self.source.count("\n", 0, max(where, 0)))
        return "?"


def _python_nodes(source: str) -> dict:
    """``{string value: [(first line, last line), ...]}`` for the strings ``python_strings`` reads."""
    import ast

    wanted: dict = {}
    for value in shapes.python_strings(source):
        wanted[value] = wanted.get(value, 0) + 1
    where: dict = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and wanted.get(node.value):
            wanted[node.value] -= 1
            where.setdefault(node.value, []).append((node.lineno, node.end_lineno))
    return where


def _screen_files() -> list:
    found = shapes.surfaces()
    return [*found["templates"], *found["screen python"]]


@functools.lru_cache(maxsize=None)
def _read(rel: str) -> tuple:
    """``(source, screen-word runs, Python string positions or None)`` of one file, read once."""
    source = (REPO_ROOT / rel).read_text()
    return source, shapes.file_text(rel, source)[0], (_python_nodes(source) if rel.endswith(".py") else None)


def _hits(rel: str, pattern: str, skip=None) -> list:
    """``[(line, matched text)]`` for ``pattern`` over the screen words of one file.

    ``skip(run)`` may return the run with the text to leave out replaced by NUL
    characters of the same length."""
    source, runs, python = _read(rel)
    regex = re.compile(pattern)
    out = []
    place = _Place(source)
    seen_python: dict = {}
    for run in runs:
        text = skip(run) if skip else run
        for match in regex.finditer(text):
            if python is not None:
                spans = python.get(run, [(0, 0)])
                index = seen_python.get(run, 0)
                first, last = spans[min(index, len(spans) - 1)]
                if first:
                    lines = source.splitlines()[first - 1:last]
                    found = re.search(_flexible(" ".join(run[max(0, match.start() - 20):match.end() + 10].split())),
                                      "\n".join(lines), re.S)
                    if found:
                        line = str(first + "\n".join(lines)[:found.start()].count("\n"))
                    else:
                        line = f"{first}-{last}" if last != first else str(first)
                else:
                    line = "?"
            else:
                line = place.line(run, match.start(), match.end())
            out.append((line, match.group(0)))
        if python is not None and run in python:
            seen_python[run] = seen_python.get(run, 0) + 1
    return out


def _all_hits(files: list, pattern: str, skip=None) -> list:
    found = []
    for rel in files:
        for line, text in _hits(rel, pattern, skip):
            found.append((rel, line, text))
    return found


def _report(found: list, advice: str) -> str:
    return "\n".join(f"  {rel}:{line}: {text!r}: {advice}" for rel, line, text in found)


# -- 1. "No" on the object ---------------------------------------------------------------

@pytest.mark.parametrize("pattern,advice", words.NO_ON_THE_OBJECT)
def test_no_is_not_put_on_the_object(pattern, advice):
    found = _all_hits(_screen_files(), pattern)
    assert not found, (
        f"{len(found)} screen sentence(s) put \"no\" on the object (copy rule 15: \"not\" goes on the verb):\n"
        + _report(found, advice))


# -- 1a. A station's readings are received and updated, never fetched --------------------------

@pytest.mark.parametrize("pattern,advice", words.RETIRED_FETCH)
def test_a_stations_readings_are_not_fetched_on_a_screen(pattern, advice):
    found = _all_hits(_screen_files(), pattern)
    assert not found, (
        f"{len(found)} sentence(s) say a station's readings are fetched:\n" + _report(found, advice))


# -- 1b. Words struck in the language passes --------------------------------------------------

@pytest.mark.parametrize("pattern,advice", words.RETIRED_WORDS)
def test_a_screen_does_not_use_a_struck_word(pattern, advice):
    found = _all_hits(_screen_files(), pattern)
    assert not found, (
        f"{len(found)} sentence(s) use a word Brent struck:\n" + _report(found, advice))


# -- 2. A page is named by its own name ----------------------------------------------------

@pytest.mark.parametrize("pattern,advice", words.RETIRED_PAGE_REFERENCES)
def test_a_page_is_not_named_by_another_pages_name(pattern, advice):
    found = _all_hits(_screen_files(), pattern)
    assert not found, (
        f"{len(found)} sentence(s) name a page by a retired name (copy rule 4):\n" + _report(found, advice))


# -- 3. Sign in, one name -------------------------------------------------------------------

@pytest.mark.parametrize("pattern,advice", words.RETIRED_SIGN_IN)
def test_the_sites_own_controls_say_sign_in(pattern, advice):
    templates = shapes.surfaces()["templates"]
    found = _all_hits(templates, pattern)
    assert not found, (
        f"{len(found)} place(s) say \"Log in\" or \"login\"; the pair is Sign in and Sign out:\n"
        + _report(found, advice))


# -- 4. A new-record page and its button say "Add" ---------------------------------------------

_TITLE_BLOCK = re.compile(r"\{%\s*block\s+(?:page_title|title)\s*%\}(.*?)\{%\s*endblock", re.S)


def _blanked(source: str) -> str:
    for pattern in shapes._BLANKED[:3]:
        source = pattern.sub(shapes._blank, source)
    return source


def _new_record_titles() -> list:
    found = []
    for rel in shapes.surfaces()["templates"]:
        if not rel.endswith(".html"):
            continue
        source = _blanked((REPO_ROOT / rel).read_text())
        for block in _TITLE_BLOCK.finditer(source):
            line = source.count("\n", 0, block.start(1)) + 1
            for run in shapes._runs(shapes._strip_not_copy(block.group(1))):
                if run.startswith(words.NEW_RECORD_TITLE_STARTS):
                    found.append((rel, str(line), run))
    return found


def test_a_new_record_page_is_titled_add():
    found = [
        (rel, line, run) for rel, line, run in _new_record_titles()
        if not any(rel == path and run.startswith(start) for path, start, _reason in EXCEPTIONS)
    ]
    assert not found, (
        f"{len(found)} page title(s) start with \"New\" or \"Create\"; the page that makes a record is titled \"Add ...\":\n"
        + _report(found, 'say "Add ..." (copy rule 4: the button carries the page\'s name)'))


def test_the_button_that_opens_a_new_record_page_says_add():
    found = _all_hits(shapes.surfaces()["templates"], words.NEW_RECORD_BUTTON)
    assert not found, (
        f"{len(found)} button(s) read \"+ New\"; the majority and the page titles say \"+ Add\":\n"
        + _report(found, 'say "+ Add ..."'))


def test_every_title_exception_still_matches():
    live = {(rel, run) for rel, _line, run in _new_record_titles()}
    for path, start, reason in EXCEPTIONS:
        assert any(rel == path and run.startswith(start) for rel, run in live), (
            f"EXCEPTIONS entry ({path}, {start!r}) matches no title now ({reason}); remove it.")


# -- 5. "Field" meaning the record ------------------------------------------------------------

_FIELD = re.compile(words.FIELD_WORD)
_OTHER_SENSES = [re.compile(pattern) for pattern, _reason in words.FIELD_OTHER_SENSES]
_EXCLUDED_FILES = {path for path, _reason in words.FIELD_WORD_EXCLUDED_FILES}


def _without_other_senses(run: str) -> str:
    """The run with a data-field phrase blanked; a one-word run is a column header or a code token."""
    if len(run.split()) < 2:
        return "\x00" * len(run)
    for pattern in _OTHER_SENSES:
        run = pattern.sub(lambda m: "\x00" * len(m.group(0)), run)
    return run


def _field_hits() -> dict:
    found = {}
    for rel in _screen_files():
        if rel in _EXCLUDED_FILES:
            continue
        hits = _hits(rel, words.FIELD_WORD, skip=_without_other_senses)
        if hits:
            found[rel] = hits
    return found


def test_the_record_is_a_use_area_not_a_field():
    over = {rel: hits for rel, hits in _field_hits().items() if len(hits) > FIELD_WORD_KEPT.get(rel, 0)}
    lines = "\n".join(
        f"  {rel}: {len(hits)} use(s), {FIELD_WORD_KEPT.get(rel, 0)} kept; at "
        + ", ".join(f"{rel}:{line}" for line, _text in hits[:12]) + (" ..." if len(hits) > 12 else "")
        for rel, hits in sorted(over.items()))
    assert not over, (
        f"{len(over)} file(s) call the record a \"field\"; it is a \"use area\" everywhere (ruling 59, 2026-10-31). "
        "Reword it, or, when the word means land outside the record or a data field, "
        "list the file in FIELD_WORD_KEPT with the reason:\n" + lines)


def test_a_field_word_ceiling_never_sits_above_the_count():
    now = {rel: len(hits) for rel, hits in _field_hits().items()}
    for rel, kept in FIELD_WORD_KEPT.items():
        assert kept <= now.get(rel, 0), (
            f"FIELD_WORD_KEPT[{rel!r}] = {kept} but the file now has {now.get(rel, 0)}; lower the ceiling.")


# -- Pages -------------------------------------------------------------------------------------

User = get_user_model()
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    text = unescape(_TAG.sub(" ", fragment)).replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture
def administrator(settings):
    settings.ACCESS_CONTROL_ENFORCED = True
    user = User.objects.create_user(
        username="screen-words-admin", email="screen-words-admin@example.org",
        password="a-good-passw0rd", is_active=True, is_staff=True)
    client = Client()
    client.force_login(user)
    return client


# -- 6. Setting names agree -------------------------------------------------------------------

def test_delivery_settings_headings_are_the_names_settings_explained_uses(administrator):
    page = administrator.get(reverse("accounting:delivery_settings"))
    assert page.status_code == 200
    headings = [_text(h) for h in re.findall(
        r'<h2 class="section-header">(.*?)</h2>', page.content.decode(), re.S)]
    assert headings, "the Delivery Settings page has no section-header headings"

    help_page = administrator.get(reverse("settings_explained"))
    assert help_page.status_code == 200
    source = help_page.content.decode()
    start = re.search(r'<h2 class="section-header">\s*Delivery Settings\s*</h2>', source)
    assert start, "Settings explained has no Delivery Settings table"
    table = source[start.end():]
    following = re.search(r'<h2\b', table)
    table = table[:following.start()] if following else table
    names = [_text(n) for n in re.findall(r'<td class="col-name">(.*?)</td>', table, re.S)]
    assert names, "the Delivery Settings table on Settings explained has no names"

    missing = [h for h in headings if h not in names]
    assert not missing, (
        "Delivery Settings headings that Settings explained does not name (copy rule 4: one name per setting):\n"
        + "\n".join(f"  {h!r}" for h in missing)
        + f"\nSettings explained names: {names}")


# -- 7. A Settings row carries its page's name -------------------------------------------------

_ROW = re.compile(r'<a\s([^>]*class="[^"]*\bsettings-row-label\b[^"]*"[^>]*)>(.*?)</a>', re.S)
_PAGE_TITLE = re.compile(r'<h1 class="page-title">(.*?)</h1>', re.S)


def test_each_settings_row_is_named_as_the_page_it_opens(administrator):
    rows = _ROW.findall(administrator.get(reverse("settings")).content.decode())
    assert rows, "the Settings page drew no rows"
    wrong = []
    for attributes, label_html in rows:
        href = re.search(r'href="([^"]+)"', attributes).group(1)
        label = _text(label_html)
        response = administrator.get(href, follow=True)
        assert response.status_code == 200, f"{label}: {href} did not open"
        title = _PAGE_TITLE.search(response.content.decode())
        assert title, f"{label}: the page at {href} has no page title"
        opened = _text(title.group(1))
        title, label_lower = opened.lower(), label.lower()
        # Equal, or the label then a colon ("Setup wizard: Boundary" for "Setup Wizard"):
        # "Methodology" opening "Methodology Settings" is a different name, not a step.
        if not (title == label_lower or title.startswith(label_lower + ":")):
            wrong.append(f"  row {label!r} opens {href} titled {opened!r}")
    assert not wrong, (
        "A Settings row carries the name of the page it opens (copy rule 4); the page title may continue after the label only past a colon:\n"
        + "\n".join(wrong))
