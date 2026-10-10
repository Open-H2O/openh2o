# SPDX-License-Identifier: AGPL-3.0-or-later
"""Count the sentence shapes Brent has struck that a machine can see.

Brent ruled on 2026-10-09 at 18:45 PDT that the shapes he has struck are to be
fixed everywhere. Seven shapes are named in DESIGN.md copy rule 15. Four of
them can be found by pattern, and this script counts those four:

- an em dash between two words, and a double hyphen used as one;
- the filler words actually, genuinely, really and simply;
- a heading made of two clauses joined by ", and what" (or who, how, where,
  why, when, which);
- a heading that ends in a trailing clause, ", by what" or ", by which".

A phrase posing as a statement, a thing acting like a person and a slogan need
a reader. This script does not try to find them.

It reads three surfaces:

1. Every template under ``templates/``, with comments, ``<script>`` and
   ``<style>`` removed, a ``{{ }}`` figure read as one word, and the text a
   reader sees in ``title``, ``placeholder``, ``aria-label`` and ``alt``
   attributes kept. The words passed into an included partial
   (``{% include "..." with text="..." %}``) are read too, because the
   partial puts them on screen.
2. String literals in ``SCREEN_PYTHON``, the Python files whose strings reach
   a screen or a downloaded file. Docstrings and strings passed to a logger
   are not read.
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

#: Python files whose strings reach a screen or a downloaded file. Management
#: commands and logging are read in a terminal, so they are not here.
SCREEN_PYTHON: tuple = (
    "accounting/ledger_words.py",
    "accounting/views.py",
    "config/views.py",
    "core/models.py",
    "datasync/freshness.py",
    "drinking/glossary.py",
    "drinking/ps_codes.py",
    "drinking/views.py",
    "health/checks.py",
    "infrastructure/views.py",
    "reporting/generators.py",
    "reporting/validators.py",
    "reporting/views.py",
    "setup/boundaries.py",
    "surface/views.py",
)

#: The public guides. Dated records in ``docs/`` (audits, proposals, ledgers)
#: say what was true on their date and are not guides, so they are not here.
GUIDES: tuple = (
    "CONTRIBUTING.md",
    "DEPLOY.md",
    "MAINTAINER.md",
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

SHAPES: tuple = ("em dash", "double hyphen", "filler", "paired heading", "trailing heading")


# -- Templates ----------------------------------------------------------------

_NOT_COPY = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<script.*?</script>", re.S),
    re.compile(r"<style.*?</style>", re.S),
)
_SEEN_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)\"""")
#: Tags that sit inside a sentence. Every other tag ends a run of text.
_INLINE = re.compile(
    r"</?(?:a|abbr|b|bdi|cite|code|data|dfn|em|i|kbd|mark|q|s|small|span|strong"
    r"|sub|sup|time|u|var|wbr)\b[^>]*>", re.I)
#: An alternative arm of an if or for tag starts a new run of text.
_BRANCH = re.compile(r"\{%\s*(?:elif|else|empty)\b.*?%\}", re.S)
_HEADING_TAG = re.compile(r"<(h[1-6]|summary|legend|caption)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
_TITLE_BLOCK = re.compile(
    r"\{%\s*block\s+(?:title|head_title|page_title|page_heading|heading)\s*%\}(.*?)"
    r"\{%\s*endblock", re.S)
_INCLUDE = re.compile(r"\{%\s*include\b(.*?)%\}", re.S)
#: The include arguments that carry words onto the screen.
_INCLUDE_ARG = re.compile(
    r"""\b(?:text|title|label|link_label|add_label|what)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


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


def _runs(source: str) -> list:
    """Template source (comments already gone) as the runs of text it shows."""
    source = " ".join(source.split())
    source = re.sub(r"\{\{.*?\}\}", " X ", source, flags=re.S)
    source = _BRANCH.sub("\n", source)
    source = re.sub(r"\{%.*?%\}", " ", source, flags=re.S)
    source = _SEEN_ATTR.sub(lambda m: ">\n" + m.group(1) + "\n<", source)
    source = _INLINE.sub(" ", source)
    source = re.sub(r"<[^>]+>", "\n", source)
    runs = (" ".join(html.unescape(run).split()) for run in source.split("\n"))
    return [run for run in runs if run]


def template_text(source: str) -> tuple:
    """``(runs, headings)``: every run of text a template shows, and its headings."""
    source = _strip_not_copy(source)
    headings = []
    for match in _TITLE_BLOCK.finditer(source):
        headings.append(" ".join(_runs(match.group(1))))
    for match in _HEADING_TAG.finditer(source):
        headings.append(" ".join(_runs(match.group(2))))
    runs = _runs(source) + include_arguments(source)
    return runs, [h for h in headings if h]


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
    }


def count_file(rel: str, source: str) -> dict:
    """``{shape: n}`` for one file's source, read as the surface its path names."""
    if rel.endswith(".html"):
        return count(*template_text(source))
    if rel.endswith(".py"):
        return count(python_strings(source), [])
    if rel.endswith(".md"):
        return count(*guide_text(source))
    raise ValueError(f"no surface reads {rel}")


def surfaces(root: Path = REPO_ROOT) -> dict:
    """``{surface: [relative path, ...]}`` for every file this script reads."""
    templates = sorted(str(p.relative_to(root)) for p in (root / "templates").rglob("*.html"))
    return {
        "templates": templates,
        "screen python": [p for p in SCREEN_PYTHON if (root / p).exists()],
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
