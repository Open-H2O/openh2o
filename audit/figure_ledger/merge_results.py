# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put the rendered and recomputed halves of one ledger section side by side.

    python3 audit/figure_ledger/merge_results.py \
        --rendered   audit/figure_ledger/results/rendered_accounting_dashboard.csv \
        --recomputed audit/figure_ledger/results/recomputed_accounting_dashboard.csv \
        --out        audit/figure_ledger/results/accounting_dashboard.csv

The comparison is exact decimal arithmetic, never floating point: these are
acre-feet to the cent, and a float round-trip would invent differences of its own
at the very precision the ledger is reading.

A figure the page deliberately withholds -- the dash shown for a row with no
calculation behind it -- is carried through as NO VALUE rather than coerced to
zero. Turning it into 0.00 here would erase the exact distinction the template was
changed to make.
"""

import argparse
import csv
import decimal
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered", required=True)
    parser.add_argument("--recomputed", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.rendered, newline="", encoding="utf-8") as handle:
        rendered = {r["id"]: r["rendered"] for r in csv.DictReader(handle)}
    with open(args.recomputed, newline="", encoding="utf-8") as handle:
        recomputed = {
            r["id"]: (r.get("label", ""), r["recomputed"]) for r in csv.DictReader(handle)
        }

    rows = []
    for fig_id in sorted(set(rendered) | set(recomputed)):
        label, right = recomputed.get(fig_id, ("(no recomputation)", ""))
        left = rendered.get(fig_id, "")
        if left in ("", "—") or right == "":
            delta = "NO VALUE"
        else:
            difference = decimal.Decimal(left) - decimal.Decimal(right)
            delta = "MATCH" if difference == 0 else str(difference)
        rows.append([fig_id, label, left, right, delta])

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "label", "rendered", "recomputed", "delta"])
        writer.writerows(rows)

    matches = sum(1 for r in rows if r[4] == "MATCH")
    print(f"  {len(rows)} rows, {matches} match to the cent -> {args.out}")
    for row in rows:
        if row[4] != "MATCH":
            print(f"    {row[0]}  rendered {row[2]}  recomputed {row[3]}  delta {row[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
