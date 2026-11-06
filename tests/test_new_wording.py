# SPDX-License-Identifier: AGPL-3.0-or-later
"""The list of a plan's new wording: every sentence and label a reader will see, and nothing else."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "new_wording.py"
sys.path.insert(0, str(ROOT / "scripts"))

import new_wording as nw  # noqa: E402


def texts(lines) -> set:
    return {line["text"] for line in lines}


def listed(base: dict, head: dict) -> list:
    return nw.new_lines(base, head)[0]


T = "templates/x.html"


def test_a_one_word_column_heading_is_listed_as_a_label():
    lines = listed({T: "<table></table>"}, {T: "<table><tr><th>Fetched</th></tr></table>"})
    assert [(line["text"], line["kind"]) for line in lines] == [("Fetched", "label")]


def test_text_in_a_comment_block_is_not_listed():
    head = "{% comment %}Words nobody will ever read here.{% endcomment %}<p>Hello there, reader of pages.</p>"
    assert texts(listed({T: ""}, {T: head})) == {"Hello there, reader of pages."}


def test_a_sentence_moved_to_another_file_is_not_new():
    words = "<p>USGS has revised these readings on file.</p>"
    assert listed({"templates/a.html": words, "templates/b.html": ""},
                  {"templates/a.html": "", "templates/b.html": words}) == []


def test_a_sentence_copied_to_another_page_is_listed():
    words = "<p>The value here is not a number.</p>"
    lines = listed({"templates/a.html": words, "templates/b.html": ""}, {"templates/a.html": words, "templates/b.html": words})
    assert [(line["file"], line["text"]) for line in lines] == [("templates/b.html", "The value here is not a number.")]
    assert lines[0]["today"] == "(the same words on another page)"


def test_a_label_copied_to_another_page_is_not_listed():
    words = "<th>Date received</th>"
    assert listed({"templates/a.html": words, "templates/b.html": ""}, {"templates/a.html": words, "templates/b.html": words}) == []


def test_a_sentence_whose_only_change_is_a_figure_is_not_new():
    base = "<p>USGS has revised {{ count }} readings on file.</p>"
    head = "<p>USGS has revised {{ revised_count|intcomma }} readings on file.</p>"
    assert listed({T: base}, {T: head}) == []


def test_model_text_a_form_can_print_is_listed():
    head = (
        "from django.db import models\n"
        "class A(models.Model):\n"
        "    a = models.CharField(help_text='Short help', verbose_name='Name', choices=[('x', 'Label A')])\n"
    )
    lines = listed({"core/models.py": ""}, {"core/models.py": head})
    assert texts(lines) == {"Short help", "Name", "Label A"}
    assert {line["kind"] for line in lines} == {"model text"}


def test_a_guide_sentence_in_a_code_fence_is_not_listed():
    head = "# Upgrades\n\nRun the upgrade after a backup.\n\n```\nmake the upgrade run now\n```\n"
    assert texts(listed({"DEPLOY.md": ""}, {"DEPLOY.md": head})) == {"Upgrades", "Run the upgrade after a backup."}


ROWS = """
| # | Where | Today | Proposed |
|---|---|---|---|
| 1 | List | Fetched is the day OpenH2O got it. | USGS changed these readings after OpenH2O received them. |
| 2 | Column | Fetched | Date received |
| 3 | Page | First fetched | USGS has revised 94 readings on file. |
"""


def test_a_sentence_in_the_proposed_column_passes():
    lines = [{"file": T, "kind": "sentence", "today": "", "text": "USGS changed these readings after OpenH2O received them."},
             {"file": T, "kind": "label", "today": "", "text": "Date received"}]
    assert nw.not_in_rows(lines, nw.approved_words([ROWS])) == []


def test_a_sentence_only_in_the_today_column_does_not_pass():
    lines = [{"file": T, "kind": "sentence", "today": "", "text": "Fetched is the day OpenH2O got it."},
             {"file": T, "kind": "label", "today": "", "text": "Fetched"}]
    assert texts(nw.not_in_rows(lines, nw.approved_words([ROWS]))) == {"Fetched is the day OpenH2O got it.", "Fetched"}


def test_a_row_showing_a_figure_passes_the_sentence_that_prints_it():
    lines = [{"file": T, "kind": "sentence", "today": "", "text": "USGS has revised X readings on file."}]
    assert nw.not_in_rows(lines, nw.approved_words([ROWS])) == []


def test_the_fixed_column_counts_and_a_label_needs_its_own_words():
    rows = "| # | Where | Now | Fixed |\n|---|---|---|---|\n| 1 | A | Old words here | New words here |\n"
    words = nw.approved_words([rows])
    assert nw.not_in_rows([{"file": T, "kind": "sentence", "today": "", "text": "New words here"}], words) == []
    assert texts(nw.not_in_rows([{"file": T, "kind": "label", "today": "", "text": "Old words"}], words)) == {"Old words"}


def test_a_label_inside_an_approved_sentence_does_not_pass():
    rows = "| # | Where | Today | Proposed |\n|---|---|---|---|\n| 1 | A | Old | Status of the right on file |\n| 2 | B | Old | Date revised, Date received |\n"
    words = nw.approved_words([rows])
    lines = [{"file": T, "kind": "label", "today": "", "text": "Status"},
             {"file": T, "kind": "label", "today": "", "text": "Date received"}]
    assert texts(nw.not_in_rows(lines, words)) == {"Status"}


def test_approved_sentences_in_the_corrections_file_count():
    corrections = ("## Sentences approved, kept as the model to write toward\n\n### 2026-11-05\n\n"
                   "1. (Station page, under the readings) USGS has revised X readings on file.\n")
    lines = [{"file": T, "kind": "sentence", "today": "", "text": "USGS has revised X readings on file."}]
    assert nw.not_in_rows(lines, nw.approved_words([corrections])) == []


PY = "accounting/views/x.py"


def test_a_field_name_and_a_route_are_not_listed_and_a_message_is():
    head = (
        "def view(request):\n"
        "    url = reverse('accounting:period_detail')\n"
        "    name = 'field_name'\n"
        "    messages.success(request, 'OpenH2O saved the reading.')\n"
        "    return 'not a sentence at all without an end'\n"
    )
    assert "OpenH2O saved the reading." in texts(listed({PY: ""}, {PY: head}))
    assert not {"accounting:period_detail", "field_name"} & texts(listed({PY: ""}, {PY: head}))


def test_a_short_message_and_a_form_label_are_listed():
    head = (
        "def view(request):\n"
        "    messages.error(request, 'Not saved.')\n"
        "    field = forms.CharField(label='Date received')\n"
    )
    assert texts(listed({PY: ""}, {PY: head})) == {"Not saved.", "Date received"}


def test_a_short_string_of_code_is_left_out_and_counted():
    head = "x = 'plain_word'\ny = 'notice'\nz = 'PXD'\nw = 'datasync:station_revised'\nv = '<a href=\"x\">y</a>'\n"
    lines, left_out = nw.new_lines({PY: ""}, {PY: head})
    assert lines == []
    assert left_out == 5


def test_a_short_string_that_reads_as_words_is_listed():
    head = (
        "a = 'Revised (station reading)'\n"
        "b = 'Record voided.'\n"
        "c = 'a former user'\n"
        "d = 'Void'\n"
        "e = f'Showing all {n}'\n"
    )
    assert texts(listed({PY: ""}, {PY: head})) == {
        "Revised (station reading)", "Record voided.", "a former user", "Void", "Showing all X"}


def test_a_sentence_built_with_an_f_string_is_read_whole():
    head = "def f(n):\n    return f'USGS sent {n} new readings.'\n"
    assert texts(listed({PY: ""}, {PY: head})) == {"USGS sent X new readings."}


def test_a_replaced_sentence_carries_its_today_words():
    base = "<p>USGS revised these readings after OpenH2O first fetched them.</p><p>Nothing like the next one at all.</p>"
    head = "<p>USGS revised these readings after OpenH2O received them.</p><p>Plain and quite separate wording.</p>"
    today = {line["text"]: line["today"] for line in listed({T: base}, {T: head})}
    assert today["USGS revised these readings after OpenH2O received them."] == \
        "USGS revised these readings after OpenH2O first fetched them."
    assert today["Plain and quite separate wording."] == ""


def test_a_drawing_lists_its_own_words():
    drawing = "<html><head><title>Mock</title><style>p{color:red}</style></head><body><th>Fetched</th><p>On file today.</p></body></html>"
    lines = nw.drawing_lines({"mock.html": drawing}, {T: "<p>On file today.</p>"})
    assert texts(lines) == {"Fetched"}


def test_a_drawing_leaves_out_its_figures_and_dates_and_says_a_line_once():
    one = "<td>103.00 ft3/s</td><td>Jul 31, 2026</td><td>Jul 31, 2026 00:00</td><th>Fetched</th>"
    two = "<th>Fetched</th>"
    assert [line["text"] for line in nw.drawing_lines({"a.html": one, "b.html": two}, {})] == ["Fetched"]


def test_batches_carry_where_and_a_key(tmp_path):
    lines = [{"file": T, "kind": "label", "today": "", "text": f"Word {n}"} for n in range(5)]
    nw.write_batches(lines, tmp_path, size=2)
    assert sorted(p.name for p in tmp_path.glob("batch-*.txt")) == ["batch-01.txt", "batch-02.txt", "batch-03.txt"]
    assert (tmp_path / "batch-01.txt").read_text().splitlines()[0] == f"L001 | {T} | Word 0"
    assert json.loads((tmp_path / "key.json").read_text())["L005"]["text"] == "Word 4"


@pytest.mark.skipif(not (ROOT / ".git").exists() or shutil.which("git") is None, reason="needs the repository's history")
def test_the_real_history_lists_both_fetched_lines():
    done = subprocess.run([sys.executable, str(TOOL), "--since", "3b329547", "--until", "1f75a2fe", "--json"],
                          capture_output=True, text=True, cwd=ROOT, check=True)
    found = {line["text"] for line in json.loads(done.stdout)["lines"]}
    assert "Fetched" in found
    assert "Fetched is the day OpenH2O got it." in found
