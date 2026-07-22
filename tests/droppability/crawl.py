# SPDX-License-Identifier: AGPL-3.0-or-later
"""Follow the links, the way a person clicking through the app does.

``checks.py`` opens the paths declared in ``_PAGES`` and inspects nav ``href``s
for dead links. It has never *followed* one. That is the reach half of ISS-091:
the two views that crashed on staging sit **two hops** past a declared page
(``/reporting/reports/`` -> ``report_detail`` -> ``calwatrs_worksheet`` /
``report_prefill``), so no one-hop check could ever have reached them. 89-03
found them by crawling the app by hand. This module is that crawl, turned into
something that runs on every ``make test-droppable``.

**It returns; it does not assert.** The zero-5xx assertion lives in ``checks.py``
so this function stays reusable — Plan 90-03 calls it against a copy of the real
demo database, where the bar is the same but the fixture is not.

Rules it holds itself to, each for a stated reason:

* **Frontier exhaustion, not a fixed depth.** Depth 1 does not reach the crash
  and depth 2 happens to; a literal ``2`` would stop being right the day a view
  moves one link further out. A ``seen`` set and a queue have no such number in
  them.
* **In-app document links only.** An ``href`` starting with a single ``/``.
  Fragments, ``mailto:``, ``tel:``, protocol-relative and absolute URLs to other
  hosts are somebody else's surface.
* **GET only, and never anything that mutates or ends the session.** See
  ``SKIPPED_*`` below — a declared table with a reason per row, the same
  discipline ``_PAGES`` and ``SCHEMA_EXCEPTIONS`` use. ``/accounts/logout/`` is
  the one that would be silently catastrophic: it ends the crawl's own login, and
  every page after it becomes a redirect to the login wall that still *looks*
  like coverage.
* **Dedupe by path; query strings collapse.** Said out loud because it is a real
  limit rather than a detail: ``/accounting/ledger/?period=3`` and
  ``/accounting/ledger/`` are one visit here. One view in this codebase genuinely
  branches on its query string — ``reporting.views.report_generate`` reads
  ``?type=`` — so that branch is crawled in one of its two shapes, not both.
  Widening this to keep capped query variants is a real option; it was not taken
  because the bar this feeds is zero 5xx, and the collapsed shape reaches every
  view.
* **Bounded, and the bound is printed.** ``max_pages`` has a declared default and
  the unvisited remainder comes back in the result *and* gets printed. A crawl
  that stopped early must never read like a crawl that finished — that is the
  exact failure shape (a gate reporting success over ground it never covered)
  that this whole phase exists to fix.
"""

from collections import namedtuple
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

#: The default ceiling on visited paths.
#:
#: Measured, not guessed: a full 16-module deployment on the 90-01 fixture
#: exhausts its frontier at **59** paths in Admin nav mode (2026-07-22) from 33
#: seeds, while 89-03's manual crawl over the real demo database reached 1,277 —
#: the difference being rows, since every parcel and well contributes a detail
#: link. 400 leaves close to an order of magnitude of headroom over the fixture
#: without letting a runaway (a paginator that keeps inventing pages) run the
#: gate into the ground. When it bites, it says so out loud.
CRAWL_MAX_PAGES = 400

#: URL prefixes the crawl never opens.
SKIPPED_PREFIXES = (
    (
        "/admin/",
        "Django's own admin is not this platform's surface. It renders from "
        "ModelAdmin rather than from these templates, it has hundreds of routes, "
        "and its delete confirmations are one form-post from destroying the "
        "fixture the rest of the crawl is reading.",
    ),
)

#: Exact paths the crawl never opens.
SKIPPED_EXACT = (
    (
        "/accounts/logout/",
        "Ends the crawl's own session. Every page after it would 302 to the "
        "login wall and the run would still finish green, having proved nothing "
        "past the first logout link it happened to follow.",
    ),
    (
        "/nav-mode/",
        "Sets the `nav_mode` cookie and bounces back (config.views.set_nav_mode). "
        "Measured 2026-07-22: the sidebar links to it, this crawl drops query "
        "strings, and a bare GET defaults `mode` to 'operations' — so an "
        "un-skipped visit silently flips the client OUT of the mode the test "
        "chose, roughly a third of the way through a sorted frontier. Nothing "
        "would fail; the two-mode parametrization in checks.py would simply stop "
        "meaning anything, which is worse.",
    ),
)

#: Path suffixes the crawl never opens.
#:
#: These stream bytes rather than render a template, so they answer nothing about
#: whether a page renders — and reading a FileResponse to completion inside a
#: test client is cost with no finding attached.
SKIPPED_SUFFIXES = (
    (
        "/export/",
        "Streams a CSV of whatever the current filters select. Not a rendered "
        "page; the view it hangs off is crawled instead.",
    ),
    (
        "/download/",
        "Streams a generated file off disk (reporting.views.report_download). "
        "404s when the file is absent, which is the fixture's normal state, so "
        "it would add a permanent 404 to the visited set and prove nothing.",
    ),
    (
        "/template/",
        "Streams the blank CSV upload template. Same class as /export/.",
    ),
)


