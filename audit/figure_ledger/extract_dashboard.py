# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the 23 accounting-dashboard figures out of the SERVED HTML.

The ledger's `rendered` column has to be what a person sees, so it is read back
out of the saved page rather than re-asked of the application. Standard library
only -- `requirements.lock` carries no HTML parsing dependency and this adds none.

**Located by position within labelled structures, not by instrumentation.** The
templates gain no `data-figure` attributes: marking up the page would change the
very output under audit and would break the byte-diff precedent
`scripts/render_baseline.py` set. So the three panel figures are found by their
own class names, and the two table rows by the account number and zone name a
reader can see, then by column order -- which is checked against the table's own
header cells, so a column inserted upstream fails loudly instead of silently
shifting every value by one.

    python3 audit/figure_ledger/extract_dashboard.py \
        --html audit/figure_ledger/rendered/accounting-dashboard-wy2026.html \
        --out audit/figure_ledger/results/rendered_accounting_dashboard.csv
"""

import argparse
import csv
import os
import re
import sys

#: The account and zone rows the ledger pins, and the ids they map to. Column
#: order here is asserted against the rendered table header before any value is
#: read, so this list cannot silently drift out of step with the screen.
ACCOUNT_COLUMNS = [
    ("FIG-accounting-033", "Consumptive Use (AF)"),
    ("FIG-accounting-029", "Surface (AF)"),
    ("FIG-accounting-030", "Groundwater (AF)"),
    ("FIG-accounting-031", "Precip (AF)"),
    ("FIG-accounting-032", "Supplies (AF)"),
    ("FIG-accounting-034", "Net (AF)"),
    ("FIG-accounting-035", "GW allocation (AF)"),
    ("FIG-accounting-036", "GW remaining (AF)"),
]
ZONE_COLUMNS = [
    ("FIG-accounting-047", "Consumptive Use (AF)"),
    ("FIG-accounting-043", "Surface (AF)"),
    ("FIG-accounting-044", "Groundwater (AF)"),
    ("FIG-accounting-045", "Precip (AF)"),
    ("FIG-accounting-046", "Supplies (AF)"),
    ("FIG-accounting-048", "Net (AF)"),
    ("FIG-accounting-049", "GW allocation (AF)"),
    ("FIG-accounting-050", "Carried fwd (AF)"),
    ("FIG-accounting-051", "GW remaining (AF)"),
]

PINNED_ACCOUNT = "MER-ACCT-001"
PINNED_ZONE = "Halvern Irrigation-Urban GSA"

_TAG = re.compile(r"<[^>]+>")


def _text(fragment):
    """Visible text of an HTML fragment, whitespace collapsed."""
    stripped = _TAG.sub(" ", fragment)
    stripped = stripped.replace("&mdash;", "—").replace("&minus;", "−")
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return " ".join(stripped.split())


def _number(fragment):
    """The figure a reader sees, thousands separator removed, as text.

    A dash is returned as-is: it is the ISS-099 suppression, a deliberate
    non-number, and turning it into 0.00 here would erase the exact distinction
    the template was changed to make.
    """
    text = _text(fragment)
    if text in {"—", "-", "&mdash;"}:
        return "—"
    match = re.search(r"[+-]?[\d,]+\.\d+", text)
    if not match:
        return text
    return match.group(0).replace(",", "").lstrip("+")


def _panel_figures(html):
    """The three grand-total cards and the three supply splits."""
    out = {}
    panel = re.search(r'<div class="budget-panel">.*?<div class="budget-panel-foot">.*?</div>',
                      html, re.S)
    if not panel:
        raise SystemExit("budget-panel not found — is this the dashboard page?")
    block = panel.group(0)

    values = re.findall(r'<div class="budget-seg-value[^"]*">(.*?)</div>', block, re.S)
    if len(values) != 3:
        raise SystemExit(
            f"expected 3 budget-seg-value blocks, found {len(values)}. The panel's "
            "shape changed; the extractor must be re-read against the template "
            "rather than made to cope."
        )
    for fig_id, value in zip(
        ("FIG-accounting-023", "FIG-accounting-024", "FIG-accounting-025"), values
    ):
        out[fig_id] = _number(value)

    foot = re.search(r'<div class="budget-panel-foot">(.*?)</div>', block, re.S).group(1)
    bolds = re.findall(r"<b>(.*?)</b>", foot, re.S)
    if len(bolds) != 3:
        raise SystemExit(f"expected 3 supply splits in the panel foot, found {len(bolds)}")
    for fig_id, value in zip(
        ("FIG-accounting-026", "FIG-accounting-027", "FIG-accounting-028"), bolds
    ):
        out[fig_id] = _number(value)
    return out


def _headers_after(html, index):
    """The header cell texts of the next table below ``index``."""
    head = re.search(r"<thead>(.*?)</thead>", html[index:], re.S)
    if not head:
        raise SystemExit("no table header found where one was expected")
    return [_text(cell) for cell in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)]


def _row_cells(html, anchor):
    """The `<td>` fragments of the table row containing ``anchor``."""
    index = html.find(anchor)
    if index == -1:
        raise SystemExit(f"pinned row {anchor!r} is not on this page")
    start = html.rfind("<tr>", 0, index)
    end = html.find("</tr>", index)
    return re.findall(r"<td[^>]*>(.*?)</td>", html[start:end], re.S)


def _table_figures(html, anchor, columns, label):
    cells = _row_cells(html, anchor)
    # The first cell is the row's name; the figures follow it in column order.
    values = cells[1:]
    if len(values) != len(columns):
        raise SystemExit(
            f"{label}: expected {len(columns)} figure cells after the name cell, "
            f"found {len(values)}. A column was added or removed — re-read the "
            "template before trusting any value from this row."
        )

    # The header check: the column each id is mapped to must still carry the
    # words the ledger recorded. This is what makes a shifted column loud.
    headers = _headers_after(html, html.rfind("<table", 0, html.find(anchor)))
    figure_headers = headers[1:]
    for (fig_id, expected), actual in zip(columns, figure_headers):
        # The header carries its explainer pop-out text too; a prefix match on the
        # visible column name is the assertion that matters.
        if not actual.startswith(expected):
            raise SystemExit(
                f"{label}: {fig_id} was recorded against column {expected!r} but "
                f"that position now reads {actual[:60]!r}. Column order moved."
            )
    return {fig_id: _number(value) for (fig_id, _h), value in zip(columns, values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.html, encoding="utf-8") as handle:
        html = handle.read()

    figures = {}
    figures.update(_panel_figures(html))
    figures.update(_table_figures(html, PINNED_ACCOUNT, ACCOUNT_COLUMNS, "account row"))
    figures.update(_table_figures(html, PINNED_ZONE, ZONE_COLUMNS, "zone row"))

    if len(figures) != 23:
        raise SystemExit(f"extracted {len(figures)} figures, expected 23")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "rendered"])
        for fig_id in sorted(figures):
            writer.writerow([fig_id, figures[fig_id]])
    print(f"  23 rendered values -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
