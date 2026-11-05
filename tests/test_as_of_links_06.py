# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-351: a link out of a reading keeps the reading.

Three pages read a date: the account page, the use area page and the Use Ledger. On a
reading (``?as_of=<past day>``) every link on one of them whose target is one of the three
carries ``as_of=<that day>``, so the reader lands on a page that is itself a reading. On
today's page no such link carries ``as_of``. A link to a page that reads no date (a well, a
point of diversion) carries none on either.

**The inventory** (what the tests below walk; file and line as of the base commit).

Use area page, ``templates/parcels/partials/_detail_pane.html`` (the page ``parcels/detail.html``
includes it; the workspace pane renders it too):

* line 50, "All ledger entries": ``accounting:ledger_list`` ``?q=<number>``
* line 125, the month links of Water use: ``accounting:ledger_list`` ``?q=..&start_date=..&end_date=..``
* line 190, "View all" in Recent ledger entries: ``accounting:ledger_list`` ``?q=<number>``
* line 26, "Open full page", pane only: ``parcels:detail`` (no query)
* lines 74, 83, 352, 370: a point of diversion, a well, a zone, a well: pages with no date, no ``as_of``
* ``_period_control.html`` line 22: HTMX ``hx-get`` of ``parcels:detail``; it already sends ``as_of``
  through ``hx-vals`` (checked below, not assumed)
* The use area page links to no water account.

Account page, ``templates/accounting/partials/_account_detail_pane.html`` and what it includes:

* ``_account_balances.html`` line 208: a use area in the balance table, ``parcels:detail``
* ``_parcel_assignment.html`` line 16: a use area chip, ``parcels:detail``
* ``_parcel_overview_map.html`` line 68 and 132: the map popup's "View use area" link, built by
  script from ``var detailUrl = '{% url "parcels:detail" 0 %}'``; the test reads that declaration
* ``_account_detail_pane.html`` line 39, "Open full page", pane only: ``accounting:account_detail``
* ``_account_balances.html`` line 24: the water year select, HTMX; it already sends ``as_of``

Use Ledger, ``templates/accounting/partials/_ledger_list_results.html`` and ``ledger_list.html``:

* ``_ledger_list_results.html`` line 111: the use area of each row, ``parcels:detail``
* sort, paging and filter controls: HTMX ``hx-get`` of ``accounting:ledger_list`` with
  ``hx-include="#ledger-filters"``; that form holds a hidden ``as_of`` on a reading
  (``ledger_list.html`` line 51), checked below
* the download link: ``accounting:ledger_export``, not one of the three pages; it carries ``as_of``
  already (``accounting/views/ledger.py`` line 383)
* line 118, "How was this calculated?": ``accounting:calculation_run_detail``, not one of the
  three, and a reading leaves it out

