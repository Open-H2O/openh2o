#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""List the Test-Change lines a release will ask for, from git alone, before the release check runs.

The release check (scripts/regress.py) runs the live release's tests against the candidate's code
and refuses every failing old test that no commit between the two excuses with a line:

    Test-Change: <test file or folder>: <reason>

Writing those lines at release time costs hours, because the reason has to be rebuilt from commits.
The plan that changed the test knows the reason the day it changes it. This script runs no test. It
reads git, lists every old test file that will need a line, and says which of them already have one.

    python3 -I scripts/test_reasons.py check [--repo DIR] [--base live|COMMIT] [--head HEAD] [--json]

Asked for: each old test file (under tests/, or conftest.py) that the range changed or deleted,
and each old ``test_*.py`` that names one of the changed files under tests/ by its stem as a whole
word, followed through test files until nothing new turns up. conftest.py and ``__init__`` are
not followed, because nearly every test uses them. A rename counts as the old path deleted. A
line covers a file when its path is the file or a folder above it, as regress.py reads them.

``--base live`` (the default) reads the commit on openh2o.com the way deploy.sh does: the
footer's ``git describe`` names it. The answer is kept for an hour in the repository's
``test-reasons-live`` file; an unreachable site falls back to the kept answer and says how old it
is; with none kept the exit is 3. It never falls back to a release tag.

Exit 0: no line missing. 1: lines missing (each printed). 3: the live commit or the repository
cannot be read. Uncommitted edits to old tests and fix commits that may need a Fix-Test line are
printed as notices and never fail the check. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Copied verbatim from scripts/regress.py: FIX_RE line 55, TEST_FILE_RE line 56, DOC_RE line 57,
# TEST_CHANGE_RE line 58, FIX_TEST_RE line 59. The meaning of a reason is regress.py's, not this file's.
FIX_RE = re.compile(r"^fix|\bfix(es|ed)?\b", re.I)
TEST_FILE_RE = re.compile(r"(^|/)(tests?|Tests|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|\.test\.(js|ts|mjs)$|Tests?\.swift$|(^|/)tests\.py$")
DOC_RE = re.compile(r"\.md$|(^|/)docs/|(^|/)\.planning/")
TEST_CHANGE_RE = re.compile(r"^\s*Test-Change:\s*([^:\s][^:]*?)\s*:\s*(\S.*?)\s*$")
FIX_TEST_RE = re.compile(r"^\s*Fix-Test:\s*([0-9a-fA-F]{7,40})\s*:\s*(\S.*?)\s*$")

DEFAULT_SITE = "https://openh2o.com/"
CACHE_NAME = "test-reasons-live"
CACHE_SECONDS = 3600
FOOTER_SECONDS = 10
SHAS_SHOWN = 4


class Unreadable(Exception):
    """The repository or the live commit cannot be read (exit 3)."""


def norm(path):
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def git(repo, *args, data=None, check=True):
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
        input=data,
        capture_output=True,
    )
    if check and done.returncode != 0:
        raise Unreadable(f"git {' '.join(args[:2])} failed in {repo}: {done.stderr.decode(errors='replace').strip()}")
    return done


def git_text(repo, *args, check=True):
    return git(repo, *args, check=check).stdout.decode(errors="replace")


def resolve(repo, rev):
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    sha = done.stdout.decode().strip()
    return sha if done.returncode == 0 and sha else None


def fetch_footer(url):
    """The footer's version string, as deploy.sh reads it (app-footer-version element)."""
    with urllib.request.urlopen(url, timeout=FOOTER_SECONDS) as page:
        text = page.read().decode("utf-8", errors="replace")
    m = re.search(r'app-footer-version"[^>]*>([^<]*)<', text)
    return m.group(1).strip() if m else ""


def age_words(seconds):
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def cache_file(repo):
    out = git_text(repo, "rev-parse", "--git-path", CACHE_NAME).strip()
    path = Path(out)
    return path if path.is_absolute() else Path(repo) / path


def read_cache(repo):
    try:
        sha, stamp = cache_file(repo).read_text().split()
        return sha, float(stamp)
    except (OSError, ValueError):
        return None


def live_base(repo):
    """The commit on the live site: (sha, how it was read)."""
    cached = read_cache(repo)
    now = time.time()
    if cached and resolve(repo, cached[0]) and 0 <= now - cached[1] < CACHE_SECONDS:
        return cached[0], f"live footer, cached {age_words(now - cached[1])} ago"
    url = os.environ.get("OPENH2O_SITE_URL") or DEFAULT_SITE
    try:
        desc = fetch_footer(url)
        problem = "the footer holds no version" if not desc else ""
    except Exception as exc:  # any network failure falls back to the kept answer
        desc, problem = "", f"{type(exc).__name__}: {exc}"
    if desc:
        desc = desc[: -len("-dirty")] if desc.endswith("-dirty") else desc
        short = desc.rsplit("-g", 1)[1] if "-g" in desc else desc
        sha = resolve(repo, short)
        if not sha:
            raise Unreadable(f"the live site names {short!r}, which this repository does not have; fetch origin and run again")
        try:
            cache_file(repo).write_text(f"{sha} {int(now)}\n")
        except OSError:
            pass
        return sha, "live footer"
    if cached and resolve(repo, cached[0]):
        return cached[0], f"live footer kept {age_words(now - cached[1])} old, site unreachable ({problem})"
    raise Unreadable(f"cannot read the live commit from {url} ({problem}) and none is kept; pass --base COMMIT")


