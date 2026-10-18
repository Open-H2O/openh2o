#!/usr/bin/env python3
# Copied verbatim from vanderoffice/testing-program regress/regress.py at 617f9acf50b0390ea4c28a98fce2e1bf15039aa6; change it there.
"""regress.py: the testing program's checks for rules 6 and 8, run before a deploy and weekly.

  old tests   the deployed commit's (base's) tests, run against the candidate's (head's) code.
              A failure means a test was changed so that it would pass, and blocks unless a commit
              in base..head records why:   Test-Change: <test file or folder>: <reason>
  fix tests   every fix commit in base..head that adds or changes a test and changes code: that
              commit's test files laid over its parent and run there. They must fail there; a
              fix whose test passes before the fix blocks unless a commit records why:
                                           Fix-Test: <commit, 7 or more hex>: <reason>

A fix with no test is never refused here (standard section 1.6 gives it to the scoreboard's count);
it is listed in the log and the record.

  regress.py plan  --repo R --base B --head H --tests PATH ...            (prints the plan, runs nothing)
  regress.py check --repo R --base B --head H --tests PATH ... --command '<suite, JUnit to {junit}>'
                   [--subset '<command on {files}, JUnit to {junit}>']
                   [--fail-exits 1,2] [--only-fix SHA | --only-old] [--out record.json] [--timeout SECONDS]
  regress.py check ... --per-file '<command on one {file} or {module}>' --test-files 'GLOB,...'

`--base weekly` means the last first-parent commit of head made at or before 7 days ago.

Exit codes: 0 pass; 1 a rule broken (every failure printed, with the line that would excuse it);
2 setup error (bad argument, a commit that is not one, base not an ancestor of head, no JUnit
report, an exit code that is neither 0 nor in --fail-exits, a timeout): never a pass;
4 git could not read the repository.

Standard library only (Python 3.9 and up). It never commits, never pushes, never moves a ref, runs
no git hook (every git call passes -c core.hooksPath=/dev/null) and removes its worktrees on every
exit. Every suite run uses the caller's environment (the head's virtualenv, if the caller made one).

Source: vanderoffice/testing-program regress/regress.py. A copy carries one header line naming
the commit it came from; change it there, not in a copy.
"""

from __future__ import annotations

import argparse
import fnmatch
import itertools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

# The scoreboard's own two patterns (scoreboard/scoreboard.py); tests/test_regress.py checks they match.
FIX_RE = re.compile(r"^fix|\bfix(es|ed)?\b", re.I)
TEST_FILE_RE = re.compile(r"(^|/)(tests?|Tests|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|\.test\.(js|ts|mjs)$|Tests?\.swift$|(^|/)tests\.py$")
DOC_RE = re.compile(r"\.md$|(^|/)docs/|(^|/)\.planning/")
TEST_CHANGE_RE = re.compile(r"^\s*Test-Change:\s*([^:\s][^:]*?)\s*:\s*(\S.*?)\s*$")
FIX_TEST_RE = re.compile(r"^\s*Fix-Test:\s*([0-9a-fA-F]{7,40})\s*:\s*(\S.*?)\s*$")
COPY_RE = re.compile(r"^# Copied verbatim from vanderoffice/testing-program regress/regress\.py at ([0-9a-f]{40})", re.M)
DEFAULT_RUNNABLE = ("test_*.py", "*_test.py", "tests.py")
WEEK = 7 * 86400


class SetupError(Exception):
    pass


class GitError(Exception):
    pass


def say(msg=""):
    print(f"regress: {msg}" if msg else "", flush=True)


# ---------------------------------------------------------------- git

