#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Capture a "golden" snapshot of the demo database — the pristine state the
# nightly reset (reset-demo.sh) restores to. Run this when the DB is in the
# exact state you want visitors to always start from:
#   * right after a fresh seed, OR
#   * after an intentional schema migration or demo-content change
#     (otherwise the nightly restore would reload the OLD shape).
#
# Custom-format dump (pg_dump -Fc) of the WHOLE database, so a restore can drop
# and recreate the database including its PostGIS extension. Uses the db
# container's own POSTGRES_* env, so it adapts to prod (openh2o) and staging
# (openh2o_staging) with no hardcoding.
#
# Usage:  scripts/snapshot-demo.sh [SNAPSHOT_PATH]
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAP="${1:-$HOME/openh2o-demo-snapshot/golden.dump}"

cd "$OPENH2O_DIR"
mkdir -p "$(dirname "$SNAP")"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

# -Fc = custom (compressed) format. Reads creds from the container env.
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$tmp"

# Only overwrite the live snapshot once the dump succeeded and is non-empty.
if [ ! -s "$tmp" ]; then
  echo "snapshot-demo: ERROR dump was empty — keeping previous snapshot" >&2
  exit 1
fi
mv "$tmp" "$SNAP"
trap - EXIT
echo "snapshot-demo: golden snapshot written -> $SNAP ($(du -h "$SNAP" | cut -f1))"
