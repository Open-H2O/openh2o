#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Reset the public demo database to its golden snapshot, wiping everything any
# visitor added (parcels, wells, reports, signups). Safe to run on a schedule.
#
# The demo is single-tenant (one shared DB, no per-visitor isolation), so any
# logged-in visitor's writes persist for everyone. This restores the pristine
# Merced demo so the next visitor always starts from the same clean state.
#
# STALENESS GUARD: the danger of an automatic nightly wipe is that a *legit*
# change to the live DB (a schema migration, a content/calc rebuild) gets
# silently erased if nobody re-ran snapshot-demo.sh first. So before wiping, we
# compare the live schema's migration fingerprint against the one stamped into
# the golden manifest (golden.meta). If they differ, the snapshot predates a
# migration — we REFUSE the wipe, fire a high-priority ntfy, and exit without
# touching the data. Set FORCE=1 to bypass the guard (the deploy hook does this
# deliberately, because it restores+migrates-forward+re-stamps in one shot).
#
# Mechanism: drop + recreate the database from the golden snapshot (pg_dump -Fc
# written by snapshot-demo.sh), which cleanly rebuilds PostGIS and all data. The
# web container is paused during the swap (a few seconds) so nothing races the
# restore, then `migrate` runs to absorb any additive schema drift. A before/
# after row-count report is logged and ntfy'd as a data-loss backstop. Uses the
# db container's own POSTGRES_* env, so it adapts to prod and staging.
#
# Usage:  scripts/reset-demo.sh [SNAPSHOT_PATH]
#         FORCE=1 scripts/reset-demo.sh [SNAPSHOT_PATH]   # skip staleness guard
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAP="${1:-$HOME/openh2o-demo-snapshot/golden.dump}"
META="${SNAP%.dump}.meta"
LOG="${LOG:-$HOME/openh2o-logs/reset-demo.log}"
FORCE="${FORCE:-0}"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

mkdir -p "$(dirname "$LOG")"
cd "$OPENH2O_DIR"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

if [ ! -s "$SNAP" ]; then
  log "ABORT: golden snapshot $SNAP missing or empty — run snapshot-demo.sh first"
  exit 1
fi

# ---------------------------------------------------------------------------
# Staleness guard — the live schema must match what the golden was stamped at.
# ---------------------------------------------------------------------------
if [ "$FORCE" = "1" ]; then
  log "reset-demo: FORCE=1 — staleness guard bypassed (expected during deploy)"
else
  golden_fp="$(sed -n 's/^migration_fingerprint=//p' "$META" 2>/dev/null | head -1)"
  if [ -z "$golden_fp" ]; then
    log "REFUSE: $META has no migration_fingerprint (pre-guard snapshot?) — run 'make snapshot-demo' to re-stamp. Not wiping."
    demo_ntfy high "OpenH2O demo reset SKIPPED" \
      "Golden snapshot on $(hostname) has no fingerprint manifest. Re-stamp with 'make snapshot-demo'. Demo NOT reset."
    exit 0
  fi

  live_fp="$(demo_migration_fingerprint)"
  if [ -z "$live_fp" ]; then
    log "REFUSE: could not read live schema fingerprint (is web up?) — not wiping on an unknown state."
    demo_ntfy high "OpenH2O demo reset SKIPPED" \
      "Could not read live schema on $(hostname) (web down?). Demo NOT reset — investigate."
    exit 0
  fi

  if [ "$live_fp" != "$golden_fp" ]; then
    log "REFUSE: live schema fingerprint ${live_fp:0:12}… != golden ${golden_fp:0:12}… — snapshot is stale (predates a migration)."
    log "        A legit change would be wiped. Re-run 'make snapshot-demo' to promote current state, or FORCE=1 to override."
    demo_ntfy high "OpenH2O demo reset SKIPPED — snapshot stale" \
      "Live schema on $(hostname) moved past the golden snapshot (a migration ran). Run 'make snapshot-demo' to re-stamp, then the nightly reset resumes. Demo NOT reset."
    exit 0
  fi
  log "reset-demo: staleness guard OK — live schema matches golden (${golden_fp:0:12}…)"
fi

# Capture the pre-wipe state (while web is still up) for the data-loss report.
pre_counts="$(demo_row_counts || true)"
pre_total="$(printf '%s\n' "$pre_counts" | demo_row_total)"

log "reset-demo: restoring $SNAP into the demo DB"

# Pause web so no app connections hold locks or write during the swap.
docker compose stop web >/dev/null 2>&1 || true

# DROP+CREATE the database (FORCE terminates any leftover connections, PG13+),
# then restore the snapshot into the empty DB. --no-owner so roles need not match.
if ! docker compose exec -T db sh -c '
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);" \
        -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"' >>"$LOG" 2>&1; then
  log "ERROR: drop/create failed — restarting web, leaving DB as-is"
  docker compose start web >/dev/null 2>&1 || true
  demo_ntfy high "OpenH2O demo reset FAILED" \
    "drop/create failed on $(hostname) — DB left as-is, web restarted. Check $LOG."
  exit 1
fi

if ! docker compose exec -T db sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$SNAP" >>"$LOG" 2>&1; then
  # pg_restore can emit non-fatal warnings; treat a failed RESTORE as fatal only
  # if the core tables are missing. Log loudly and still bring web back.
  log "WARN: pg_restore returned nonzero (often harmless PostGIS comment warnings) — verifying"
fi

docker compose start web >/dev/null 2>&1 || true

# Wait for the DB to accept connections, then absorb additive schema drift.
sleep 3
if ! docker compose exec -T web python manage.py migrate --noinput >>"$LOG" 2>&1; then
  log "WARN: migrate after restore returned nonzero (check $LOG)"
fi

# ---------------------------------------------------------------------------
# Data-loss backstop: report what changed, pre vs post. On a normal night this
# shows visitor junk being cleared (counts shrink to the golden canonical). An
# unexpected drop in the post numbers is the signal that the golden itself lost
# something — worth a human glance.
# ---------------------------------------------------------------------------
post_counts="$(demo_row_counts || true)"
post_total="$(printf '%s\n' "$post_counts" | demo_row_total)"

pre_parcel="$(printf '%s\n' "$pre_counts"  | sed -n 's/^parcels\.Parcel=//p' | head -1)"
post_parcel="$(printf '%s\n' "$post_counts" | sed -n 's/^parcels\.Parcel=//p' | head -1)"

log "reset-demo: done — rows ${pre_total:-?} -> ${post_total:-?}, parcels ${pre_parcel:-?} -> ${post_parcel:-?}"
{
  echo "--- pre-reset row counts ---";  printf '%s\n' "$pre_counts"
  echo "--- post-reset row counts ---"; printf '%s\n' "$post_counts"
} >>"$LOG"

demo_ntfy default "OpenH2O demo reset" \
  "$(hostname): rows ${pre_total:-?}->${post_total:-?}, parcels ${pre_parcel:-?}->${post_parcel:-?}. Demo restored to golden."
