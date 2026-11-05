# SPDX-License-Identifier: AGPL-3.0-or-later
"""The as-of date box on the pages.

A clerk asked "What did the district know when it billed him?" types a date and reads
the records and figures as they were at the end of that day. These tests drive the REAL
views through the test client, on the D1 district (``tests/ledger_districts.py``, built
and calculated by the fixtures of ``tests/test_fingerprint_04.py``), with the backdating
helper of ``tests/test_as_of_05.py`` (:func:`age`), and prove the feature from outside.

**The instrument.** A reading is compared with the REAL earlier page, not with a formula.
Before a change the test fetches the ordinary page (``snapshot``); after the change and
:func:`age` it fetches the page again as of the day before and the day of the change. The
reading before the change must equal the earlier page, the reading on the day must equal
today's page, and the two must differ (a precondition: a change that moves nothing proves
nothing). Counts the pages print are held against ``Reading.changed_count`` and
``has_records`` called with the scope the design states, so a wrong expectation here shows
on the code that exists, not only on the code to come.

**What a test assumes about markup** (the drawing, ``as-of-mockup-2026-11-04``):

* the line is the one element with class ``as-of-line`` (its text: the sentence, a
  separator, ``Show today``), inside an element with class ``as-of-reading``;
* the box is an ``<input type="date" name="as_of">`` inside a ``<form>``. The test submits
  that form as a browser would (its hidden fields and selects, plus the date) and holds the
  result to "same page, every other parameter kept". A box that is not in a form fails
  ``test_the_box_is_a_form_...``; that is the one place this file leans on a design choice;
* a control that carries the date through HTMX does so in its own tag (``as_of`` in the
  ``hx-get``, ``hx-vals`` or ``hx-include``) or through ``hx-include="#ledger-filters"``
  while that form holds an ``as_of`` field.
"""
import csv
import datetime as dt
import io
import re
from decimal import Decimal as D
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from accounting.models import ReportingPeriod, WaterAccount
from core.as_of import reading_as_of
from core.corrections import correct, void
from parcels.models import ParcelLedger
from tests import ledger_districts as ld

# The fixtures and helpers of the two earlier files: one hand-checked district, built and
# calculated, a year that can be finalized, three kinds of person; and the backdating helper.
from tests.test_as_of_05 import (  # noqa: F401
    REASON,
    WY25,
    age,
    day_ago,
    double_july_et,
    forget_history,
    meter_row,
)
from tests.test_fingerprint_04 import (  # noqa: F401  (fixtures are used by name)
    HX,
    NO_CHANGES,
    _answer,
    _client,
    administrator,
    d1,
    filed,
    operator,
    viewer,
    year,
)

pytestmark = pytest.mark.django_db

# Written out here, never read back from the code under test.
UNREADABLE = "That date could not be read. This page shows today."
IN_FUTURE = "That date is in the future. This page shows today."
NO_RECORDS = "No records had been entered by then."
CSV_COLUMNS = [
    "parcel_number", "effective_date", "amount_acre_feet", "source_type",
    "water_type_code", "description", "transaction_date", "calculation_method",
]
DEMONSTRATION_LINE = "This file comes from the OpenH2O demonstration. Its figures are sample data."
FORBIDDEN = ("audit trail", "tamper", "evidence", "attestation", "sworn", "certified", "verify", "proof")


@pytest.fixture(autouse=True)
def _quiet(settings):
    """Like the fingerprint tests: access control on, and no calculation starts on its own."""
    from unittest import mock

    settings.ACCESS_CONTROL_ENFORCED = True
    with mock.patch("accounting.engine_run.start_calculation"):
        yield


# ================================================================ small tools
def words(day):
    """A date as the pages print it: Nov 3, 2026."""
    return f"{day:%b} {day.day}, {day.year}"


def since(n):
    if n == 0:
        return "Since then no records changed."
    return f"Since then {n} record{'' if n == 1 else 's'} changed."


_TAG = re.compile(r"<(/?)([a-zA-Z][\w:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
_VOID = {"input", "br", "img", "hr", "meta", "link", "source", "area", "col", "wbr", "base", "embed", "track", "param"}


def without_actions(html):
    """The page without its row-menu cells: those are writing controls, not figures."""
    return re.sub(r"<t([dh])\b[^>]*\brow-actions\b[^>]*>.*?</t\1>", "", html, flags=re.S)


def scrub(html):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S | re.I)


def elements(html, match):
    """Every element whose start tag satisfies ``match(tag, attrs)``: ``[(tag, attrs, inner_html)]``."""
    html = scrub(html)
    found, stack = [], []
    for m in _TAG.finditer(html):
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag in _VOID or attrs.rstrip().endswith("/"):
            continue
        if not closing:
            stack.append((tag, attrs, m.end(), bool(match(tag, attrs))))
            continue
        while stack:
            top = stack.pop()
            if top[0] == tag:
                if top[3]:
                    found.append((tag, top[1], html[top[2]:m.start()]))
                break
    return found


def attr(attrs, name):
    m = re.search(rf"""(?:^|\s){re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)')""", attrs)
    if not m:
        return None
    return unescape(m.group(1) if m.group(1) is not None else m.group(2))


def has_flag(attrs, name):
    return bool(re.search(rf"(?:^|\s){re.escape(name)}(?=[\s=/]|$)", attrs))


def has_class(attrs, name):
    return name in (attr(attrs, "class") or "").split()


def text_of(fragment):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", scrub(fragment)))).strip()


def start_tags(html, needle):
    """Every start tag (as text) that contains ``needle``."""
    return [m.group(0) for m in _TAG.finditer(scrub(html)) if not m.group(1) and needle in m.group(0)]


def main_of(html):
    found = elements(html, lambda t, a: t == "main")
    assert found, "the page has no <main>"
    return found[0][2]


def visible(html):
    return text_of(main_of(html))


# ---------------------------------------------------------------- the line, the box, the forms
def lines_of(html):
    return [text_of(i) for _, _, i in elements(html, lambda t, a: has_class(a, "as-of-line"))]


def line_of(html):
    found = lines_of(html)
    assert len(found) == 1, f"expected exactly one as-of line, found {len(found)}"
    return found[0]


def assert_line(html, day, tail):
    """The line reads ``As of the end of <day>. <tail>``, a separator, then ``Show today``."""
    text = line_of(html)
    head = f"As of the end of {words(day)}. {tail}"
    assert text.startswith(head), f"{text!r} does not start with {head!r}"
    rest = text[len(head):].strip()
    assert rest.endswith("Show today"), text
    separator = rest[: -len("Show today")].strip()
    assert separator and not re.search(r"\w", separator), f"no separator between the sentence and Show today: {text!r}"


def show_today_href(html):
    for _, attrs, inner in elements(html, lambda t, a: has_class(a, "as-of-line")):
        for _, a_attrs, a_inner in elements(inner, lambda t, a: t == "a"):
            if text_of(a_inner) == "Show today":
                return attr(a_attrs, "href")
    raise AssertionError("Show today is not a link in the line")