def in_tests(path):
    return path.startswith("tests/") or path == "conftest.py"


def is_test(path):
    return re.search(r"(^|/)test_[^/]*\.py$", path) is not None


def stem(path):
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def read_blobs(repo, rev, paths):
    """Contents of each path at rev, through one git cat-file process."""
    if not paths:
        return {}
    wanted = [f"{rev}:{p}\n" for p in paths]
    raw = git(repo, "cat-file", "--batch", data="".join(wanted).encode()).stdout
    out, pos = {}, 0
    for p in paths:
        end = raw.index(b"\n", pos)
        header = raw[pos:end].split()
        if len(header) < 3 or header[1] != b"blob":
            pos = end + 1
            out[p] = ""
            continue
        size = int(header[2])
        out[p] = raw[end + 1 : end + 1 + size].decode(errors="replace")
        pos = end + 1 + size + 1
    return out


def fan_out(seeds, texts):
    """Old test files that name a seed's stem, then each such file's stem, until nothing is new."""
    words = {p: set(re.findall(r"\w+", t)) for p, t in texts.items() if is_test(p)}
    found = {}
    frontier = [(s, s) for s in sorted(seeds)]
    while frontier:
        nxt = []
        for current, root in frontier:
            name = stem(current)
            if name in ("conftest", "__init__"):
                continue
            plain = re.fullmatch(r"\w+", name) is not None
            pattern = None if plain else re.compile(r"\b" + re.escape(name) + r"\b")
            for p in sorted(words):
                if p == current or p in found:
                    continue
                if (name in words[p]) if plain else bool(pattern.search(texts[p])):
                    found[p] = root
                    nxt.append((p, root))
        frontier = nxt
    return found


def changed_between(repo, base, head):
    out = {}
    for line in git_text(repo, "diff", "--name-status", "--no-renames", base, head).splitlines():
        status, path = line.split("\t", 1)
        if in_tests(path) and status in ("M", "D"):
            out[path] = status
    return out


def commits_by_path(repo, base, head):
    """path -> short shas of the commits in base..head that touched it, newest first."""
    log = git_text(repo, "log", "--no-renames", "--name-only", "--format=@%h", f"{base}..{head}")
    by_path, sha = {}, None
    for line in log.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        elif line.strip() and sha:
            by_path.setdefault(line.strip(), []).append(sha)
    return by_path


def reasons_in_range(repo, base, head):
    log = git_text(repo, "log", "--format=%H%x00%B%x1e", f"{base}..{head}")
    changes, fix_tests = [], []
    for entry in log.split("\x1e"):
        entry = entry.strip("\n")
        if not entry:
            continue
        sha, body = entry.split("\0", 1)
        for line in body.splitlines():
            m = TEST_CHANGE_RE.match(line)
            if m:
                changes.append(norm(m.group(1)))
            m = FIX_TEST_RE.match(line)
            if m:
                fix_tests.append(m.group(1).lower())
    return changes, fix_tests


def covered_by(path, specs):
    for spec in specs:
        spec = spec.rstrip("/")
        if path == spec or path.startswith(spec + "/"):
            return True
    return False


def fix_notices(repo, base, head, base_paths, fix_tests):
    """Fix commits that change an old test file and code, with no Fix-Test line naming them."""
    notices = []
    shas = git_text(repo, "rev-list", "--no-merges", "--reverse", f"{base}..{head}").split()
    for sha in shas:
        subject = git_text(repo, "log", "-1", "--format=%s", sha).strip()
        if not FIX_RE.search(subject):
            continue
        rows = git_text(repo, "show", "--no-renames", "--name-status", "--format=", sha).splitlines()
        changes = [r.split("\t", 1) for r in rows if "\t" in r]
        old = [p for s, p in changes if s == "M" and p in base_paths and TEST_FILE_RE.search(p)]
        code = [p for s, p in changes if s in "AMT" and not TEST_FILE_RE.search(p) and not DOC_RE.search(p)]
        if old and code and not any(sha.startswith(f) for f in fix_tests):
            notices.append({"commit": sha[:7], "subject": subject[:70], "tests": old})
    return notices


