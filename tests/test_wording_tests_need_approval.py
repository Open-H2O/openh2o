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
``# wording approved: <the ruling or ROWS row>`` or ``# not wording: <why>``,
with a reason. Every sentence-only test that existed when this file was written
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

MARK = re.compile(r"#\s*(wording approved|not wording):\s*(\S.*)$")
SHOWN = 5


# -- The detector (not written yet: the self-checks below come first) ------------------------


def scan(source, rel):
    raise NotImplementedError


def failures(current, baseline):
    raise NotImplementedError


def _names(ids):
    raise NotImplementedError


SHOWN = 5


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
    for marker in ("# wording approved: ruling 999", "# not wording: a CSS value"):
        assert scan(_marked_copy(marker), "tests/test_x.py") == [("tests/test_x.py::test_page_words", True)]


def test_a_marker_inside_the_test_counts():
    source = SENTENCE_ONLY.replace("    body =", "    # wording approved: ruling 999\n    body =")
    assert scan(source, "tests/test_x.py") == [("tests/test_x.py::test_page_words", True)]


def test_an_empty_marker_does_not_count():
    assert scan(_marked_copy("# wording approved:"), "tests/test_x.py") == [
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
