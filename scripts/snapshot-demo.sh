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
# IDENTITY GATE: before anything is written, the live database is scanned for
# real agency, district, farm and owner names sitting on invented demonstration
# data, and a finding REFUSES the snapshot. This is the moment that matters. A
# golden snapshot is permanent — production reloads it every night — so a real
# name frozen in here is served every day until a human notices, which in July
# 2026 took three days. reset-demo.sh runs the same scan but only ALERTS,
# because by the time it runs the demo is already restored and serving and
# aborting would leave the site worse off. Here the opposite holds: nothing has
# been written yet, and not creating a bad snapshot costs nothing at all.
#
# Usage:  scripts/snapshot-demo.sh [SNAPSHOT_PATH]
#         FORCE=1 scripts/snapshot-demo.sh [SNAPSHOT_PATH]   # skip identity gate
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAP="${1:-$HOME/openh2o-demo-snapshot/golden.dump}"
META="${SNAP%.dump}.meta"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

cd "$OPENH2O_DIR"
mkdir -p "$(dirname "$SNAP")"

# ---------------------------------------------------------------------------
# Identity gate — refuse to freeze a demo carrying a real water district's name.
# Runs FIRST, so a refusal leaves the previous snapshot and manifest untouched.
# ---------------------------------------------------------------------------
if [ "${FORCE:-0}" = "1" ]; then
  echo "snapshot-demo: FORCE=1 — identity gate bypassed (nothing has checked this database)"
else
  scan_status=0
  scan_json="$(docker compose exec -T web python manage.py scan_demo_identity --json 2>/dev/null)" || scan_status=$?
  # $? captured on the SAME line. Read after an if/fi it is the compound's
  # status — 0 — which would turn every real finding into a silent success.

  scan_violations="$(printf '%s' "$scan_json" | sed -n 's/.*"violations": *\([0-9]*\).*/\1/p' | head -1)"

  if [ -z "$scan_violations" ]; then
    # Not an all-clear. Same reasoning as the fingerprint check further down:
    # a state nothing could verify must not be frozen as the known-good one.
    echo "snapshot-demo: REFUSING — the identity scan could not run (exit ${scan_status})." >&2
    echo "  Nothing has checked this database for real water-district names, and an" >&2
    echo "  unverified state must not become the golden. Previous snapshot kept." >&2
    demo_ntfy low "OpenH2O snapshot refused — check did not run" \
      "snapshot-demo on $(hostname) refused to write a new golden snapshot because the name check could not run. The previous snapshot is untouched."
    exit 1
  fi

  if [ "$scan_violations" != "0" ]; then
    echo "snapshot-demo: REFUSING — ${scan_violations} real name(s) on invented demonstration data:" >&2
    printf '%s' "$scan_json" | docker compose exec -T web python -c '
import json, sys
for f in json.load(sys.stdin).get("findings", []):
    value = " ".join(f["value"].split())
    if len(value) > 120:
        value = value[:120] + "..."
    print("  %s.%s pk=%s: %s" % (f["table"], f["column"], f["pk"], value))
    print("      matches banned %r" % f["matched"])
' >&2 2>/dev/null || true
    echo "  A golden snapshot is permanent — production reloads it every night. Fix the" >&2
    echo "  data first, then re-run. Previous snapshot kept. FORCE=1 overrides." >&2
    demo_ntfy low "OpenH2O snapshot refused — real name in the demo" \
      "snapshot-demo on $(hostname) refused to freeze this database: it is showing ${scan_violations} real name(s) where only invented ones belong. The previous snapshot is untouched and production is unaffected."
    exit 1
  fi

  echo "snapshot-demo: identity gate OK — no real agency/district/farm/owner name in this database"
fi

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
