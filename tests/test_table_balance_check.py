# SPDX-License-Identifier: AGPL-3.0-or-later
"""The table balance check exists, measures what it must, and is wired.

The tables with a column rule came out of balance after every fix that was
judged on one screenshot at one width, because nothing measured the spacing.
`scripts/table_balance.js` measures it in a browser and `scripts/table_check.py`
runs it on every page of a running site at three widths (`make table-check`).
The suite cannot run a browser, so this file holds the pieces in place: removing
the check, narrowing what it measures, or unwiring the sizing rule fails here.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEASURE = ROOT / "scripts" / "table_balance.js"
CHECK = ROOT / "scripts" / "table_check.py"
CSS = ROOT / "static" / "css" / "app.css"


def test_the_measurement_reports_every_kind_of_imbalance():
    # not wording: checks the result fields the check fails on
    source = MEASURE.read_text()
    for field in ("rules", "headers", "groups", "sticky_gap", "sticky_borders", "header_rules", "pass"):
        assert re.search(rf"\b{field}\b", source), field
    # The limits: a rule's two sides within 4 px, a header within 2 px of its figures.
    assert re.search(r"rule:\s*4\b", source) and re.search(r"header:\s*2\b", source)


def test_the_check_runs_the_measurement_at_three_widths_and_fails_the_run():
    # not wording: checks the script's wiring
    source = CHECK.read_text()
    assert '"table_balance.js"' in source
    assert "WIDTHS = (1024, 1440, 1730)" in source
    assert "sys.exit(1)" in source
    assert "TABLE_CHECK_PASSWORD" in source  # never a password on the command line


def test_make_table_check_runs_it():
    # not wording: checks the make target
    makefile = (ROOT / "Makefile").read_text()
    assert re.search(r"^table-check:.*\n(?:\t.*\n)*\tpython3 scripts/table_check\.py", makefile, re.M)


def test_every_page_loads_the_sizing_script():
    # not wording: checks the base template loads the shared sizing script
    base = (ROOT / "templates" / "base.html").read_text()
    assert "js/table-rule.js" in base
    assert (ROOT / "static" / "js" / "table-rule.js").exists()


def test_a_pinned_header_draws_its_lines_inside_its_cells():
    # not wording: a collapsed border on a sticky header cell leaves a strip the
    # rows scrolling beneath show through; the lines are inset or a pseudo-element
    css = CSS.read_text()
    pinned = re.search(r"\.data-table thead th \{(.*?)\}", css, re.S).group(1)
    assert "border-bottom: 0" in pinned and "inset 0 -2px 0" in pinned
    assert re.search(r"\.data-table--grouped thead th\.col-sep::before \{[^}]*left: -1px", css, re.S)
    assert re.search(r"\.data-table--grouped thead tr\.th-group ~ tr th \{\s*top: var\(--th-group-h, 36px\);", css)
