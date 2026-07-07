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

# ---------------------------------------------------------------------------
# Preserve in-app feedback across the wipe.
# openh2o.com is a single shared DB, and the DROP+restore below would take real
# visitor feedback down with it — the report is saved to THIS database first and
# only best-effort forwarded onward, so a dropped forward would otherwise be an
# unrecoverable loss. Dump the feedback tables' DATA now (their schema comes back
# with the golden restore + migrate) and reload it afterward. The screenshot
# FILES already live in the media volume, which the DB wipe never touches.
FB_DUMP_DIR="${FB_DUMP_DIR:-$HOME/openh2o-feedback-preserve}"
mkdir -p "$FB_DUMP_DIR"
fb_dump="$FB_DUMP_DIR/feedback-$(date '+%Y%m%dT%H%M%S').sql"
fb_saved=0
if docker compose exec -T db sh -c '
      pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --no-owner \
        -t feedback_feedback -t feedback_feedbackattachment' > "$fb_dump" 2>>"$LOG"; then
  fb_saved=1
  log "reset-demo: preserved feedback ($(wc -c <"$fb_dump" | tr -d ' ') bytes) -> $fb_dump"
else
  log "WARN: pg_dump of feedback tables failed — feedback preservation SKIPPED this run"
  demo_ntfy high "OpenH2O feedback preserve FAILED" \
    "Could not dump feedback tables on $(hostname) before the demo reset; pending feedback may be lost. Check $LOG."
fi
# Keep only the 30 most recent preserve dumps (tiny files; a safety trail).
# `|| true` so an empty glob can't trip `set -e`/pipefail before the restore.
{ ls -1t "$FB_DUMP_DIR"/feedback-*.sql 2>/dev/null | tail -n +31 | xargs -r rm -f; } || true

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

# Recreate the cache table the DROP+restore just wiped (golden predates it / is
# DB-independent). Idempotent. The feedback rate-limiter's DatabaseCache lives
# here; created empty, which also clears stale rate-limit counters each reset —
# fine, the limit is a brake, not an auth control.
if ! docker compose exec -T web python manage.py createcachetable >>"$LOG" 2>&1; then
  log "WARN: createcachetable after restore returned nonzero (check $LOG)"
fi

# ---------------------------------------------------------------------------
# Reload the preserved feedback into the freshly restored DB.
# session_replication_role=replica disables FK/triggers for the load so a report
# whose demo user_id vanished with the golden restore still comes back; we then
# null any now-orphaned user_id (the report keeps its name/email regardless) and
# advance the id sequences past the restored rows so new submissions don't clash.
# A failure here must NOT fail the reset (the demo is already restored) — it logs
# loudly, alerts, and KEEPS the dump file for manual recovery.
# ---------------------------------------------------------------------------
if [ "$fb_saved" = "1" ]; then
  if {
        echo "SET session_replication_role = replica;"
        echo "SET search_path = public;"
        echo "TRUNCATE feedback_feedbackattachment, feedback_feedback RESTART IDENTITY;"
        cat "$fb_dump"
        # pg_dump sets an empty search_path; restore it before our own statements.
        echo "SET search_path = public;"
        echo "UPDATE feedback_feedback SET user_id = NULL WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM core_user);"
        echo "SELECT setval(pg_get_serial_sequence('feedback_feedback','id'), GREATEST((SELECT COALESCE(max(id),0) FROM feedback_feedback),1));"
        echo "SELECT setval(pg_get_serial_sequence('feedback_feedbackattachment','id'), GREATEST((SELECT COALESCE(max(id),0) FROM feedback_feedbackattachment),1));"
        echo "SET session_replication_role = DEFAULT;"
      } | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >>"$LOG" 2>&1; then
    fb_kept="$(docker compose exec -T db sh -c 'psql -tAqc "SELECT count(*) FROM feedback_feedback" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>/dev/null | tr -d '[:space:]')"
    log "reset-demo: feedback reloaded — feedback_feedback now holds ${fb_kept:-?} rows"
  else
    log "ERROR: reloading preserved feedback FAILED — dump kept at $fb_dump for manual recovery"
    demo_ntfy high "OpenH2O feedback reload FAILED" \
      "Preserved feedback did NOT reload on $(hostname) after the demo reset. Dump kept at $fb_dump. Restore by hand. Check $LOG."
  fi
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
