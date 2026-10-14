#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decide whether one commit passed its `tests` workflow on GitHub.

`make deploy` asks this, through `make ci-gate`, before its `git reset --hard`,
and refuses to deploy unless the answer is green. It judges only the runs for
the exact 40-character SHA, and the newest of those decides.

Three ways to give it the runs:

    # Ask GitHub itself (what `make ci-gate` does: anonymous, the repository is public)
    python3 scripts/ci_gate.py --fetch --repo Open-H2O/openh2o --workflow tests.yml --sha <sha>

    # The REST API's answer on stdin, {"workflow_runs": [...]}
    curl -s "https://api.github.com/repos/Open-H2O/openh2o/actions/workflows/tests.yml/runs?head_sha=<sha>" \\
      | python3 scripts/ci_gate.py --sha <sha> --workflow tests.yml

    # `gh run list` JSON on stdin, a bare list or {"runs": [...]}
    gh run list -R Open-H2O/openh2o -w tests.yml --commit <sha> \\
        --json databaseId,headSha,status,conclusion,attempt,createdAt,url \\
      | python3 scripts/ci_gate.py --sha <sha> --workflow tests.yml

Exit codes:
    0  the newest run for this SHA completed with success
    2  refused: no run, still running, or any other conclusion
    3  bad input: malformed JSON, a SHA that is not 40 hex characters, or a
       repository or workflow name that is not a plain name
    4  refused: GitHub could not be asked (network error, HTTP error, rate limit)

Exit 4 fails closed on purpose. When GitHub cannot be asked, this refuses
rather than running the suite on the deploy host: the suite needs PostGIS in
Docker and takes close to half an hour on GitHub's runners, and running it on
the machine that serves the site would put load and a second stack beside the
live one.

Standard library only: it runs on the host, outside the image.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKFLOW_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RUNNING = {"queued", "in_progress", "waiting", "requested", "pending"}

API = (
    "https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs"
    "?head_sha={sha}&per_page=50"
)
TIMEOUT_SECONDS = 15

# The REST API names the same fields differently from `gh run list --json`.
REST_TO_GH = {
    "id": "databaseId",
    "head_sha": "headSha",
    "status": "status",
    "conclusion": "conclusion",
    "run_attempt": "attempt",
    "created_at": "createdAt",
    "html_url": "url",
    "event": "event",
}


class FetchError(Exception):
    """GitHub could not be asked; the message says why."""


def _from_rest(run):
    return {gh: run.get(rest) for rest, gh in REST_TO_GH.items()}


def load_runs(text):
    """Accept a bare list, {"runs": [...]}, or the REST shape {"workflow_runs": [...]}.

    Unknown top-level keys (a fixture's "_note", say) are ignored.
    """
    data = json.loads(text)
    rest = isinstance(data, dict) and "workflow_runs" in data
    if isinstance(data, dict):
        data = data.get("workflow_runs") if rest else data.get("runs", [])
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError("expected a list of run objects")
    return [_from_rest(r) for r in data] if rest else data


def verdict(runs, sha):
    """Return (exit_code, reason, run_or_None) for the newest run on this SHA."""
    mine = [r for r in runs if r.get("headSha") == sha]
    if not mine:
        return 2, "no CI run for this commit", None
    run = max(mine, key=lambda r: r.get("createdAt") or "")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status in RUNNING:
        return 2, f"CI run still running ({status})", run
    if status != "completed":
        return 2, f"CI run in an unexpected status ({status})", run
    if conclusion != "success":
        return 2, f"CI run concluded {conclusion or 'with no conclusion'}", run
    attempt = run.get("attempt") or 1
    if attempt > 1:
        return 0, f"green (passed on attempt {attempt})", run
    return 0, "green", run


def fetch(repo, workflow, sha, timeout=TIMEOUT_SECONDS):
    """Return the REST API's answer for this SHA's runs, or raise FetchError."""
    request = urllib.request.Request(
        API.format(repo=repo, workflow=workflow, sha=sha),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "openh2o-ci-gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            raise FetchError(f"rate limited, HTTP {exc.code}") from exc
        raise FetchError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise FetchError(f"network error: {exc}") from exc
    if status != 200:
        raise FetchError(f"HTTP {status}")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError("the answer was not text") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", required=True, help="full 40-character commit SHA")
    parser.add_argument("--workflow", required=True, help="workflow file name, e.g. tests.yml")
    parser.add_argument("--fetch", action="store_true", help="ask GitHub instead of reading stdin")
    parser.add_argument("--repo", help="owner/name on GitHub; required with --fetch")
    args = parser.parse_args(argv)

    sha = args.sha.strip().lower()
    if not SHA_RE.match(sha):
        print(f"ci_gate: BAD INPUT: {args.sha!r} is not a 40-character hex SHA")
        return 3
    if not WORKFLOW_RE.match(args.workflow):
        print(f"ci_gate: BAD INPUT: {args.workflow!r} is not a workflow file name")
        return 3

    if args.fetch:
        if not args.repo or not REPO_RE.match(args.repo):
            print(f"ci_gate: BAD INPUT: --fetch needs --repo owner/name (got {args.repo!r})")
            return 3
        try:
            text = fetch(args.repo, args.workflow, sha)
            runs = load_runs(text)
        except FetchError as exc:
            print(f"ci_gate: REFUSED: could not ask GitHub ({exc})")
            return 4
        except ValueError as exc:
            print(f"ci_gate: REFUSED: could not ask GitHub (the answer could not be read: {exc})")
            return 4
    else:
        try:
            runs = load_runs(sys.stdin.read())
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            print(f"ci_gate: BAD INPUT: runs JSON could not be read ({exc})")
            return 3

    code, reason, run = verdict(runs, sha)
    url = (run or {}).get("url") or "no run"
    attempt = (run or {}).get("attempt") or "-"
    word = "PASS" if code == 0 else "REFUSE"
    print(f"ci_gate: {word} {sha} {args.workflow} run={url} attempt={attempt}: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
