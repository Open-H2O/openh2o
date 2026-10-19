#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Restore an OpenH2O site from a backup made by scripts/backup.sh.
#
# THIS REPLACES EVERY RECORD ON THE SITE with the contents of the backup. It refuses to run
# without --yes, and it takes a safety backup of the current site first (so a mistaken restore
# can itself be undone) and stops if that backup fails.
#
# Usage:  scripts/restore.sh <dump file> [<media file>] --yes
#   e.g.  scripts/restore.sh backups/openh2o-20261019-012501.dump backups/media-20261019-012501.tar.gz --yes
#
# In order:
#   1. writes .restore-in-progress in the checkout. The scheduled sync (run-sync.sh) and backup
#      (backup.sh) skip while it exists, so nothing starts the website or dumps a half-built site
#      in the middle. It is removed when this script ends, on success and on failure alike.
#   2. runs scripts/backup.sh as the safety backup.
#   3. stops the web container, then drops and recreates the database from the db container,
#      using that container's own POSTGRES_USER and POSTGRES_DB (never names written here).
#      It connects to the `postgres` maintenance database to do this, ends other connections
#      first, and creates the new database from template0. A restore into the database the
#      postgis image makes at first start fails ("schema tiger already exists"), because that
#      image installs the postgis and tiger extensions into it; the dump creates its own.
#   4. pg_restore --no-owner --exit-on-error, reading the dump from standard input, so the
#      file never has to be copied into the container.
#   5. Uploaded files, when a media file is given: the web container is stopped, so a one-off
#      `docker compose run --rm --no-deps --entrypoint sh web` mounts the same media volume,
#      empties /app/media and unpacks the archive into it. (The normal entrypoint would
#      migrate against the database first, so it is bypassed.)
#   6. starts the web container again. Its entrypoint migrates, so a backup made on an older
#      version is brought up to this version. Waits until web reports healthy, runs
#      run_health_checks and prints every table's row count.
#
# Environment (all optional):
#   OPENH2O_DIR            the checkout (default: the folder above scripts/)
#   OPENH2O_LOG_DIR        where restore.log goes (default: backups/logs in the checkout)
#   RESTORE_WAIT_TRIES     how many health polls to make (default 90)
#   RESTORE_WAIT_SECS      seconds between polls (default 5)
set -uo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_DIR="${OPENH2O_LOG_DIR:-$OPENH2O_DIR/backups/logs}"
TRIES="${RESTORE_WAIT_TRIES:-90}"
SECS="${RESTORE_WAIT_SECS:-5}"

usage() {
  echo "Usage: scripts/restore.sh <dump file> [<media file>] --yes   (replaces every record on the site)" >&2
  exit 2
}

dump="" media="" yes=0
for arg in "$@"; do
  case $arg in
    --yes) yes=1 ;;
    -*) usage ;;
    *) if [ -z "$dump" ]; then dump=$arg; elif [ -z "$media" ]; then media=$arg; else usage; fi ;;
  esac
done
[ -n "$dump" ] || usage
if [ ! -f "$dump" ] || [ ! -r "$dump" ]; then
  echo "Restore refused: cannot read the dump file $dump" >&2
  exit 2
fi
if [ -n "$media" ] && { [ ! -f "$media" ] || [ ! -r "$media" ]; }; then
  echo "Restore refused: cannot read the media file $media" >&2
  exit 2
fi
if [ "$yes" != 1 ]; then
  echo "Restore refused: this replaces every record on the site with the contents of $dump." >&2
  echo "Run it again with --yes to go ahead." >&2
  exit 2
