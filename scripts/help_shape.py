# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure how much of a help page is paragraphs, and how long its longest one is.

Brent's rule for the help pages (149.1): a block of prose is at most 60 words,
and at most half of a page's words sit in prose blocks. A table, a heading, a
badge or a link card is the shape wanted; a wall of ``<p>`` is the fault.

A block is one ``<p>``, ``<li>`` or ``<dd>`` element. Its words are the visible
words inside it, with nested blocks counted once, at the innermost block (an
``<li>`` holding a ``<p>`` is one block, the ``<p>``). ``<th>`` and ``<td>``
words count toward the page total and are never blocks.

The text is read the way ``tests/test_screen_text_shapes.py::visible()`` reads
a template (copied here, not imported: this runs on the host with the standard
library only, no Django and no test imports). ``{% comment %}`` blocks, HTML
comments and ``{% %}`` tags are not copy, and a ``{{ }}`` figure is one word.
Inline tags (``<strong>``, ``<a>``, ``<code>`` and the rest) never end a block.

Usage::

    python3 scripts/help_shape.py templates/help/*.html templates/help/partials/*.html
"""

import html
import re
import sys
from pathlib import Path

#: Brent, 2026-10-06 18:17 PDT
MAX_BLOCK_WORDS = 60
#: Brent, 2026-10-06 18:17 PDT
MAX_PROSE_SHARE = 0.50

_NOT_COPY = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<script.*?</script>", re.S),
    re.compile(r"<style.*?</style>", re.S),
)
_SEEN_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)\"""")
_INLINE = re.compile(
    r"</?(?:a|abbr|b|bdi|cite|code|data|dfn|em|i|kbd|mark|q|s|small|span|strong"
    r"|sub|sup|time|u|var|wbr)\b[^>]*>", re.I)
_BRANCH = re.compile(r"\{%\s*(?:elif|else|empty)\b.*?%\}", re.S)
_TAG = re.compile(r"<(/?)\s*([a-zA-Z][a-zA-Z0-9]*)?[^>]*>")
_BLOCKS = {"p", "li", "dd"}


def _prepare(source: str) -> str:
    """Template source with copy-less markup removed and inline tags dissolved."""
    for pattern in _NOT_COPY:
        source = pattern.sub(" ", source)
    source = " ".join(source.split())
    source = re.sub(r"\{\{.*?\}\}", " X ", source, flags=re.S)
    source = _BRANCH.sub("<br>", source)
    source = re.sub(r"\{%.*?%\}", " ", source, flags=re.S)
    source = _SEEN_ATTR.sub(lambda m: "> " + m.group(1) + " <", source)
    return _INLINE.sub(" ", source)


def measure(path) -> dict:
    """Block word counts and prose share for one template file."""
    source = _prepare(Path(path).read_text())
    blocks: list = []
    stack: list = []
    total = 0
    position = 0

    def add(text: str) -> None:
        nonlocal total
        words = len(html.unescape(text).split())
        total += words
        if stack:
            stack[-1] += words

    for tag in _TAG.finditer(source):
        add(source[position:tag.start()])
        position = tag.end()
        name = (tag.group(2) or "").lower()
        if name not in _BLOCKS:
            continue
        if tag.group(1):
            if stack:
                blocks.append(stack.pop())
        else:
            stack.append(0)
    add(source[position:])
    while stack:
        blocks.append(stack.pop())

    blocks = [words for words in blocks if words]  # an <li> that only wraps a <p>
    block_words = sum(blocks)
    return {
        "blocks": blocks,
        "longest": max(blocks, default=0),
        "share": block_words / total if total else 0.0,
        "over_60": sum(1 for words in blocks if words > MAX_BLOCK_WORDS),
    }


def main(argv: list) -> int:
    print(f"{'file':<52} {'blocks':>6} {'longest':>7} {'share':>6} {'over_60':>7}")
    for arg in argv:
        row = measure(arg)
        print(f"{arg:<52} {len(row['blocks']):>6} {row['longest']:>7} "
              f"{row['share']:>6.2f} {row['over_60']:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
