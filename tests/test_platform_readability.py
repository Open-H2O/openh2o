# SPDX-License-Identifier: AGPL-3.0-or-later
"""The copy rules bind the platform, not one module.

``DESIGN.md``'s *Copy rules* section says so in its own words — "They are stated
for the platform, not for one module. The drinking module is where they were
first enforced" — and until this file existed that sentence was aspirational.
``tests/test_drinking_readability.py`` pinned the mechanical rules for ten
drinking surfaces and twenty-two drinking templates; the platform's other
seventy-three pages were ungoverned, and **every copy defect this platform has
shipped was caught by a human reading the screen rather than by a gate.**

**This file does not replace that one, and deliberately duplicates some of it.**
The drinking file carries a sixty-line record of two defects a month apart and
holds module-specific assertions — the state's own vocabulary in the point
builder, GAMA and ELAP expansions, facility-type wording — that do not
generalise to a page about a recharge basin. What generalises is the mechanical
half: an American spelling, a publisher's casing, a page that says what it is,
and a comment syntax that does not leak. Those four are pinned here for
everything.

**A rule, a casing, a spelling or a proper name may be pinned — a sentence may
not.** That line is inherited whole from the drinking file and it is the reason
this file is safe to have. Three tests there once MANDATED sentences explaining
what a well is, and every hand correction was reverted by the suite on the next
run (ISS-129). If an assertion here ever requires particular words to be on a
screen, it is that defect again.

**Two halves, and the honest part.**

*Source.* Every template under ``templates/`` — pages, partials, layout shells,
199 files — with no database at all. This half reaches the arm of an ``{% if %}``
no fixture happens to take, and the HTMX partials a GET never renders. It cannot
tell a context variable from prose, so where the two halves disagree the
rendered page is the authority.

*Rendered.* Every page route the URLconf offers that takes no argument, fetched
through the authenticated test client. Pages that need a primary key the empty
test database cannot supply, endpoints that return JSON or CSV rather than a
page, and routes that redirect are **named and counted** by
``test_the_rendered_half_covers_the_pages_it_claims_to`` rather than dropped
silently — a page that stops being covered fails the gate instead of quietly
leaving it.

**Why the URLconf and not the 137-03 census.** The plan called for reversing the
census's eighty pinned URLs. The census lives in ``.planning/``, which is in both
``.gitignore`` and ``.dockerignore``, so it is not in the image the suite runs
in and a test cannot read it. Enumerating the URLconf reaches the same pages
without depending on a file that is not shipped, and it has the property the
census does not: a route added tomorrow is covered tomorrow, with no list to
update.

**Rule 6 (the 75ch prose measure) is deliberately not enforced here.** Every
``max-width: <n>ch`` in the repository is in the drinking templates. A
platform-wide assertion would be a new design mandate rather than a check on an
existing rule, and this file's job is the second thing.
"""

import json
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import get_resolver

from tests.droppability.checks import visible_text
from tests.test_drinking_readability import BRITISH_SPELLINGS, template_prose

#: Every template the platform ships: pages, partials and the layout shells.
#: Deliberately wider than the 137-03 census's 80 pages + 3 shells — a partial
#: is copy the moment HTMX swaps it in, and three of the four lowercase prose
#: `id`s the drinking audit found lived in exactly such a partial.
PLATFORM_TEMPLATES = sorted((Path(settings.BASE_DIR) / "templates").rglob("*.html"))

#: Django template syntax. Removed before the prose is read, for the reason the
#: drinking file states: `{% if recognised %}` is a context key, not copy, and
#: renaming a variable to satisfy a spelling rule would be the tail wagging the
#: dog. Non-greedy and DOTALL rather than the drinking file's character-class
#: form, because several templates carry `>=` inside a `{% if %}` and a few
#: carry `%` inside a filter argument.
_TEMPLATE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)

#: A bare lowercase `id` in prose. `ID` is capitalised in prose as well as in
#: labels (DESIGN.md rule 2). The lookarounds keep `identifier`, `id-scheme`
#: and `path/id` out of it.
_BARE_ID = re.compile(r"(?<![\w/-])id(?![\w-])")


