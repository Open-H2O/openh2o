#!/usr/bin/env python3
"""List the labels that restate the heading above them (ISS-168, DESIGN.md copy rule 13).

Standard library only; runs on the host over ``templates/**/*.html``. For every label
element (``th``, ``dt``, ``label``, ``.field-label``, ``.card-subtitle``,
``.page-description``, and the first ``.text-xs`` / ``.text-sm`` line directly under a
heading) it finds the nearest heading above it in the same file (``h1``-``h4``,
``.section-header*``, ``.card-title``, a ``{% block title %}`` or
``{% block page_title %}``) and prints the pair when, after lowercasing and dropping stop
words and ``{{ }}`` figures, the label shares a run of three or more words with the
heading, or holds 70% or more of the heading's words.

It lists candidates; it judges nothing. A table column that must name its column, or a
quantity's own name standing alone, is a STANDS the reader marks by hand.

    python3 scripts/label_repeats.py                 # every template
    python3 scripts/label_repeats.py path/a.html ... # named files
    python3 scripts/label_repeats.py --count         # the count only
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

HEADING_TAGS = {"h1", "h2", "h3", "h4"}
HEADING_CLASS = re.compile(r"(?:^|\s)(?:section-header[\w-]*|card-title)(?:\s|$)")
LABEL_TAGS = {"th", "dt", "label"}
LABEL_CLASS = re.compile(r"(?:^|\s)(?:field-label|card-subtitle|page-description)(?:\s|$)")
UNDER_HEADING_CLASS = re.compile(r"(?:^|\s)(?:text-xs|text-sm)(?:\s|$)")

STOP = {
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "by", "this", "that",
    "is", "are", "with", "at", "as", "per", "or", "it", "its", "no", "not", "from",
    "af", "acre", "feet", "ft",
}

RUN = 3
SHARE = 0.70

COMMENT_BLOCK = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", re.S)
HASH_COMMENT = re.compile(r"{#.*?#}", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
BLOCK_TITLE = re.compile(
    r"{%\s*block\s+(?:page_)?title\s*%}(.*?){%\s*endblock", re.S
)
FIGURE = re.compile(r"{{.*?}}", re.S)
TAG = re.compile(r"{%.*?%}", re.S)


def _blank(match: re.Match) -> str:
    """Replace a match with spaces, keeping every newline so line numbers hold."""
    return re.sub(r"[^\n]", " ", match.group(0))


def preprocess(src: str) -> tuple[str, list[tuple[int, str]]]:
    """Strip template syntax while keeping line numbers; return block titles as headings."""
    src = COMMENT_BLOCK.sub(_blank, src)
    src = HASH_COMMENT.sub(_blank, src)
    src = HTML_COMMENT.sub(_blank, src)
    titles: list[tuple[int, str]] = []
    for m in BLOCK_TITLE.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        text = TAG.sub(" ", FIGURE.sub(" ", m.group(1)))
        text = text.split(" - Open Water")[0]
        titles.append((line, text))
    src = FIGURE.sub(_blank, src)
    src = TAG.sub(_blank, src)
    return src, titles


class Collector(HTMLParser):
    """Record every heading and label element with its line and visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[int, str, str]] = []  # (line, kind, text)
        self._open: list[tuple[str, str, int, list[str]]] = []  # (tag, kind, line, buf)
        self._after_heading = False

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> str:
        for k, v in attrs:
            if k == "class":
                return v or ""
        return ""

    def _kind(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        cls = self._classes(attrs)
        if tag in HEADING_TAGS or HEADING_CLASS.search(cls):
            return "heading"
        if tag in LABEL_TAGS or LABEL_CLASS.search(cls):
            return "label"
        if self._after_heading and UNDER_HEADING_CLASS.search(cls):
            return "label"
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        kind = self._kind(tag, attrs)
        line = self.getpos()[0]
        if kind:
            self._open.append((tag, kind, line, []))
        elif self._open:
            self._open[-1][3].append(" ")

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                _, kind, line, buf = self._open.pop(i)
                text = " ".join("".join(buf).split())
                if text:
                    self.items.append((line, kind, text))
                    self._after_heading = kind == "heading"
                break

    def handle_data(self, data: str) -> None:
        if self._open:
            self._open[-1][3].append(data)


def words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower()):
        w = w.strip("'-")
        if w and w not in STOP and not re.fullmatch(r"[\d.,%]+", w):
            out.append(w)
    return out


def overlap(heading: str, label: str) -> str | None:
    hw, lw = words(heading), words(label)
    if not hw or not lw:
        return None
    runs = set()
    for i in range(len(lw) - RUN + 1):
        run = lw[i : i + RUN]
        for j in range(len(hw) - RUN + 1):
            if hw[j : j + RUN] == run:
                runs.add(" ".join(run))
    if runs:
        return "run: " + "; ".join(sorted(runs))
    shared = [w for w in dict.fromkeys(lw) if w in hw]
    ratio = len(shared) / len(set(hw))
    if ratio >= SHARE:
        return f"share: {len(shared)}/{len(set(hw))} of the heading's words ({' '.join(shared)})"
    return None


def scan(path: Path) -> list[tuple[Path, int, str, str, str]]:
    src, titles = preprocess(path.read_text(encoding="utf-8"))
    parser = Collector()
    parser.feed(src)
    items = sorted(parser.items + [(line, "heading", t) for line, t in titles])
    found = []
    heading: str | None = None
    for line, kind, text in items:
        if kind == "heading":
            heading = text
            continue
        if heading is None:
            continue
        why = overlap(heading, text)
        if why:
            found.append((path, line, heading, text, why))
    return found


def main(argv: list[str]) -> int:
    count_only = "--count" in argv
    args = [a for a in argv if not a.startswith("--")]
    paths = [Path(a) for a in args] if args else sorted(TEMPLATES.rglob("*.html"))
    found = []
    for p in paths:
        found.extend(scan(p))
    if not count_only:
        for path, line, heading, label, why in found:
            try:
                rel = path.resolve().relative_to(ROOT)
            except ValueError:
                rel = path
            print(f"{rel}:{line}\n  heading: {heading}\n  label:   {label}\n  {why}")
    print(f"{len(found)} candidate(s) in {len(paths)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
