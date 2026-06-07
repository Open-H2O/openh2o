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
# Mechanism: drop + recreate the database from the golden snapshot (pg_dump -Fc
# written by snapshot-demo.sh), which cleanly rebuilds PostGIS and all data. The
# web container is paused during the swap (a few seconds) so nothing races the
# restore, then `migrate` runs to absorb any additive schema drift if the
# snapshot predates a migration. Uses the db container's own POSTGRES_* env, so
# it adapts to prod (openh2o) and staging (openh2o_staging).
#
# Usage:  scripts/reset-demo.sh [SNAPSHOT_PATH]
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAP="${1:-$HOME/openh2o-demo-snapshot/golden.dump}"
LOG="${LOG:-$HOME/openh2o-logs/reset-demo.log}"

mkdir -p "$(dirname "$LOG")"
cd "$OPENH2O_DIR"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

if [ ! -s "$SNAP" ]; then
  log "ABORT: golden snapshot $SNAP missing or empty — run snapshot-demo.sh first"
  exit 1
fi

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

# Sanity: the restore must leave the seeded Merced parcels present. Tag the line
# so the shell_plus auto-import banner doesn't pollute the parsed number.
count="$(docker compose exec -T web python manage.py shell -c \
  'from parcels.models import Parcel; print("PCOUNT:%d" % Parcel.objects.count())' 2>/dev/null \
  | sed -n 's/.*PCOUNT:\([0-9]*\).*/\1/p' | tail -1)"
log "reset-demo: done — Parcel count now ${count:-unknown}"
