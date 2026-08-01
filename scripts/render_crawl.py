# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gate 4: crawl the running app as a signed-in operator and read what a person
would actually SEE.

**This is the only gate that can catch a real district's name living in a
TEMPLATE.** Gates 1-3 all interrogate the database. A banned name hardcoded into
an HTML heading is invisible to every one of them and renders on the page anyway,
directly beneath the site's own promise that the demonstration "names no real
water district at all". It is also the only gate that notices a view that 500s
against real rows -- the class ISS-091 named, where three phases of green gates
missed eight live crashes because the droppability harness renders against an
EMPTY database.

Run inside the scratch web container, against the RESTORED candidate:

    python scripts/render_crawl.py --policy data/demo/identity_policy.json

Three things about how it runs are load-bearing and each one, done wrong, turns
this gate into a lie:

1. **An unauthenticated crawl is vacuous.** Every data route 302s to
   /accounts/login/, so an anonymous crawler collects 200s having read the login
   page over and over. This authenticates, and then PROVES the session is live
   before it crawls a single page -- because a crawl whose login silently failed
   looks exactly like a clean one.

2. **The scratch stack runs production settings.** That means SECURE_SSL_REDIRECT
   (every plain request 301s away), secure-only session cookies, and an
   ALLOWED_HOSTS that has never heard of "testserver". Requests therefore go out
   with secure=True and "testserver" is appended to ALLOWED_HOSTS at runtime.
   Without this the whole gate reads as a catastrophic failure that is really a
   configuration detail.

3. **Masking the protected half is not optional, and the obvious algorithm is
   wrong.** Rendered HTML has no table.column to scope against, so the scoping
   that makes the database scan precise is unavailable here. Masking every
   protected value first and then searching for banned ones would silence the
   demonstration's real geography -- but it would ALSO create false negatives,
   because two banned entries CONTAIN a protected one:

       BANNED  'Bear Creek Bottomlands LLC'  contains PROTECTED 'Bear Creek'
       BANNED  'Merced Subbasin GSA'         contains PROTECTED 'Merced Subbasin'

   Mask-then-search would blind this gate to both of those names permanently,
   and it would never go red to tell anyone. So the scan is a single
   longest-match-wins pass over the COMBINED vocabulary: at each position the
   longest policy value wins, and whether that value is banned or protected
   decides the outcome. 'Merced Subbasin GSA' beats 'Merced Subbasin'; 'Merced
   River' has no banned superstring and is masked; 'Le Grand Orchards Inc.'
   beats 'Le Grand Orchards' so one name reports once rather than twice.
