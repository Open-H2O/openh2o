# SPDX-License-Identifier: AGPL-3.0-or-later
"""The comprehension gate: no operator document may use a word before defining it.

``core/operator_vocabulary.py`` is the list — thirty-four concepts, each one
written down by a zero-context agent who hit it during a v2.9 clean-room
deployment. This file is what makes the list bite.

**The marker convention.** A document defines a term by carrying
``<!-- defines: slug -->`` on the line that defines it. It is an HTML comment,
so it is invisible in rendered Markdown on GitHub and in every viewer: the
reader sees prose, the gate sees a claim.

**What this gate proves.** That a term from the list appears in a document with
nothing defining it first. That is all. It cannot read a definition and judge
whether a thirty-year groundwater engineer would understand it — no test can,
and a marker is a claim by whoever wrote the line, not evidence. Phase 114
pairs this gate with a human read for exactly that reason, and nothing here
should ever be quoted as saying the documents are comprehensible.

**The gate is green.** It was red at **55** — 14 in ``README.md``, 17 in
``docs/AI-OPERATOR-GUIDE.md`` and 24 in ``DEPLOY.md`` — and the recorded red run
is ``.planning/phases/110-comprehension-gate/110-01-EVIDENCE.md``. Phase 114 took
it to zero: 114-01 rewrote the two front-door documents, 114-02 rewrote
``DEPLOY.md``. It ran under ``@pytest.mark.xfail(strict=True)`` from Phase 110
until that moment, so that a passing gate could not sit disguised as a failing
one; ``strict=True`` broke the suite the instant the last document reached zero,
the marker was deleted in 114-02, and this is now an ordinary test that must
stay green.

**Why all four documents sit at a baseline of zero.** Three of them predate the
vocabulary list and carried legacy wording that Phase 114 rewrote away.
``docs/INSTALL-WITHOUT-DOCKER.md`` never did: 112-02 wrote it with the list
already in hand, so it started clean and stayed clean. All four zeros are now
strict ratchets, not unmeasured defaults.

**Why the two fixture tests exist.** A scorer that never fails is not a
measurement. One plants a violation and demands it be reported; the other proves
the scanner stays silent both on a correct definition and on a term that appears
only inside a fenced command block. Both run against strings, never against the
real documents, so they stay green through Phase 114 and keep proving the
scanner works after the documents themselves go clean.

All four tests call ``scan()``. A control that exercises a different code path
from the gate proves nothing.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from core.operator_vocabulary import COMPILED, TERMS

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The four documents an operator reads to stand this platform up. Phases
#: 111-114 rewrite the first three; this is the set they are rewritten against.
#: The fourth was WRITTEN against this list rather than rewritten to satisfy it
#: — 112-02 created it with the thirty-four terms already in hand — which is why
#: it is the only one whose baseline below is zero.
DOCUMENTS: tuple = (
    "README.md",
    "DEPLOY.md",
    "docs/AI-OPERATOR-GUIDE.md",
    "docs/INSTALL-WITHOUT-DOCKER.md",
)

#: ``<!-- defines: dns -->``. Case-insensitive on the keyword, but the slug must
#: match ``core.operator_vocabulary`` exactly, so a typo un-defines the term
#: loudly rather than quietly claiming a definition that is not there.
MARKER = re.compile(r"<!--\s*defines:\s*([A-Za-z0-9_]+)\s*-->")

#: A fenced block opener or closer. Everything between a pair is a command the
#: operator types, not prose using the word — ``docker compose up -d --build``
#: is not the document explaining Docker. Failing to strip these would fire on
#: every code sample in DEPLOY.md and the gate would be noise nobody reads.
FENCE = re.compile(r"^\s*(?:```|~~~)")


@dataclass(frozen=True)
class Offender:
    """One term used in a document before anything defined it."""

    slug: str
    label: str
    line: int

    def __str__(self) -> str:
        return f"line {self.line} — {self.label}"


def _prose_and_markers(text: str):
    """Split a document into matchable prose lines and its definition claims.

    Line numbers are preserved throughout: stripped lines are blanked, never
    removed, so a reported line number is the line number in the real file.

    Marker comments are blanked out of the prose too. ``<!-- defines: dns -->``
    contains the string "dns", and leaving it in would let a marker count as a
    use of its own term.
    """
    prose = []
    markers: dict = {}
    inside_fence = False

    for number, raw in enumerate(text.splitlines(), start=1):
        if FENCE.match(raw):
            inside_fence = not inside_fence
            prose.append("")
            continue
        if inside_fence:
            prose.append("")
            continue

        for match in MARKER.finditer(raw):
            slug = match.group(1)
            markers.setdefault(slug, number)

        prose.append(MARKER.sub(" ", raw))

    return prose, markers


def scan(text: str):
    """Every term this document uses before anything in it defines the term.

    A term is an offender when it is used and either carries no marker at all,
    or its first marker comes after its first bare use. Equal line numbers pass:
    the defining sentence carries its own marker.
    """
    prose, markers = _prose_and_markers(text)
    offenders = []

    for term in TERMS:
        first_use = None
        for number, line in enumerate(prose, start=1):
            if any(pattern.search(line) for pattern in COMPILED[term.slug]):
                first_use = number
                break
        if first_use is None:
            continue

        marker_line = markers.get(term.slug)
        defined_in_time = marker_line is not None and marker_line <= first_use
        if not defined_in_time:
            offenders.append(Offender(term.slug, term.label, first_use))

    return sorted(offenders, key=lambda offender: (offender.line, offender.slug))


def _scan_document(relative_path: str):
    return scan((REPO_ROOT / relative_path).read_text())


# -- The gate ----------------------------------------------------------------


def test_every_operator_term_is_defined_before_first_use():
    offenders = []
    for document in DOCUMENTS:
        for offender in _scan_document(document):
            offenders.append(f"{document}:{offender.line} — {offender.label}")

    assert not offenders, (
        f"{len(offenders)} operator terms are used before anything defines "
        "them. Define each on or before its first use and mark the defining "
        "line with <!-- defines: slug -->:\n  " + "\n  ".join(offenders)
    )


# -- The ratchet -------------------------------------------------------------

#: **ALL FOUR ARE STRICT RATCHETS as of 114-02.** Every operator document now
#: defines every term on the list before it uses it, so a baseline of zero is a
#: measured reading rather than a ceiling: the next undefined operator term added
#: to any of these four fails the build on the next run, immediately, instead of
#: waiting for a human to notice.
#:
#: How each entry got here. 110-01 measured the original ceilings on 2026-08-04
#: and recorded them verbatim in ``110-01-EVIDENCE.md`` —
#: ``docs/INSTALL-WITHOUT-DOCKER.md`` at 0 because 112-02 wrote it from scratch
#: with the thirty-four-term list already in hand, and the other three carrying
#: legacy vocabulary that predated the list. 114-01 took ``README.md`` (14 → 0)
#: and ``docs/AI-OPERATOR-GUIDE.md`` (17 → 0); 114-02 took ``DEPLOY.md`` (24 → 0,
#: from an entry that read 25 — a ceiling, never a reading).
#:
#: **The ordering is load-bearing.** Each baseline was lowered only AFTER its
#: document was clean. A baseline of 0 against a document that still has
#: offenders fails ``test_the_undefined_term_count_never_climbs`` immediately,
#: which is the correct behaviour and the reason for the ordering.
#:
#: Do not "fix" any of these upward. A raised baseline is a silently weakened
#: gate, and lowering a baseline remains the only legitimate edit to this table —
#: which, at zero, leaves no legitimate edit at all short of adding a document.
BASELINE_OFFENDERS: dict = {
    "README.md": 0,
    "DEPLOY.md": 0,
    "docs/AI-OPERATOR-GUIDE.md": 0,
    "docs/INSTALL-WITHOUT-DOCKER.md": 0,
}


def test_the_undefined_term_count_never_climbs():
    climbed = []
    for document, baseline in BASELINE_OFFENDERS.items():
        count = len(_scan_document(document))
        if count > baseline:
            climbed.append(f"{document}: {baseline} -> {count}")

    assert not climbed, (
        "these documents gained undefined operator vocabulary. Either define "
        "the new term or do not introduce it; lowering the baseline is the "
        "only legitimate edit to BASELINE_OFFENDERS: " + "; ".join(climbed)
    )


# -- The controls ------------------------------------------------------------

PLANTED_VIOLATION = """\
# Standing the platform up