def platform_prose(path):
    """A template's source reduced to the words a reader would see.

    Three passes, in this order, and the order is load-bearing:

    1. ``template_prose`` — the drinking file's stripper, imported rather than
       reimplemented. It removes ``{% comment %}``, ``{# #}``, HTML comments,
       ``<script>``, ``<style>`` and ``<th>`` (data-table headers are exempt
       from the casing rule by DESIGN.md and are uppercased in CSS anyway).
    2. Django template syntax. This must happen **before** the tags are
       stripped: `<td class="{% if x >= 0 %}a{% endif %}">` carries a ``>``
       inside the attribute, so a tag regex run first would close the tag early
       and spill markup into the prose.
    3. ``visible_text`` — the same function the rendered assertions use. It
       keeps the four attributes whose values a person reads (``placeholder``,
       ``title``, ``aria-label``, ``alt``) and takes every other attribute with
       the tag.

    Step 3 is what the drinking file's source half does not do, and it is here
    because of a measured false positive: ``_feedback_widget.html`` carries
    ``aria-labelledby="oh2o-fb-title"``, an attribute NAME containing the
    British ``labelled``. An attribute name is markup. Narrowing the spelling
    pattern to dodge it would have been a silencing fix; drawing the
    markup/copy line where ``visible_text`` already draws it is not.
    """
    stripped = _TEMPLATE_TAG.sub(" ", template_prose(path))
    return visible_text(stripped)


def _relative(path):
    return str(path.relative_to(Path(settings.BASE_DIR)))


# ---------------------------------------------------------------------------
# The rendered half: which routes are pages, and which pages an empty database
# can actually reach.
# ---------------------------------------------------------------------------

#: URL prefixes whose views are not this platform's pages. Django's admin and
#: the debug toolbar ship their own copy and are not ours to police.
_NOT_OUR_PAGES = ("admin/", "__debug__/")


def _no_argument_routes():
    """Every URLconf route that a GET can reach with no arguments at all.

    Recursive over ``include()``d resolvers. A pattern containing ``<`` needs a
    primary key or a code the empty test database cannot supply, so it is not
    reachable here — that is a coverage fact, reported by
    ``test_the_rendered_half_covers_the_pages_it_claims_to``, not a violation.
    """
    routes = []

    def walk(resolver, prefix=""):
        for entry in resolver.url_patterns:
            pattern = prefix + str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                walk(entry, pattern)
            elif "<" not in pattern and not pattern.startswith(_NOT_OUR_PAGES):
                routes.append("/" + pattern)

    walk(get_resolver())
    return sorted(set(routes))


#: The crawl is cached for the module. Every one of these requests is a GET
#: against a database with no rows in it, so the response cannot depend on which
#: test asked for it, and crawling once instead of once per assertion is the
#: difference between a gate that runs in seconds and one nobody wants in the
#: suite.
_CRAWL_CACHE = {}


def _crawl(client):
    """Fetch every argument-free route and partition it into pages and not-pages.

    Returns ``(rendered, unreachable)``. ``rendered`` maps a URL to its raw
    markup and to the words a reader sees on it; ``unreachable`` maps a URL to
    the reason it is not in the first dictionary — a status code, a content
    type, or a body that is a fragment rather than a document.
    """
    if _CRAWL_CACHE:
        return _CRAWL_CACHE["rendered"], _CRAWL_CACHE["unreachable"]

    rendered, unreachable = {}, {}
    for url in _no_argument_routes():
        try:
            response = client.get(url)
        except Exception as exc:  # noqa: BLE001 — the reason is the report
            unreachable[url] = f"raised {type(exc).__name__}"
            continue
        if response.status_code != 200:
            unreachable[url] = f"HTTP {response.status_code}"
            continue
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            unreachable[url] = f"not a page ({content_type.split(';')[0]})"
            continue
        body = response.content.decode(errors="replace")
        if "</html>" not in body:
            unreachable[url] = "HTMX fragment, not a document"
            continue
        rendered[url] = {"html": body, "text": visible_text(body)}

    _CRAWL_CACHE["rendered"] = rendered
    _CRAWL_CACHE["unreachable"] = unreachable
    return rendered, unreachable


