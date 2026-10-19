#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Nightly backup for OpenH2O: the database and the uploaded files, checked by reading them back.
#
# What it writes, all in backups/ inside the checkout (a fixed folder, so this script, the
# schedule in crontab.txt and the read-only mount in docker-compose.yml cannot disagree):
#   openh2o-<stamp>.dump      the database, pg_dump custom format (-Fc)
#   media-<stamp>.tar.gz      the uploaded files (the web container's /app/media)
#   last-backup.json          what the last good run wrote and counted
#   last-backup-failure.json  why the last run failed (removed by the next good run)
# The record is a file beside the dumps and never a database row, because a restore (or the
# demonstration's nightly reset) would roll a database row back to the moment of the backup.
#
# The read-back check: the dump is listed with `pg_restore --list` and its TABLE DATA entries for
# the public schema are counted. A dump that cannot be listed, or that holds fewer entries than the
# database has base tables in its public schema, is not a backup and the run fails. Only the public
# schema is compared: the PostGIS image also carries tiger and topology tables that this site does
# not use. `pg_restore --list` reads a custom-format dump from standard input (checked on the
# postgis/postgis:16-3.4 image), so the file never has to be copied into the container.
#
# The database user and name are read inside the db container (POSTGRES_USER, POSTGRES_DB),
# never written here. A dump is written as .partial and renamed only when the whole run passes.
#
# Environment (all optional):
#   OPENH2O_DIR          the checkout (default: the folder above scripts/)
#   OPENH2O_LOG_DIR      where the log goes (default: backups/logs in the checkout)
#   OPENH2O_NTFY_URL     an ntfy topic URL; a failed backup posts there
#   OPENH2O_BACKUP_KEEP  how many dumps and media files to keep (default 14)
#   OPENH2O_IGNORE_RESTORE_MARKER=1  set by restore.sh for its own safety backup
#
# Usage:  backup.sh
set -uo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_DIR="${OPENH2O_LOG_DIR:-$OPENH2O_DIR/backups/logs}"
NTFY_URL="${OPENH2O_NTFY_URL:-}"
KEEP="${OPENH2O_BACKUP_KEEP:-14}"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/backup.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" >>"$LOG"; }
alert() {
  [ -n "$NTFY_URL" ] || return 0  # alerting disabled unless a topic URL is set
  curl -fsS -H "Title: OpenH2O backup" -H "Priority: high" -H "Tags: warning" \
    -d "$1" "$NTFY_URL" >/dev/null 2>&1 || true
}
# ISO 8601 with a colon in the offset (date prints +0000, JSON readers want +00:00).
iso_now() { date '+%Y-%m-%dT%H:%M:%S%z' | sed 's/\(..\)$/:\1/'; }
bytes() { wc -c <"$1" | tr -d ' '; }
json_text() { printf '%s' "$1" | tr '\n\t' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

cd "$OPENH2O_DIR" 2>/dev/null || {
  log "FATAL: cannot cd to $OPENH2O_DIR"
  alert "OpenH2O backup FATAL: cannot cd to $OPENH2O_DIR"
  exit 1
}

# A restore is replacing the database; a backup taken now would be of a half-built site.
if [ -f .restore-in-progress ] && [ "${OPENH2O_IGNORE_RESTORE_MARKER:-0}" != 1 ]; then
  log "restore in progress, backup skipped"
  exit 0
fi

mkdir -p backups || { log "FATAL: cannot make backups/"; exit 1; }

STAMP=$(date '+%Y%m%d-%H%M%S')
DUMP="openh2o-$STAMP.dump"
MEDIA="media-$STAMP.tar.gz"
# The files this run is writing, removed again if any step fails.
trap_files=("backups/$DUMP.partial" "backups/$DUMP" "backups/$MEDIA.partial" "backups/$MEDIA")

fail() {  # fail <step> <reason>
  local step=$1 reason=$2
  log "FAILED at $step: $reason"
  rm -f "${trap_files[@]}"
  printf '{\n  "failed_at": "%s",\n  "step": "%s",\n  "reason": "%s"\n}\n' \
    "$(iso_now)" "$(json_text "$step")" "$(json_text "$reason")" \
    >backups/last-backup-failure.json.tmp \
    && mv backups/last-backup-failure.json.tmp backups/last-backup-failure.json
  alert "OpenH2O backup FAILED at $step on $(hostname): $reason (see $LOG)"
  exit 1
}

log ">>> backup $STAMP"

# 1. The database, from inside the db container with its own user and database name.
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  >"backups/$DUMP.partial" 2>>"$LOG" \
  || fail "dump" "pg_dump failed (is the db container running?)"
[ -s "backups/$DUMP.partial" ] || fail "dump" "pg_dump wrote an empty file"

# 2. Read it back: list the dump and count the public tables it holds data for.
listing=$(docker compose exec -T db pg_restore --list <"backups/$DUMP.partial" 2>>"$LOG") \
  || fail "read-back" "pg_restore could not list the dump"
table_data=$(printf '%s\n' "$listing" | grep -c ' TABLE DATA public ' || true)

base_tables=$(docker compose exec -T db sh -c 'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from information_schema.tables where table_schema = '"'"'public'"'"' and table_type = '"'"'BASE TABLE'"'"'"' 2>>"$LOG") \
  || fail "read-back" "could not count the database's tables"
base_tables=$(printf '%s' "$base_tables" | tr -d '[:space:]')
case $base_tables in ''|*[!0-9]*) fail "read-back" "table count was not a number: $base_tables" ;; esac
case $table_data in ''|*[!0-9]*) fail "read-back" "dump entry count was not a number" ;; esac
if [ "$table_data" -lt "$base_tables" ]; then
  fail "read-back" "the dump lists $table_data tables with data but the database has $base_tables"
fi
mv "backups/$DUMP.partial" "backups/$DUMP" || fail "dump" "could not rename the dump"

# 3. The uploaded files. An empty media folder gives a small valid archive; a tar error fails.
docker compose exec -T web tar czf - -C /app media >"backups/$MEDIA.partial" 2>>"$LOG" \
  || fail "media" "tar of /app/media failed (is the web container running?)"
mv "backups/$MEDIA.partial" "backups/$MEDIA" || fail "media" "could not rename the media archive"

# 4. The record, written then moved so a reader never sees half a file.
printf '{\n  "finished_at": "%s",\n  "dump_file": "%s",\n  "dump_bytes": %s,\n  "table_data_entries": %s,\n  "base_tables": %s,\n  "media_file": "%s",\n  "media_bytes": %s\n}\n' \
  "$(iso_now)" "$DUMP" "$(bytes "backups/$DUMP")" "$table_data" "$base_tables" \
  "$MEDIA" "$(bytes "backups/$MEDIA")" >backups/last-backup.json.tmp \
  && mv backups/last-backup.json.tmp backups/last-backup.json \
  || fail "record" "could not write last-backup.json"
rm -f backups/last-backup-failure.json

# 5. Retention, only now that this backup is good. File names carry the stamp, so a reverse
# name sort is newest first.
prune() {  # prune <glob prefix> <suffix>
  ls -1 backups 2>/dev/null | grep -E "^$1-[0-9]{8}-[0-9]{6}$2\$" | sort -r \
    | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "backups/$old"; log "pruned $old"; done
}
prune openh2o '\.dump'
prune media '\.tar\.gz'

log "<<< backup OK: $DUMP ($table_data of $base_tables tables), $MEDIA"
exit 0
