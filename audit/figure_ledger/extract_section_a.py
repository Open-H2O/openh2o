# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read section A's 31 figures out of the SERVED HTML.

The ledger's `rendered` column has to be what a person sees, so it is read back
out of the saved pages rather than re-asked of the application. Standard library
only -- `requirements.lock` carries no HTML parsing dependency and this adds none.
Same shape and the same safety rule as `extract_dashboard.py`, which did this for
the accounting dashboard in 135-01.

**Located by position within labelled structures, not by instrumentation.** No
template gains a `data-figure` attribute: marking up the page would change the
very output under audit. So the panel figures are found by their own class names
and their visible labels, and the table figures by the account number, parcel
number or allocation name a reader can see, then by column order -- which is
checked against the table's own header cells first, so a column inserted upstream
fails loudly instead of silently shifting every value by one.

**A figure that does not render is recorded as NOT RENDERED, never as zero.** The
run page's banking block and the preview's no-steps fallback are both behind
conditions this demonstration data cannot satisfy, and writing 0.00 for them would
turn "the screen never showed this" into "the screen showed nothing there", which
is a different and false claim.

    python3 audit/figure_ledger/extract_section_a.py \
        --rendered audit/figure_ledger/rendered \
        --out audit/figure_ledger/results/rendered_accounting_detail.csv
"""

import argparse
import csv
import os
import re
import sys

#: Marker for a site whose surrounding block never rendered on the pinned screen.
NOT_RENDERED = "NOT RENDERED"

PINNED_PARCEL_ROW = "MER-APN-021"
PINNED_ALLOC_LIST = "Halvern Irrigation-Urban GSA — Groundwater WY 2025-2026"
PINNED_ALLOC_PERIOD = "Halvern Valley GSA — Groundwater WY 2025-2026"

#: The per-parcel table's columns, in screen order. Asserted against the table's
#: own header cells before a single value is read.
PARCEL_COLUMNS = [
    ("FIG-accounting-015", "Consumptive Use"),
    ("FIG-accounting-016", "Surface"),
    ("FIG-accounting-017", "Groundwater"),
    ("FIG-accounting-018", "Precip"),
    ("FIG-accounting-019", "Supplies"),
    ("FIG-accounting-020", "Net"),
]
WATERFALL_HEADERS = ["#", "Step", "Detail", "In (AF)", "Out (AF)"]
LEDGER_HEADERS = ["Date", "Parcel", "Amount (AF)", "Source", "Water Type", "Description"]
ALLOC_HEADERS = ["Name", "Zone", "Water Type", "Period", "Allocation (AF)"]
PERIOD_ALLOC_HEADERS = ["Name", "Zone", "Water Type", "Allocation (AF)"]

_TAG = re.compile(r"<[^>]+>")
_ENTITIES = {
    "&mdash;": "—",
    "&minus;": "−",
    "&middot;": "·",
    "&equals;": "=",
    "&larr;": "<-",
    "&rarr;": "->",
    "&amp;": "&",
    "&quot;": '"',
    "&#9650;": "",
    "&#9660;": "",
    "&ldquo;": '"',
    "&rdquo;": '"',
}


def _text(fragment):
    """Visible text of an HTML fragment, whitespace collapsed."""
    stripped = _TAG.sub(" ", fragment)
    for entity, char in _ENTITIES.items():
        stripped = stripped.replace(entity, char)
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return " ".join(stripped.split())


def _number(fragment):
    """The figure a reader sees, thousands separator removed, as text.

    A dash comes back as a dash: it is a deliberate non-number and turning it
    into 0.00 here would erase exactly the distinction the template makes.
    """
    text = _text(fragment)
    if text in {"—", "-", "−"}:
        return "—"
    match = re.search(r"[+\-−]?[\d,]+\.\d+", text)
    if not match:
        return text
    return match.group(0).replace(",", "").replace("−", "-").lstrip("+")


def _read(rendered_dir, slug):
    path = os.path.join(rendered_dir, f"{slug}.html")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _rows(table_html):
    """(header_texts, [row_cell_texts]) for one <table> fragment."""
    head = re.search(r"<thead.*?</thead>", table_html, re.S)
    headers = (
        [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", head.group(0), re.S)]
        if head
        else []
    )
    body = re.search(r"<tbody.*?</tbody>", table_html, re.S)
    rows = []
    if body:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(0), re.S):
            rows.append(re.findall(r"<td[^>]*>(.*?)</td>", row, re.S))
    return headers, rows


def _table_after(html, marker):
    """The first <table> ... </table> appearing after `marker` in the page."""
    start = html.find(marker)
    if start < 0:
        raise AssertionError(f"marker not found on the page: {marker!r}")
    table = re.search(r"<table.*?</table>", html[start:], re.S)
    if table is None:
        raise AssertionError(f"no table follows {marker!r}")
    return table.group(0)


def _assert_headers(actual, expected, where):
    if actual != expected:
        raise AssertionError(
            f"{where}: the table's header cells are {actual!r}, not {expected!r}. "
            "A column moved, so every value below it would have shifted. "
            "Refusing to read rather than reporting the wrong figure."
        )


def _budget_segments(html):
    """{label: value} for the balance panel's three segments."""
    panel = re.search(r'<div class="budget-panel-row">.*?</div>\s*</div>\s*</div>', html, re.S)
    if panel is None:
        raise AssertionError("no budget-panel-row on the account page")
    out = {}
    for seg in re.findall(r'<div class="budget-seg">(.*?)(?=<div class="budget-(?:op|seg)"|\Z)',
                          panel.group(0) + "<div class=\"budget-op\"", re.S):
        label = re.search(r'budget-seg-label[^>]*>(.*?)(?:<span|</div>)', seg, re.S)
        value = re.search(r'budget-seg-value[^>]*>(.*?)</div>', seg, re.S)
        if label and value:
            out[_text(label.group(1))] = _number(value.group(1))
    return out