@pytest.fixture
def crawled(db, django_user_model):
    """Every reachable page's visible text, and every unreachable route's reason.

    The crawler signs in as a **superuser**, and that is a coverage decision
    rather than a convenience. Signed in as an ordinary reader, eleven pages —
    the whole setup wizard, the user list, the methodology and delivery
    settings screens — answer 302 and drop out of the gate entirely. Those
    pages carry copy like any other; the person who reads them is an
    administrator.
    """
    user = django_user_model.objects.filter(username="platform-reader").first()
    if user is None:
        user = django_user_model.objects.create(
            username="platform-reader",
            email="platform-reader@example.gov",
            password=make_password("pw"),
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
    client = Client()
    client.force_login(user)
    return _crawl(client)


# ---------------------------------------------------------------------------
# Rule 3 — American spelling in anything a reader sees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", BRITISH_SPELLINGS)
def test_no_british_spelling_sits_in_any_template(spelling):
    """Rule 3, at source, across every template the platform ships.

    This is the rule with a shipped defect behind it: `GAMA programme` reached
    staging in Phase 101 across four surfaces and was caught by eye.
    """
    offenders = []
    for template in PLATFORM_TEMPLATES:
        if spelling in platform_prose(template).lower():
            offenders.append(_relative(template))
    assert offenders == [], (
        f"'{spelling}' is British and reaches a reader in: {offenders}. "
        "DESIGN.md copy rule 3 — American spelling in anything a reader sees."
    )


def test_no_british_spelling_reaches_a_rendered_page(crawled):
    """Rule 3, on the pages themselves.

    All twenty-one spellings in one pass rather than a parametrised test each:
    the crawl is the expensive part and it is shared, so splitting would buy
    nothing but wall-clock.
    """
    rendered, _ = crawled
    offenders = []
    for url, page in rendered.items():
        lowered = page["text"].lower()
        for spelling in BRITISH_SPELLINGS:
            if spelling in lowered:
                offenders.append(f"{url}: {spelling}")
    assert offenders == [], f"British spelling on a rendered page: {offenders}"


# ---------------------------------------------------------------------------
# Rule 2 — a published identifier keeps the publisher's own casing
# ---------------------------------------------------------------------------


def test_identifier_is_capitalised_in_prose_everywhere():
    """Rule 2, at source. The platform writes "Facility ID"; prose that writes
    "id" is the outlier, not the rule.

    An HTML ``id=`` attribute is markup and never reaches this text —
    ``platform_prose`` strips it with the tag rather than by a special case.
    """
    offenders = []
    for template in PLATFORM_TEMPLATES:
        if _BARE_ID.search(platform_prose(template)):
            offenders.append(_relative(template))
    assert offenders == [], f"a bare lowercase 'id' in prose: {offenders}"


def test_identifier_is_capitalised_on_every_rendered_page(crawled):
    """Rule 2, on the pages themselves."""
    rendered, _ = crawled
    offenders = [url for url, page in rendered.items() if _BARE_ID.search(page["text"])]
    assert offenders == [], f"a bare lowercase 'id' in prose: {offenders}"


def test_the_states_field_name_keeps_the_states_casing():
    """Rule 2's measured instance. California's own SDWIS4 export heads the
    column ``PS Code``, so that is the spelling — in prose, in a field label and
    in a placeholder alike.

    Zero violations outside the drinking module when this gate was written. It
    is here so that stays true when a second module starts reading state files.
    """
    offenders = [
        _relative(template)
        for template in PLATFORM_TEMPLATES
        if "PS code" in platform_prose(template)
    ]
    assert offenders == [], f"writing the state's field name as 'PS code': {offenders}"


def test_the_states_field_name_keeps_its_casing_on_every_page(crawled):
    """Rule 2's measured instance, on the pages themselves."""
    rendered, _ = crawled
    offenders = [url for url, page in rendered.items() if "PS code" in page["text"]]
    assert offenders == [], f"writing the state's field name as 'PS code': {offenders}"


# ---------------------------------------------------------------------------
# Rule 10 — multi-line template comments use {% comment %}
# ---------------------------------------------------------------------------


def test_a_multi_line_comment_uses_the_comment_tag():
    """Rule 10. ``{# #}`` closes at end of line, so its second line onward
    renders as page text — the defect
    ``test_no_template_syntax_leaks_into_the_page`` exists to catch.

    A run of two or more consecutive ``{# #}`` lines is a multi-line comment
    written in the single-line syntax. One ``{# #}`` line is fine and stays fine.
    """
    offenders = []
    for template in PLATFORM_TEMPLATES:
        run = 0
        for number, line in enumerate(template.read_text().splitlines(), start=1):
            if line.strip().startswith("{#"):
                run += 1
                continue
            if run >= 2:
                offenders.append(f"{_relative(template)}:{number - run} ({run} lines)")
            run = 0
        if run >= 2:
            offenders.append(f"{_relative(template)} (trailing run of {run})")
    assert offenders == [], (
        "a multi-line comment written as repeated {# #} — DESIGN.md copy rule 10 "
        f"says use {{% comment %}}: {offenders}"
    )


# ---------------------------------------------------------------------------
# Rule 1's neighbour — a page that says what it is
# ---------------------------------------------------------------------------

#: The pages that carry no `<p class="page-description">`, and why.
#:
#: **Measured before this was written, and the measurement changed the rule.**
#: The plan asked for "every page carries a non-empty page description". Crawled,
#: 39 of the 60 reachable pages carry one and 21 do not — and the 21 are not an
#: oversight, they are three coherent kinds of page. A `page-description` lives
#: in the breadcrumb bar of a LIST or DETAIL page, where a reader arriving from
#: the sidebar needs to be told what they are looking at. A form page says what
#: it is in the card header above the fields ("Create water account"); an auth
#: screen says it in its own heading; the two landing pages say it in a hero.
#: Asserting a description on all sixty would have MANDATED twenty-one new
#: sentences, which is the ISS-129 defect wearing a different hat.
#:
#: So this is a ratchet in both directions, not an exemption list. A page that
#: loses its description fails. A page listed here that GAINS one fails too, so
#: the entry gets deleted rather than accumulating. A new page lands in neither
#: set and forces a deliberate call.
PAGES_WITHOUT_A_DESCRIPTION = {
    # Phase 143-02 (R-031, R-132) gave the create forms, the station form, the
    # user form, Profile and About a description under a visible title, and
    # their card headers now say the remainder ("Details"). One form page keeps
    # the exemption: its lead-in sentence sits in the card because it is
    # conditional on the module set.
    "/reporting/reports/generate/": "form page — the lead-in sentence is in the card",
    # The signed-in home opens with a hero that carries the same job.
    "/": "landing page — the hero carries it",
    # django-allauth's screens. Their headings are the description, they are
    # not part of the sidebar's information architecture, and their markup is
    # allauth's rather than ours.
    "/accounts/3rdparty/": "auth screen — its own heading carries it",
    "/accounts/3rdparty/login/cancelled/": "auth screen — its own heading carries it",
    "/accounts/confirm-email/": "auth screen — its own heading carries it",
    "/accounts/email/": "auth screen — its own heading carries it",
    "/accounts/inactive/": "auth screen — its own heading carries it",
    "/accounts/logout/": "auth screen — its own heading carries it",
    "/accounts/password/change/": "auth screen — its own heading carries it",
    "/accounts/password/reset/": "auth screen — its own heading carries it",
    "/accounts/password/reset/done/": "auth screen — its own heading carries it",
    "/accounts/password/reset/key/done/": "auth screen — its own heading carries it",
    "/accounts/reauthenticate/": "auth screen — its own heading carries it",
}


def _page_description(html):
    """The words inside a page's `<p class="page-description">`, or None."""
    blocks = re.findall(r'<p class="page-description">(.*?)</p>', html, re.S)
    if not blocks:
        return None
    return visible_text(blocks[0]).strip() or None


def test_every_list_and_detail_page_says_what_it_is(crawled):
    """Rule 1's neighbour. Asserts a description EXISTS and has words in it,
    never which words — the whole point of the ISS-129 line this file inherits.
    """
    rendered, _ = crawled
    bare = [
        url
        for url, page in rendered.items()
        if url not in PAGES_WITHOUT_A_DESCRIPTION
        and _page_description(page["html"]) is None
    ]
    assert bare == [], (
        "a page carries no description and is not one of the form, auth or "
        f"landing pages that answer that another way: {bare}"
    )


def test_the_description_ratchet_holds_in_the_other_direction(crawled):
    """A page listed as having no description that now has one.

    Without this half the list only ever grows, and a gate whose exemption list
    grows is a gate that stops governing.
    """
    rendered, _ = crawled
    gained = [
        url
        for url in PAGES_WITHOUT_A_DESCRIPTION
        if url in rendered and _page_description(rendered[url]["html"]) is not None
    ]
    assert gained == [], (
        "these pages now carry a page description — delete their entries from "
        f"PAGES_WITHOUT_A_DESCRIPTION: {gained}"
    )


# ---------------------------------------------------------------------------
# Coverage — what the rendered half could not reach, by name
# ---------------------------------------------------------------------------

#: Every argument-free route the crawl could not turn into a page, with the
#: reason the crawl gave. Pinned so that a page dropping out of coverage FAILS
#: rather than quietly reducing what this gate governs.
#:
#: Measured 2026-09-06: **108 argument-free routes, 60 of them pages, 48 here.**
#: Regenerate deliberately, never to get green — a route arriving in this list
#: means a page stopped being governed, and that is the failure this dictionary
#: exists to produce.
EXPECTED_UNREACHABLE = {
    # Map layers, downloads and health probes. These carry data, not copy — a
    # GeoJSON feature collection has no prose for a spelling rule to read.
    "/accounting/ledger/export/": "not a page (text/csv)",
    "/accounting/ledger/template/": "not a page (text/csv)",
    "/datasync/stations/freshness-geojson/": "not a page (application/json)",
    "/datasync/stations/geojson/": "not a page (application/json)",
    "/drinking/facilities/geojson/": "not a page (application/json)",
    "/health/api/": "not a page (application/json)",
    "/health/db/": "not a page (text/plain)",
    "/health/live/": "not a page (text/plain)",
    "/infrastructure/geojson/": "not a page (application/json)",
    "/map/boundaries/geojson/": "not a page (application/json)",
    "/map/flowlines/geojson/": "not a page (application/json)",
    "/map/tie-lines/geojson/": "not a page (application/json)",
    "/map/zones/geojson/": "not a page (application/json)",
    "/map/zones/labels/geojson/": "not a page (application/json)",
    "/map/zones/overview/geojson/": "not a page (application/json)",
    "/parcels/geojson/": "not a page (application/json)",
    "/recharge/sites/geojson/": "not a page (application/json)",
    "/surface/pods/geojson/": "not a page (application/json)",
    "/wells/geojson/": "not a page (application/json)",
    # POST-only endpoints. A GET is refused, so there is no page to read. The
    # templates BEHIND these — the import previews, the onboarding review — are
    # swept by the source half, which is exactly why the source half exists.
    "/drinking/import/commit/": "HTTP 405",
    "/drinking/import/preview/": "HTTP 405",
    "/drinking/onboard/commit/": "HTTP 405",
    "/drinking/onboard/lookup/": "HTTP 405",
    "/feedback/submit/": "HTTP 405",
    "/infrastructure/import/commit/": "HTTP 405",
    "/infrastructure/import/preview/": "HTTP 405",
    "/infrastructure/parcels/create/": "HTTP 405",
    "/setup/activate-stations/": "HTTP 405",
    "/setup/progress/": "HTTP 405",
    # HTMX fragments: a GET returns a piece of a page rather than a document.
    # Their templates are swept at source.
    "/accounting/methodology/preview/": "HTMX fragment, not a document",
    "/infrastructure/parcels/search/": "HTMX fragment, not a document",
    "/search/": "HTMX fragment, not a document",
    # Redirects that are the point of the route: a preference toggle bounces
    # back, and a setup step that has nothing to confirm sends you to the step
    # that does.
    "/nav-mode/": "HTTP 302",
    "/setup/confirm/": "HTTP 302",
    "/setup/run/": "HTTP 302",
    # django-allauth. Sign-in, sign-up and password-set redirect because the
    # crawler is already signed in — that is the correct behaviour, and it is
    # why `templates/account/` is swept at source instead. The social-account
    # routes 404 or 301 because no provider is configured on this platform.
    "/accounts/3rdparty/login/error/": "HTTP 401",
    "/accounts/3rdparty/signup/": "HTTP 302",
    "/accounts/google/login/": "HTTP 404",
    "/accounts/google/login/callback/": "HTTP 404",
    "/accounts/google/login/token/": "HTTP 404",
    "/accounts/login/": "HTTP 302",
    "/accounts/login/code/confirm/": "HTTP 302",
    "/accounts/password/set/": "HTTP 302",
    "/accounts/signup/": "HTTP 302",
    "/accounts/social/connections/": "HTTP 301",
    "/accounts/social/login/cancelled/": "HTTP 301",
    "/accounts/social/login/error/": "HTTP 301",
    "/accounts/social/signup/": "HTTP 301",
}


def test_the_rendered_half_covers_the_pages_it_claims_to(crawled):
    """The honest half of a rendered-page gate.

    The source sweep needs no data and covers every template. The rendered
    sweep covers whatever an empty test database can actually reach, and this
    test is the record of the difference: every route that did not become a
    page is named here with its reason, so coverage shrinking is a failure and
    not a silence.
    """
    rendered, unreachable = crawled
    assert rendered, "the crawl reached no pages at all"

    appeared = {
        url: reason
        for url, reason in unreachable.items()
        if url not in EXPECTED_UNREACHABLE
    }
    vanished = {
        url: reason
        for url, reason in EXPECTED_UNREACHABLE.items()
        if url not in unreachable
    }
    changed = {
        url: f"{EXPECTED_UNREACHABLE[url]} -> {reason}"
        for url, reason in unreachable.items()
        if url in EXPECTED_UNREACHABLE and EXPECTED_UNREACHABLE[url] != reason
    }
    assert not appeared, (
        "a page left the rendered half of the readability gate: "
        f"{json.dumps(appeared, indent=2, sort_keys=True)}"
    )
    assert not vanished, (
        "a route pinned as unreachable now reaches — delete its pin: "
        f"{json.dumps(vanished, indent=2, sort_keys=True)}"
    )
    assert not changed, (
        "an unreachable route changed its reason: "
        f"{json.dumps(changed, indent=2, sort_keys=True)}"
    )