class Git:
    def __init__(self, repo):
        self.repo = repo

    def run(self, *args, input=None, check=True):
        p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", self.repo, *args],
                           input=input, capture_output=True)
        if check and p.returncode:
            err = p.stderr.decode("utf-8", "replace").strip().splitlines()
            raise GitError(f"git {' '.join(args[:3])}: exit {p.returncode}: {err[0] if err else ''}")
        return p

    def out(self, *args):
        return self.run(*args).stdout.decode("utf-8", "replace")

    def commit(self, rev, what):
        p = self.run("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
        sha = p.stdout.decode().strip()
        if p.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise SetupError(f"{what} '{rev}' is not a commit in {self.repo}")
        return sha

    def tree(self, rev):
        """path -> (mode, sha) for every blob or link in rev."""
        entries = {}
        for rec in self.out("ls-tree", "-r", "-z", "--full-tree", rev).split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind == "blob":
                entries[path] = (mode, sha)
        return entries

    def blobs(self, shas):
        if not shas:
            return {}
        out = self.run("cat-file", "--batch", input="".join(s + "\n" for s in shas).encode()).stdout
        got, i = {}, 0
        while i < len(out):
            nl = out.index(b"\n", i)
            sha, _kind, size = out[i:nl].decode().split()
            size = int(size)
            got[sha] = out[nl + 1:nl + 1 + size]
            i = nl + 1 + size + 1
        return got

    def changes(self, sha):
        """[(status letter, path)] for a non-merge commit, renames as delete plus add."""
        parts = self.out("diff-tree", "--no-commit-id", "--no-renames", "-r", "-z", "--name-status", "--root", sha).split("\0")
        parts = [p for p in parts if p != ""]
        return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


# ---------------------------------------------------------------- paths

def norm(path):
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def glob_match(path, pattern):
    if "/" in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    return fnmatch.fnmatchcase(os.path.basename(path), pattern)


def under(path, spec):
    """A --tests value: a file, a folder, or a glob (a glob with no slash matches the file name)."""
    if any(c in spec for c in "*?["):
        return glob_match(path, spec)
    spec = norm(spec).rstrip("/")
    return path == spec or path.startswith(spec + "/")


def module_of(path):
    return re.sub(r"\.py$", "", path).replace("/", ".")


# ---------------------------------------------------------------- the engine

class Engine:
    def __init__(self, args):
        self.a = args
        self.git = Git(args.repo)
        self.tmp = None
        self.worktrees = []
        self.proc = None
        self.seq = itertools.count()
        self.record = {"engine": engine_commit(), "repo": os.path.abspath(args.repo), "result": "setup-error",
                       "exit": 2, "base": None, "head": None, "old_tests": None, "fixes": [],
                       "fixes_without_test": [], "reasons_used": [], "reason_lines": [], "notes": []}

    # ---- setup

    def resolve(self):
        a = self.a
        p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", a.repo, "rev-parse", "--git-dir"],
                           capture_output=True)
        if p.returncode:
            raise GitError(f"cannot read the repository at {a.repo}")
        self.head = self.git.commit(a.head, "head")
        if a.base == "weekly":
            now = float(os.environ.get("REGRESS_NOW") or time.time())
            sha = self.git.out("rev-list", "-1", "--first-parent", f"--before={int(now - WEEK)}", self.head).strip()
            if not sha:
                raise SetupError(f"no first-parent commit of {self.head} is 7 days old or older")
            self.base = sha
            self.title = "deploy checks weekly"
        else:
            self.base = self.git.commit(a.base, "base")
            self.title = f"deploy checks {self.head} from {self.base}"
        r = self.git.run("merge-base", "--is-ancestor", self.base, self.head, check=False)
        if r.returncode == 1:
            raise SetupError(f"base {self.base} is not an ancestor of head {self.head}")
        if r.returncode:
            raise GitError(f"git merge-base: exit {r.returncode}")
        self.record.update(base=self.base, head=self.head, title=self.title)

        self.specs = [norm(t) for t in (a.tests or [])]
        if any(s in ("", ".") for s in self.specs):
            raise SetupError("--tests names the whole repository; name the test folder or files")
        self.runnable_globs = [g.strip() for g in (a.test_files or "").split(",") if g.strip()]
        if a.per_file and not self.specs:
            self.specs = list(self.runnable_globs)
        if not self.specs:
            raise SetupError("--tests is required (the test folder or files)")
        if not self.runnable_globs:
            self.runnable_globs = list(DEFAULT_RUNNABLE)
        self.fail_exits = set()
        for x in (a.fail_exits or "1").split(","):
            if not x.strip().isdigit() or int(x) == 0:
                raise SetupError(f"--fail-exits '{a.fail_exits}': a comma list of non-zero exit codes")
            self.fail_exits.add(int(x))

        self.range = self.git.out("rev-list", f"{self.base}..{self.head}").split()
        self.read_reasons()
        self.find_fixes()

    def read_reasons(self):
        log = self.git.out("log", "--format=%H%x00%B%x1e", f"{self.base}..{self.head}")
        self.test_changes, self.fix_tests = [], {}
        for entry in log.split("\x1e"):
            entry = entry.strip("\n")
            if not entry:
                continue
            sha, body = entry.split("\0", 1)
            for line in body.splitlines():
                m = TEST_CHANGE_RE.match(line)
                if m:
                    self.test_changes.append({"path": norm(m.group(1)), "line": line.strip(), "commit": sha})
                    self.record["reason_lines"].append({"line": line.strip(), "commit": sha})
                m = FIX_TEST_RE.match(line)
                if m:
                    prefix = m.group(1).lower()
                    hits = [c for c in self.range if c.startswith(prefix)]
                    if len(hits) > 1:
                        raise SetupError(f"'{line.strip()}' (in {sha[:12]}): {prefix} matches {len(hits)} commits in the range; give more digits")
                    self.record["reason_lines"].append({"line": line.strip(), "commit": sha})
                    if not hits:
                        self.record["notes"].append(f"unused: '{line.strip()}' names no commit in the range")
                        continue
                    self.fix_tests.setdefault(hits[0], {"line": line.strip(), "commit": sha})

    def is_test(self, path):
        return any(under(path, s) for s in self.specs) or bool(TEST_FILE_RE.search(path))

    def runnable(self, path):
        return any(glob_match(path, g) for g in self.runnable_globs)

    def find_fixes(self):
        self.fixes, self.no_test = [], []
        for sha in self.git.out("rev-list", "--no-merges", "--reverse", f"{self.base}..{self.head}").split():
            subject = self.git.out("log", "-1", "--format=%s", sha).strip()
            if not FIX_RE.search(subject):
                continue
            ch = self.git.changes(sha)
            tests = [p for s, p in ch if s in "AMT" and self.is_test(p)]
            code = [p for s, p in ch if not self.is_test(p) and not DOC_RE.search(p)]
            if tests and code:
                self.fixes.append({"commit": sha, "subject": subject, "parent": self.git.commit(f"{sha}^", "parent"),
                                   "test_files": tests, "code_files": code})
            elif code and not any(self.is_test(p) for _, p in ch):
                self.no_test.append({"commit": sha, "subject": subject})
        self.record["fixes_without_test"] = self.no_test

    # ---- worktrees and runs

    def worktree(self, rev, name):
        if self.tmp is None:
            self.tmp = tempfile.mkdtemp(prefix="regress-")
        d = os.path.join(self.tmp, name)
        self.git.run("worktree", "add", "--detach", "-q", d, rev)
        self.worktrees.append(d)
        return d

    def cleanup(self):
        if self.proc is not None and self.proc.poll() is None:
            kill(self.proc)
        for d in self.worktrees:
            r = self.git.run("worktree", "remove", "--force", d, check=False)
            if r.returncode:
                shutil.rmtree(d, ignore_errors=True)
        if self.worktrees:
            self.git.run("worktree", "prune", check=False)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def lay(self, wt, entries, paths):
        """Write each path's blob from entries (a tree listing) into the worktree."""
        data = self.git.blobs(sorted({entries[p][1] for p in paths}))
        for p in paths:
            mode, sha = entries[p]
            dest = os.path.join(wt, p)
            if os.path.lexists(dest) and not os.path.isdir(dest):
                os.remove(dest)
            os.makedirs(os.path.dirname(dest) or wt, exist_ok=True)
            if mode == "120000":
                os.symlink(data[sha].decode(), dest)
                continue
            with open(dest, "wb") as fh:
                fh.write(data[sha])
            os.chmod(dest, 0o755 if mode == "100755" else 0o644)

    def run(self, cmd, cwd, what):
        log = os.path.join(self.tmp, f"log-{next(self.seq)}.txt")
        env = dict(os.environ, REGRESS_TREE=cwd, REGRESS_REPO=os.path.abspath(self.a.repo))
        t0 = time.time()
        with open(log, "wb") as fh:
            self.proc = subprocess.Popen(["bash", "-c", cmd], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, env=env, start_new_session=True)
            try:
                rc = self.proc.wait(timeout=self.a.timeout)
            except subprocess.TimeoutExpired:
                kill(self.proc)
                self.tail(log)
                raise SetupError(f"{what} timed out after {self.a.timeout} s")
            finally:
                self.proc = None
        return rc, round(time.time() - t0, 1), log

    def tail(self, log, n=25):
        try:
            with open(log, "rb") as fh:
                lines = fh.read().decode("utf-8", "replace").splitlines()[-n:]
        except OSError:
            return
        for line in lines:
            print(f"    | {line}")

    def suite(self, cmd, cwd, what):
        """Run a command that writes JUnit to {junit}; returns (exit, seconds, [(id, file, failed)])."""
        junit = os.path.join(self.tmp, f"junit-{next(self.seq)}.xml")
        rc, secs, log = self.run(cmd.replace("{junit}", shlex.quote(junit)), cwd, what)
        if rc != 0 and rc not in self.fail_exits:
            self.tail(log)
            raise SetupError(f"{what} ended with exit {rc}, which is neither 0 nor in --fail-exits {sorted(self.fail_exits)}")
        if not os.path.exists(junit):
            self.tail(log)
            raise SetupError(f"{what}: no JUnit report where the command was told to write it ({{junit}}), exit {rc}")
        try:
            cases = junit_cases(junit, cwd)
        except ET.ParseError as e:
            raise SetupError(f"{what}: the JUnit report does not parse ({e})")
        if rc != 0 and not any(f for _, _, f in cases):
            self.tail(log)
            raise SetupError(f"{what} ended with exit {rc} but its JUnit report names no failing test")
        return rc, secs, cases

    def per_file_run(self, path, cwd, what):
        cmd = self.a.per_file.replace("{file}", shlex.quote(path)).replace("{module}", shlex.quote(module_of(path)))
        rc, secs, log = self.run(cmd, cwd, what)
        if rc != 0 and rc not in self.fail_exits:
            self.tail(log)
            raise SetupError(f"{what} ended with exit {rc}, which is neither 0 nor in --fail-exits {sorted(self.fail_exits)}")
        return rc, secs, log

    # ---- the two checks

    def old_tests(self):
        say(f"old tests: base's {', '.join(self.specs)} on head's code")
        wt = self.worktree(self.head, "old-tests")
        head_tree, base_tree = self.git.tree(self.head), self.git.tree(self.base)
        for p in head_tree:
            if any(under(p, s) for s in self.specs):
                os.remove(os.path.join(wt, p))
        restored = [p for p in base_tree if any(under(p, s) for s in self.specs)]
        self.lay(wt, base_tree, restored)
        res = {"test_paths": self.specs, "files_laid": len(restored), "failures": []}
        if self.a.per_file:
            files = sorted(p for p in restored if self.runnable(p))
            res["files_run"], t0 = files, time.time()
            for p in files:
                rc, secs, log = self.per_file_run(p, wt, f"old test file {p}")
                if rc != 0:
                    res["failures"].append({"id": p, "file": p, "exit": rc})
                    self.tail(log, 10)
            res["seconds"] = round(time.time() - t0, 1)
        else:
            rc, secs, cases = self.suite(self.a.command, wt, "the old-tests run")
            res.update(exit=rc, seconds=secs, tests=len(cases))
            res["failures"] = [{"id": i, "file": f} for i, f, failed in cases if failed]
        for f in res["failures"]:
            f["excused_by"] = self.test_change_for(f["file"])
        self.record["old_tests"] = res
        n = len(res["failures"])
        say(f"old tests: {n} failing" + (f" of {res['tests']} run" if "tests" in res else
                                         f" of {len(res.get('files_run', []))} files run") + f" ({res['seconds']} s)")
        for f in res["failures"]:
            where = f"file {f['file']}" if f["file"] else "names no file, so no Test-Change line can excuse it"
            state = f"excused by {f['excused_by']}" if f["excused_by"] else "NOT EXCUSED"
            print(f"  FAILED {f['id']}: old test failing on new code ({where}); {state}")

    def test_change_for(self, path):
        if not path:
            return None
        for tc in self.test_changes:
            spec = tc["path"].rstrip("/")
            if path == spec or path.startswith(spec + "/"):
                self.use(tc)
                return tc["line"]
        return None

    def use(self, reason):
        item = {"line": reason["line"], "commit": reason["commit"]}
        if item not in self.record["reasons_used"]:
            self.record["reasons_used"].append(item)

    def fix_tests_run(self, only=None):
        fixes = self.fixes
        if only:
            fixes = [f for f in self.fixes if f["commit"] == only]
        say(f"fix commits: {len(fixes)} to check, {len(self.no_test)} without a test (never refused)")
        for nt in self.no_test:
            print(f"  {nt['commit'][:12]} {nt['subject'][:70]!r}: fix without test (not refused; the scoreboard counts it)")
        for fx in fixes:
            self.record["fixes"].append(self.one_fix(fx))

    def one_fix(self, fx):
        sha = fx["commit"]
        wt = self.worktree(fx["parent"], f"fix-{sha[:12]}")
        self.lay(wt, self.git.tree(sha), fx["test_files"])
        out = {"commit": sha, "subject": fx["subject"], "parent": fx["parent"], "test_files": fx["test_files"]}
        runnable = [p for p in fx["test_files"] if self.runnable(p)]
        t0 = time.time()
        if self.a.per_file:
            out.update(mode="per-file", ran=runnable)
            if not runnable:
                out.update(verdict="no-runnable-test-file", seconds=0)
            else:
                rcs = [self.per_file_run(p, wt, f"fix {sha[:12]}'s test file {p} on its parent")[0] for p in runnable]
                out.update(exit=max(rcs), exits=rcs,
                           verdict="failed-before-fix" if any(rc in self.fail_exits for rc in rcs) else "passed-before-fix")
        elif self.a.subset and runnable:
            files = " ".join(shlex.quote(p) for p in runnable)
            junit = os.path.join(self.tmp, f"junit-fix-{sha[:12]}.xml")
            cmd = self.a.subset.replace("{files}", files).replace("{junit}", shlex.quote(junit))
            rc, secs, log = self.run(cmd, wt, f"fix {sha[:12]}'s tests on its parent")
            out.update(mode="subset", ran=runnable, exit=rc)
            if rc in self.fail_exits:
                out["verdict"] = "failed-before-fix"
            elif rc == 0:
                out["verdict"] = "passed-before-fix"
            else:
                self.tail(log)
                raise SetupError(f"fix {sha[:12]}'s tests on its parent ended with exit {rc}, which is neither 0 nor in --fail-exits {sorted(self.fail_exits)}")
        else:
            rc, _, laid = self.suite(self.a.command, wt, f"fix {sha[:12]}: the whole suite on its parent with its tests")
            own = self.worktree(fx["parent"], f"parent-{sha[:12]}")
            _, _, plain = self.suite(self.a.command, own, f"fix {sha[:12]}: the parent's own whole suite")
            before = {i for i, _, failed in plain if failed}
            new = sorted(i for i, _, failed in laid if failed and i not in before)
            out.update(mode="whole-suite", ran="whole suite", exit=rc, new_failures=new,
                       verdict="failed-before-fix" if new else "passed-before-fix")
        out["seconds"] = round(time.time() - t0, 1)
        out["excused_by"] = None
        if out["verdict"] == "passed-before-fix" and sha in self.fix_tests:
            self.use(self.fix_tests[sha])
            out["excused_by"] = self.fix_tests[sha]["line"]
        if out["verdict"] == "failed-before-fix":
            state = "its test fails before the fix, as it should"
        elif out["verdict"] == "passed-before-fix":
            state = "fix whose test passes before the fix; " + (f"excused by {out['excused_by']}" if out["excused_by"] else "NOT EXCUSED")
        else:
            state = "changed no runnable test file (support files only); not refused"
        print(f"  {sha[:12]} {fx['subject'][:70]!r}: {state} ({out['mode']}, exit {out.get('exit', '-')}, {out['seconds']} s)")
        return out

    # ---- top level

    def check(self):
        self.resolve()
        say(self.title)
        say(f"repo {self.record['repo']}; engine {self.record['engine']}")
        say(f"base {self.base}  head {self.head}  ({len(self.range)} commits)")
        say("every run uses the caller's environment (head's), not base's")
        only = None
        if self.a.only_fix:
            prefix = self.a.only_fix.lower()
            hits = [c for c in self.range if c.startswith(prefix)]
            if len(hits) != 1 or hits[0] not in {f["commit"] for f in self.fixes}:
                raise SetupError(f"--only-fix {self.a.only_fix} is not a fix commit with a test in {self.base[:12]}..{self.head[:12]}")
            only = hits[0]
        else:
            self.old_tests()
        if self.a.only_old:
            say(f"fix commits: not run here (--only-old): {len(self.fixes)} with a test, each for an --only-fix run;"
                f" {len(self.no_test)} without a test")
        else:
            self.fix_tests_run(only)

        old_bad = [f for f in (self.record["old_tests"] or {}).get("failures", []) if not f["excused_by"]]
        fix_bad = [f for f in self.record["fixes"] if f["verdict"] == "passed-before-fix" and not f["excused_by"]]
        for line in self.record["notes"]:
            say(f"note: {line}")
        if not old_bad and not fix_bad:
            self.record.update(result="pass", exit=0)
            say("PASS: no unexcused old test failing on new code, no unexcused fix whose test passes before the fix"
                + (f"; {len(self.record['reasons_used'])} recorded reason(s) used" if self.record["reasons_used"] else ""))
            return 0
        self.record.update(result="rule-broken", exit=1)
        say(f"RULE BROKEN: {len(old_bad)} old test(s) failing on new code, {len(fix_bad)} fix(es) whose test passes before the fix")
        lines = []
        for path in dict.fromkeys(f["file"] for f in old_bad if f["file"]):
            lines.append(f"Test-Change: {path}: <reason>")
        for f in fix_bad:
            lines.append(f"Fix-Test: {f['commit'][:12]}: <reason>")
        if any(not f["file"] for f in old_bad):
            say("a failure that names no file cannot be excused: fix the test, or the report so it names its file")
        if lines:
            say("if each is deliberate, record why in any commit in the range (an empty commit will do) and run again:")
            print("  git commit --allow-empty -m 'Recorded reasons' -m " + shlex.quote("\n".join(lines)))
            say("the lines, each with its reason in place of <reason>:")
            for line in lines:
                print(line)
        return 1

    def plan(self):
        self.resolve()
        base_tree = self.git.tree(self.base)
        old = sorted(p for p in base_tree if any(under(p, s) for s in self.specs))
        plan = {"title": self.title, "base": self.base, "head": self.head, "commits": len(self.range),
                "test_paths": self.specs, "old_test_files": len(old),
                "fixes": [{"commit": f["commit"], "subject": f["subject"], "test_files": f["test_files"],
                           "runnable": [p for p in f["test_files"] if self.runnable(p)]} for f in self.fixes],
                "fixes_without_test": self.no_test, "reason_lines": self.record["reason_lines"],
                "notes": self.record["notes"]}
        print(json.dumps(plan, indent=1))
        return 0