def account_pane(html, slug):
    """FIG-accounting-009..020: the balance panel and one per-parcel row."""
    out = []
    segs = _budget_segments(html)
    for fig, label in [
        ("FIG-accounting-009", "Supplies"),
        ("FIG-accounting-010", "Consumptive use"),
        ("FIG-accounting-011", "Balance"),
    ]:
        if label not in segs:
            raise AssertionError(
                f"the balance panel no longer carries a segment labelled {label!r}; "
                f"it carries {sorted(segs)!r}"
            )
        out.append((fig, slug, label, segs[label]))

    foot = re.search(r'<div class="budget-panel-foot">(.*?)</div>', html, re.S)
    if foot is None:
        raise AssertionError("no budget-panel-foot on the account page")
    foot_pairs = dict(
        (_text(m.group(1)).strip(), _number(m.group(2)))
        for m in re.finditer(r"<span>([^<]*?)\s*<b>(.*?)</b></span>", foot.group(1), re.S)
    )
    for fig, label in [
        ("FIG-accounting-012", "Surface"),
        ("FIG-accounting-013", "Groundwater"),
        ("FIG-accounting-014", "Rain"),
    ]:
        if label not in foot_pairs:
            raise AssertionError(
                f"the panel foot no longer carries {label!r}; it carries {sorted(foot_pairs)!r}"
            )
        out.append((fig, slug, label, foot_pairs[label]))

    table = _table_after(html, "Per-Parcel breakdown")
    headers, rows = _rows(table)
    _assert_headers(
        headers,
        ["Parcel"] + [label for _, label in PARCEL_COLUMNS],
        "per-parcel breakdown",
    )
    match = next((r for r in rows if PINNED_PARCEL_ROW in _text(r[0])), None)
    if match is None:
        raise AssertionError(f"the pinned parcel row {PINNED_PARCEL_ROW} is not on this page")
    for offset, (fig, label) in enumerate(PARCEL_COLUMNS, start=1):
        out.append((fig, slug, f"{PINNED_PARCEL_ROW} {label}", _number(match[offset])))
    return out