def date_inputs(html):
    """The visible date boxes: ``<input type="date" name="as_of">``."""
    return [
        m.group(0) for m in re.finditer(r"<input\b[^>]*>", scrub(html), re.I)
        if attr(m.group(0), "name") == "as_of" and attr(m.group(0), "type") == "date"
    ]


class BoxForm:
    def __init__(self, action, method, fields, value, input_tag):
        self.action, self.method, self.fields, self.value, self.input_tag = action, method, fields, value, input_tag


def box_form(html):
    """The form that holds the date box, with the fields a browser would send from it."""
    for tag, attrs, inner in elements(html, lambda t, a: t == "form"):
        box = [m.group(0) for m in re.finditer(r"<input\b[^>]*>", inner, re.I)
               if attr(m.group(0), "name") == "as_of" and attr(m.group(0), "type") == "date"]
        if not box:
            continue
        fields = {}
        for m in re.finditer(r"<input\b[^>]*>", inner, re.I):
            tag_text = m.group(0)
            name, kind = attr(tag_text, "name"), (attr(tag_text, "type") or "text").lower()
            if not name or name == "as_of" or kind in ("submit", "button", "reset", "file", "image"):
                continue
            if kind in ("checkbox", "radio") and not has_flag(tag_text, "checked"):
                continue
            fields[name] = attr(tag_text, "value") or ""
        for _, s_attrs, s_inner in elements(inner, lambda t, a: t == "select"):
            name = attr(s_attrs, "name")
            options = [m.group(0) for m in re.finditer(r"<option\b[^>]*>", s_inner, re.I)]
            chosen = next((o for o in options if has_flag(o, "selected")), options[0] if options else None)
            if name and chosen is not None:
                fields[name] = attr(chosen, "value") or ""
        return BoxForm(attr(attrs, "action") or "", (attr(attrs, "method") or "get").lower(), fields,
                       attr(box[0], "value") or "", box[0])
    raise AssertionError("the date box is not inside a <form>")


def assert_box_leads_to(html, path, expected, day):
    """Submitting the box form lands on ``path`` with ``expected`` kept and ``as_of`` set to ``day``."""
    form = box_form(html)
    assert form.method == "get"
    target = urlsplit(form.action)
    assert (target.path or path) == path, f"the box leads to {form.action!r}, not {path!r}"
    sent = {k: v[0] for k, v in parse_qs(target.query, keep_blank_values=True).items()}
    sent.update(form.fields)
    for key, value in expected.items():
        assert key in sent and sent[key] == value, f"the box drops or changes {key}={value!r}: sends {sent!r}"
    return {**sent, "as_of": day.isoformat()}


def hrefs_in_main(html):
    out = []
    for _, attrs, _inner in elements(main_of(html), lambda t, a: t == "a"):
        href = attr(attrs, "href")
        if href and href.startswith("/") and not href.startswith("//") and not href.startswith("/static/") \
                and "logout" not in href:
            out.append(unescape(href))
    return sorted(set(out))


# ---------------------------------------------------------------- the district and the requests
def u_account(account):
    return reverse("accounting:account_detail", args=[account.pk])


def u_parcel(parcel):
    return reverse("parcels:detail", args=[parcel.pk])


def u_ledger():
    return reverse("accounting:ledger_list")


def u_export():
    return reverse("accounting:ledger_export")


def acct(number):
    return WaterAccount.objects.get(account_number=number)


def wy25():
    return ReportingPeriod.objects.get(name=WY25)


def wy26():
    return ReportingPeriod.objects.get(name="WY 2025-2026")


def get(client, url, params=None, *, as_of=None, hx=False, status=200):
    query = dict(params or {})
    if as_of is not None:
        query["as_of"] = as_of if isinstance(as_of, str) else as_of.isoformat()
    response = client.get(url, query, **(HX if hx else {}))
    assert response.status_code == status, f"{url} {query} answered {response.status_code}"
    return response


def page(client, url, params=None, **kwargs):
    return get(client, url, params, **kwargs).content.decode()


def csv_rows(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))


# ---------------------------------------------------------------- what a page's figures are
def account_figs(html):
    return " | ".join(text_of(i) for _, a, i in elements(html, lambda t, a: has_class(a, "budget-panel")))


def parcel_figs(html):
    keep = lambda t, a: t == "table" or has_class(a, "statement-lead") or has_class(a, "statement-balance")  # noqa: E731
    return " | ".join(text_of(without_actions(i)) for _, _, i in elements(html, keep))


def ledger_table(html):
    """The table's text. "How was this calculated?" is left out: a reading leaves that row unlinked
    (its target shows today's receipt, or answers 404 when the month has none today), so the words go with the link."""
    text = " | ".join(
        text_of(without_actions(i)) for _, a, i in elements(html, lambda t, a: t == "table" and has_class(a, "data-table"))
    )
    return re.sub(r"\s+", " ", text.replace("How was this calculated?", "")).strip()


def ledger_rows(html):
    """Each row of the ledger as ``(struck, [cell texts])``."""
    out = []
    for _, attrs, inner in elements(html, lambda t, a: t == "tr" and attr(a, "id")):
        cells = [text_of(i) for _, _, i in elements(inner, lambda t, a: t == "td")]
        out.append((has_class(attrs, "record-void"), cells))
    return out


def snapshot(client, d1_, *, as_of=None):
    """The pages and the file that carry the figures, for WY 2024-2025, as of a day (or today)."""
    year_ = {"period": str(wy25().pk)}
    snap = {
        "account_a": account_figs(page(client, u_account(acct("D1-A")), year_, as_of=as_of)),
        "account_b": account_figs(page(client, u_account(acct("D1-B")), year_, as_of=as_of)),
        "f1": parcel_figs(page(client, u_parcel(d1_["F1"]), year_, as_of=as_of)),
        "f3": parcel_figs(page(client, u_parcel(d1_["F3"]), year_, as_of=as_of)),
        "ledger": ledger_table(page(client, u_ledger(), year_, as_of=as_of)),
    }
    rows = csv_rows(get(client, u_export(), year_, as_of=as_of))
    if as_of is not None:
        assert rows[0] == [f"As of the end of {words(as_of)}."], rows[0]
        rows = rows[1:]
    snap["csv"] = rows
    return snap


def assert_reads(client, d1_, day, expected):
    got = snapshot(client, d1_, as_of=day)
    for key in expected:
        assert got[key] == expected[key], f"{key} as of {day} is not the page it should be"


def settle():
    """Run July once so every use area (the fingerprint district's extra field too) has its calculation."""
    ld.run_months(["2025-07"])


def logged_in(user):
    return _client(user)


# ---------------------------------------------------------------- the changes
def correct_f1_july(d1_, user):
    """F1's July meter-reading entry, -30 to -20, made 10 days ago in a district set up 30 days ago."""
    client = logged_in(user)
    pre = snapshot(client, d1_)
    age(20)
    correct(meter_row(d1_["F1"], ld.JUL), user=user, reason=REASON, changes={"amount_acre_feet": D("-20.0000")})
    age(10)
    return client, pre, snapshot(client, d1_)