Out of scope, with the reason: the "Show today" link of the as-of line (it is the same page
with the date taken off, so it must NOT carry one); the site navigation and breadcrumbs (page
chrome that leaves the reading on purpose); links to pages that read no date.
"""
import datetime as dt
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import Resolver404, resolve

from accounting.models import WaterAccountParcel
from tests import ledger_districts as ld
from tests.test_as_of_pages_05 import (  # noqa: F401  (the autouse fixture runs by name)
    HX,
    LEDGER_PARAMS,
    _quiet,
    acct,
    age,
    day_ago,
    elements,
    has_class,
    attr,
    lines_of,
    main_of,
    logged_in,
    page,
    text_of,
    u_account,
    u_ledger,
    u_parcel,
    wy25,
    words,
)
from tests.test_fingerprint_04 import d1, operator  # noqa: F401  (fixtures are used by name)

pytestmark = pytest.mark.django_db

THE_THREE = {"parcels:detail", "accounting:ledger_list", "accounting:account_detail"}
_A_TAG = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)


def _without_scripts(html):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S | re.I)


def links(html):
    """Every ``<a href>`` on a local path: ``[(raw_href, href, text)]``, the as-of line's own links left out.

    ``raw_href`` is the attribute as written in the HTML (so ``&amp;`` shows), ``href`` is it decoded.
    """
    html = _without_scripts(html)
    if "<main" in html:  # a full page: the navigation and breadcrumbs around <main> leave the reading on purpose
        html = main_of(html)
    # The line's "Show today" is the same page with the date taken off: it is not a link out.
    for _, _, inner in elements(html, lambda t, a: has_class(a, "as-of-line")):
        html = html.replace(inner, "")
    out = []
    for m in _A_TAG.finditer(html):
        raw = re.search(r"""(?:^|\s)href\s*=\s*"([^"]*)\"""", m.group(1))
        if not raw or not raw.group(1).startswith("/") or raw.group(1).startswith(("//", "/static/")):
            continue
        out.append((raw.group(1), unescape(raw.group(1)), text_of(m.group(2))))
    return out


def target_of(href):
    try:
        return resolve(urlsplit(href).path).view_name
    except Resolver404:
        return None


def to_the_three(html):
    return [(raw, href, text) for raw, href, text in links(html) if target_of(href) in THE_THREE]


def query_of(href):
    return parse_qs(urlsplit(href).query, keep_blank_values=True)


def assert_well_joined(raw, href):
    """One ``?``, every ``&`` written ``&amp;``, no empty parameter, the date once."""
    assert raw.count("?") <= 1 and "??" not in raw, raw
    assert not re.search(r"&(?!amp;)", raw), f"a bare & in {raw!r}"
    assert "&amp;&amp;" not in raw and not raw.endswith(("?", "&amp;")), raw
    assert len(query_of(href).get("as_of", [])) <= 1, href


def assert_reading(html, day, *, expect):
    """Every link to the three pages carries the day; ``expect`` names links that must be there at all."""
    found = to_the_three(html)
    assert found, "no link to any of the three pages on this page"
    for raw, href, text in found:
        assert_well_joined(raw, href)
        assert query_of(href).get("as_of") == [day.isoformat()], f"{text!r} {raw!r} leaves the reading"
    for label, check in expect.items():
        assert any(check(raw, href, text) for raw, href, text in found), f"inventory link missing: {label}"


def assert_today(html, *, expect):
    found = to_the_three(html)
    assert found
    for raw, href, text in found:
        assert "as_of" not in raw, f"{text!r} {raw!r} carries a date on today's page"
    for label, check in expect.items():
        assert any(check(raw, href, text) for raw, href, text in found), f"inventory link missing: {label}"


def is_month_link(raw, href, text):
    q = query_of(href)
    return (
        target_of(href) == "accounting:ledger_list"
        and re.fullmatch(r"[A-Z][a-z]{2} \d{4}", text) is not None
        and q.get("q") == ["F1"] and "start_date" in q and "end_date" in q
    )


PARCEL_PAGE = {
    "All ledger entries (line 50)": lambda raw, href, text: text == "All ledger entries" and query_of(href).get("q") == ["F1"],
    "month links of Water use (line 125)": is_month_link,
    "View all (line 190)": lambda raw, href, text: text.startswith("View all") and query_of(href).get("q") == ["F1"],
}
ACCOUNT_PAGE = {
    "use area in the balance table (_account_balances line 208)": lambda raw, href, text: text == "F1" and target_of(href) == "parcels:detail",
    "use area chip (_parcel_assignment line 16)": lambda raw, href, text: text == "F2" and target_of(href) == "parcels:detail",
}
LEDGER_PAGE = {
    "use area of a row (_ledger_list_results line 111)": lambda raw, href, text: text == "F1" and target_of(href) == "parcels:detail",
}

YEAR = lambda: {"period": str(wy25().pk)}  # noqa: E731


@pytest.fixture
def reading(d1, operator):
    """D1 and D2 built and aged five days, a signed-in client, and a day two days back to read."""
    d2 = ld.build_d2()
    # G1 sits in account D1-A so its page shows the surface water block, with the point of diversion that serves it.
    WaterAccountParcel.objects.create(
        water_account=acct("D1-A"), parcel=d2["G1"],
    )
    ld.run_months(["2025-07"])  # every use area, G1 too, gets its calculation, so its page has figures
    age(5)
    return logged_in(operator), day_ago(2)


# ============================================================ every link, on a reading and on today
def test_use_area_page_links_to_the_ledger_carry_the_day_on_a_reading_with_their_other_parameters(d1, reading):
    client, day = reading
    html = page(client, u_parcel(d1["F1"]), YEAR(), as_of=day)
    assert_reading(html, day, expect=PARCEL_PAGE)


def test_use_area_page_links_carry_no_date_on_todays_page(d1, reading):
    client, _ = reading
    html = page(client, u_parcel(d1["F1"]), YEAR())
    assert_today(html, expect=PARCEL_PAGE)
    assert not lines_of(html)


def test_account_page_links_to_use_areas_carry_the_day_on_a_reading(d1, reading):
    client, day = reading
    html = page(client, u_account(acct("D1-A")), YEAR(), as_of=day)
    assert_reading(html, day, expect=ACCOUNT_PAGE)


def test_account_page_links_carry_no_date_on_todays_page(d1, reading):
    client, _ = reading
    html = page(client, u_account(acct("D1-A")), YEAR())
    assert_today(html, expect=ACCOUNT_PAGE)


def test_ledger_links_to_use_areas_carry_the_day_on_a_reading(d1, reading):
    client, day = reading
    params = {**YEAR(), "q": "F1"}
    html = page(client, u_ledger(), params, as_of=day)
    assert_reading(html, day, expect=LEDGER_PAGE)


def test_ledger_links_carry_no_date_on_todays_page(d1, reading):
    client, _ = reading
    html = page(client, u_ledger(), {**YEAR(), "q": "F1"})
    assert_today(html, expect=LEDGER_PAGE)


def test_a_use_area_link_on_a_ledger_page_that_has_other_filters_still_joins_the_day_with_one_question_mark(d1, reading):
    client, day = reading
    html = page(client, u_ledger(), LEDGER_PARAMS(), as_of=day)
    rows = [t for t in to_the_three(html) if t[2] == "F1"]
    assert rows, "the ledger lists no F1 link"
    for raw, href, _ in rows:
        assert_well_joined(raw, href)
        assert query_of(href)["as_of"] == [day.isoformat()]


# ============================================================ the panes, which are the same pages in the workspace
def test_the_open_full_page_links_of_the_use_area_and_account_panes_carry_the_day_on_a_reading(d1, reading):
    client, day = reading
    for url, name in ((u_parcel(d1["F1"]), "parcels:detail"), (u_account(acct("D1-A")), "accounting:account_detail")):
        params = {} if name == "accounting:account_detail" else YEAR()  # a period on the account asks for its balance card only
        pane = page(client, url, params, as_of=day, hx=True)
        full = [t for t in to_the_three(pane) if t[2].startswith("Open full page")]
        assert len(full) == 1, f"{name}: expected one Open full page link, found {len(full)}"
        raw, href, _ = full[0]
        assert target_of(href) == name
        assert query_of(href).get("as_of") == [day.isoformat()], raw
        today = page(client, url, params, hx=True)
        assert all("as_of" not in t[0] for t in to_the_three(today) if t[2].startswith("Open full page"))


# ============================================================ the map popup on the account page
def test_the_account_map_builds_its_use_area_link_from_a_url_that_carries_the_day_on_a_reading(d1, reading):
    client, day = reading
    declared = re.compile(r"var detailUrl = '([^']*)'")
    on_reading = declared.search(page(client, u_account(acct("D1-A")), YEAR(), as_of=day))
    assert on_reading, "the account page declares no detailUrl for its map popup"
    url = unescape(on_reading.group(1))
    assert "/0/" in url, "the popup swaps the pk into the /0/ segment"
    assert query_of(url).get("as_of") == [day.isoformat()], url
    on_today = declared.search(page(client, u_account(acct("D1-A")), YEAR()))
    assert on_today and "as_of" not in on_today.group(1)


# ============================================================ links to pages that read no date
def test_links_to_a_well_a_point_of_diversion_and_a_zone_carry_no_date_on_a_reading(d1, reading):
    client, day = reading
    seen = set()
    for parcel in (d1["F1"], ld.Parcel.objects.get(parcel_number="G1")):
        html = page(client, u_parcel(parcel), YEAR(), as_of=day)
        for raw, href, text in links(html):
            view = target_of(href)
            if view in ("wells:detail", "surface:pod_detail", "geography:zone_detail"):
                seen.add(view)
                assert "as_of" not in raw, f"{text!r} {raw!r} carries a date to a page that reads none"
    assert seen >= {"wells:detail", "surface:pod_detail"}, f"the pages gave no such link to check: {seen}"


# ============================================================ the controls that already keep the day
def test_the_water_year_selects_and_the_ledger_form_already_send_the_day(d1, reading):
    client, day = reading
    iso = day.isoformat()
    parcel = page(client, u_parcel(d1["F1"]), YEAR(), as_of=day)
    assert any(f'"as_of": "{iso}"' in t for t in re.findall(r"<select\b[^>]*>", parcel) if "hx-get" in t)
    account = page(client, u_account(acct("D1-A")), YEAR(), as_of=day)
    assert any(f'"as_of": "{iso}"' in t for t in re.findall(r"<select\b[^>]*>", account) if "hx-get" in t)
    ledger = page(client, u_ledger(), YEAR(), as_of=day)
    forms = [i for _, a, i in elements(ledger, lambda t, a: attr(a, "id") == "ledger-filters")]
    assert forms and f'name="as_of" value="{iso}"' in forms[0]


# ============================================================ follow one link from each page
def _follow(client, html, picker, day):
    raw, href, text = next(t for t in to_the_three(html) if picker(*t))
    landed = client.get(href)
    assert landed.status_code == 200, f"{href} answered {landed.status_code}"
    body = landed.content.decode()
    lines = lines_of(body)
    assert len(lines) == 1, f"following {text!r} ({raw}) lands on a page with {len(lines)} as-of lines"
    assert lines[0].startswith(f"As of the end of {words(day)}."), lines[0]
    return body


def test_following_a_link_from_the_use_area_page_lands_on_a_reading(d1, reading):
    client, day = reading
    html = page(client, u_parcel(d1["F1"]), YEAR(), as_of=day)
    body = _follow(client, html, lambda raw, href, text: text == "All ledger entries", day)
    assert 'name="q"' in body or "F1" in text_of(body)  # the ledger it landed on is the F1 search


def test_following_a_link_from_the_account_page_lands_on_a_reading(d1, reading):
    client, day = reading
    html = page(client, u_account(acct("D1-A")), YEAR(), as_of=day)
    body = _follow(client, html, lambda raw, href, text: text == "F1" and target_of(href) == "parcels:detail", day)
    assert "F1" in text_of(body)


def test_following_a_link_from_the_ledger_lands_on_a_reading(d1, reading):
    client, day = reading
    html = page(client, u_ledger(), {**YEAR(), "q": "F1"}, as_of=day)
    body = _follow(client, html, lambda raw, href, text: text == "F1" and target_of(href) == "parcels:detail", day)
    assert "F1" in text_of(body)


def test_following_a_month_link_lands_on_a_reading_of_that_month(d1, reading):
    client, day = reading
    html = page(client, u_parcel(d1["F1"]), YEAR(), as_of=day)
    _follow(client, html, lambda raw, href, text: is_month_link(raw, href, text), day)