def _waterfall(html, slug, ids, where):
    """The first waterfall row's In and Out, header-checked. Shared by two pages."""
    table = _table_after(html, where)
    headers, rows = _rows(table)
    _assert_headers(headers, WATERFALL_HEADERS, where)
    if not rows:
        raise AssertionError(f"{where}: the waterfall table rendered no rows")
    first = rows[0]
    return [
        (ids[0], slug, "step 1 In (AF)", _number(first[3])),
        (ids[1], slug, "step 1 Out (AF)", _number(first[4])),
    ]


def calculation_run(html, slug):
    """FIG-accounting-001..008: the run audit page."""
    out = []
    acres = re.search(r"<div class=\"text-tertiary text-sm\">\s*(.*?)acres", html, re.S)
    if acres is None:
        raise AssertionError("the run page no longer states the parcel's acreage")
    out.append(("FIG-accounting-001", slug, "parcel acres", _number(acres.group(1))))

    header = re.search(
        r"<div class=\"td-num-bold\"[^>]*>\s*(.*?)\s*AF\s*<div class=\"field-label\"[^>]*>"
        r"Billable groundwater",
        html,
        re.S,
    )
    if header is None:
        raise AssertionError("the run page no longer states a header Billable groundwater figure")
    out.append(("FIG-accounting-002", slug, "header Billable groundwater", _number(header.group(1))))

    out.extend(
        _waterfall(html, slug, ("FIG-accounting-003", "FIG-accounting-004"), "Calculation steps")
    )

    # The banking block is behind `has_banking`. Absent means the screen showed
    # nothing there, which is not the same as showing a zero.
    banking = "Banked water" in html
    out.append((
        "FIG-accounting-005", slug, "Deposited this month",
        _number(re.search(r"Deposited this month.*?>([\d.,]+) AF", html, re.S).group(1))
        if banking else NOT_RENDERED,
    ))
    out.append((
        "FIG-accounting-006", slug, "Drawn down this month",
        _number(re.search(r"Drawn down this month.*?>([\d.,]+) AF", html, re.S).group(1))
        if banking else NOT_RENDERED,
    ))
    draws = "Credit banked in" in html
    out.append((
        "FIG-accounting-007", slug, "one credit draw Drawn (AF)",
        _number(_rows(_table_after(html, "Credit banked in"))[1][0][1]) if draws else NOT_RENDERED,
    ))

    result = re.search(r'<div class="result-card-value">(.*?)</div>', html, re.S)
    if result is None:
        raise AssertionError("the run page no longer carries a result card")
    out.append(("FIG-accounting-008", slug, "result card final", _number(result.group(1))))
    return out


def methodology_preview(html, slug):
    """FIG-accounting-050..053: the live preview fragment."""
    out = []
    header = re.search(
        r"<div class=\"td-num-bold\"[^>]*>\s*(.*?)\s*AF\s*<div class=\"field-label\"[^>]*>"
        r"Billable groundwater",
        html,
        re.S,
    )
    if header is None:
        raise AssertionError("the preview no longer states a Billable groundwater figure")
    out.append(("FIG-accounting-050", slug, "preview Billable groundwater", _number(header.group(1))))
    out.extend(
        _waterfall(html, slug, ("FIG-accounting-051", "FIG-accounting-052"), "Uses the currently-saved")
    )
    # The fourth site lives in the {% else %} arm, reached only when the saved
    # methodology yields no steps at all.
    fallback = re.search(r"No enabled steps produced a breakdown.*?final (.*?) AF", html, re.S)
    out.append((
        "FIG-accounting-053", slug, "no-steps fallback final",
        _number(fallback.group(1)) if fallback else NOT_RENDERED,
    ))
    return out


