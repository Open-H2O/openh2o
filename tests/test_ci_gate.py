# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for scripts/ci_gate.py, the deploy path's "is this commit green" check.

`make ci-gate` runs the script on the host, as its own process, before
`make deploy` touches anything. The verdict tests call it the same way, runs
JSON on stdin. The --fetch tests load it in-process so they can replace
`urllib.request.urlopen`: none of them reaches the network, which is why none
carries the `network` marker.

The fixtures are invented runs (TEST DATA) with example.invalid URLs.
"""

import email.message
import importlib.util
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci_gate.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ci_gate"
SHA = "a" * 40


def _load():
    spec = importlib.util.spec_from_file_location("ci_gate_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_gate = _load()


def gate(stdin, sha=SHA):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--sha", sha, "--workflow", "tests.yml"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def gate_fixture(name, sha=SHA):
    return gate((FIXTURES / f"{name}.json").read_text(), sha=sha)


# -- The verdict, from `gh run list` JSON ------------------------------------


def test_green_run_passes():
    result = gate_fixture("green")
    assert result.returncode == 0, result.stdout
    assert "PASS" in result.stdout
    assert SHA in result.stdout
    assert "https://example.invalid/runs/1" in result.stdout


def test_failed_run_refused():
    result = gate_fixture("failed")
    assert result.returncode == 2, result.stdout
    assert "concluded failure" in result.stdout


def test_cancelled_run_refused():
    result = gate_fixture("cancelled")
    assert result.returncode == 2, result.stdout
    assert "concluded cancelled" in result.stdout


def test_run_in_progress_refused():
    result = gate_fixture("in_progress")
    assert result.returncode == 2, result.stdout
    assert "still running" in result.stdout


def test_no_run_refused():
    result = gate_fixture("no_run")
    assert result.returncode == 2, result.stdout
    assert "no CI run for this commit" in result.stdout


def test_bare_list_accepted():
    runs = json.loads((FIXTURES / "green.json").read_text())["runs"]
    result = gate(json.dumps(runs))
    assert result.returncode == 0, result.stdout


def test_newer_failed_run_beats_older_green():
    result = gate_fixture("newer_decides_red")
    assert result.returncode == 2, result.stdout
    assert "runs/6" in result.stdout


def test_newer_green_rerun_passes_and_names_attempt():
    result = gate_fixture("newer_decides_green")
    assert result.returncode == 0, result.stdout
    assert "passed on attempt 2" in result.stdout


def test_run_for_a_sha_sharing_the_prefix_does_not_count():
    result = gate_fixture("prefix_twin")
    assert result.returncode == 2, result.stdout
    assert "no CI run for this commit" in result.stdout


# -- The verdict, from the REST API's shape ------------------------------------


def test_rest_green_run_passes():
    result = gate_fixture("rest_green")
    assert result.returncode == 0, result.stdout
    assert "https://example.invalid/runs/11" in result.stdout


def test_rest_failed_run_refused():
    result = gate_fixture("rest_failed")
    assert result.returncode == 2, result.stdout
    assert "concluded failure" in result.stdout


def test_rest_run_in_progress_refused():
    result = gate_fixture("rest_in_progress")
    assert result.returncode == 2, result.stdout
    assert "still running (in_progress)" in result.stdout


def test_rest_no_run_refused():
    result = gate_fixture("rest_empty")
    assert result.returncode == 2, result.stdout
    assert "no CI run for this commit" in result.stdout


def test_rest_newer_failed_run_beats_older_green():
    result = gate_fixture("rest_newer_decides_red")
    assert result.returncode == 2, result.stdout
    assert "runs/15" in result.stdout


# -- Bad input -----------------------------------------------------------------


def test_short_sha_is_bad_input():
    result = gate_fixture("green", sha="a" * 7)
    assert result.returncode == 3, result.stdout
    assert "BAD INPUT" in result.stdout


def test_non_hex_sha_is_bad_input():
    result = gate_fixture("green", sha="z" * 40)
    assert result.returncode == 3, result.stdout


def test_malformed_json_is_bad_input():
    result = gate("{not json")
    assert result.returncode == 3, result.stdout
    assert "BAD INPUT" in result.stdout


# -- Asking GitHub (--fetch), with the network replaced --------------------------


class _Answer:
    """Stands in for the response object urlopen returns."""

    def __init__(self, body, status=200):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, remaining=None):
    headers = email.message.Message()
    if remaining is not None:
        headers["X-RateLimit-Remaining"] = remaining
    return urllib.error.HTTPError(
        "https://example.invalid/api", code, "error", headers, io.BytesIO(b"{}")
    )


def _fetch(monkeypatch, capsys, urlopen, repo="Open-H2O/openh2o"):
    monkeypatch.setattr(ci_gate.urllib.request, "urlopen", urlopen)
    argv = ["--fetch", "--repo", repo, "--workflow", "tests.yml", "--sha", SHA]
    code = ci_gate.main(argv)
    return code, capsys.readouterr().out


def test_fetch_green_passes_and_asks_for_this_sha(monkeypatch, capsys):
    asked = []

    def urlopen(request, timeout):
        asked.append((request.full_url, timeout))
        return _Answer((FIXTURES / "rest_green.json").read_text())

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 0, out
    assert "PASS" in out
    [(url, timeout)] = asked
    assert url.startswith(
        "https://api.github.com/repos/Open-H2O/openh2o/actions/workflows/tests.yml/runs?"
    )
    assert f"head_sha={SHA}" in url
    assert timeout == 15


def test_fetch_failed_run_refused(monkeypatch, capsys):
    def urlopen(request, timeout):
        return _Answer((FIXTURES / "rest_failed.json").read_text())

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 2, out
    assert "concluded failure" in out


def test_fetch_network_failure_refuses_with_4(monkeypatch, capsys):
    def urlopen(request, timeout):
        raise urllib.error.URLError("Name or service not known")

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 4, out
    assert "REFUSED: could not ask GitHub (network error: Name or service not known)" in out


def test_fetch_timeout_refuses_with_4(monkeypatch, capsys):
    def urlopen(request, timeout):
        raise TimeoutError("timed out")

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 4, out
    assert "could not ask GitHub" in out


def test_fetch_rate_limit_refuses_with_4(monkeypatch, capsys):
    def urlopen(request, timeout):
        raise _http_error(403, remaining="0")

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 4, out
    assert "rate limited, HTTP 403" in out


def test_fetch_http_error_refuses_with_4(monkeypatch, capsys):
    def urlopen(request, timeout):
        raise _http_error(502)

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 4, out
    assert "could not ask GitHub (HTTP 502)" in out


def test_fetch_unreadable_answer_refuses_with_4(monkeypatch, capsys):
    def urlopen(request, timeout):
        return _Answer("<html>not json</html>")

    code, out = _fetch(monkeypatch, capsys, urlopen)
    assert code == 4, out
    assert "could not ask GitHub" in out


@pytest.mark.parametrize("repo", [None, "openh2o", "Open-H2O/openh2o?x=1", "a/b/c"])
def test_fetch_without_a_plain_repo_is_bad_input_and_asks_nothing(monkeypatch, capsys, repo):
    def urlopen(request, timeout):
        raise AssertionError("must not ask GitHub")

    monkeypatch.setattr(ci_gate.urllib.request, "urlopen", urlopen)
    argv = ["--fetch", "--workflow", "tests.yml", "--sha", SHA]
    if repo is not None:
        argv += ["--repo", repo]
    assert ci_gate.main(argv) == 3
    assert "BAD INPUT" in capsys.readouterr().out
