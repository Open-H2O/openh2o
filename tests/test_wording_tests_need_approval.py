# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new test may not check only exact sentences unless it says why.

A test whose every check is an exact sentence on a page holds that sentence in
place: when the maintainer rewords the page, the test fails and the next change
puts the old sentence back. CLAUDE.md has said since August 2026 that a test may
never mandate a domain description, and sentence-only tests kept arriving
anyway, about six a day in the month before this file. A written rule did not
stop them; this test does.

**The rule.** A *prose literal* is a string constant of 12 or more characters
with a space and a run of three letters. An *assertion* is an ``assert`` whose
test is a comparison (or ``not`` around one), or a call whose name starts with
``assert``. A test is *sentence-only* when it has assertions and every one
compares a prose literal, unless every literal it compares is not wording a
person reads: HTML (it starts with ``<`` or holds ``class="``), a demonstration
marker ``(DEMO)``, a path (a ``/`` with no space on either side) or shape
notation (``{`` or ``}``).

**What passes.** A sentence-only test passes when, in the two lines above its
``def`` (or its first decorator) or inside it, it carries
``# Default wording, approved by the maintainer on <date>. To change the wording,
update this test in the same commit.`` (the date the maintainer approved those
exact words) or ``# not wording: <why>``, with a reason. Every sentence-only test that existed when this file was written
is listed in ``wording_tests_baseline.txt`` and left alone. That list may only
shrink: a listed test that is gone, or no longer sentence-only, must come off it.

The scan reads the committed test files with ``ast``; it needs no database.
"""

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
BASELINE = TESTS_DIR / "wording_tests_baseline.txt"

MARK = re.compile(
    r"#\s*Default wording, approved by the maintainer on \d{4}-\d{2}-\d{2}\.\s+To change the wording, update this test"
    r"|#\s*not wording:\s*\S"
)
SHOWN = 5


# -- The detector ------------------------------------------------------------------------------


def is_prose(node):
    """A string constant of 12+ characters holding a space and a run of three letters."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) >= 12
        and " " in node.value
        and re.search(r"[A-Za-z]{3}", node.value) is not None
    )


def _prose_in(nodes):
    return [n for n in nodes if is_prose(n)]


def assertions(fn):
    """``[(assertion node, [prose literal nodes it compares])]`` for every assertion in ``fn``."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            test = node.test
            literals = []
            if isinstance(test, ast.Compare):
                literals = _prose_in([test.left, *test.comparators])
            elif isinstance(test, ast.UnaryOp) and isinstance(test.operand, ast.Compare):
                literals = _prose_in([test.operand.left, *test.operand.comparators])
            out.append((node, literals))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
        ):
            out.append((node, _prose_in(list(node.args) + [k.value for k in node.keywords])))
    return out


def not_wording(text):
    """Whether a literal is something other than wording a person reads."""
    return (
        text.startswith("<")
        or 'class="' in text
        or "(DEMO)" in text
        or re.search(r"(?<! )/(?! )", text) is not None
        or "{" in text
        or "}" in text
    )


def is_sentence_only(fn):
    """Every assertion compares a prose literal, and not every literal is something other than wording."""
    found = assertions(fn)
    if not found or not all(literals for _node, literals in found):
        return False
    texts = [lit.value for _node, literals in found for lit in literals]
    return not all(not_wording(text) for text in texts)


def _marked(fn, lines):
    """Whether the test carries a marker with a reason above its def or inside it."""
    first = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
    above = lines[max(first - 3, 0):first - 1]
    inside = lines[fn.lineno - 1:fn.end_lineno]
    return any(MARK.search(line) for line in above + inside)


def _qualname(node, parents):
    names = [node.name]
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(parent.name)
        parent = parents.get(parent)
    return "::".join(reversed(names))


def scan(source, rel):
    """``[(test id, marked)]`` for every sentence-only test in one file's source; ``rel`` is its path."""
    tree = ast.parse(source)
    lines = source.splitlines()
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    out, seen = [], set()
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")):
            continue
        if not is_sentence_only(node):
            continue
        test_id = f"{rel}::{_qualname(node, parents)}"
        if test_id in seen:
            test_id = f"{test_id}@{node.lineno}"
        seen.add(test_id)
        out.append((test_id, _marked(node, lines)))
    return out


def unmarked_in_tree(root=REPO_ROOT):
    """The ids of every sentence-only test with no marker, across ``tests/``."""
    found = set()
    for path in sorted((root / "tests").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        found |= {test_id for test_id, marked in scan(path.read_text(), rel) if not marked}
    return found


def read_baseline(text):
    return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}


