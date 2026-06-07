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
# Two files are written side by side:
#   golden.dump  — pg_dump -Fc of the WHOLE database (drop+recreate restorable,
#                  PostGIS included). Uses the db container's own POSTGRES_* env,
#                  so it adapts to prod (openh2o) and staging (openh2o_staging).
#   golden.meta  — a manifest stamping WHAT this snapshot is: the schema
#                  (migration) fingerprint, the deployed code version, a
#                  timestamp, and per-model row counts. reset-demo.sh reads the
#                  fingerprint to refuse a wipe when the live schema has moved on
#                  past this snapshot (the "staleness guard").
#
# Usage:  scripts/snapshot-demo.sh [SNAPSHOT_PATH]
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAP="${1:-$HOME/openh2o-demo-snapshot/golden.dump}"
META="${SNAP%.dump}.meta"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

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

# Stamp the manifest from the SAME live state we just dumped. The fingerprint is
# the load-bearing field — it's what the nightly guard compares against.
fingerprint="$(demo_migration_fingerprint)"
if [ -z "$fingerprint" ]; then
  echo "snapshot-demo: ERROR could not read live schema fingerprint (is web up?) — keeping previous manifest" >&2
  exit 1
fi
version="$(git describe --tags --always --dirty 2>/dev/null || echo dev)"
stamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

metatmp="$(mktemp)"
trap 'rm -f "$metatmp"' EXIT
{
  echo "# OpenH2O demo golden-snapshot manifest — written by snapshot-demo.sh"
  echo "# reset-demo.sh refuses to wipe if the live migration_fingerprint differs."
  echo "schema_version=$version"
  echo "migration_fingerprint=$fingerprint"
  echo "snapshot_timestamp=$stamp"
  echo ""
  echo "# first-party row counts (app.Model=count) at snapshot time"
  demo_row_counts
} > "$metatmp"
mv "$metatmp" "$META"
trap - EXIT

echo "snapshot-demo: golden snapshot written -> $SNAP ($(du -h "$SNAP" | cut -f1))"
echo "snapshot-demo: manifest written -> $META (version $version, fingerprint ${fingerprint:0:12}…)"
