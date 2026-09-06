# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the 20 parcel-detail-pane figures out of the SERVED HTML.

Same contract as ``extract_dashboard.py`` and the same reasons: the ledger's
`rendered` column has to be what a person sees, so it is read back out of the
saved page rather than re-asked of the application; standard library only,
because ``requirements.lock`` carries no HTML parsing dependency; and the
template gains no ``data-figure`` attributes, because marking up the page would
change the very output under audit.

**Located by the words a reader can see.** Every value is found by the label
printed beside it -- "Consumptive use (ET)", "Total supplies", the row label
"Recharge" in the supply-vs-use table -- and each label is asserted present
before its value is read. A renamed label therefore fails loudly instead of
silently handing back the number from the card next door.

Two of the twenty sites sit in the pane's "ET has not been computed" branch
(``_detail_pane.html`` lines 178-179). This extractor reports them as ABSENT
rather than inventing a value: on this data every parcel has calculation runs,
so that branch never renders and the ledger records those two rows UNVERIFIED.

    python3 audit/figure_ledger/extract_parcel_pane.py \
        --html audit/figure_ledger/rendered/parcel-detail-disagree-mer-apn-032.html \
        --out audit/figure_ledger/results/rendered_parcel_pane_mer_apn_032.csv
"""

import argparse
import csv
import os
import re
import sys

_TAG = re.compile(r"<[^>]+>")

#: The three top cards and the three supply splits, by the label printed above
#: each one. Order is not trusted: each is found by its own label text.
INSET_CARDS = [
    ("FIG-parcels-001", "Consumptive use (ET)"),
    ("FIG-parcels-002", "Total supplies"),
    ("FIG-parcels-003", "Supplies − consumptive use"),
    ("FIG-parcels-005", "Surface water"),
    ("FIG-parcels-006", "Groundwater"),
    ("FIG-parcels-007", "Precipitation"),
]

#: The supply-vs-use table, by the row label beside each number. The table has
#: two label/number pairs per row: supplies on the left, uses on the right.
SUMMARY_ROWS = [
    ("FIG-parcels-008", "Surface"),
    ("FIG-parcels-009", "ET"),
    ("FIG-parcels-010", "Precip"),
    ("FIG-parcels-011", "Recharge"),
    ("FIG-parcels-012", "Groundwater pumped"),
    ("FIG-parcels-013", "Runoff"),
    ("FIG-parcels-014", "Net Banked/Drawn (credits)"),
]


def _text(fragment):
    """Visible text of an HTML fragment, whitespace collapsed."""
    stripped = _TAG.sub(" ", fragment)
    stripped = stripped.replace("&mdash;", "-").replace("&minus;", "-")
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return " ".join(stripped.split())


def _number(fragment):
    """The figure a reader sees, thousands separator removed, as text."""
    text = _text(fragment)
    if text in {"-", "\u2014", "\u2212"}:   # the product's own em dash / minus, as data
        return "(dash)"   # the product printed a dash, not a number
    match = re.search(r"[+−-]?[\d,]+\.\d+", text)
    if not match:
        return text
    return match.group(0).replace(",", "").replace("−", "-").lstrip("+")


def _inset_cards(html, out):
    """Each stat card, found by the label printed above its number."""
    for fid, label in INSET_CARDS:
        pattern = (
            r'<div class="stat-card-label">\s*'
            + re.escape(label)
            + r'\s*</div>\s*<div class="stat-card-value-sm[^"]*">(.*?)</div>'
        )
        match = re.search(pattern, html, re.S)
        if not match:
            raise SystemExit(
                f"{fid}: no stat card labelled {label!r}. The pane's labels have "
                "moved; fix this extractor rather than reading a neighbour's value."
            )
        out[fid] = _number(match.group(1))


def _net_consumptive(html, out):
    """The net consumptive demand in the sentence under the three cards."""
    match = re.search(
        r"Net consumptive demand of\s*<span class=\"text-usage\"[^>]*>(.*?)</span>",
        html,
        re.S,
    )
    if not match:
        raise SystemExit("FIG-parcels-004: 'Net consumptive demand of' sentence not found.")
    out["FIG-parcels-004"] = _number(match.group(1))


def _summary_table(html, out):
    """The supply-vs-use table, checked against its own header cells first."""
    match = re.search(
        r'<h3 class="section-header-sm">Supply vs\. use summary</h3>\s*'
        r'<table class="data-table text-sm">(.*?)</table>',
        html,
        re.S,
    )
    if not match:
        raise SystemExit("Supply vs. use summary table not found. Is this the parcel pane?")
    table = match.group(1)
    header = re.search(r"<thead>(.*?)</thead>", table, re.S)
    cells = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", header.group(1), re.S)]
    if cells != ["Supplies", "AF", "Uses", "AF"]:
        raise SystemExit(
            f"supply-vs-use header is {cells}, not ['Supplies','AF','Uses','AF']. "
            "A column moved; every value below would shift with it."
        )
    body = re.search(r"<tbody>(.*?)</tbody>", table, re.S).group(1)
    for fid, label in SUMMARY_ROWS:
        pattern = (
            r'<td class="text-secondary">\s*'
            + re.escape(label)
            + r'\s*</td>\s*<td class="td-num[^"]*">(.*?)</td>'
        )
        cell = re.search(pattern, body, re.S)
        if not cell:
            raise SystemExit(f"{fid}: no summary row labelled {label!r}.")
        out[fid] = _number(cell.group(1))


def _residual(html, out):
    match = re.search(
        r'Residual:\s*<span class="td-num">(.*?)</span>\s*AF', html, re.S
    )
    if not match:
        raise SystemExit("FIG-parcels-015: the Residual line was not found.")
    out["FIG-parcels-015"] = _number(match.group(1))


def _et_not_computed_branch(html, out):
    """Lines 178-179: the two supply figures inside the no-ET warning.

    Reported ABSENT when the branch did not render, which is the honest answer
    for a parcel that has calculation runs. Never fabricated as 0.00.
    """
    match = re.search(
        r'<div class="alert-warning">(.*?)</div>', html, re.S
    )
    if not match or "ET has not been computed" not in match.group(1):
        out["FIG-parcels-016"] = "ABSENT"
        out["FIG-parcels-017"] = "ABSENT"
        return
    block = match.group(1)
    surface = re.search(r"surface\s*([\d,]+\.\d+)", block)
    groundwater = re.search(r"groundwater\s*([\d,]+\.\d+)", block)
    out["FIG-parcels-016"] = surface.group(1).replace(",", "") if surface else "ABSENT"
    out["FIG-parcels-017"] = (
        groundwater.group(1).replace(",", "") if groundwater else "ABSENT"
    )


def _area_acres(html, out):
    """The one editable field the pane renders as a number (Area (Acres))."""
    match = re.search(
        r'<div id="field-area_acres" class="field-row">.*?'
        r'<span class="field-value"[^>]*>(.*?)</span>',
        html,
        re.S,
    )
    if not match:
        raise SystemExit("FIG-parcels-018: the Area (Acres) field was not found.")
    out["FIG-parcels-018"] = _number(match.group(1))


def _well_fraction(html, out):
    """The first well share in the Related wells card."""
    if "Related wells" not in html:
        out["FIG-parcels-019"] = "ABSENT"
        return
    card = html.split("Related wells", 1)[1]
    match = re.search(r'<span class="text-tertiary text-xs">(.*?)fraction</span>', card, re.S)
    out["FIG-parcels-019"] = _number(match.group(1)) if match else "ABSENT"


def _first_ledger_amount(html, out):
    """The Amount cell of the first row of Recent ledger entries."""
    if "Recent ledger entries" not in html:
        out["FIG-parcels-020"] = "ABSENT"
        return
    card = html.split("Recent ledger entries", 1)[1]
    table = re.search(r"<thead>(.*?)</thead>.*?<tbody>(.*?)</tbody>", card, re.S)
    if not table:
        out["FIG-parcels-020"] = "ABSENT"
        return
    cells = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", table.group(1), re.S)]
    if cells != ["Date", "Amount (AF)", "Source"]:
        raise SystemExit(
            f"ledger header is {cells}, not ['Date','Amount (AF)','Source']. "
            "The Amount column moved."
        )
    first_row = re.search(r"<tr>(.*?)</tr>", table.group(2), re.S)
    tds = re.findall(r"<td[^>]*>(.*?)</td>", first_row.group(1), re.S)
    out["FIG-parcels-020"] = _number(tds[1])


ORDER = [f"FIG-parcels-{n:03d}" for n in range(1, 21)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.html) as handle:
        html = handle.read()

    out = {}
    _inset_cards(html, out)
    _net_consumptive(html, out)
    _summary_table(html, out)
    _residual(html, out)
    _et_not_computed_branch(html, out)
    _area_acres(html, out)
    _well_fraction(html, out)
    _first_ledger_amount(html, out)

    missing = [fid for fid in ORDER if fid not in out]
    if missing:
        raise SystemExit(f"not extracted: {missing}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "rendered"])
        for fid in ORDER:
            writer.writerow([fid, out[fid]])
    print(f"  {len(ORDER)} figures -> {args.out}")
    for fid in ORDER:
        print(f"  {fid}  {out[fid]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