def junit_cases(path, tree):
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        failed = any(child.tag in ("failure", "error") for child in tc)
        name, classname = tc.get("name") or "", tc.get("classname") or ""
        f = file_of(tc.get("file"), classname, tree)
        cases.append((case_id(f, classname, name), f, failed))
    return cases


def file_of(file, classname, tree):
    """The test file a JUnit case belongs to: its file attribute; else a dotted classname naming an
    existing file; else the Tests/<target>/ folder its classname names, or the first one there is."""
    if file:
        return norm(file)
    parts = [p for p in classname.split(".") if p]
    for k in range(len(parts), 0, -1):
        cand = "/".join(parts[:k]) + ".py"
        if os.path.isfile(os.path.join(tree, cand)):
            return cand
    tests = os.path.join(tree, "Tests")
    if os.path.isdir(tests):
        targets = sorted(d for d in os.listdir(tests) if os.path.isdir(os.path.join(tests, d)))
        if parts and parts[0] in targets:
            return f"Tests/{parts[0]}/"
        if targets:
            return f"Tests/{targets[0]}/"
    return None


def case_id(file, classname, name):
    if file and file.endswith(".py"):
        mod = module_of(file)
        if classname in ("", mod):
            return file if (classname == "" and name == mod) else f"{file}::{name}"
        if classname.startswith(mod + "."):
            return f"{file}::{classname[len(mod) + 1:].replace('.', '::')}::{name}"
    return f"{classname}::{name}" if classname else name