def _names(ids):
    ids = sorted(ids)
    shown = ", ".join(ids[:SHOWN])
    return f"{shown} and {len(ids) - SHOWN} more" if len(ids) > SHOWN else shown


def failures(current, baseline):
    """The messages for new unmarked sentence-only tests and for baseline lines to delete."""
    out = []
    new = current - baseline
    if new:
        out.append(
            f"{len(new)} new test(s) check only exact sentences: {_names(new)}. A test that requires a "
            "sentence puts it back whenever the maintainer edits the page (CLAUDE.md: a test may never mandate a domain "
            "description). Check the fact the page must show (a number, a name, a status, that a warning is "
            "present) instead. Only if the maintainer approved this exact wording, add `# Default wording, approved by the maintainer on <date>. To change the "
            "wording, update this test in the same commit.` above the test, with the date of the approval; if the literal is not wording a person reads, add "
            "`# not wording: <why>`. Do not add it to the baseline list. (If you are not Claude: pass this to "
            "Claude.)"
        )
    gone = baseline - current
    if gone:
        out.append(
            f"{len(gone)} line(s) of tests/wording_tests_baseline.txt name a test that is gone or no longer "
            f"checks only sentences: {_names(gone)}. Delete those lines; the list only shrinks."
        )
    return out


# -- The guard ---------------------------------------------------------------------------------


def test_no_new_test_checks_only_unapproved_sentences():
    problems = failures(unmarked_in_tree(), read_baseline(BASELINE.read_text()))
    assert problems == [], "\n\n".join(problems)


# -- Self-checks, on test data ----------------------------------------------------------------

SENTENCE_ONLY = '''
def test_page_words(client):
    body = client.get("/x/").content.decode()
    assert "Every use area has a well on file." in body
'''

WITH_A_FACT = '''
def test_page_words(client):
    body = client.get("/x/").content.decode()
    assert "Every use area has a well on file." in body
    assert body.count("<tr") == 3
'''

HTML_ONLY = '''
def test_page_markup(client):
    body = client.get("/x/").content.decode()
    assert '<span class="badge">' in body
'''


def _marked_copy(marker):
    return SENTENCE_ONLY.replace("def test_page_words", f"{marker}\ndef test_page_words")


def test_a_sentence_only_test_is_caught():
    assert scan(SENTENCE_ONLY, "tests/test_x.py") == [("tests/test_x.py::test_page_words", False)]


def test_one_check_that_is_not_a_sentence_lets_it_pass():
    assert scan(WITH_A_FACT, "tests/test_x.py") == []


def test_each_marker_with_a_reason_silences_it():
    for marker in ("# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.", "# not wording: a CSS value"):
        assert scan(_marked_copy(marker), "tests/test_x.py") == [("tests/test_x.py::test_page_words", True)]


def test_a_marker_inside_the_test_counts():
    source = SENTENCE_ONLY.replace("    body =", "    # Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.\n    body =")
    assert scan(source, "tests/test_x.py") == [("tests/test_x.py::test_page_words", True)]


def test_an_empty_marker_does_not_count():
    assert scan(_marked_copy("# not wording:"), "tests/test_x.py") == [
        ("tests/test_x.py::test_page_words", False)
    ]


def test_the_old_numbered_marker_no_longer_counts():
    """A decision number points into a record no outside reader can open; the date replaces it."""
    assert scan(_marked_copy("# wording approved: decision 999"), "tests/test_x.py") == [
        ("tests/test_x.py::test_page_words", False)
    ]


def test_an_html_only_literal_passes():
    assert scan(HTML_ONLY, "tests/test_x.py") == []


def test_a_listed_test_passes():
    test_id = "tests/test_x.py::test_page_words"
    assert failures({test_id}, {test_id}) == []


def test_a_new_unlisted_test_fails():
    problems = failures({"tests/test_x.py::test_page_words"}, set())
    assert len(problems) == 1
    # not wording: the guard's own message, read for the test's id
    assert "tests/test_x.py::test_page_words" in problems[0]


def test_a_listed_test_that_is_gone_is_reported():
    problems = failures(set(), {"tests/test_x.py::test_gone"})
    assert len(problems) == 1
    # not wording: the guard's own message, read for the test's id
    assert "tests/test_x.py::test_gone" in problems[0]


def test_at_most_five_names_then_a_count():
    ids = {f"tests/test_x.py::test_{n}" for n in range(8)}
    named = _names(ids)
    assert named.count("tests/test_x.py::") == SHOWN
    assert named.endswith(" and 3 more")