def use_ledger(html, slug):
    """FIG-accounting-046..049: one entry row and the three footer totals."""
    table = _table_after(html, 'id="ledger-results"' if 'id="ledger-results"' in html else "<tbody>")
    headers, rows = _rows(table)
    _assert_headers(headers, LEDGER_HEADERS, "use ledger")
    if not rows:
        raise AssertionError("the use ledger rendered no entry rows")
    out = [("FIG-accounting-046", slug, "first row Amount (AF)", _number(rows[0][2]))]

    foot = re.search(r"<tfoot.*?</tfoot>", table, re.S)
    if foot is None:
        raise AssertionError("the use ledger no longer carries a footer total row")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", foot.group(0), re.S)
    out.append(("FIG-accounting-047", slug, "footer net", _number(cells[1])))
    split = _text(cells[2])
    credits = re.search(r"\+([\d,]+\.\d+)\s*credits", split)
    debits = re.search(r"([\-−][\d,]+\.\d+)\s*debits", split)
    if credits is None or debits is None:
        raise AssertionError(f"the footer's credits/debits line reads {split!r}")
    out.append(("FIG-accounting-048", slug, "footer credits", credits.group(1).replace(",", "")))
    out.append((
        "FIG-accounting-049", slug, "footer debits",
        debits.group(1).replace(",", "").replace("−", "-"),
    ))
    return out


def allocations(html, slug):
    """FIG-accounting-021..022: one allocation row and the footer total."""
    table = _table_after(html, "result-count-bar")
    headers, rows = _rows(table)
    _assert_headers(headers, ALLOC_HEADERS, "allocations list")
    match = next((r for r in rows if _text(r[0]) == PINNED_ALLOC_LIST), None)
    if match is None:
        raise AssertionError(f"the pinned allocation {PINNED_ALLOC_LIST!r} is not on this page")
    out = [("FIG-accounting-021", slug, PINNED_ALLOC_LIST, _number(match[4]))]
    foot = re.search(r"<tfoot.*?</tfoot>", table, re.S)
    if foot is None:
        raise AssertionError("the allocations table no longer carries a footer total")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", foot.group(0), re.S)
    out.append(("FIG-accounting-022", slug, "footer total allocated", _number(cells[1])))
    return out


def period_detail(html, slug):
    """FIG-accounting-054: one allocation row on the reporting-period page."""
    table = _table_after(html, "Allocations</h2>")
    headers, rows = _rows(table)
    _assert_headers(headers, PERIOD_ALLOC_HEADERS, "period detail allocations")
    match = next((r for r in rows if _text(r[0]) == PINNED_ALLOC_PERIOD), None)
    if match is None:
        raise AssertionError(f"the pinned allocation {PINNED_ALLOC_PERIOD!r} is not on this page")
    return [("FIG-accounting-054", slug, PINNED_ALLOC_PERIOD, _number(match[3]))]


PAGES = [
    ("accounting-a-calcrun-p16-2026-03", calculation_run),
    ("accounting-a-account-78-p2", account_pane),
    ("accounting-a-allocations-p2", allocations),
    ("accounting-a-ledger-p2", use_ledger),
    ("accounting-a-methodology-preview-p16-2026-03", methodology_preview),
    ("accounting-a-period-2", period_detail),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered", default="audit/figure_ledger/rendered")
    parser.add_argument("--out", default="audit/figure_ledger/results/rendered_accounting_detail.csv")
    args = parser.parse_args()

    records = []
    for slug, reader in PAGES:
        records.extend(reader(_read(args.rendered, slug), slug))
    records.sort(key=lambda r: r[0])

    if len(records) != 31:
        print(
            f"expected 31 sites, read {len(records)}. The section covers exactly "
            "the 31 figures inventory.json records for these six templates.",
            file=sys.stderr,
        )
        return 1

    # A site whose block never rendered has NO rendered value, and the `rendered`
    # column says so by being empty. The reason moves into `note`, so
    # merge_results.py reports NO VALUE rather than trying to subtract a sentence
    # from an acre-foot figure.
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "screen_slug", "label", "rendered", "note"])
        for fig, slug, label, value in records:
            if value == NOT_RENDERED:
                writer.writerow([fig, slug, label, "", NOT_RENDERED])
            else:
                writer.writerow([fig, slug, label, value, ""])
    for record in records:
        print("  ".join(str(field) for field in record))
    print(f"  {len(records)} sites -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