def engine_commit():
    env = os.environ.get("REGRESS_ENGINE_COMMIT", "").strip()
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "COMMIT")) as fh:
            return fh.read().strip()
    except OSError:
        pass
    try:
        with open(os.path.abspath(__file__)) as fh:
            m = COPY_RE.search(fh.read(4096))
        if m:
            return m.group(1)
    except OSError:
        pass
    p = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel", "HEAD"], capture_output=True, text=True)
    lines = p.stdout.split()
    if p.returncode == 0 and len(lines) == 2 and os.path.realpath(os.path.join(lines[0], "regress", "regress.py")) == os.path.realpath(__file__):
        dirty = subprocess.run(["git", "-C", here, "status", "--porcelain", "--", "regress.py"], capture_output=True, text=True).stdout.strip()
        return lines[1] + (" (with uncommitted changes)" if dirty else "")
    return "unknown"


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def parse(argv):
    ap = argparse.ArgumentParser(prog="regress.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "check"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--base", required=True)
        p.add_argument("--head", required=True)
        p.add_argument("--tests", action="append", default=[], help="a test folder, file or glob (repeatable)")
        p.add_argument("--command", help="the whole suite, writing JUnit to {junit}")
        p.add_argument("--subset", help="the suite on {files}, writing JUnit to {junit}")
        p.add_argument("--per-file", dest="per_file", help="one test file: {file} or {module}")
        p.add_argument("--test-files", dest="test_files", help="comma list of globs: which test files run")
        p.add_argument("--fail-exits", dest="fail_exits", default="1")
        p.add_argument("--only-fix", dest="only_fix")
        p.add_argument("--only-old", dest="only_old", action="store_true", help="the old tests only, no fix")
        p.add_argument("--out")
        p.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        if a.per_file and (a.command or a.subset):
            ap.error("--per-file replaces --command and --subset")
        if a.per_file and not a.test_files:
            ap.error("--per-file needs --test-files")
        if not a.per_file and not a.command:
            ap.error("check needs --command (or --per-file)")
        if a.only_old and a.only_fix:
            ap.error("--only-old cannot be used with --only-fix")
        if a.timeout < 1:
            ap.error("--timeout must be at least 1 second")
    return a


def main(argv=None):
    a = parse(sys.argv[1:] if argv is None else argv)

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    eng = Engine(a)
    code = 2
    try:
        code = eng.check() if a.cmd == "check" else eng.plan()
    except SetupError as e:
        say(f"SETUP ERROR: {e}")
        say("this is not a pass: nothing was decided")
        code = 2
    except GitError as e:
        say(f"GIT ERROR: {e}")
        code = 4
    finally:
        eng.cleanup()
        eng.record["exit"] = code
        if code == 2:
            eng.record["result"] = "setup-error"
        elif code == 4:
            eng.record["result"] = "git-error"
        if a.out and a.cmd == "check":
            with open(a.out, "w") as fh:
                json.dump(eng.record, fh, indent=1)
                fh.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
