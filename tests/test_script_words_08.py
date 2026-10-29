# SPDX-License-Identifier: AGPL-3.0-or-later
"""The writing guard reads the words a template's script puts on screen.

``scripts/writing_shapes.py`` used to drop every ``<script>`` block, so a sentence
a script prints (a ``toast(...)``, a ``textContent =``, an ``alert(...)``) was
read by nobody. It now reads the string literals passed to the calls that put
words on screen. These tests build their own small templates; none depends on
what a real page says today.

**Kill switch:** ``OPENH2O_WRITING_SHAPES_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_WRITING_SHAPES_CHECK", "1") == "0",
    reason="OPENH2O_WRITING_SHAPES_CHECK=0",
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "writing_shapes.py"


def _load():
    spec = importlib.util.spec_from_file_location("writing_shapes_script_words", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shapes = _load()


def _page(script: str) -> str:
    return f"<h1>A page</h1>\n<p>Plain words.</p>\n<script>\n{script}\n</script>\n"


def _counts(script: str) -> dict:
    return shapes.count_file("planted.html", _page(script))


def _words(script: str) -> list:
    return [run for _line, _kind, runs in shapes.script_words(_page(script))[0] for run in runs]


def test_a_sentence_a_script_prints_is_counted_for_every_call_that_shows_words():
    for line in (
        "el.textContent = 'It is simply the total.';",
        "el.innerText = 'It is simply the total.';",
        "el.innerHTML = '<p>It is simply the total.</p>';",
        "alert('It is simply the total.');",
        "if (confirm('It is simply the total.')) { go(); }",
        "toast('It is simply the total.', 'error');",
        "window.showToast('It is simply the total.');",
    ):
        assert _counts(line)["filler"] == 1, line


def test_every_shape_is_found_in_a_script_sentence():
    counts = _counts("el.textContent = 'The total -- and your district can edit it.';")
    assert counts["double hyphen"] == 1
    assert counts["district reader"] == 1
    assert _counts("note.textContent = 'The total — as stored.';")["em dash"] == 1


def test_both_branches_of_a_choice_and_a_fallback_are_read():
    assert _words("el.textContent = ok ? 'Really done' : 'Not done';") == ["Really done", "Not done"]
    assert _words("t.textContent = msg || 'Nothing to show';") == ["Nothing to show"]


def test_a_sentence_built_from_pieces_is_read_with_the_variable_as_one_word():
    assert _words("el.textContent = 'Copied ' + name + ' to the list';") == ["Copied X to the list"]
    assert _words("el.innerHTML = '<b>' + n + '</b> rows imported';") == ["X rows imported"]
    assert _words("el.textContent = `Saved ${n} rows`;") == ["Saved X rows"]


def test_a_literal_that_is_only_compared_or_looked_up_is_not_words():
    script = (
        "if (type === 'error — bad') { el.className = 'x -- y'; }\n"
        "var a = 'x — y';\n"
        "document.getElementById('a — b').style.display = 'none';\n"
        "el.textContent = type === 'really' ? 'Done' : 'Failed';\n"
    )
    assert _words(script) == ["Done", "Failed"]
    assert set(_counts(script).values()) == {0}


def test_a_comment_in_a_script_is_not_read():
    script = (
        "// el.textContent = 'simply a comment';\n"
        "/* alert('really a comment'); */\n"
        "el.textContent = 'http://example.org/path';\n"
        "{# el.textContent = 'actually a template comment'; #}\n"
    )
    assert _words(script) == ["http://example.org/path"]
    assert _counts(script)["filler"] == 0


def test_a_sentence_in_a_template_variable_slot_and_tag_is_read_around_them():
    script = (
        "{% if show %}\n"
        "el.textContent = 'Saved {{ count }} rows, simply.';\n"
        "{% endif %}\n"
    )
    assert _words(script) == ["Saved X rows, simply."]


def test_a_popup_function_that_returns_markup_is_read():
    script = (
        "function popup(p) {\n"
        "  return '<strong>' + p.name + '</strong><br>' + 'It is simply a well';\n"
        "}\n"
    )
    assert _counts(script)["filler"] == 1


def test_words_held_in_a_variable_with_a_name_for_words_are_read():
    assert _words("var hint = n + ' corners placed.';\nshow(hint);") == ["X corners placed."]


def test_a_string_built_only_from_variables_is_reported_unreadable_with_its_line():
    found, unreadable = shapes.script_words(_page("var a = 1;\nel.textContent = label;\nalert(msg);"))
    assert found == []
    assert [(line, kind) for line, kind, _expr in unreadable] == [(5, "textContent"), (6, "alert")]
    assert [expr for _line, _kind, expr in unreadable] == ["label", "msg"]


def test_a_function_definition_is_not_a_call():
    found, unreadable = shapes.script_words(_page("function toast(msg, type) { run(msg); }"))
    assert (found, unreadable) == ([], [])


def test_the_line_of_a_sentence_is_its_line_in_the_template():
    found, _unreadable = shapes.script_words(_page("var a = 1;\n\nel.textContent = 'Hello there';"))
    assert found == [(6, "textContent", ["Hello there"])]


def test_a_script_that_loads_a_file_or_prints_nothing_changes_no_count():
    source = '<script src="/static/x.js"></script><script>var a = 1; run(a);</script><p>Plain.</p>'
    assert set(shapes.count_file("planted.html", source).values()) == {0}
    assert shapes.script_words(source) == ([], [])


def test_attribute_words_a_script_sets_are_read():
    assert _words("b.setAttribute('aria-label', 'Remove it');\nb.setAttribute('data-x', 'not words');") == ["Remove it"]
