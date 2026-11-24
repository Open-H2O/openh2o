# SPDX-License-Identifier: AGPL-3.0-or-later
"""The figures diff (scripts/figures_moved.py) lists every printed demonstration figure that moved.

The release test tests/test_year_reading_demonstration.py writes every figure the demonstration
prints; the script compares two such files. These tests use small hand-made files, so they need no
database and no demonstration load.
"""

import importlib.util
import io
import json
import shutil
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("figures_moved", REPO / "scripts" / "figures_moved.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)


def row(name, month, figure, value, scope="use_area", method="metered", detail=""):
    """A row of a period's figures list: scope, name, month, figure, value, method, detail."""
    return [scope, name, month, figure, value, method, detail]


def year(figures=None, **extra):
    return {"figures": figures or [], **extra}


def run(before, now, tmp_path, *args):
    """The script's printed rows and summary, and its exit code, for two figure files."""
    a, b = tmp_path / "before.json", tmp_path / "now.json"
    a.write_text(json.dumps(before))
    b.write_text(json.dumps(now))
    out = io.StringIO()
    with redirect_stdout(out):
        code = fm.main(["--before", str(a), str(b), *args])
    return out.getvalue(), code


def test_a_changed_decimal_is_listed_with_its_change(tmp_path):
    before = {"WY 2024-2025": year(zone_pages={"Halvern Valley GSA": [{"used": "D:1.0000"}]})}
    now = {"WY 2024-2025": year(zone_pages={"Halvern Valley GSA": [{"used": "D:1.0950"}]})}
    text, _ = run(before, now, tmp_path)
    assert ".WY 2024-2025.zone_pages.Halvern Valley GSA[0].used\tD:1.0000\tD:1.0950\t0.0950" in text


def test_figure_rows_are_matched_by_their_key_not_their_place(tmp_path):
    a = row("MER-APN-001", "2025-06", "surface", "D:1.00")
    b = row("MER-APN-002", "2025-06", "surface", "D:2.00")
    before = {"WY 2024-2025": year([a, b])}
    reordered = {"WY 2024-2025": year([b, a])}
    text, _ = run(before, reordered, tmp_path)
    assert "MER-APN-00" not in text

    moved = {"WY 2024-2025": year([b, row("MER-APN-001", "2025-06", "surface", "D:1.25")])}
    text, _ = run(before, moved, tmp_path)
    rows = text.split("\n# ", 1)[0]
    lines = [line for line in rows.splitlines() if "MER-APN-001" in line]
    assert len(lines) == 1 and lines[0].endswith("\tD:1.00\tD:1.25\t0.25")


def test_a_key_on_one_side_only_is_listed_as_absent_on_the_other(tmp_path):
    before = {"WY 2024-2025": year(dashboard={"grand_net": "D:5"})}
    now = {"WY 2024-2025": year(dashboard={"grand_net": "D:5", "unmet_demand_total": "D:3"})}
    text, _ = run(before, now, tmp_path)
    assert ".WY 2024-2025.dashboard.unmet_demand_total\t<absent>\tD:3" in text


def test_the_summary_counts_by_year_and_section_and_names_the_largest(tmp_path):
    before = {
        "WY 2024-2025": year([row("MER-APN-038", "2025-06", "surface", "D:24.53")], dashboard={"grand_net": "D:10"}),
        "WY 2025-2026": year([row("MER-APN-038", "2026-06", "surface", "D:24.53")]),
    }
    now = {
        "WY 2024-2025": year([row("MER-APN-038", "2025-06", "surface", "D:24.67")], dashboard={"grand_net": "D:11"}),
        "WY 2025-2026": year([row("MER-APN-038", "2026-06", "surface", "D:24.60")]),
    }
    text, code = run(before, now, tmp_path)
    assert code == 0
    summary = text.split("# 3 printed values moved", 1)[1]
    assert "WY 2024-2025: 2 (dashboard 1, figures 1)" in summary
    assert "WY 2025-2026: 1 (figures 1)" in summary
    largest = summary.split("Largest", 1)[1].splitlines()
    assert "grand_net" in largest[1] and "1" in largest[1]


def test_nothing_moved_says_so_and_exits_zero(tmp_path):
    same = {"WY 2024-2025": year([row("MER-APN-001", "2025-06", "surface", "D:1.00")])}
    text, code = run(same, same, tmp_path)
    assert code == 0
    assert "No printed figure moved." in text


@pytest.mark.skipif(shutil.which("git") is None, reason="reads git, and the web image has none")
def test_the_before_file_can_come_from_a_commit(tmp_path):
    repo = tmp_path / "repo"
    stored = repo / "tests" / "data" / "demonstration_figures_before.json"
    stored.parent.mkdir(parents=True)

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    stored.write_text(json.dumps({"WY 2024-2025": year(dashboard={"grand_net": "D:1"})}))
    git("add", ".")
    git("commit", "-q", "-m", "first")
    first = git("rev-parse", "HEAD").strip()
    stored.write_text(json.dumps({"WY 2024-2025": year(dashboard={"grand_net": "D:2"})}))
    git("commit", "-q", "-am", "second")

    now = tmp_path / "now.json"
    now.write_text(json.dumps({"WY 2024-2025": year(dashboard={"grand_net": "D:2"})}))
    out = io.StringIO()
    with redirect_stdout(out):
        fm.main(["--repo", str(repo), "--base-commit", first, str(now)])
    assert ".WY 2024-2025.dashboard.grand_net\tD:1\tD:2\t1" in out.getvalue()


def test_the_figures_test_writes_where_it_is_told_and_leaves_the_stored_file(monkeypatch, tmp_path):
    from tests import test_year_reading_figures as figures

    target = tmp_path / "figures-now.json"
    monkeypatch.setenv("YEAR_FIGURES_OUT", str(target))
    assert figures.figures_out_path(Path("tests/data/demonstration_figures_before.json")) == target
    monkeypatch.delenv("YEAR_FIGURES_OUT")
    stored = Path("tests/data/demonstration_figures_before.json")
    assert figures.figures_out_path(stored) == stored