def uncommitted(repo, head, base_paths, specs):
    """Old test files edited or deleted in the working tree against head, not yet committed."""
    if resolve(repo, "HEAD") != head:
        return []
    out = []
    for line in git_text(repo, "diff", "--name-status", "--no-renames", head).splitlines():
        status, path = line.split("\t", 1)
        if status in ("M", "D") and is_test(path) and in_tests(path) and path in base_paths and not covered_by(path, specs):
            out.append(path)
    return sorted(out)


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def analyse(repo, base_arg, head_arg):
    if not git(repo, "rev-parse", "--git-dir", check=False).returncode == 0:
        raise Unreadable(f"{repo} is not a git repository")
    head = resolve(repo, head_arg)
    if not head:
        raise Unreadable(f"head {head_arg!r} is not a commit in {repo}")
    if base_arg == "live":
        base, how = live_base(repo)
    else:
        base = resolve(repo, base_arg)
        if not base:
            raise Unreadable(f"base {base_arg!r} is not a commit in {repo}")
        how = "given"
    note = ""
    if git(repo, "merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
        mb = git_text(repo, "merge-base", base, head, check=False).strip()
        if not mb:
            raise Unreadable(f"{base[:8]} and {head[:8]} share no history")
        note = f"{base[:8]} is not an ancestor of {head[:8]}; using the merge-base {mb[:8]}"
        base = mb

    base_paths = [p for p in git_text(repo, "ls-tree", "-r", "--name-only", base).splitlines() if in_tests(p)]
    base_set = set(base_paths)
    changed = changed_between(repo, base, head)
    texts = read_blobs(repo, base, [p for p in base_paths if p.endswith(".py")]) if changed else {}
    found = fan_out(set(changed), texts)
    asked = sorted({p for p in changed if is_test(p)} | set(found))
    specs, fix_tests = reasons_in_range(repo, base, head)
    shas = commits_by_path(repo, base, head)
    rows = []
    for p in asked:
        row = {"file": p, "covered": covered_by(p, specs)}
        if p in changed:
            row["changed_by"] = shas.get(p, [])
        else:
            root = found[p]
            row["names"] = root
            row["changed_by"] = shas.get(root, [])
        rows.append(row)
    return {
        "base": base,
        "base_how": how,
        "note": note,
        "head": head,
        "changed": sorted(p for p in changed if is_test(p)),
        "helpers_changed": sorted(p for p in changed if not is_test(p)),
        "asked": asked,
        "covered": [r["file"] for r in rows if r["covered"]],
        "missing": [r["file"] for r in rows if not r["covered"]],
        "rows": rows,
        "uncommitted": uncommitted(repo, head, base_set, specs),
        "fix_notices": fix_notices(repo, base, head, base_set, fix_tests),
    }


def hint(row):
    shown = row["changed_by"][:SHAS_SHOWN]
    more = len(row["changed_by"]) - len(shown)
    by = "changed by " + ", ".join(shown) + (f" and {more} more" if more > 0 else "") if shown else "no commit found"
    return f"  ({'names ' + row['names'] + ', ' if 'names' in row else ''}{by})"


def report(res):
    print(
        f"test_reasons: base {res['base'][:8]} ({res['base_how']}), head {res['head'][:8]}; "
        f"{plural(len(res['changed']), 'old test file')} changed, "
        f"{len(res['asked'])} asked for, {plural(len(res['missing']), 'line')} missing"
    )
    if res["note"]:
        print(f"test_reasons: {res['note']}")
    rows = {r["file"]: r for r in res["rows"]}
    for p in res["missing"]:
        print(f"Test-Change: {p}: <reason>{hint(rows[p])}")
    if res["missing"]:
        print()
        print("test_reasons: if each is deliberate, record why in any commit in the range (an empty commit will do):")
        lines = "\n".join(f"Test-Change: {p}: <reason>" for p in res["missing"])
        print("  git commit --allow-empty -m 'Recorded reasons' -m " + shlex.quote(lines))
        print("test_reasons: replace each <reason> with why the old test no longer holds, and leave the parenthesis out.")
    if res["uncommitted"]:
        print()
        print("test_reasons: will need a line when committed (edited in the working tree, not committed):")
        for p in res["uncommitted"]:
            print(f"  {p}")
    if res["fix_notices"]:
        print()
        print("test_reasons: notice, not a failure. A fix commit changed an old test and code; if its test passes on the commit before it, add Fix-Test: <sha>: <reason>:")
        for n in res["fix_notices"]:
            print(f"  Fix-Test: {n['commit']}: <reason>  ({n['subject']!r}, tests: {', '.join(n['tests'])})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="test_reasons.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    ck = sub.add_parser("check", help="list the Test-Change lines the range will need")
    ck.add_argument("--repo", default=".", help="the repository (default: the current folder)")
    ck.add_argument("--base", default="live", help="'live' (the commit on the site) or a commit")
    ck.add_argument("--head", default="HEAD")
    ck.add_argument("--json", action="store_true", help="print the whole result, asked-for files included, as JSON")
    args = ap.parse_args(argv)
    try:
        res = analyse(args.repo, args.base, args.head)
    except Unreadable as exc:
        print(f"test_reasons: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        report(res)
    return 1 if res["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
