# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read section C's 14 figures out of the SERVED HTML.

Standard library only. Located by position within LABELLED structures, never by
instrumentation: no template gains a data-figure attribute, because marking up
the page would change the very output under audit.

Every table read here first asserts the table's own header cells still carry the
words each id was recorded against, so a column inserted upstream fails loudly
instead of shifting every value by one. Every field read asserts the label text
beside it.

    python3 extract_section_c.py --rendered <dir> --out <csv>
"""

import argparse
import csv
import re
import sys

_TAG = re.compile(r"<[^>]+>")


def _text(fragment):
    stripped = _TAG.sub(" ", fragment)
    stripped = stripped.replace("&mdash;", "—").replace("&minus;", "−")
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return " ".join(stripped.split())


def _number(fragment):
    text = _text(fragment)
    if text in {"—", "-"}:
        return "—"
    match = re.search(r"[+-]?[\d,]+(?:\.\d+)?", text)
    if not match:
        return text
    return match.group(0).replace(",", "").lstrip("+")


def _cells(row_html):
    return re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)


def _table_after(html, marker, expected_headers, what):
    """The first <table> at or after `marker`, with its header row checked."""
    start = html.find(marker)
    if start < 0:
        raise SystemExit(f"{what}: marker {marker!r} not on the page")
    table = re.search(r"<table\b.*?</table>", html[start:], re.S)
    if not table:
        raise SystemExit(f"{what}: no table after {marker!r}")
    body = table.group(0)
    head = re.search(r"<thead\b.*?</thead>", body, re.S)
    if not head:
        raise SystemExit(f"{what}: table has no header row")
    got = [_text(c) for c in _cells(head.group(0))]
    if got[: len(expected_headers)] != expected_headers:
        raise SystemExit(
            f"{what}: header cells are {got!r}, expected to start "
            f"{expected_headers!r}. A column moved; every value below would have "
            "shifted silently."
        )
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S)
    return [r for r in rows if "<td" in r]


def _field(html, label, what):
    """The field-value div that follows a field-label carrying `label`."""
    for match in re.finditer(r'class="field-label[^"]*"[^>]*>(.*?)</div>', html, re.S):
        if _text(match.group(1)).startswith(label):
            tail = html[match.end():]
            value = re.search(r'class="field-value[^"]*"[^>]*>(.*?)</div>', tail, re.S)
            if not value:
                raise SystemExit(f"{what}: label {label!r} has no value beside it")
            return _number(value.group(1))
    raise SystemExit(f"{what}: no field labelled {label!r} on the page")


def extract(rendered):
    def read(slug):
        with open(f"{rendered}/{slug}.html", encoding="utf-8") as handle:
            return handle.read()

    out = {}

    # ── /surface/diversion/9/ — MER-POD-011-DEMO Snelling Re-Diversion ────────
    pod = read("surface-pod-detail-snelling")
    if "MER-POD-011-DEMO Snelling Re-Diversion" not in pod:
        raise SystemExit("pod detail: not the pinned diversion point")
    out["FIG-surface-001"] = _field(pod, "Max rate (CFS)", "pod detail")
    out["FIG-surface-002"] = _field(pod, "Face value (AF)", "pod detail")

    rows = _table_after(
        pod, "Diversion records",
        ["Month", "Diverted (AF)", "Return Flow (AF)", "Retained (AF)", "Period"],
        "pod diversion records",
    )
    pinned = [r for r in rows if _text(_cells(r)[0]) == "May 2026"]
    if len(pinned) != 1:
        raise SystemExit(f"pod diversion records: {len(pinned)} rows read 'May 2026'")
    cells = _cells(pinned[0])
    out["FIG-surface-003"] = _number(cells[1])
    out["FIG-surface-004"] = _number(cells[2])
    out["FIG-surface-005"] = _number(cells[3])

    # ── /surface/rights/ — the list, first row by right identifier ────────────
    lst = read("surface-rights-list")
    rows = _table_after(
        lst, 'result-count-bar',
        ["Right ID", "Holder", "Face Value", "Status"], "rights list",
    )
    cells = _cells(rows[0])
    if _text(cells[0]) != "MER-WR-004-DEMO":
        raise SystemExit(f"rights list: first row is {_text(cells[0])!r}, not the pin")
    out["FIG-surface-006"] = _number(cells[2])

    # ── /surface/rights/7/ — MER-WR-010-DEMO ──────────────────────────────────
    right = read("surface-right-detail-wr010")
    if "MER-WR-010-DEMO" not in right:
        raise SystemExit("right detail: not the pinned water right")
    out["FIG-surface-007"] = _field(right, "Face value (AF)", "right detail")

    pods_card = right[right.find("Points of diversion"):]
    first_pod = re.search(
        r'data-table-link field-value-sm[^>]*>(.*?)</a>.*?Max rate:\s*([\d.,]+)\s*cfs',
        pods_card, re.S,
    )
    if not first_pod:
        raise SystemExit("right detail: no 'Max rate: N cfs' line in the points card")
    if "MER-POD-010-DEMO" not in _text(first_pod.group(1)):
        raise SystemExit(
            f"right detail: first point is {_text(first_pod.group(1))!r}, not the pin"
        )
    out["FIG-surface-008"] = first_pod.group(2).replace(",", "")

    rows = _table_after(
        right, "Recent diversion records",
        ["Month", "POD", "Volume (AF)", "Type"], "right recent diversions",
    )
    cells = _cells(rows[0])
    if _text(cells[0]) != "Sep 2026" or "MER-POD-010-DEMO" not in _text(cells[1]):
        raise SystemExit(
            f"right recent diversions: first row is {_text(cells[0])!r} / "
            f"{_text(cells[1])!r}, not the pin"
        )
    out["FIG-surface-009"] = _number(cells[2])

    # ── /reporting/reports/4/calwatrs-worksheet/ ──────────────────────────────
    ws = read("reporting-calwatrs-worksheet-sub4")
    first_block = ws.find("MER-BPOD-001 El Nido Canal Recharge Intake")
    if first_block < 0:
        raise SystemExit("worksheet: the pinned first block is not on the page")
    # 136-02 (ISS-152 a): the intake diverts under MER-WR-011-DEMO, so the block
    # heading is the right id where it read the red "No linked water right".
    # Re-pinned, not deleted: the block must still be FIRST and still carry the
    # intake's records, and the heading must be the linked right, not a blank.
    window = ws[first_block:first_block + 900]
    if "MER-WR-011-DEMO" not in window:
        raise SystemExit("worksheet: the pinned block does not read 'MER-WR-011-DEMO'")
    if "No linked water right" in window:
        raise SystemExit("worksheet: the pinned block still reads 'No linked water right'")
    rows = _table_after(
        ws[first_block:], "<table",
        ["Month", "Volume (AF)", "Max Rate (CFS)"], "worksheet block 1",
    )
    cells = _cells(rows[0])
    if _text(cells[0]) != "2026-01":
        raise SystemExit(f"worksheet: first row month is {_text(cells[0])!r}, not the pin")
    out["FIG-reporting-001"] = _number(cells[1])
    out["FIG-reporting-002"] = _number(cells[2])

    # ── /reporting/reports/shared-supply-check/?period=2 ──────────────────────
    ss = read("reporting-shared-supply-wy2026")
    group = ss.find("Point of diversion: MER-POD-004-DEMO Atwater Canal Headgate")
    if group < 0:
        raise SystemExit("shared supply: the pinned first group is not on the page")
    rows = _table_after(
        ss[group:], "<table",
        ["Use area", "Your share", "ET-implied share", "Gap", ""],
        "shared supply group 1",
    )
    pinned = [r for r in rows if _text(_cells(r)[0]) == "MER-APN-058"]
    if len(pinned) != 1:
        raise SystemExit(f"shared supply: {len(pinned)} rows read 'MER-APN-058'")
    cells = _cells(pinned[0])
    out["FIG-reporting-003"] = _number(cells[1])
    out["FIG-reporting-004"] = _number(cells[2])
    out["FIG-reporting-005"] = _number(cells[3])

    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered", default="audit/figure_ledger/rendered")
    parser.add_argument("--out", default="audit/figure_ledger/results/rendered_section_c.csv")
    args = parser.parse_args()

    values = extract(args.rendered)
    with open(args.out, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "rendered"])
        for key in sorted(values):
            writer.writerow([key, values[key]])
            print(f"  {key:<20} {values[key]}")
    print(f"  {len(values)} figures -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
