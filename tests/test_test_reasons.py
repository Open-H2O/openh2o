# SPDX-License-Identifier: AGPL-3.0-or-later
"""The check that lists the Test-Change lines a release will ask for, read from git alone.

Each case builds a small repository in a temporary folder, commits an old test, changes it in a
later commit and runs the script against it with the base given as a commit, so nothing reaches
the network. The web image has no git, so these skip there and run on the host.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "test_reasons.py"
sys.path.insert(0, str(ROOT / "scripts"))

import test_reasons as tr  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the check reads git, and the web image has none")


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def write(repo, path, text):
    target = Path(repo) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def commit(repo, message, *paths):
    for p in paths:
        git(repo, "add", "--", p)
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    git(r, "config", "commit.gpgsign", "false")
    write(r, "tests/test_a.py", "def test_a():\n    assert 1\n")
    write(r, "tests/test_b.py", "from tests import districts\n\n\ndef test_b():\n    assert districts\n")
    write(r, "tests/test_c.py", "import tests.test_b\n\n\ndef test_c():\n    assert tests.test_b\n")
    write(r, "tests/test_d.py", "def test_d():\n    assert 1\n")
    write(r, "tests/districts.py", "NAMES = []\n")
    write(r, "tests/sub/test_e.py", "def test_e():\n    assert 1\n")
    write(r, "conftest.py", "import pytest\n")
    write(r, "app.py", "x = 1\n")
    commit(r, "base", "tests", "conftest.py", "app.py")
    return r


def base_of(repo):
    return git(repo, "rev-parse", "HEAD")


def check(repo, base, *extra, capsys):
    rc = tr.main(["check", "--repo", str(repo), "--base", base, *extra])
    return rc, capsys.readouterr().out


def asked(repo, base, capsys):
    rc, out = check(repo, base, "--json", capsys=capsys)
    return rc, json.loads(out)


def test_a_changed_old_test_without_a_line_is_missing(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    sha = commit(repo, "feat: change a", "tests/test_a.py")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 1
    assert f"Test-Change: tests/test_a.py: <reason>  (changed by {sha[:7]})" in out.splitlines()


def test_the_hint_stays_out_of_the_reason_and_the_command_is_printed_once(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: change a", "tests/test_a.py")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 1
    assert out.count("git commit --allow-empty") == 1
    command = [line for line in out.splitlines() if "git commit --allow-empty" in line][0]
    assert "changed by" not in command


def test_a_line_in_a_later_empty_commit_covers_it(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: change a", "tests/test_a.py")
    commit(repo, "chore: reasons\n\nTest-Change: tests/test_a.py: the answer is now two")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 0
    assert "0 lines missing" in out


def test_a_folder_line_covers_the_files_under_it(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/sub/test_e.py", "def test_e():\n    assert 2\n")
    commit(repo, "feat: change e", "tests/sub/test_e.py")
    rc, _ = check(repo, base, capsys=capsys)
    assert rc == 1
    commit(repo, "chore: reasons\n\nTest-Change: tests/sub/: the folder's answers moved")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 0
    assert "0 lines missing" in out


def test_a_deleted_old_test_is_asked_for(repo, capsys):
    base = base_of(repo)
    git(repo, "rm", "-q", "tests/test_d.py")
    commit(repo, "feat: drop d")
    rc, data = asked(repo, base, capsys)
    assert rc == 1
    assert data["missing"] == ["tests/test_d.py"]


def test_a_new_test_file_is_not_asked_for(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_new.py", "def test_new():\n    assert 1\n")
    commit(repo, "test: add new", "tests/test_new.py")
    rc, data = asked(repo, base, capsys)
    assert rc == 0
    assert data["asked"] == []


def test_a_rename_is_the_old_path_deleted(repo, capsys):
    base = base_of(repo)
    git(repo, "mv", "tests/test_d.py", "tests/test_d2.py")
    commit(repo, "refactor: rename d")
    rc, data = asked(repo, base, capsys)
    assert rc == 1
    assert data["asked"] == ["tests/test_d.py"]


def test_a_changed_helper_asks_for_its_importer_and_the_importers_importer(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/districts.py", "NAMES = ['x']\n")
    commit(repo, "feat: districts", "tests/districts.py")
    rc, data = asked(repo, base, capsys)
    assert rc == 1
    assert data["asked"] == ["tests/test_b.py", "tests/test_c.py"]


def test_a_dependent_line_names_the_changed_file_it_names(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/districts.py", "NAMES = ['x']\n")
    sha = commit(repo, "feat: districts", "tests/districts.py")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 1
    assert f"Test-Change: tests/test_b.py: <reason>  (names tests/districts.py, changed by {sha[:7]})" in out.splitlines()


def test_a_changed_conftest_does_not_fan_out(repo, capsys):
    base = base_of(repo)
    write(repo, "conftest.py", "import pytest\n\nVALUE = 1\n")
    commit(repo, "feat: conftest", "conftest.py")
    rc, data = asked(repo, base, capsys)
    assert rc == 0
    assert data["asked"] == []


def test_an_uncommitted_change_is_listed_and_does_not_fail(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 3\n")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 0
    assert "will need a line when committed" in out
    assert "tests/test_a.py" in out


def test_a_fix_commit_that_changes_an_old_test_and_code_is_a_notice(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    write(repo, "app.py", "x = 2\n")
    sha = commit(repo, "fix: the answer", "tests/test_a.py", "app.py")
    commit(repo, "chore: reasons\n\nTest-Change: tests/test_a.py: the answer is now two")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 0
    assert f"Fix-Test: {sha[:7]}: <reason>" in out
    commit(repo, f"chore: more\n\nFix-Test: {sha[:7]}: it failed before the fix")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 0
    assert "Fix-Test: " + sha[:7] + ": <reason>" not in out


def test_the_live_commit_is_read_once_an_hour(repo, capsys, monkeypatch):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: change a", "tests/test_a.py")
    calls = []

    def footer(url):
        calls.append(url)
        return f"v1.0-3-g{base[:10]}-dirty"

    clock = [1_000_000.0]
    monkeypatch.setattr(tr, "fetch_footer", footer)
    monkeypatch.setattr(tr.time, "time", lambda: clock[0])
    monkeypatch.setenv("OPENH2O_SITE_URL", "https://example.test/")
    rc = tr.main(["check", "--repo", str(repo)])
    assert rc == 1
    assert calls == ["https://example.test/"]
    assert f"base {base[:8]} (live footer)" in capsys.readouterr().out
    clock[0] += 1800
    rc = tr.main(["check", "--repo", str(repo)])
    assert rc == 1
    assert len(calls) == 1
    assert "cached 30 min ago" in capsys.readouterr().out
    clock[0] += 3600
    tr.main(["check", "--repo", str(repo)])
    assert len(calls) == 2


def test_an_unreachable_site_uses_the_cache_and_says_its_age(repo, capsys, monkeypatch):
    base = base_of(repo)
    clock = [2_000_000.0]
    monkeypatch.setattr(tr.time, "time", lambda: clock[0])
    monkeypatch.setattr(tr, "fetch_footer", lambda url: f"v1.0-3-g{base[:10]}")
    assert tr.main(["check", "--repo", str(repo)]) == 0
    capsys.readouterr()

    def down(url):
        raise OSError("no route")

    monkeypatch.setattr(tr, "fetch_footer", down)
    clock[0] += 3 * 3600
    assert tr.main(["check", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "site unreachable" in out
    assert "3 h old" in out


def test_the_footer_is_asked_for_with_its_own_user_agent(monkeypatch):
    # openh2o.com answers Python's default agent with 403 Forbidden (seen 2026-11-18), which
    # would leave every live read on the cache or on exit 3.
    seen = []

    class Page:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'<span class="app-footer-version">v3.0-106-g4c4ec105</span>'

    def urlopen(request, timeout):
        seen.append(request)
        return Page()

    monkeypatch.setattr(tr.urllib.request, "urlopen", urlopen)
    assert tr.fetch_footer("https://example.test/") == "v3.0-106-g4c4ec105"
    agent = seen[0].get_header("User-agent") or ""
    assert agent and not agent.startswith("Python-urllib")


def test_an_unreachable_site_with_no_cache_is_exit_three_and_ignores_tags(repo, capsys, monkeypatch):
    git(repo, "tag", "v9.9")

    def down(url):
        raise OSError("no route")

    monkeypatch.setattr(tr, "fetch_footer", down)
    rc = tr.main(["check", "--repo", str(repo)])
    assert rc == 3
    err = capsys.readouterr().err
    assert "live" in err
    assert "v9.9" not in err


def test_a_base_that_is_not_an_ancestor_falls_back_to_the_merge_base(repo, capsys):
    fork = base_of(repo)
    git(repo, "checkout", "-q", "-b", "other")
    write(repo, "tests/test_d.py", "def test_d():\n    assert 4\n")
    commit(repo, "feat: other side", "tests/test_d.py")
    other = base_of(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: main side", "tests/test_a.py")
    rc, data = asked(repo, other, capsys)
    assert rc == 1
    assert data["base"] == fork
    assert data["asked"] == ["tests/test_a.py"]


def test_an_unknown_base_is_exit_three(repo, capsys):
    rc, _ = check(repo, "0" * 40, capsys=capsys)
    assert rc == 3


def test_it_runs_isolated_from_another_folder(repo, tmp_path):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: change a", "tests/test_a.py")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    done = subprocess.run(
        [sys.executable, "-I", str(TOOL), "check", "--repo", str(repo), "--base", base],
        capture_output=True,
        text=True,
        cwd=elsewhere,
    )
    assert done.returncode == 1
    assert "Test-Change: tests/test_a.py: <reason>" in done.stdout


def test_the_first_line_says_what_was_checked(repo, capsys):
    base = base_of(repo)
    write(repo, "tests/test_a.py", "def test_a():\n    assert 2\n")
    commit(repo, "feat: change a", "tests/test_a.py")
    rc, out = check(repo, base, capsys=capsys)
    assert rc == 1
    first = out.splitlines()[0]
    assert f"base {base[:8]} (given)" in first
    assert "1 old test file changed" in first
    assert "1 line missing" in first
