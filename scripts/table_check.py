#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""table_check.py: fail when any data table on a running site sits off balance.

Signs in to a running OpenH2O site, visits every page it can reach by GET (one
page per URL shape, and every instance up to --per-shape of the shapes whose
tables carry a column rule, because the gaps depend on each record's figures),
and evaluates scripts/table_balance.js on each at 1,024, 1,440 and 1,730 px.
It exits 1 and names each failing table when, on any table:

- the nearest figures on the two sides of a column rule stand more than 4 px
  apart in their distance from it;
- a header sits more than 2 px off its figures along their shared edge;
- a bracket label sits off the figures it spans, or off its own underline;
- a pinned two-row header leaves a gap between its rows, a pinned header cell
  keeps a collapsed border of its own (the rows beneath show through the strip
  it leaves), or the header's piece of a rule is off the rule below it.

Each of these came back after a fix judged on one screenshot at one width;
nothing measured them, so this does. It is GET only: it never submits a form or
follows a link that changes data.

This is a host-side developer tool, like scripts/walk.py: it needs `playwright`
in the HOST Python, never in pyproject.toml. It uses the headless Chrome on
:9222 when one is running and launches a private headless chromium otherwise.

Usage:
  scripts/table_check.py --base https://localhost --login you@example.org
      (the password is read from TABLE_CHECK_PASSWORD, never the command line)
  make table-check BASE=https://localhost LOGIN=you@example.org
"""
import argparse
import os
import re
import sys
from collections import deque

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
MEASURE = os.path.join(HERE, "table_balance.js")
WIDTHS = (1024, 1440, 1730)
# Path words that change data or leave the page: never visited.
BLOCKED_WORDS = ("delete", "remove", "logout", "edit", "create", "import", "assign",
                 "finalize", "reopen", "reset", "export", "download", "upload")
BLOCKED_PREFIX = ("/admin/", "/accounts/", "/static/", "/media/")
BLOCKED_SUFFIX = (".csv", ".json", ".geojson", ".zip", ".pdf")


def blocked(path):
    p = path.lower()
    if p.startswith(BLOCKED_PREFIX) or p.endswith(BLOCKED_SUFFIX):
        return True
    words = [w for w in re.split(r"[^a-z0-9]+", p) if w]
    return any(w.startswith(b) for w in words for b in BLOCKED_WORDS)


def shape(path):
    return re.sub(r"\d+", "N", path)


def load(page, url):
    """Load a page and let tables that arrive by HTMX on scroll arrive."""
    resp = page.goto(url, wait_until="networkidle", timeout=45000)
    height = page.evaluate("document.documentElement.scrollHeight")
    y = 0
    while y < height:
        y += 800
        page.evaluate("y => window.scrollTo(0, y)", y)
        page.wait_for_timeout(120)
        height = page.evaluate("document.documentElement.scrollHeight")
    page.evaluate("window.scrollTo(0, 0)")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    return resp


def links(page):
    found = set()
    for href in page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"):
        if href and href.startswith("/") and not href.startswith("//"):
            found.add(href.split("#")[0].split("?")[0])
    # The use area list carries its row links in an attribute, not an href.
    found.update(re.findall(r"/parcels/\d+/", page.content()))
    return sorted(f for f in found if f)


def faults(table):
    """Plain-words reasons one measured table fails."""
    out = []
    for r in table["rules"]:
        if not r["pass"]:
            out.append(f"rule between {r['headers'][0] or 'col ' + str(r['between'][0])} and "
                       f"{r['headers'][1] or 'col ' + str(r['between'][1])}: {r['left']} px left, {r['right']} px right")
    for h in table["headers"]:
        if not h["pass"]:
            out.append(f"header {h['header']!r} {h['offset']} px off its figures ({h['header_align']} over {h['figures']})")
    for g in table["groups"]:
        if not g["pass"]:
            out.append(f"bracket {g['header']!r} {g['offset']} px off its figures, {g['underline']} px off its underline")
    if table.get("sticky_gap") not in (None, 0) and abs(table["sticky_gap"]) > 0.5:
        out.append(f"pinned header rows {table['sticky_gap']} px apart")
    if table.get("sticky_borders"):
        out.append(f"{table['sticky_borders']} pinned header cells keep a collapsed border")
    for h in table.get("header_rules", []):
        if not h["pass"]:
            out.append(f"header rule over {h['header']!r} {h['offset']} px off the rule below")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="the site, e.g. https://localhost")
    ap.add_argument("--login", required=True, help="an account that can read every page")
    ap.add_argument("--per-shape", type=int, default=15)
    ap.add_argument("--cap", type=int, default=400, help="most pages to visit")
    ap.add_argument("--start", nargs="*", default=["/"], help="paths to start from")
    args = ap.parse_args()
    password = os.environ.get("TABLE_CHECK_PASSWORD")
    if not password:
        sys.exit("table_check: set TABLE_CHECK_PASSWORD to the account's password")
    base = args.base.rstrip("/")
    source = open(MEASURE).read()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp("http://localhost:9222", timeout=8000)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
        try:
            page = ctx.new_page()
            page.goto(base + "/accounts/login/", wait_until="networkidle")
            page.fill("input[name=login]", args.login)
            page.fill("input[name=password]", password)
            page.click("button[type=submit]")
            try:
                page.wait_for_url(lambda u: "/accounts/login" not in u, timeout=20000)
            except Exception:
                sys.exit("table_check: the sign-in did not leave the login page; check the account")

            queue, seen = deque(args.start), set(args.start)
            visits, has_rule = {}, {}
            pages = tables = 0
            failing = []
            while queue and pages < args.cap:
                path = queue.popleft()
                sh = shape(path)
                if visits.get(sh, 0) >= (args.per_shape if has_rule.get(sh) else 1):
                    continue
                visits[sh] = visits.get(sh, 0) + 1
                try:
                    resp = load(page, base + path)
                except Exception as exc:
                    print(f"  could not load {path}: {str(exc)[:100]}", file=sys.stderr)
                    continue
                if "/accounts/login" in page.url or not resp or "html" not in resp.headers.get("content-type", ""):
                    continue
                pages += 1
                for link in links(page):
                    if link not in seen and not blocked(link):
                        seen.add(link)
                        queue.append(link)
                for width in WIDTHS:
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.wait_for_timeout(400)
                    result = page.evaluate(source, {"overlay": False})
                    for t in result["tables"]:
                        tables += 1
                        if t["rules"]:
                            has_rule[sh] = True
                        if not t["pass"]:
                            failing.append((path, width, t["name"], faults(t)))
                page.set_viewport_size({"width": 1440, "height": 1000})
        finally:
            ctx.close()

    print(f"table_check: {pages} pages, {tables} tables measured at {', '.join(f'{w:,}' for w in WIDTHS)} px")
    if not pages:
        sys.exit("table_check: no page was measured")
    for path, width, name, why in failing:
        print(f"FAIL {path} at {width:,} px, {name!r}: " + "; ".join(why))
    if failing:
        print(f"table_check: {len(failing)} tables off balance")
        sys.exit(1)
    print("table_check: every table balanced")


if __name__ == "__main__":
    main()