Copy the .env file into place and start the containers.
"""

# Two shapes on purpose. `env_file` is defined on a line ABOVE its first use;
# `docker` carries its marker on the SAME line as the sentence that defines it,
# which is the boundary case the whole convention rests on. Without the second
# shape, mutating the scanner's `<=` to `<` passes unnoticed and the control
# stops being a control.
CORRECT_DEFINITION = """\
# Standing the platform up

<!-- defines: env_file -->
The settings live in a plain text file of NAME=value lines called `.env`.

<!-- defines: docker --> Each piece of the program runs in a container: a sealed
box holding that piece plus everything it needs to run.

Copy the .env file into place and start the containers.
"""

CODE_BLOCK_ONLY = """\
# Standing the platform up

Run the command below. It prints a line when it has finished.

```
docker compose up -d --build
sudo cp .env.example .env
```

Nothing else is needed.
"""


def test_the_gate_reports_a_planted_violation():
    slugs = {offender.slug for offender in scan(PLANTED_VIOLATION)}

    assert "env_file" in slugs, (
        "the scanner missed a bare .env with no definition anywhere in the "
        f"document; it reported {sorted(slugs)}"
    )
    assert "docker" in slugs, (
        "the scanner missed a bare 'containers' with no definition anywhere in "
        f"the document; it reported {sorted(slugs)}"
    )


def test_the_gate_stays_silent_on_a_correct_definition_and_on_code_blocks():
    defined = {offender.slug for offender in scan(CORRECT_DEFINITION)}
    assert "env_file" not in defined and "docker" not in defined, (
        "a term whose <!-- defines: --> marker sits on its own defining line "
        f"was reported anyway: {sorted(defined)}"
    )

    fenced = {offender.slug for offender in scan(CODE_BLOCK_ONLY)}
    assert "docker" not in fenced and "sudo" not in fenced, (
        "a term appearing ONLY inside a fenced command block was reported as "
        f"prose: {sorted(fenced)}"
    )
