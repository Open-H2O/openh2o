# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the 15 parcel-detail-pane figures out of the SERVED HTML (137-01 basis).

Same contract as ``extract_dashboard.py`` and the same reasons: the ledger's
`rendered` column has to be what a person sees, so it is read back out of the
saved page rather than re-asked of the application; standard library only,
because ``requirements.lock`` carries no HTML parsing dependency; and the
template gains no ``data-figure`` attributes, because marking up the page would
change the very output under audit.

**Rewritten for 137-01.** The pane used to carry 20 figures across three stat
cards, a "Net consumptive demand" sentence, three composition cards, a
supply-vs-use table and a free-standing residual row. 137-01 replaced all of
that with ONE ``.budget-panel`` (three segments — Supplies, Uses, Residual —
plus a two-line foot) and added the ISS-157 unmet-demand line. This extractor
reads the NEW markup only; the OLD extractor (stat cards, summary table,
"Net consumptive demand" sentence) is retired along with the markup it read.

**Located by the words a reader can see.** Every value is found by the label
printed beside it — "Supplies", "Uses", "Residual", the foot's "Surface" /
"Groundwater" / "Rain" / "Consumptive use" / "Recharge" / "Storage change" —
and each label is asserted present before its value is read. A renamed label
therefore fails loudly instead of silently handing back the number from the
segment next door.

Two of the fifteen sites sit in the pane's "ET has not been computed" branch
(``_detail_pane.html``, the ``{% else %}`` of ``{% if run_periods %}``). This
extractor reports them as ABSENT rather than inventing a value: on this data
every parcel has calculation runs, so that branch never renders and the ledger
records those two rows UNVERIFIED, exactly as before 137-01.

The ISS-157 unmet-demand line (FIG-parcels-010) renders only when
``unmet_demand_af > 0`` (DESIGN.md rule 8: a zero renders nothing). Reported
ABSENT on a screen where it does not render — that is the platform working as
designed, not a missing figure.

    python3 audit/figure_ledger/extract_parcel_pane.py \
        --html audit/figure_ledger/rendered/parcel-detail-mer-apn-011-dry.html \
        --out audit/figure_ledger/results/rendered_parcel_pane_mer_apn_011_dry.csv
"""

import argparse
import csv
import os
import re
import sys

_TAG = re.compile(r"<[^>]+>")

#: The three segments of the ONE balance statement, by the label printed above
#: each value. Order is not trusted: each is found by its own label text.
SEGMENTS = [
    ("FIG-parcels-001", "Supplies"),
    ("FIG-parcels-005", "Uses"),
    ("FIG-parcels-009", "Residual"),
]

#: The two-line foot, by the word printed beside each number. First line is
#: supplies, second is uses — found by label text, not position, so the two
#: lines could swap order in the template with nothing here going stale-quiet.
FOOT_CELLS = [
    ("FIG-parcels-002", "Surface"),
    ("FIG-parcels-003", "Groundwater"),
    ("FIG-parcels-004", "Rain"),
    ("FIG-parcels-006", "Consumptive use"),
    ("FIG-parcels-007", "Recharge"),
    ("FIG-parcels-008", "Storage change"),
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
    if text in {"-", "—", "−"}:   # the product's own em dash / minus, as data
        return "(dash)"   # the product printed a dash, not a number
    match = re.search(r"[+−-]?[\d,]+\.\d+", text)
    if not match:
        return text
    return match.group(0).replace(",", "").replace("−", "-").lstrip("+")


def _segments(html, out):
    """The three .budget-seg values, found by their .budget-seg-label text."""
    for fid, label in SEGMENTS:
        pattern = (
            r'<div class="budget-seg-label">\s*'
            + re.escape(label)
            + r'\s*</div>\s*<div class="budget-seg-value[^"]*">(.*?)<span class="budget-seg-unit"'
        )
        match = re.search(pattern, html, re.S)
        if not match:
            raise SystemExit(
                f"{fid}: no budget-seg labelled {label!r}. The panel's segment "
                "labels have moved; fix this extractor rather than reading a "
                "neighbouring segment's value."
            )
        out[fid] = _number(match.group(1))


def _foot(html, out):
    """The two-line .budget-panel-foot, found by each cell's own label word."""
    foot_block = re.findall(
        r'<div class="budget-panel-foot">(.*?)</div>\s*(?=<div class="budget-panel-foot">|</div>|\{% comment %\}|\{% if )',
        html,
        re.S,
    )
    combined = "\n".join(foot_block) if foot_block else html
    for fid, label in FOOT_CELLS:
        pattern = r"<span>\s*" + re.escape(label) + r"\s*<b>(.*?)</b>\s*</span>"
        match = re.search(pattern, combined, re.S) or re.search(pattern, html, re.S)
        if not match:
            raise SystemExit(
                f"{fid}: no foot cell labelled {label!r}. The panel foot's "
                "labels have moved."
            )
        out[fid] = _number(match.group(1))


