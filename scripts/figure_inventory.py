# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emit the figure inventory: every ``floatformat`` site in ``templates/``.

**Why a script and not a list.** A hand-typed inventory of 107 sites is wrong the
first time a template gains a column, and nothing goes red to say so. This walks
the tree and emits one record per occurrence, so the ledger's row set is a
measurement rather than a transcription.

One record per OCCURRENCE, not per line: ``_station_detail_pane.html:104``
renders latitude and longitude in a single line and is two figures on screen.

Stable ids. ``FIG-<app>-<NNN>`` numbers within each app in (template, line,
column) order after a deterministic sort. A re-run that renumbered would break
every ledger row written by an earlier plan, so the sort key must not depend on
filesystem walk order -- ``sorted()`` over the collected records, never
``os.walk`` order.

Usage::

    python3 scripts/figure_inventory.py --out audit/figure_ledger/inventory.json

Runs on the HOST with the standard library only: no Django, no bs4, no lxml.
``requirements.lock`` carries none of them and this adds no dependency.
"""

import argparse
import json
import os
import re
import sys

TEMPLATE_ROOT = "templates"

#: Opening delimiters of a Django template tag, longest first so ``{%`` is not
#: mistaken for a bare ``{``.
_OPENERS = (("{{", "}}"), ("{%", "%}"))

#: A run of text that could be a human-readable label: at least one letter, and
#: not the inside of an HTML tag or a template tag (both are stripped first).
_HAS_LETTER = re.compile(r"[A-Za-z]")

_FOR_TAG = re.compile(r"\{%\s*for\s+(?P<vars>[\w., ]+?)\s+in\s+(?P<seq>[^\s%]+)")
_ENDFOR_TAG = re.compile(r"\{%\s*endfor\s*%\}")

#: Regions of a template that never reach a browser. Measured 2026-09-05: exactly
#: ONE of the 107 occurrences lives in one of these -- prose in
#: ``drinking/partials/_result_value.html`` explaining that lab results
#: deliberately do NOT go through ``floatformat``. It is a word in a comment, not
#: a number on a screen, so the tree holds 107 occurrences and **106 figures**.
#: Both counts are kept: 107 is what ``grep -c`` sees and is the reproducible
#: check on this extractor; 106 is what the ledger has rows for.
_COMMENT_BLOCK = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)
_COMMENT_INLINE = re.compile(r"\{#.*?#\}", re.S)


def _comment_spans(text):
    """Character ranges of ``{% comment %}`` blocks and ``{# ... #}`` comments."""
    spans = [m.span() for m in _COMMENT_BLOCK.finditer(text)]
    spans += [m.span() for m in _COMMENT_INLINE.finditer(text)]
    return spans


def _enclosing_tag(text, index):
    """Return the full template tag containing the character at ``index``.

    Searches backwards for the nearest opener and forwards for its closer. A
    ``floatformat`` that is somehow not inside a tag returns None rather than a
    guess -- the caller reports it, because that would mean the extractor's model
    of the file is wrong and the count cannot be trusted.
    """
    best = None
    for opener, closer in _OPENERS:
        start = text.rfind(opener, 0, index)
        if start == -1:
            continue
        end = text.find(closer, index)
        if end == -1:
            continue
        # The opener must not be closed before it reaches us.
        if text.find(closer, start, index) != -1:
            continue
        if best is None or start > best[0]:
            best = (start, end + len(closer))
    if best is None:
        return None
    return text[best[0]:best[1]]


def _enclosing_loop(text, index):
    """The innermost ``{% for x in y %}`` still open at ``index``, or None.

    Kept as a plain depth walk over the preceding text rather than a parse: the
    ledger only needs to know what ``row`` is bound to so ``row.surface`` can be
    resolved to a real column later.
    """
    stack = []
    for match in re.finditer(r"\{%\s*(for|endfor)\b", text[:index]):
        if match.group(1) == "for":
            for_match = _FOR_TAG.match(text, match.start())
            if for_match:
                stack.append(
                    f"{for_match.group('vars').strip()} in {for_match.group('seq').strip()}"
                )
            else:
                stack.append("?")
        elif stack:
            stack.pop()
    return stack[-1] if stack else None


def _nearest_label(text, index):
    """Best-effort: the closest preceding human-readable words.

    A HINT for the ledger's ``label`` column, never authority. In a data table
    the words a reader actually sees are in a ``<th>`` far above the cell, so
    this will often return something adjacent and unhelpful. The ledger author
    reads the template; this only saves the first lookup.
    """
    window = text[max(0, index - 400):index]
    # Drop template tags first, then HTML tags, then look at what is left.
    window = re.sub(r"\{[{%].*?[%}]\}", "\x00", window, flags=re.S)
    window = re.sub(r"<[^>]*>", "\x00", window, flags=re.S)
    window = re.sub(r"&[a-zA-Z]+;", " ", window)
    chunks = [chunk.strip() for chunk in window.split("\x00")]
    for chunk in reversed(chunks):
        collapsed = " ".join(chunk.split())
        if collapsed and _HAS_LETTER.search(collapsed):
            return collapsed[:120]
    return None


def collect(root=TEMPLATE_ROOT):
    """Every ``floatformat`` occurrence under ``root``, as unnumbered records."""
    records = []
    problems = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.endswith(".html"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            spans = _comment_spans(text)
            for match in re.finditer("floatformat", text):
                index = match.start()
                commented = any(start <= index < end for start, end in spans)
                line = text.count("\n", 0, index) + 1
                column = index - (text.rfind("\n", 0, index) + 1) + 1
                expression = _enclosing_tag(text, index)
                if expression is None:
                    if not commented:
                        problems.append(
                            f"{path}:{line} floatformat outside any template tag"
                        )
                    expression = ""
                rel = os.path.relpath(path, root)
                records.append(
                    {
                        "app": rel.split(os.sep)[0],
                        "kind": "comment_prose" if commented else "figure",
                        "template": path.replace(os.sep, "/"),
                        "line": line,
                        "column": column,
                        "expression": " ".join(expression.split()),
                        "enclosing_loop": _enclosing_loop(text, index),
                        "nearest_label": _nearest_label(text, index),
                    }
                )
    return records, problems


def number(records):
    """Assign stable ``FIG-<app>-<NNN>`` ids over a deterministic sort."""
    records = sorted(records, key=lambda r: (r["app"], r["template"], r["line"], r["column"]))
    counters = {}
    for record in records:
        counters[record["app"]] = counters.get(record["app"], 0) + 1
        record["id"] = f"FIG-{record['app']}-{counters[record['app']]:03d}"
    # id first in the serialised dict, so the JSON reads like the ledger does.
    return [
        {
            "id": r["id"],
            "app": r["app"],
            "kind": r["kind"],
            "template": r["template"],
            "line": r["line"],
            "column": r["column"],
            "expression": r["expression"],
            "enclosing_loop": r["enclosing_loop"],
            "nearest_label": r["nearest_label"],
        }
        for r in records
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=TEMPLATE_ROOT)
    parser.add_argument("--out", default="audit/figure_ledger/inventory.json")
    args = parser.parse_args()

    records, problems = collect(args.root)
    records = number(records)

    for problem in problems:
        print(f"  PROBLEM: {problem}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, sort_keys=False)
        handle.write("\n")

    templates = {r["template"] for r in records}
    figures = [r for r in records if r["kind"] == "figure"]
    by_app = {}
    for record in figures:
        by_app[record["app"]] = by_app.get(record["app"], 0) + 1
    print(
        f"  {len(records)} occurrences across {len(templates)} templates "
        f"-> {args.out}"
    )
    prose = len(records) - len(figures)
    print(
        f"  {len(figures)} are rendered figures; {prose} "
        + ("is" if prose == 1 else "are")
        + " prose inside a template comment"
    )
    for app in sorted(by_app):
        print(f"    {app:<12} {by_app[app]:>4}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