fi
# Absolute paths, since the script changes folder.
case $dump in /*) ;; *) dump="$PWD/$dump" ;; esac
case $media in ''|/*) ;; *) media="$PWD/$media" ;; esac

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/restore.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" | tee -a "$LOG"; }

cd "$OPENH2O_DIR" 2>/dev/null || { echo "Restore refused: cannot cd to $OPENH2O_DIR" >&2; exit 1; }

if [ -f .restore-in-progress ]; then
  echo "Restore refused: .restore-in-progress already exists in $OPENH2O_DIR." >&2
  echo "Another restore is running, or an earlier one was cut off. If none is running, delete the file and try again." >&2
  exit 1
fi

# From here on the marker exists, and it is removed however this script ends.
: > .restore-in-progress
ROOT=$PWD
trap 'rm -f "$ROOT/.restore-in-progress"' EXIT

stopped() {  # stopped <reason>: say what state the site is left in
  log "RESTORE FAILED: $1"
  [ -n "${safety:-}" ] && log "The site's records before this restore are in backups/$safety; restore that file to undo."
  [ "${web_stopped:-0}" = 1 ] && log "The web container may be stopped. Fix the problem above, then run: docker compose start web"
  exit 1
}

log ">>> restore from $dump${media:+ and $media}"

# Safety backup of the site as it is now.
log "taking a safety backup first"
OPENH2O_IGNORE_RESTORE_MARKER=1 bash "$OPENH2O_DIR/scripts/backup.sh" >>"$LOG" 2>&1 \
  || { log "Restore stopped: the safety backup failed. Nothing was changed."; exit 1; }
safety=$(sed -n 's/.*"dump_file": *"\([^"]*\)".*/\1/p' backups/last-backup.json 2>/dev/null)
log "safety backup: backups/${safety:-unknown}"

# Checked again: nothing may have removed the file between the start and now.
[ -r "$dump" ] || { log "Restore stopped: $dump is no longer readable. Nothing was changed."; exit 1; }
[ -z "$media" ] || [ -r "$media" ] || { log "Restore stopped: $media is no longer readable. Nothing was changed."; exit 1; }

web_stopped=1
docker compose stop web >>"$LOG" 2>&1 || stopped "could not stop the web container"

RECREATE='set -e
psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -At -c "select pg_terminate_backend(pid) from pg_stat_activity where datname = '"'"'$POSTGRES_DB'"'"' and pid <> pg_backend_pid()" >/dev/null
dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
createdb -U "$POSTGRES_USER" -T template0 -O "$POSTGRES_USER" "$POSTGRES_DB"'
log "dropping and recreating the database"
docker compose exec -T db sh -c "$RECREATE" >>"$LOG" 2>&1 || stopped "could not recreate the database"

log "loading the dump"
docker compose exec -T db sh -c 'pg_restore --no-owner --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <"$dump" >>"$LOG" 2>&1 || stopped "pg_restore failed; the database is not complete"

if [ -n "$media" ]; then
  log "replacing the uploaded files"
  docker compose run --rm --no-deps -T --entrypoint sh web \
    -c 'mkdir -p /app/media && find /app/media -mindepth 1 -delete && tar xzf - -C /app' \
    <"$media" >>"$LOG" 2>&1 || stopped "could not unpack the uploaded files"
fi

log "starting the web container (it migrates an older backup up to this version)"
docker compose start web >>"$LOG" 2>&1 || stopped "could not start the web container"
web_stopped=0

healthy=0 i=0
while [ "$i" -lt "$TRIES" ]; do
  cid=$(docker compose ps -q web 2>/dev/null)
  state=$([ -n "$cid" ] && docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null)
  if [ "$state" = healthy ]; then healthy=1; break; fi
  i=$((i + 1))
  sleep "$SECS"
done
if [ "$healthy" != 1 ]; then
  docker compose logs --tail 50 web 2>&1 | tee -a "$LOG"
  stopped "the web container did not become healthy"
fi

rm -f .restore-in-progress

# Counted before the health checks, which write rows of their own, so these numbers are the
# restored backup's and can be compared with it table by table.
log "row counts, table by table"
docker compose exec -T db sh -c 'psql -At -F " " -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL' 2>&1 | tee -a "$LOG"
select table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1;
SQL

log "running the health checks"
health_out=$(docker compose exec -T web python manage.py run_health_checks 2>&1)
health_rc=$?
printf '%s\n' "$health_out" | tee -a "$LOG"

if [ "$health_rc" != 0 ]; then
  log "Restore finished, but run_health_checks reported a problem (exit $health_rc). Read its output above."
  exit 1
fi
log "<<< restore OK from $dump (safety backup: backups/${safety:-unknown})"
exit 0