def _unmet_demand(html, out):
    """FIG-parcels-010, ISS-157: renders only when unmet_demand_af > 0."""
    match = re.search(
        r"Water use recorded, no supply reported:\s*</strong>\s*"
        r'<span class="td-num">(.*?)</span>',
        html,
        re.S,
    )
    out["FIG-parcels-010"] = _number(match.group(1)) if match else "ABSENT"


def _et_not_computed_branch(html, out):
    """The two supply figures inside the no-ET warning.

    Reported ABSENT when the branch did not render, which is the honest answer
    for a parcel that has calculation runs. Never fabricated as 0.00.
    """
    match = re.search(r'<div class="alert-warning">(.*?)</div>', html, re.S)
    if not match or "ET has not been computed" not in match.group(1):
        out["FIG-parcels-011"] = "ABSENT"
        out["FIG-parcels-012"] = "ABSENT"
        return
    block = match.group(1)
    surface = re.search(r"surface\s*([\d,]+\.\d+)", block)
    groundwater = re.search(r"groundwater\s*([\d,]+\.\d+)", block)
    out["FIG-parcels-011"] = surface.group(1).replace(",", "") if surface else "ABSENT"
    out["FIG-parcels-012"] = (
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
        raise SystemExit("FIG-parcels-013: the Area (Acres) field was not found.")
    out["FIG-parcels-013"] = _number(match.group(1))


def _well_fraction(html, out):
    """The first well share in the Related wells card."""
    if "Related wells" not in html:
        out["FIG-parcels-014"] = "ABSENT"
        return
    card = html.split("Related wells", 1)[1]
    match = re.search(r'<span class="text-tertiary text-xs">(.*?)fraction</span>', card, re.S)
    out["FIG-parcels-014"] = _number(match.group(1)) if match else "ABSENT"


def _first_ledger_amount(html, out):
    """The Amount cell of the first row of Recent ledger entries."""
    if "Recent ledger entries" not in html:
        out["FIG-parcels-015"] = "ABSENT"
        return
    card = html.split("Recent ledger entries", 1)[1]
    table = re.search(r"<thead>(.*?)</thead>.*?<tbody>(.*?)</tbody>", card, re.S)
    if not table:
        out["FIG-parcels-015"] = "ABSENT"
        return
    cells = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", table.group(1), re.S)]
    if cells != ["Date", "Amount (AF)", "Source"]:
        raise SystemExit(
            f"ledger header is {cells}, not ['Date','Amount (AF)','Source']. "
            "The Amount column moved."
        )
    first_row = re.search(r"<tr>(.*?)</tr>", table.group(2), re.S)
    tds = re.findall(r"<td[^>]*>(.*?)</td>", first_row.group(1), re.S)
    out["FIG-parcels-015"] = _number(tds[1])


ORDER = [f"FIG-parcels-{n:03d}" for n in range(1, 16)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.html) as handle:
        html = handle.read()

    out = {}
    _segments(html, out)
    _foot(html, out)
    _unmet_demand(html, out)
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