CrawlResult = namedtuple(
    "CrawlResult",
    "visited referrers unvisited skipped errors",
)
"""What a crawl found.

``visited``   -- ``{path: status_code}``, the final status after any redirects.
                 A view that RAISED is recorded as ``500`` here — see ``crawl``
                 for why that is the honest status rather than a special case.
``referrers`` -- ``{path: referring_path}``, where each path was first found.
                 Seeds map to ``None``. This is what makes a failure message
                 say WHICH page carried the link, which was 89-03's whole value.
``unvisited`` -- sorted paths still queued when ``max_pages`` bit. Empty on a
                 crawl that finished.
``skipped``   -- ``{path: reason}``, every link a ``SKIPPED_*`` row turned away.
``errors``    -- ``{path: repr}`` for paths whose view raised, so the assertion
                 can name the exception, not just the 500.
"""


class _LinkFinder(HTMLParser):
    """Every ``href`` on the page, in document order.

    ``HTMLParser`` rather than a regex because an ``href`` is markup, not prose:
    it can be single- or double-quoted, entity-escaped, or sit beside attributes
    containing angle brackets. ``visible_text`` in ``checks.py`` uses a regex for
    the opposite reason — it is reading words, and a real parser would be the
    wrong tool there.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def skip_reason(path):
    """Why the crawl refuses this path, or ``None`` if it does not."""
    for prefix, reason in SKIPPED_PREFIXES:
        if path.startswith(prefix):
            return reason
    for exact, reason in SKIPPED_EXACT:
        if path == exact:
            return reason
    for suffix, reason in SKIPPED_SUFFIXES:
        if path.endswith(suffix):
            return reason
    return None


def normalize(href):
    """An in-app path to crawl, or ``None`` if this ``href`` is not one.

    Drops the query string and the fragment — see the module docstring for why
    that is a stated limit rather than an oversight.
    """
    href = unescape(href).strip()
    if not href.startswith("/") or href.startswith("//"):
        # Fragments, mailto:, tel:, absolute URLs to other hosts, and
        # protocol-relative links all land here. A protocol-relative "//host/x"
        # starts with "/" and is NOT ours, which is why it is excluded by name.
        return None
    parts = urlsplit(href)
    return parts.path or None


def links_on(markup):
    """The in-app paths an HTML body links to, deduplicated, in document order."""
    finder = _LinkFinder()
    finder.feed(markup)
    out = []
    for href in finder.hrefs:
        path = normalize(href)
        if path and path not in out:
            out.append(path)
    return out


def crawl(client, seeds, *, max_pages=CRAWL_MAX_PAGES, verbose=True):
    """Walk ``seeds`` and everything they link to, and report what happened.

    ``client`` is a logged-in Django test ``Client``. Redirects are FOLLOWED, so
    the status recorded is the one the page finally answers with — a login wall
    that redirects into a 500 is a 500 here, not a 302 that looks harmless.

    The queue is drained in sorted order so two runs over the same tree visit the
    same paths in the same sequence. That matters at the cap: which paths land in
    ``unvisited`` has to be a fact about the app rather than about dict ordering.

    **A view that raises is recorded as a 500, not allowed to abort the crawl.**
    Django's test client re-raises a server exception by default — a testing
    convenience that hides exactly what this gate is looking for. In production
    Gunicorn turns that same exception into an HTTP 500, which is what a real
    user's browser gets, so 500 is the honest status to record. Catching it here
    also means one crash no longer masks the others behind it, and it makes this
    function correct for Plan 90-03's real HTTP client, which returns 500 as an
    ordinary status and never raises at all.
    """
    visited = {}
    referrers = {}
    skipped = {}
    errors = {}
    queue = []

    def offer(path, referrer):
        if path in visited or path in referrers or path in skipped:
            return
        reason = skip_reason(path)
        if reason:
            skipped[path] = reason
            return
        referrers[path] = referrer
        queue.append(path)

    for seed in seeds:
        offer(seed, None)

    while queue and len(visited) < max_pages:
        queue.sort()
        path = queue.pop(0)
        try:
            response = client.get(path, follow=True)
        except Exception as exc:  # noqa: BLE001 — a crash IS the finding here.
            # The view raised. In production this is a 500; record it as one and
            # keep going, so the crawl reports every crash rather than dying on
            # the first. The repr is kept so the assertion can name the cause.
            visited[path] = 500
            errors[path] = repr(exc)
            continue
        visited[path] = response.status_code
        # Only a rendered HTML body has links worth following. A streamed
        # response has no `.content` to read without consuming it, and a
        # non-HTML body (JSON, CSV that escaped the skip table) has no anchors.
        if response.status_code != 200:
            continue
        if "text/html" not in response.headers.get("Content-Type", ""):
            continue
        if getattr(response, "streaming", False):
            continue
        for link in links_on(response.content.decode()):
            offer(link, path)

    unvisited = sorted(queue)
    if unvisited and verbose:
        # NO SILENT CAPS. A truncated crawl that reports success reads as
        # "covered everything" when it did not — the same failure shape as
        # ISS-091 itself.
        print(
            f"\ncrawl(): stopped at max_pages={max_pages} with "
            f"{len(unvisited)} URL(s) unvisited:\n  "
            + "\n  ".join(unvisited)
        )
    return CrawlResult(
        visited=visited,
        referrers=referrers,
        unvisited=unvisited,
        skipped=skipped,
        errors=errors,
    )