"""

import argparse
import json
import os
import re
import sys

import django

# Run as `python scripts/render_crawl.py`, so sys.path[0] is scripts/ rather than
# the project root -- put the root back or `config` does not import. Same repair
# scripts/render_baseline.py makes, for the same reason.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402

#: Characters of surrounding text quoted beside each hit. This is what lets a
#: human tell a genuine leak from a policy gap in one glance -- a bare
#: "page X contains Y" sends the reader back to the page to find out which.
CONTEXT_CHARS = 80


def _prepare_settings():
    """Make production settings answerable by Django's test client.

    Every line here is a configuration detail that would otherwise be
    indistinguishable from a real, catastrophic gate failure.
    """
    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]


def _authenticated_client():
    """A signed-in operator client, PROVEN to be signed in.

    The throwaway superuser is written into the restored candidate in the scratch
    database. That is fine and deliberate: the dump was taken before this stack
    existed, the stack is deleted afterwards, and this gate never writes to the
    candidate FILE. It runs after gate 2 has counted rows, so the pinned
    core.User=0 is measured before this row exists.
    """
    from core.models import User

    user = User.objects.create_superuser(
        username="render-crawl",
        email="render-crawl@example.invalid",
        password="render-crawl-throwaway",
    )
    client = Client()
    client.force_login(user)
    # nav_mode=admin is the render that carries the whole sidebar; the operations
    # mode shows a subset. Crawling admin reaches strictly more of the app.
    client.cookies["nav_mode"] = "admin"
    return client, user


class RecordingClient:
    """Wraps a test Client so the crawl's page bodies can be scanned afterwards.

    crawl() returns status codes, not HTML. Re-fetching every page to read its
    body would double the work and could disagree with what the crawl actually
    saw; capturing in flight cannot.

    secure=True on every request is what satisfies SECURE_SSL_REDIRECT and the
    secure-only cookies under production settings -- and it is also the more
    faithful render, since that is how a visitor reaches this site.
    """

    def __init__(self, inner):
        self._inner = inner
        self.bodies = {}

    def get(self, path, **kwargs):
        kwargs.setdefault("secure", True)
        response = self._inner.get(path, **kwargs)
        content_type = response.headers.get("Content-Type", "")
        if (
            response.status_code == 200
            and "text/html" in content_type
            and not getattr(response, "streaming", False)
        ):
            self.bodies[path] = response.content.decode("utf-8", errors="replace")
        return response


def build_vocabulary(policy):
    """Every policy value that means anything in HTML, longest first.

    Two exclusions, each stated rather than silent:

    * Banned entries with ``"match": "scoped"`` are SKIPPED. Today that is only
      ``"MID "``, scoped precisely because a bare three-letter token matched
      globally fires on ordinary prose -- and an HTML page is nothing but prose.
    * Protected entries with ``"value": "*"`` are skipped. A blanket
      whole-column protection is a statement about a database column and has no
      meaning in a rendered page.
    """
    vocab = []
    skipped_scoped = []

    for entry in policy["banned"]:
        if entry.get("match", "global") != "global":
            skipped_scoped.append(entry["value"])
            continue
        vocab.append((entry["value"], "banned", entry))

    for entry in policy["protected"]:
        value = entry.get("value", "")
        if value == "*":
            continue
        vocab.append((value, "protected", entry))

    # Longest first. Python's re alternation is leftmost-FIRST-alternative, not
    # leftmost-longest, so this ordering is exactly what makes the combined
    # vocabulary resolve 'Merced Subbasin GSA' ahead of 'Merced Subbasin'.
    vocab.sort(key=lambda item: len(item[0]), reverse=True)
    return vocab, skipped_scoped


def compile_scanner(vocab):
    """One case-insensitive alternation over the whole vocabulary.

    A pure-Python position-by-position scan would be O(text x vocabulary) and the
    real crawl covers hundreds of pages; this pushes the same semantics into the
    regex engine.
    """
    pattern = re.compile(
        "|".join(re.escape(value) for value, _kind, _entry in vocab),
        re.IGNORECASE,
    )
    lookup = {}
    for value, kind, entry in vocab:
        lookup.setdefault(value.lower(), (kind, entry))
    return pattern, lookup


def scan_body(text, pattern, lookup):
    """Banned names visible on this page, with the text around each one."""
    hits = []
    for match in pattern.finditer(text):
        kind, entry = lookup[match.group(0).lower()]
        if kind != "banned":
            # A protected value matched and won at this position: real published
            # record, left alone. This is the masking, done as resolution.
            continue
        start = max(0, match.start() - CONTEXT_CHARS)
        end = min(len(text), match.end() + CONTEXT_CHARS)
        context = " ".join(text[start:end].split())
        hits.append(
            {
                "matched": match.group(0),
                "banned": entry["value"],
                "reason": entry["reason"],
                "context": context,
            }
        )
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="data/demo/identity_policy.json")
    parser.add_argument("--max-pages", type=int, default=3000)
    args = parser.parse_args()

    with open(args.policy) as handle:
        policy = json.load(handle)

    _prepare_settings()

    # Seeds are config-derived from inside this running container, never
    # transcribed. A hand-copied list goes stale the first time a module gains a
    # page -- and a page absent from the list looks exactly like a page that was
    # crawled and found clean.
    from tests.droppability.checks import ANON_PAGES, KEPT_PAGES
    from tests.droppability.crawl import crawl

    seeds = list(KEPT_PAGES)
    for path in ANON_PAGES:
        if path not in seeds:
            seeds.append(path)

    client, user = _authenticated_client()
    recorder = RecordingClient(client)

    # PROVE the session before trusting anything the crawl says. If force_login
    # silently failed, every page below would be the login wall answering 200 and
    # this gate would report perfect coverage of one page repeated hundreds of
    # times.
    probe = recorder.get("/profile/")
    if probe.status_code != 200 or b"/accounts/login/" in probe.content:
        print("  RENDER CRAWL COULD NOT AUTHENTICATE.", file=sys.stderr)
        print(
            f"    /profile/ answered {probe.status_code} and looks like the login "
            "wall. Everything after this point would be vacuous, so the gate "
            "refuses rather than reporting a clean crawl of the sign-in page.",
            file=sys.stderr,
        )
        return 1
    print(f"  authenticated as {user.username} — /profile/ answers 200")

    vocab, skipped_scoped = build_vocabulary(policy)
    pattern, lookup = compile_scanner(vocab)
    banned_n = sum(1 for _v, kind, _e in vocab if kind == "banned")
    protected_n = sum(1 for _v, kind, _e in vocab if kind == "protected")
    print(
        f"  vocabulary: {banned_n} banned + {protected_n} protected, "
        "longest-match-wins over the combined set"
    )
    if skipped_scoped:
        print(
            "  skipped (match=scoped, meaningless without a table.column): "
            + ", ".join(repr(v) for v in skipped_scoped)
        )

    print(f"  crawling from {len(seeds)} seeds (max_pages={args.max_pages})...")
    result = crawl(recorder, seeds, max_pages=args.max_pages, verbose=False)

    failures = []

    # --- the crawl must have EXHAUSTED its frontier -------------------------
    # 90-03 measured the real-data frontier at 1,277 paths and had to raise the
    # cap from 400 to 2,000 to exhaust it. A capped crawl reporting success over
    # ground it never covered is the precise failure shape this milestone exists
    # to end, so a non-empty remainder fails the gate.
    if result.unvisited:
        failures.append(
            "the crawl hit its cap of %d pages with %d path(s) still queued. It "
            "covered less of the app than it appears to. Raise --max-pages."
            % (args.max_pages, len(result.unvisited))
        )
        print("  UNVISITED (first 25):", file=sys.stderr)
        for path in result.unvisited[:25]:
            print(f"    {path}", file=sys.stderr)

    # --- zero 5xx ----------------------------------------------------------
    server_errors = sorted(
        (path, status) for path, status in result.visited.items() if status >= 500
    )
    if server_errors:
        failures.append(f"{len(server_errors)} page(s) returned 5xx")
        print("  SERVER ERRORS:", file=sys.stderr)
        for path, status in server_errors:
            referrer = result.referrers.get(path) or "(seed)"
            print(f"    {status}  {path}", file=sys.stderr)
            print(f"          linked from: {referrer}", file=sys.stderr)
            if path in result.errors:
                print(f"          raised: {result.errors[path]}", file=sys.stderr)

    # --- no banned name on any rendered page -------------------------------
    page_hits = {}
    for path, body in recorder.bodies.items():
        hits = scan_body(body, pattern, lookup)
        if hits:
            page_hits[path] = hits

    if page_hits:
        total = sum(len(h) for h in page_hits.values())
        failures.append(
            f"{total} banned name(s) rendering on {len(page_hits)} page(s)"
        )
        print("  REAL NAMES ON RENDERED PAGES:", file=sys.stderr)
        for path in sorted(page_hits):
            print(f"    {path}", file=sys.stderr)
            seen = set()
            for hit in page_hits[path]:
                if hit["banned"] in seen:
                    continue
                seen.add(hit["banned"])
                print(f"      banned: {hit['banned']!r}", file=sys.stderr)
                print(f"      in:     ...{hit['context']}...", file=sys.stderr)
                print(f"      why:    {hit['reason']}", file=sys.stderr)

    # --- report coverage, always -------------------------------------------
    # A gate that does not say how much ground it covered is indistinguishable
    # from one that covered none.
    statuses = {}
    for status in result.visited.values():
        statuses[status] = statuses.get(status, 0) + 1
    status_summary = ", ".join(f"{n}x{code}" for code, n in sorted(statuses.items()))

    print(
        f"  crawled {len(result.visited)} pages "
        f"({len(recorder.bodies)} HTML bodies scanned), "
        f"unvisited={len(result.unvisited)}, skipped={len(result.skipped)}"
    )
    print(f"  statuses: {status_summary}")

    # Coverage BY SECTION, not just a total. A single number cannot answer the
    # only question a reader actually has — "is the screen I care about in
    # there?" — and a whole domain missing from the crawl looks exactly like a
    # whole domain that was crawled and found clean. That is the defect ISS-097
    # found in the droppability crawl, which was missing every drinking-water
    # detail page while reporting a healthy total.
    sections = {}
    for path in result.visited:
        head = path.strip("/").split("/")[0] if path.strip("/") else "(root)"
        sections[head] = sections.get(head, 0) + 1
    print("  coverage by section:")
    for name, count in sorted(sections.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {count:5d}  /{name}/" if name != "(root)" else f"    {count:5d}  /")

    if failures:
        print("", file=sys.stderr)
        print("  RENDER CRAWL FAILED:", file=sys.stderr)
        for line in failures:
            print(f"    - {line}", file=sys.stderr)
        return 1

    print("  PASS — frontier exhausted, zero 5xx, no banned name on any page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
