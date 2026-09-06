#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Run one figure-ledger recomputation file against the demonstration database
# and print the result as CSV.
#
#     bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/<file>.sql
#
# THIS RUNS ON THE HOST, NOT IN THE `web` CONTAINER, AND THAT IS HALF THE
# CORRECTNESS ARGUMENT OF THE WHOLE LEDGER. The recomputation never enters the
# Python process that owns the object-relational mapper, so it cannot import,
# call, or accidentally reach through the code whose arithmetic it is checking.
# A check that runs inside the application can only ever prove the application
# agrees with itself.
#
# Two flags carry weight:
#   ON_ERROR_STOP=1  a typo'd column name aborts with a non-zero exit instead of
#                    scrolling past. Without it psql keeps going and the run
#                    ends with an empty result set that reads exactly like
#                    "checked, no discrepancy" -- the most dangerous output this
#                    harness could produce.
#   --csv            machine-comparable output, so a rendered-vs-recomputed diff
#                    is a column comparison rather than an eyeball.
#
# Read-only by construction: nothing here writes, and every recomputation file
# is a SELECT. The guard test tests/test_figure_ledger_independence.py enforces
# the mechanical half of the independence rule.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <file.sql>" >&2
  exit 2
fi

SQL_FILE="$1"
if [ ! -f "$SQL_FILE" ]; then
  echo "no such SQL file: $SQL_FILE" >&2
  exit 2
fi

docker compose exec -T db \
  psql -U openh2o -d openh2o -v ON_ERROR_STOP=1 --csv -f - < "$SQL_FILE"
