# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pair two figure inventories and print ``old_id -> new_id`` for every site.

Figure ids are assigned in (app, template, line, column) order, so editing a
template renumbers every figure after the edit and moves every ``site`` line.
This pairs the k-th occurrence of an expression in a template with the k-th
occurrence of the same expression in the same template of the newer inventory,
which is the one thing an edit that adds no figure cannot change.

It REFUSES to guess: a template that gained or lost a site is listed and the
run exits non-zero. A gained site is a new figure and needs a full trace; a
lost one needs its ledger row deleted with a reason.

    python3 audit/figure_ledger/remap_ids.py --old <before.json> --new audit/figure_ledger/inventory.json
"""
import argparse
import json
import sys
from collections import defaultdict


def _by_key(records, aliases=None):
    grouped = defaultdict(list)
    for record in records:
        if record["kind"] != "figure":
            continue
        expression = record["expression"]
        for old_name, new_name in (aliases or {}).items():
            expression = expression.replace(old_name, new_name)
        grouped[(record["template"], expression)].append(record)
    return grouped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument(
        "--alias", action="append", default=[], metavar="OLD_EXPR=NEW_EXPR",
        help="a context variable RENAMED in place, stated explicitly so the "
             "pairing does not read a rename as one site lost and one gained",
    )
    parser.add_argument(
        "--expect-lost", action="append", default=[], metavar="EXPR",
        help="an expression whose site was deliberately REMOVED; the run still "
             "lists it, but does not refuse over it",
    )
    args = parser.parse_args()
    aliases = dict(item.split("=", 1) for item in args.alias)
    old = _by_key(json.load(open(args.old)), aliases)
    new = _by_key(json.load(open(args.new)))

    problems = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key, []), new.get(key, [])
        if len(before) != len(after):
            line = f"  {key[0]} {key[1]!r}: {len(before)} before, {len(after)} after"
            if not after and key[1] in args.expect_lost:
                print(f"{before[0]['id']} -> (retired)   {key[0]}:{before[0]['line']}   expected loss")
            else:
                problems.append(line)
            continue
        for a, b in zip(before, after):
            moved = "" if (a["id"], a["line"]) == (b["id"], b["line"]) else "   <-- moved"
            print(f"{a['id']} -> {b['id']}   {key[0]}:{a['line']} -> :{b['line']}{moved}")

    if problems:
        print("REFUSING TO GUESS. Sites gained or lost, one per line:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
