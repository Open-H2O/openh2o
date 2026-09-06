# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water quantities this platform names, read out of ``DESIGN.md`` rule 12.

Rule 11 (``core/domain_vocabulary.py``) says never explain the water. This is the
companion: name each quantity once, and the same way on every screen. The
definitions table lives in ``DESIGN.md`` between ``<!-- vocabulary: begin -->``
and ``<!-- vocabulary: end -->``, and this module is the one reader of it. The
document is the source; nothing here restates a definition.

**Why the table is read and not transcribed.** Phase 135 found that every
defect it could confirm was a correct number under a label naming something
else, or two screens describing the same rows differently (ISS-151, ISS-153,
ISS-155, and the word halves of ISS-143 and ISS-148). The product had two live
definitions of "supply" and had never chosen. A list copied into a test would be
a third place for the choice to drift. Reading the table means the gate and the
document cannot disagree.

**What a rule is.** Each row's "Never called" cell carries zero or more entries
of one of two shapes::

    `phrase` in `templates/<dir>/`
    `phrase` anywhere

Each becomes one :class:`Rule`: the phrase is wrong wherever it appears inside
that scope, so the gate holds every rule at a strict zero. A row whose misuse is
a concept rather than a string says ``no gated phrase`` in that cell, so a row
that parses to nothing is a deliberate statement and not a silent gap.

**Matching.** Case-sensitive, exactly as written, and word-bounded. ``Surplus``
is the badge word and a hit; ``text-surplus`` is a CSS token and is not.

**Pure data plus one reader.** No Django import, no settings access, no
database: the gate runs anywhere the repository does, the same as
``core/domain_vocabulary.py``.
"""

import re
from dataclasses import dataclass
from pathlib import Path

BEGIN_MARKER = "<!-- vocabulary: begin -->"
END_MARKER = "<!-- vocabulary: end -->"

#: The literal a row uses to say, on purpose, that nothing in it is gated.
NO_GATED_PHRASE = "no gated phrase"

#: One entry in the "Never called" cell. The scope is a repo-relative template
#: directory ending in a slash, or the word ``anywhere``.
_ENTRY = re.compile(
    r"`(?P<phrase>[^`]+)`\s+(?:in\s+`(?P<scope>templates/[^`]+/)`|(?P<anywhere>anywhere))"
)


@dataclass(frozen=True)
class Rule:
    """A phrase that may not appear inside a scope, and the term it misnames."""

    #: The row's term, verbatim from the table, used in failure messages.
    term: str
    #: The forbidden phrase, exactly as written.
    phrase: str
    #: Repo-relative directory prefix, or ``None`` for every surface.
    scope: str | None

    @property
    def pattern(self) -> re.Pattern:
        return re.compile(rf"(?<![\w-]){re.escape(self.phrase)}(?![\w-])")

    def applies_to(self, location: str) -> bool:
        """Whether this rule is in force at ``location`` (a repo-relative path)."""
        return self.scope is None or location.startswith(self.scope)

    def __str__(self) -> str:
        where = "anywhere" if self.scope is None else f"in {self.scope}"
        return f"`{self.phrase}` {where} (the term is {self.term})"


def _cells(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_rules(markdown: str) -> list:
    """Every :class:`Rule` in the table between the two markers.

    Raises ``AssertionError`` in plain English when the markers are missing, the
    table has no rows, a row has the wrong shape, or a row's "Never called" cell
    neither carries an entry nor says ``no gated phrase``. A gate that parses
    nothing must fail loudly rather than pass quietly.
    """
    begin = markdown.find(BEGIN_MARKER)
    end = markdown.find(END_MARKER)
    if begin < 0 or end < 0 or end < begin:
        raise AssertionError(
            f"DESIGN.md rule 12 is missing its {BEGIN_MARKER} / {END_MARKER} "
            "markers, so the water-vocabulary gate has no table to read. "
            "Restore the markers around the definitions table; do not delete "
            "the gate."
        )
    block = markdown[begin + len(BEGIN_MARKER):end]

    table_lines = [line for line in block.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        raise AssertionError(
            "DESIGN.md rule 12's definitions table has no rows between its "
            "markers. The gate would scan nothing and report a pass; add the "
            "table back."
        )

    header = [cell.strip("* ").lower() for cell in _cells(table_lines[0])]
    try:
        term_index = header.index("term")
        never_index = header.index("never called")
    except ValueError as exc:
        raise AssertionError(
            f"DESIGN.md rule 12's table header is {header!r}; it must carry a "
            "`Term` column and a `Never called` column for the gate to read."
        ) from exc

    rules = []
    for line in table_lines[2:]:
        cells = _cells(line)
        if len(cells) != len(header):
            raise AssertionError(
                f"DESIGN.md rule 12: this row has {len(cells)} cells against a "
                f"{len(header)}-column header, so its cells would be read under "
                f"the wrong headings: {line.strip()[:80]!r}"
            )
        term = cells[term_index].strip("* ")
        never = cells[never_index]
        entries = list(_ENTRY.finditer(never))
        if not entries and NO_GATED_PHRASE not in never:
            raise AssertionError(
                f"DESIGN.md rule 12: the row for {term!r} has a `Never called` "
                f"cell the gate cannot read: {never!r}. Write one or more entries "
                "of the form `phrase` in `templates/<dir>/` or `phrase` anywhere, "
                f"or say {NO_GATED_PHRASE!r} on purpose."
            )
        for match in entries:
            rules.append(Rule(
                term=term,
                phrase=match.group("phrase"),
                scope=None if match.group("anywhere") else match.group("scope"),
            ))

    if not rules:
        raise AssertionError(
            "DESIGN.md rule 12's table parsed to zero gated phrases. Every row "
            f"says {NO_GATED_PHRASE!r}, so the gate would hold nothing. At least "
            "the four sites Phase 136 measured red must be gated."
        )
    return rules


def load_rules(source) -> list:
    """Rules from a path to ``DESIGN.md``, or from markdown text handed in directly.

    A string that already contains the begin marker is treated as the document
    itself; anything else is a path. The controls in the gate use the first
    form so they can prove the parser fails loudly on an empty table.
    """
    if isinstance(source, str) and BEGIN_MARKER in source:
        return parse_rules(source)
    return parse_rules(Path(source).read_text(encoding="utf-8"))