def assert_moved(pre, post, keys):
    for key in keys:
        assert pre[key] != post[key], f"the change must move {key} or this proves nothing"


# ================================================================ (a) a corrected row
def test_a_reading_corrected_on_day_10_shows_the_old_figure_as_of_day_9_and_the_new_as_of_day_10(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    assert_moved(pre, post, ["account_a", "f1", "ledger", "csv"])
    assert pre["account_b"] == post["account_b"] and pre["f3"] == post["f3"]  # nothing else moved
    assert_reads(client, d1, day_ago(11), pre)  # the day before the correction: the old figures
    assert_reads(client, d1, day_ago(10), post)  # the day of it: the new ones


def test_the_csv_as_of_the_day_before_a_correction_carries_the_old_amount_and_the_day_of_it_the_new(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)

    def f1_july(rows):
        return [r[2] for r in rows if r[0] == "F1" and r[1] == "2025-07-01" and r[3] == "meter_reading"]

    assert f1_july(pre["csv"]) == ["-30.0000"] and f1_july(post["csv"]) == ["-20.0000"]
    year_ = {"period": str(wy25().pk)}
    old = csv_rows(get(client, u_export(), year_, as_of=day_ago(11)))
    new = csv_rows(get(client, u_export(), year_, as_of=day_ago(10)))
    assert f1_july(old[1:]) == ["-30.0000"]
    assert f1_july(new[1:]) == ["-20.0000"]


# ================================================================ (b) a voided row
def test_a_voided_row_shows_as_of_the_day_before_the_void_unstruck_and_not_after(d1, operator):
    client = logged_in(operator)
    pre = snapshot(client, d1)
    age(15)
    void(meter_row(d1["F2"], ld.AUG), user=operator, reason=REASON)
    age(5)  # voided 5 days ago
    post = snapshot(client, d1)
    assert_moved(pre, post, ["account_a", "ledger", "csv"])
    year_ = {"period": str(wy25().pk)}

    before = page(client, u_ledger(), year_, as_of=day_ago(6))
    assert "record-void" not in before, "the row was not voided yet: it must not be struck"
    assert not any(struck for struck, _ in ledger_rows(before))
    assert_reads(client, d1, day_ago(6), pre)

    after = page(client, u_ledger(), year_, as_of=day_ago(5))
    assert any(struck for struck, cells in ledger_rows(after) if cells[1] == "F2"), "from its day the row is struck"
    assert_reads(client, d1, day_ago(5), post)


# ================================================================ (c) a recalculation
def test_a_recalculation_on_day_12_that_moved_a_figure_reads_the_earlier_run_as_of_day_11(d1, operator):
    client = logged_in(operator)
    settle()
    pre = snapshot(client, d1)
    age(8)
    double_july_et(d1["F3"])
    ld.run_months(["2025-07"])  # re-run 12 days ago, below
    post = snapshot(client, d1)
    age(12)
    assert_moved(pre, post, ["account_b", "f3", "ledger", "csv"])
    assert pre["account_a"] == post["account_a"] and pre["f1"] == post["f1"]
    assert_reads(client, d1, day_ago(13), pre)
    assert_reads(client, d1, day_ago(12), post)


# ================================================================ (d) rows with no history, and none at all
def test_a_date_before_any_event_on_rows_with_no_history_shows_the_rows_as_they_are_and_counts_later_changes(
    d1, operator
):
    client = logged_in(operator)
    forget_history()
    age(20)  # every row created 20 days ago, with no history at all
    pre = snapshot(client, d1)
    f1, f2 = d1["F1"], d1["F2"]
    ld.ledger(f1, dt.date(2025, 9, 15), "-5.0000", "manual_entry", "GW")  # three later changes, today
    correct(meter_row(f2, ld.JUL), user=operator, reason=REASON, changes={"amount_acre_feet": D("-99.0000")})
    void(meter_row(f2, ld.AUG), user=operator, reason=REASON)
    assert_moved(pre, snapshot(client, d1), ["ledger", "csv"])

    day = day_ago(5)
    assert_reads(client, d1, day, pre)
    year_ = {"period": str(wy25().pk)}
    with reading_as_of(day) as reading:  # the scopes the design states
        in_year = dict(start=wy25().start_date, end=wy25().end_date)
        assert reading.changed_count(**in_year) == 3
        assert reading.changed_count(parcel_ids=[f1.pk, f2.pk], **in_year) == 3
        assert reading.changed_count(parcel_ids=[f1.pk], **in_year) == 1
        assert reading.changed_count(parcel_ids=[f2.pk], **in_year) == 2
    assert_line(page(client, u_ledger(), year_, as_of=day), day, since(3))
    assert_line(page(client, u_account(acct("D1-A")), year_, as_of=day), day, since(3))
    assert_line(page(client, u_parcel(f1), year_, as_of=day), day, since(1))
    assert_line(page(client, u_parcel(f2), year_, as_of=day), day, since(2))


def test_a_date_before_every_row_shows_zeros_and_says_no_records_had_been_entered(d1, operator):
    client = logged_in(operator)
    forget_history()
    age(20)
    day = day_ago(25)
    year_ = {"period": str(wy25().pk)}
    with reading_as_of(day) as reading:
        in_year = dict(start=wy25().start_date, end=wy25().end_date)
        assert reading.has_records(**in_year) is False
        assert reading.has_records(parcel_ids=[], **in_year) is False  # the account has no use areas yet

    account_html = page(client, u_account(acct("D1-A")), year_, as_of=day)
    assert_line(account_html, day, NO_RECORDS)
    leads = [text_of(i) for _, a, i in elements(account_html, lambda t, a: has_class(a, "budget-seg-value"))]
    assert leads and all(re.match(r"^-?0\.00", lead) for lead in leads), leads

    ledger_html = page(client, u_ledger(), year_, as_of=day)
    assert_line(ledger_html, day, NO_RECORDS)
    assert "No ledger entries found." in visible(ledger_html)
    assert ledger_rows(ledger_html) == [] or all("No ledger entries" in " ".join(c) for _, c in ledger_rows(ledger_html))
    assert "Since then" not in line_of(ledger_html)


# ================================================================ (e) the ledger as of a date
def test_the_ledger_as_of_a_date_lists_the_rows_current_then_unstruck_with_the_totals_of_those_rows(d1, operator):
    from accounting.views.ledger import _ledger_footer_totals

    client, pre, post = correct_f1_july(d1, operator)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(11)
    html = page(client, u_ledger(), year_, as_of=day)
    assert "record-void" not in html
    rows = ledger_rows(html)
    assert rows and not any(struck for struck, _ in rows)
    with reading_as_of(day):
        current = ParcelLedger.objects.current().filter(reporting_period=wy25())
        totals = _ledger_footer_totals(current)
        expected_count = current.count()
    assert len(rows) == expected_count
    text = ledger_table(html)
    assert f"All {expected_count} entr" in text
    assert f"+{(totals['credits'] or D('0')):,.2f}" in text
    assert f"{abs(totals['water'] or D('0')):,.2f}" in text
    # And today's totals are not these: the reading is not today's page.
    assert ledger_table(page(client, u_ledger(), year_)) != text


# ================================================================ (f) an invalid or a future date
@pytest.mark.parametrize("bad, sentence", [
    ("not-a-date", UNREADABLE), ("2026-13-45", UNREADABLE), ("11/03/2026", UNREADABLE),
    ((timezone.localdate() + dt.timedelta(days=3)).isoformat(), IN_FUTURE),
])
def test_an_invalid_or_future_date_prints_its_sentence_and_today_s_page_with_writing_controls(d1, operator, bad, sentence):
    client = logged_in(operator)
    year_ = {"period": str(wy25().pk)}
    surfaces = {
        "account": (u_account(acct("D1-A")), account_figs),
        "parcel": (u_parcel(d1["F1"]), parcel_figs),
        "ledger": (u_ledger(), ledger_table),
    }
    for name, (url, figs) in surfaces.items():
        today = page(client, url, year_)
        html = page(client, url, year_, as_of=bad)
        text = visible(html)
        assert sentence in text, f"{name}: the sentence is not on the page"
        assert not lines_of(html) and "as-of-line" not in html, f"{name}: a refused date gets no line"
        assert "as-of-reading" not in html, f"{name}: a refused date is not pinned"
        assert "Since then" not in text
        assert figs(html) == figs(today), f"{name}: the page must be today's"
        assert any(m in html for m in WRITING[name](d1)), f"{name}: writing controls stay on today's page"
    plain = get(client, u_export(), year_)
    refused = get(client, u_export(), year_, as_of=bad)
    assert refused.content == plain.content
    assert refused["Content-Disposition"] == 'attachment; filename="ledger_export.csv"'


# ================================================================ (g) a Viewer uses the box
def test_a_viewer_uses_the_box_on_all_four_surfaces(d1, operator, viewer):
    client, pre, post = correct_f1_july(d1, operator)
    reader = logged_in(viewer)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(11)
    for url, figs, key in (
        (u_account(acct("D1-A")), account_figs, "account_a"),
        (u_parcel(d1["F1"]), parcel_figs, "f1"),
        (u_ledger(), ledger_table, "ledger"),
    ):
        today = page(reader, url, year_)
        assert len(date_inputs(today)) == 1 and not has_flag(date_inputs(today)[0], "disabled")
        html = page(reader, url, year_, as_of=day)
        assert_line(html, day, since(1))
        assert figs(html) == pre[key]
    exported = get(reader, u_export(), year_, as_of=day)
    rows = csv_rows(exported)
    assert rows[0] == [f"As of the end of {words(day)}."]
    assert rows[1:] == pre["csv"]


# ================================================================ a reading writes no record
def _write_state(period):
    from core.changes import event_models

    counts = {label: model.objects.count() for label, model in event_models().items()}
    try:
        from pghistory.models import Context

        contexts = Context.objects.count()
    except Exception:  # pragma: no cover - a pghistory without the table
        contexts = None
    period.refresh_from_db()
    return counts, contexts, (period.fingerprint, period.fingerprint_parts, period.fingerprint_at)


def test_a_reading_writes_no_record_and_the_year_still_answers_no_changes_found(filed, administrator, d1):
    from accounting.fingerprints import check_fingerprint

    client = logged_in(administrator)
    before = _write_state(filed)
    assert check_fingerprint(filed).state == "matches"
    year_ = {"period": str(filed.pk)}
    for day in (day_ago(1), timezone.localdate()):
        # The district was built today, so a use area has no record yesterday: that page is a notice.
        urls = [u_account(acct("D1-A")), u_account(acct("D1-B")), u_ledger()]
        if day == timezone.localdate():
            urls.append(u_parcel(d1["F1"]))
        for url in urls:
            html = page(client, url, year_, as_of=day)
            assert lines_of(html), f"{url}: no reading was made"
            page(client, url, year_, as_of=day, hx=True)
        get(client, u_export(), year_, as_of=day)
        get(client, u_account(acct("D1-A")), year_, as_of=day, hx=True)
    assert _write_state(filed) == before, "a reading changed a record, an event, a context or the stored code"
    assert check_fingerprint(filed).state == "matches"
    assert _answer(_client(administrator), filed).startswith(NO_CHANGES[:len("No changes found since ")])


# ================================================================ writing controls
def _write_markers():
    return {
        "ledger": lambda d1_: ["Upload CSV", "Add ledger entry", "row-actions-btn", reverse("accounting:csv_upload")],
        "account": lambda d1_: [reverse("accounting:account_edit", args=[acct("D1-A").pk]), "assignment-search"],
        "parcel": lambda d1_: [
            reverse("accounting:ledger_create") + f"?parcel={d1_['F1'].pk}",
            reverse("parcels:edit_field", args=[d1_["F1"].pk]),
        ],
    }


class _Writing(dict):
    def __getitem__(self, name):
        return _write_markers()[name]


WRITING = _Writing()


@pytest.mark.parametrize("who", ["operator", "administrator"])
def test_every_writing_control_is_absent_on_a_reading_and_present_again_without_the_date(d1, request, who):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    user = request.getfixturevalue(who)
    client = logged_in(user)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(1)
    targets = {
        "ledger": (u_ledger(), True),
        "account": (u_account(acct("D1-A")), False),
        "parcel": (u_parcel(d1["F1"]), False),
    }
    for name, (url, _) in targets.items():
        markers = WRITING[name](d1)
        today = page(client, url, year_)
        missing = [m for m in markers if m not in today]
        assert not missing, f"{name}: today's page should carry {missing} for an operator"
        for hx in (False, True):
            html = page(client, url, year_, as_of=day, hx=hx)
            assert lines_of(html) or hx, f"{name}: the reading was not made"
            kept = [m for m in markers if m in html]
            assert not kept, f"{name} (hx={hx}): a past reading must not carry {kept}"
        assert any(m in page(client, url, year_) for m in markers)  # and present again
    # Download CSV stays, on the page and in the fragment the filters swap in.
    export_url = u_export()
    assert "Download CSV" in page(client, u_ledger(), year_, as_of=day)
    fragment = page(client, u_ledger(), year_, as_of=day, hx=True)
    assert "Download CSV" in fragment and export_url in fragment


def test_a_ledger_row_menu_and_the_page_actions_of_a_reading_are_what_a_viewer_sees(d1, operator, viewer):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    year_ = {"period": str(wy25().pk)}
    day = day_ago(1)
    as_operator = page(logged_in(operator), u_ledger(), year_, as_of=day)
    as_viewer = page(logged_in(viewer), u_ledger(), year_, as_of=day)
    assert ledger_table(as_operator) == ledger_table(as_viewer)
    assert "row-actions" not in as_operator
    assert "Actions" not in ledger_table(as_operator)


# ================================================================ the count
def test_the_count_is_one_for_one_correction_and_zero_after_a_rerun_that_moves_nothing(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(11)
    with reading_as_of(day) as reading:
        assert reading.changed_count(start=wy25().start_date, end=wy25().end_date) == 1
    assert_line(page(client, u_ledger(), year_, as_of=day), day, since(1))
    on_the_day = day_ago(10)
    assert_line(page(client, u_ledger(), year_, as_of=on_the_day), on_the_day, since(0))


def test_a_rerun_that_moves_no_figure_reads_zero_although_history_grew(d1, operator):
    client = logged_in(operator)
    settle()
    age(9)
    ld.run_months(["2025-07"])  # same inputs: every calculated row deleted and written again
    age(5)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(6)
    with reading_as_of(day) as reading:
        assert reading.changed_count(start=wy25().start_date, end=wy25().end_date) == 0
    for url in (u_ledger(), u_account(acct("D1-A")), u_account(acct("D1-B")), u_parcel(d1["F3"])):
        assert_line(page(client, url, year_, as_of=day), day, since(0))


def test_the_count_belongs_to_the_records_behind_the_page_not_the_whole_ledger(d1, operator):
    client = logged_in(operator)
    f1, f3, f4 = d1["F1"], d1["F3"], d1["F4"]
    row = ld.ledger(f3, dt.date(2025, 9, 15), "-5.0000", "manual_entry", "GW")  # a use area of account B
    age(10)
    correct(row, user=operator, reason=REASON, changes={"amount_acre_feet": D("-8.0000")})  # today
    day = day_ago(5)
    in_year = dict(start=wy25().start_date, end=wy25().end_date)
    with reading_as_of(day) as reading:
        assert reading.changed_count(parcel_ids=[f3.pk], **in_year) == 1
        assert reading.changed_count(parcel_ids=[f1.pk], **in_year) == 0
        assert reading.changed_count(**in_year) == 1
        assert reading.changed_count(parcel_ids=[f3.pk], start=dt.date(2025, 10, 1)) == 0
    year_ = {"period": str(wy25().pk)}
    water_type = ld.wt("GW").pk
    zone = d1["gsa"].pk

    def line(url, params=None, **kw):
        return line_of(page(client, url, {**year_, **(params or {})}, as_of=day, **kw))

    def expect(text, n):
        """``n`` records changed, or None when nothing was on record in the page's scope that day."""
        tail = NO_RECORDS if n is None else since(n)
        assert text.startswith(f"As of the end of {words(day)}. {tail}"), text

    expect(line(u_account(acct("D1-A"))), 0)  # account A holds F1 and F2
    expect(line(u_account(acct("D1-B"))), 1)  # account B holds F3
    expect(line(u_parcel(f1)), 0)
    expect(line(u_parcel(f4)), 0)
    expect(line(u_parcel(f3)), 1)
    expect(line(u_ledger()), 1)  # the whole district's ledger for the year
    expect(line(u_ledger(), {"q": "F1"}), 0)  # a search narrows the use areas counted
    expect(line(u_ledger(), {"q": "F3"}), 1)
    expect(line(u_ledger(), {"zone": str(zone)}), 1)  # a zone filter narrows the same way
    expect(line(u_ledger(), {"source_type": "calculated"}), 1)  # the source filter does not narrow the count
    expect(line(u_ledger(), {"water_type": str(water_type), "q": "F3"}), 1)  # nor the water type
    expect(line(u_ledger(), {"start_date": "2025-10-01"}), None)  # typed dates do: nothing was on record from October
    expect(line(u_ledger(), {"start_date": "2025-09-01", "end_date": "2025-09-30"}), 1)
    expect(line(u_account(acct("D1-B")), {"period": str(wy26().pk)}), None)  # another water year: nothing on record in it
    expect(line(u_account(acct("D1-B")), {"period": ""}), 1)  # All Time: no dates


def test_the_account_counts_the_year_shown_and_all_time_counts_without_dates(d1, operator):
    client = logged_in(operator)
    ld.ledger(d1["F1"], dt.date(2025, 11, 1), "-2.0000", "manual_entry", "GW")  # WY 2025-2026, already on record
    age(10)
    ld.ledger(d1["F1"], dt.date(2025, 11, 15), "-3.0000", "manual_entry", "GW")  # WY 2025-2026, today
    day = day_ago(5)
    a = u_account(acct("D1-A"))
    for params, n in (({"period": str(wy25().pk)}, 0), ({"period": str(wy26().pk)}, 1), ({"period": ""}, 1)):
        assert_line(page(client, a, params, as_of=day), day, since(n))
    assert_line(page(client, u_parcel(d1["F1"]), {"period": str(wy26().pk)}, as_of=day), day, since(1))
    assert_line(page(client, u_parcel(d1["F1"]), {"period": str(wy25().pk)}, as_of=day), day, since(0))


def test_the_words_are_singular_for_one_and_plural_for_several(d1, operator):
    client = logged_in(operator)
    forget_history()
    age(20)
    ld.ledger(d1["F1"], dt.date(2025, 9, 15), "-5.0000", "manual_entry", "GW")
    day = day_ago(5)
    year_ = {"period": str(wy25().pk)}
    one = line_of(page(client, u_ledger(), year_, as_of=day))
    assert "Since then 1 record changed." in one
    correct(meter_row(d1["F2"], ld.JUL), user=operator, reason=REASON, changes={"amount_acre_feet": D("-99.0000")})
    void(meter_row(d1["F2"], ld.AUG), user=operator, reason=REASON)
    many = line_of(page(client, u_ledger(), year_, as_of=day))
    assert "Since then 3 records changed." in many
    none = line_of(page(client, u_ledger(), year_, as_of=timezone.localdate()))
    assert "Since then no records changed." in none


# ================================================================ Show today, the box, the controls
LEDGER_PARAMS = lambda: {  # noqa: E731
    "period": str(wy25().pk), "q": "F1", "source_type": "meter_reading", "water_type": str(ld.wt("GW").pk),
    "sort": "amount", "dir": "asc", "page_size": "25",
}


def test_show_today_and_the_box_carry_the_other_parameters_on_the_ledger(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    params = LEDGER_PARAMS()
    day = day_ago(2)
    html = page(client, u_ledger(), params, as_of=day)
    href = urlsplit(show_today_href(html))
    assert href.path == u_ledger()
    assert {k: v[0] for k, v in parse_qs(href.query, keep_blank_values=True).items()} == params
    sent = assert_box_leads_to(html, u_ledger(), params, day)
    landed = page(client, u_ledger(), sent)  # what the browser does next
    assert_line(landed, day, since(0))
    assert box_form(landed).value == day.isoformat()


@pytest.mark.parametrize("period_key", ["year", "all"])
def test_show_today_and_the_box_carry_the_water_year_on_the_account_and_use_area_pages(d1, operator, period_key):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    period = str(wy25().pk) if period_key == "year" else ""
    params = {"period": period}
    day = day_ago(2)
    for url in (u_account(acct("D1-A")),) + ((u_parcel(d1["F1"]),) if period_key == "year" else ()):
        html = page(client, url, params, as_of=day)
        href = urlsplit(show_today_href(html))
        assert href.path == url
        assert {k: v[0] for k, v in parse_qs(href.query, keep_blank_values=True).items()} == params
        sent = assert_box_leads_to(html, url, params, day)
        assert_line(page(client, url, sent), day, since(0))


def test_the_box_is_a_form_empty_by_default_in_the_head_of_the_card_that_holds_the_figures(d1, operator):
    client = logged_in(operator)
    year_ = {"period": str(wy25().pk)}
    for url, head_class in (
        (u_account(acct("D1-A")), "page-grid-account-head"),
        (u_parcel(d1["F1"]), "statement-head"),
        (u_ledger(), "ledger-card-head"),
    ):
        html = page(client, url, year_)
        assert len(date_inputs(html)) == 1, url
        assert box_form(html).value == ""
        heads = elements(html, lambda t, a: has_class(a, head_class))
        assert heads and any(date_inputs(inner) for _, _, inner in heads), f"{url}: the box is not in the {head_class}"
        assert "As of" in text_of(next(i for _, _, i in heads if date_inputs(i)))
        assert not lines_of(html) and "as-of-reading" not in html


def test_a_pane_in_a_workspace_shows_the_box_and_it_leads_to_the_standalone_page(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(2)
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"])):
        pane = page(client, url, year_, hx=True)  # what a row click swaps into the workspace
        assert len(date_inputs(pane)) == 1
        sent = assert_box_leads_to(pane, url, year_, day)
        standalone = page(client, url, sent)
        assert_line(standalone, day, since(0))
    # With no water year chosen the pane still carries the year it shows.
    pane = page(client, u_account(acct("D1-A")), hx=True)
    assert "period" in box_form(pane).fields and box_form(pane).fields["period"] != "x"


def test_the_water_year_filters_paging_and_download_carry_the_date_on_a_reading_and_not_without_one(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    params = LEDGER_PARAMS()
    day = day_ago(2)
    iso = day.isoformat()

    # -- the account's water year select and the use area's period control
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"])):
        today = page(client, url, {"period": str(wy25().pk)})
        reading = page(client, url, {"period": str(wy25().pk)}, as_of=day)
        selects = lambda h: [t for t in start_tags(h, "<select") if attr(t, "name") == "period"]  # noqa: E731
        assert selects(reading) and all("as_of" in t for t in selects(reading)), f"{url}: the water year select"
        assert not any("as_of" in t for t in selects(today)), f"{url}: today's select must be unchanged"

    # -- the ledger: filter bar, sort, paging, Download CSV
    today = page(client, u_ledger(), params)
    reading = page(client, u_ledger(), params, as_of=day)

    def filter_bar_holds_the_date(html):
        bar = elements(html, lambda t, a: attr(a, "id") == "ledger-filters")
        return bool(bar) and any(
            attr(m.group(0), "name") == "as_of" and (attr(m.group(0), "value") or "") == iso
            for m in re.finditer(r"<input\b[^>]*>", bar[0][2], re.I)
        )

    def carries(html, tag):
        return "as_of" in tag or ("#ledger-filters" in tag and filter_bar_holds_the_date(html))

    ledger_tags = start_tags(reading, f'hx-get="{u_ledger()}"')
    assert len(ledger_tags) >= 8, "the filter bar, the sort headers and the paging controls"
    assert all(carries(reading, t) for t in ledger_tags), [t for t in ledger_tags if not carries(reading, t)][:2]
    assert not filter_bar_holds_the_date(today)
    assert not any("as_of" in t for t in start_tags(today, f'hx-get="{u_ledger()}"'))

    download = [t for t in start_tags(reading, "ledger-download")][0]
    assert parse_qs(urlsplit(attr(download, "href")).query).get("as_of") == [iso]
    today_download = [t for t in start_tags(today, "ledger-download")][0]
    assert "as_of" not in attr(today_download, "href")

    # -- the fragment a filter swaps in carries the same, and holds the box with the date
    fragment = page(client, u_ledger(), params, as_of=day, hx=True)
    frag_download = [t for t in start_tags(fragment, "ledger-download")][0]
    assert parse_qs(urlsplit(attr(frag_download, "href")).query).get("as_of") == [iso]
    assert box_form(fragment).value == iso
    sorts = start_tags(fragment, f'hx-get="{u_ledger()}"')
    assert sorts and all("as_of" in t or "#ledger-filters" in t for t in sorts)
    assert "as_of" not in attr([t for t in start_tags(page(client, u_ledger(), params, hx=True), "ledger-download")][0], "href")


# ================================================================ HTMX partials
def test_an_htmx_partial_on_a_reading_returns_past_figures(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    year_ = {"period": str(wy25().pk)}
    day = day_ago(11)

    balances = page(client, u_account(acct("D1-A")), year_, as_of=day, hx=True)  # the water year select's swap
    assert account_figs(balances) == pre["account_a"] != account_figs(
        page(client, u_account(acct("D1-A")), year_, hx=True))

    pane = page(client, u_parcel(d1["F1"]), year_, as_of=day, hx=True)  # the period control's swap
    assert parcel_figs(pane) == pre["f1"]

    results = page(client, u_ledger(), year_, as_of=day, hx=True)  # a filter's swap
    assert ledger_table(results) == pre["ledger"]
    assert "record-void" not in results


def swapped_line(html):
    """The line a fragment carries out of band, as its whole tag, or fail."""
    found = re.findall(r'<p id="as-of-line"[^>]*>.*?</p>', html, re.S)
    assert len(found) == 1, "a fragment on a reading must carry the line for its own scope"
    assert 'hx-swap-oob="true"' in found[0]
    return found[0]


def assert_counts(client, url, params, day, words_):
    assert words_ in " ".join(visible(page(client, url, params, as_of=day)).split())


def test_an_allocation_moved_since_is_counted_on_the_account_page(d1, operator):
    from accounting.models import AllocationPlan

    client = logged_in(operator)
    settle()
    age(5)
    plan = AllocationPlan.objects.filter(reporting_period=wy25()).first()
    AllocationPlan.objects.filter(pk=plan.pk).update(allocation_acre_feet=plan.allocation_acre_feet + 1)
    url, year_ = u_account(acct("D1-A")), {"period": str(wy25().pk)}
    assert_counts(client, url, year_, day_ago(1), "Since then 1 record changed.")
    # The next year's page has no rows of its own, and that year's allocation did not move.
    assert "1 record changed." not in visible(page(client, url, {"period": str(wy26().pk)}, as_of=day_ago(1)))


def test_a_use_area_moved_between_accounts_since_is_counted_on_the_account_page(d1, operator):
    from accounting.models import WaterAccountParcel

    client = logged_in(operator)
    settle()
    age(5)
    link = WaterAccountParcel.objects.filter(water_account=acct("D1-A")).first()
    WaterAccountParcel.objects.filter(pk=link.pk).update(removed_date=dt.date(2025, 10, 1))
    assert_counts(client, u_account(acct("D1-A")), {"period": str(wy25().pk)}, day_ago(1), "Since then 1 record changed.")


def test_a_credit_moved_since_is_counted_on_the_account_page(d1, operator):
    from decimal import Decimal

    from accounting.models import AccountCredit
    from accounting.services import account_water_year

    client = logged_in(operator)
    settle()
    age(5)
    AccountCredit.objects.create(
        water_account=acct("D1-A"), water_type=ld.wt("GW"), water_year=account_water_year(wy25()),
        origin="recharge", amount_af=Decimal("5.0000"), source_key="test", description="test credit",
    )
    assert_counts(client, u_account(acct("D1-A")), {"period": str(wy25().pk)}, day_ago(1), "Since then 1 record changed.")
    assert_counts(client, u_account(acct("D1-B")), {"period": str(wy25().pk)}, day_ago(1), "no records changed.")


def test_a_use_area_edit_since_is_counted_on_its_own_page_only(d1, operator):
    from decimal import Decimal

    from parcels.models import Parcel

    client = logged_in(operator)
    settle()
    age(5)
    Parcel.objects.filter(pk=d1["F1"].pk).update(area_acres=d1["F1"].area_acres + Decimal("1"))
    year_ = {"period": str(wy25().pk)}
    assert_counts(client, u_parcel(d1["F1"]), year_, day_ago(1), "Since then 1 record changed.")
    assert_counts(client, u_parcel(d1["F3"]), year_, day_ago(1), "no records changed.")


def test_a_rerun_that_moves_nothing_still_counts_zero_on_the_account_page(d1, operator):
    client = logged_in(operator)
    settle()
    age(5)
    settle()
    assert_counts(client, u_account(acct("D1-A")), {"period": str(wy25().pk)}, day_ago(1), "no records changed.")


def oob_line_of(html):
    return re.sub(r"<[^>]+>", " ", swapped_line(html))


def test_changing_the_year_on_a_reading_changes_the_line_with_the_figures(d1, operator):
    """The line counts the records behind what is shown, so a swap of the figures swaps it too."""
    client, pre, post = correct_f1_july(d1, operator)
    day = day_ago(11)
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"]), u_ledger()):
        assert "1 record changed." in oob_line_of(page(client, url, {"period": str(wy25().pk)}, as_of=day, hx=True))
        assert "no records" in oob_line_of(page(client, url, {"period": str(wy26().pk)}, as_of=day, hx=True)) or (
            "No records had been entered" in oob_line_of(page(client, url, {"period": str(wy26().pk)}, as_of=day, hx=True))
        )


def test_a_filter_narrowing_the_ledger_on_a_reading_changes_the_line(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    day = day_ago(11)
    year_ = {"period": str(wy25().pk)}
    assert "1 record changed." in oob_line_of(page(client, u_ledger(), {**year_, "q": "F1"}, as_of=day, hx=True))
    assert "no records changed." in oob_line_of(page(client, u_ledger(), {**year_, "q": "F3"}, as_of=day, hx=True))


def test_show_today_in_a_swapped_line_keeps_the_year_it_was_swapped_for(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    html = page(client, u_account(acct("D1-A")), {"period": str(wy26().pk)}, as_of=day_ago(11), hx=True)
    assert f"period={wy26().pk}" in swapped_line(html)
    assert "as_of" not in swapped_line(html)


def test_a_fragment_today_carries_no_line(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    html = page(client, u_account(acct("D1-A")), {"period": str(wy25().pk)}, hx=True)
    assert 'id="as-of-line"' not in html


# ================================================================ the file
def test_the_csv_on_a_reading_has_the_date_line_first_and_the_dated_filename(d1, operator):
    client, pre, post = correct_f1_july(d1, operator)
    day = day_ago(11)
    response = get(client, u_export(), {"period": str(wy25().pk)}, as_of=day)
    assert response["Content-Disposition"] == f'attachment; filename="ledger_export_as_of_{day.isoformat()}.csv"'
    rows = csv_rows(response)
    assert rows[0] == [f"As of the end of {words(day)}."]
    assert rows[1] == CSV_COLUMNS
    assert len(rows[0]) == 1


def test_the_csv_on_a_reading_of_a_demonstration_site_has_the_demonstration_line_then_the_date_line(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    from core.models import SiteConfig

    SiteConfig.objects.update(demonstration_mode=True)
    client = logged_in(operator)
    day = day_ago(1)
    rows = csv_rows(get(client, u_export(), as_of=day))
    assert rows[0] == [DEMONSTRATION_LINE]
    assert rows[1] == [f"As of the end of {words(day)}."]
    assert rows[2] == CSV_COLUMNS
    # The page: the demonstration notice first, then the line, before any other content.
    html = page(client, u_ledger(), as_of=day)
    before_line = visible(html).split("As of the end of", 1)[0]
    assert "demo" in before_line.lower()


def test_todays_export_is_unchanged_in_shape(d1, operator):
    client = logged_in(operator)
    year_ = {"period": str(wy25().pk)}
    plain = get(client, u_export(), year_)
    assert plain["Content-Disposition"] == 'attachment; filename="ledger_export.csv"'
    assert csv_rows(plain)[0] == CSV_COLUMNS
    assert plain.content == get(client, u_export(), {**year_, "as_of": ""}).content
    assert not any("As of the end of" in cell for row in csv_rows(plain) for cell in row)


def _import(text):
    from accounting.ledger_import import import_ledger_rows

    return import_ledger_rows(io.StringIO(text), dry_run=True)


PAST_FILE_REFUSED = "This file holds the ledger as of a past date, so its rows may have been corrected or voided since. Download today's file to import."


def test_a_file_saved_on_a_reading_is_refused_by_the_import(d1, operator):
    """Its rows are compared with today's, so a row since corrected would come back as a new entry."""
    age(5)
    client = logged_in(operator)
    day = day_ago(1)
    params = {"period": str(wy25().pk), "source_type": "meter_reading"}
    reading = get(client, u_export(), params, as_of=day).content.decode("utf-8")
    assert reading.splitlines()[0].strip('"') == f"As of the end of {words(day)}."
    result = _import(reading)
    assert result["created_count"] == 0
    assert result["errors"] == [{"line": 1, "messages": [PAST_FILE_REFUSED]}]
    today = _import(get(client, u_export(), params).content.decode("utf-8"))
    assert today["error_count"] == 0 and today["skipped_duplicate"] > 0


def test_the_date_line_is_refused_wherever_a_download_puts_it(d1):
    body = ",".join(CSV_COLUMNS) + "\r\nNO-SUCH-PARCEL,2025-01-01,-1,manual_entry,,,,\r\n"
    line = "As of the end of Nov 3, 2026."
    for head in (f"{line}\r\n", f"{DEMONSTRATION_LINE}\r\n{line}\r\n", f'"{line}"\r\n'):
        assert _import(head + body)["errors"] == [{"line": 1, "messages": [PAST_FILE_REFUSED]}], head


@pytest.mark.parametrize("first", [
    "Some other sentence.",
    "As of the end of Nov 3, 2026. Extra words.",
    "As of the end of Nov 3, 2026",
    "As of the end of November 3, 2026.",
    "As of Nov 3, 2026.",
    "as of the end of Nov 3, 2026.",
])
def test_a_file_whose_first_line_is_any_other_sentence_is_still_refused(d1, first):
    body = ",".join(CSV_COLUMNS) + "\r\n"
    result = _import(f"{first}\r\n" + body)
    assert any("Missing required columns" in m for e in result["errors"] for m in e["messages"])


# ================================================================ links on a reading
def test_no_link_on_a_reading_answers_404_for_a_row_that_was_since_replaced(d1, operator):
    client = logged_in(operator)
    settle()
    age(8)
    double_july_et(d1["F3"])
    ld.run_months(["2025-07"])  # the calculated rows (and the runs behind them) are written again
    correct(meter_row(d1["F1"], ld.JUL), user=operator, reason=REASON, changes={"amount_acre_feet": D("-20.0000")})
    age(3)
    day = day_ago(4)
    year_ = {"period": str(wy25().pk)}
    pages = [
        page(client, u_ledger(), year_, as_of=day),
        page(client, u_parcel(d1["F1"]), year_, as_of=day),
        page(client, u_parcel(d1["F3"]), year_, as_of=day),
        page(client, u_account(acct("D1-A")), year_, as_of=day),
        page(client, u_account(acct("D1-B")), year_, as_of=day),
    ]
    checked = set()
    for html in pages:
        assert lines_of(html), "the reading was not made"
        for href in hrefs_in_main(html):
            if href in checked:
                continue
            checked.add(href)
            status = client.get(href).status_code
            assert status < 400 or status in (401, 403), f"{href} answers {status} from a reading"
    assert any(h.startswith("/parcels/") for h in checked) and any("ledger" in h for h in checked)


# ================================================================ an optional module switched off
def test_with_an_optional_module_switched_off_the_pages_still_read(d1, operator, settings):
    from core.modules import ALL_MODULE_NAMES

    settings.OPENH2O_MODULES = [m for m in ALL_MODULE_NAMES if m not in ("surface", "recharge")]
    client = logged_in(operator)
    day = day_ago(0)
    year_ = {"period": str(wy25().pk)}
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"]), u_ledger()):
        assert_line(page(client, url, year_, as_of=day), day, since(0))
    assert csv_rows(get(client, u_export(), year_, as_of=day))[0] == [f"As of the end of {words(day)}."]


# ================================================================ nowhere else, and the words
def test_the_box_and_the_line_are_absent_from_every_other_page(d1, operator):
    client = logged_in(operator)
    day = day_ago(1).isoformat()
    others = [
        reverse("accounting:accounts_list"), reverse("parcels:list"), reverse("accounting:periods_list"),
        reverse("accounting:dashboard"), reverse("accounting:ledger_create"),
    ]
    for url in others:
        for params in ({}, {"as_of": day}):
            html = page(client, url, params)
            assert "as-of-line" not in html and "as-of-reading" not in html, url
            assert not date_inputs(html), url
            assert 'name="as_of"' not in html, url


def test_the_line_s_markup_carries_the_pinned_class_and_leads_the_page_content(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    day = day_ago(1)
    year_ = {"period": str(wy25().pk)}
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"]), u_ledger()):
        html = page(client, url, year_, as_of=day)
        line = elements(html, lambda t, a: has_class(a, "as-of-line"))
        assert len(line) == 1
        assert any("as-of-line" in inner for _, _, inner in elements(html, lambda t, a: has_class(a, "as-of-reading"))), \
            "the line sits inside the element that carries as-of-reading"
        before_line = visible(html).split("As of the end of", 1)[0]
        assert before_line.strip() == "", f"{url}: {before_line!r} comes before the line"
        assert 'class="as-of-line"' in html or "as-of-line " in html or ' as-of-line' in html


def test_the_visible_text_of_a_reading_never_says_as_it_stood_or_a_forbidden_word(d1, operator):
    age(5)  # the district was set up five days ago: a reading two days back sees it
    client = logged_in(operator)
    day = day_ago(1)
    year_ = {"period": str(wy25().pk)}
    shown = []
    for url in (u_account(acct("D1-A")), u_parcel(d1["F1"]), u_ledger()):
        for params in ({**year_, "as_of": day.isoformat()}, {**year_, "as_of": "garbage"}, {**year_, "as_of": "2999-01-01"}):
            html = page(client, url, params)
            shown.append(visible(html))
            assert "as it stood" not in visible(html).lower() and "as it stood" not in html.lower().replace("<!--", "")
            for text in lines_of(html):
                shown.append(text)
        form_text = text_of(next(i for _, _, i in elements(page(client, url, year_, as_of=day),
                                                            lambda t, a: t == "form") if date_inputs(i)))
        shown.append(form_text)
    box_and_lines = [t for t in shown if len(t) < 400]
    for text in box_and_lines:
        lowered = text.lower()
        assert not [w for w in FORBIDDEN if w in lowered], text
    export = get(client, u_export(), {}, as_of=day).content.decode().lower()
    assert "as it stood" not in export


# ================================================================ a use area that was not there yet
def test_a_use_area_asked_for_before_it_existed_shows_today_under_a_sentence_and_one_that_never_did_is_404(d1, operator):
    client = logged_in(operator)
    year_ = {"period": str(wy25().pk)}
    url = u_parcel(d1["F1"])
    day = day_ago(1)  # the district was built today
    today = page(client, url, year_)
    html = page(client, url, year_, as_of=day)
    assert f"This use area was not on record on {words(day)}. This page shows today." in visible(html)
    assert "as-of-line" not in html and "as-of-reading" not in html  # not pinned, no reading
    assert "Since then" not in visible(html)
    assert parcel_figs(html) == parcel_figs(today)
    assert any(m in html for m in WRITING["parcel"](d1)), "writing controls follow today's page"
    # The box is still there, and the pane (HTMX) is today's too.
    assert len(date_inputs(html)) == 1
    assert parcel_figs(page(client, url, year_, as_of=day, hx=True)) == parcel_figs(today)
    # An id that never existed is still a 404, with or without a date.
    get(client, reverse("parcels:detail", args=[9999999]), as_of=day, status=404)
    get(client, reverse("parcels:detail", args=[9999999]), status=404)
    # And on a day it was there, the reading is made.
    assert lines_of(page(client, url, year_, as_of=timezone.localdate()))
