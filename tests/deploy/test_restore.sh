#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Tests for scripts/restore.sh and the restore check in scripts/run-sync.sh. No Docker and no
# database: a stand-in for docker goes first on PATH and logs each call (with whether the
# .restore-in-progress marker existed at that moment) to calls.log, a stand-in backup.sh plays
# the safety backup, and a temporary folder plays the checkout. Files in the state folder steer
# the stand-ins:
#   backup_fail    the safety backup exits 1
#   restore_fail   pg_restore exits 1
#   health_fail    run_health_checks exits 1
#   unhealthy      the web container never reports healthy
#
# Run: bash tests/deploy/test_restore.sh   (bash 3.2 on a Mac, bash 5 on Linux)
set -uo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
SH=${BASH:-bash}
T=$(mktemp -d "${TMPDIR:-/tmp}/test-restore.XXXXXX")
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/bin"

cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
m=0; [ -f "$CO/.restore-in-progress" ] && m=1
echo "marker=$m docker $(printf '%s ' "$@" | tr '\n' ' ')" >> "$S/calls.log"
if [ "$1" = inspect ]; then
  if [ -f "$S/unhealthy" ]; then echo starting; else echo healthy; fi
  exit 0
fi
[ "$1" = compose ] || exit 0
shift
case $1 in
  ps) echo abc123 ;;
  logs) echo "web log line" ;;
  run) cat > /dev/null ;;
  exec)
    case " $* " in
      *" pg_restore "*) cat > /dev/null; [ -f "$S/restore_fail" ] && { echo "pg_restore: error: boom" >&2; exit 1; } ;;
      *" run_health_checks "*) echo "health: ok"; [ -f "$S/health_fail" ] && exit 1 ;;
      *" psql "*) echo "core_user 3" ;;
    esac ;;
esac
exit 0
EOF
chmod +x "$T/bin/docker"

setup() {
  export S="$T/case$1/state" CO="$T/case$1/co"
  mkdir -p "$S" "$CO/scripts" "$CO/backups" "$T/case$1/logs"
  cp "$REPO/scripts/restore.sh" "$REPO/scripts/run-sync.sh" "$CO/scripts/"
  # The stand-in safety backup: logs, then writes the record restore.sh reads.
  cat > "$CO/scripts/backup.sh" <<'EOS'
m=0; [ -f "$OPENH2O_DIR/.restore-in-progress" ] && m=1
echo "marker=$m backup.sh ignore=${OPENH2O_IGNORE_RESTORE_MARKER-unset}" >> "$S/calls.log"
[ -f "$S/backup_fail" ] && exit 1
echo '{ "dump_file": "openh2o-SAFETY.dump" }' > "$OPENH2O_DIR/backups/last-backup.json"
EOS
  : > "$S/calls.log"
  echo "PGDMP" > "$T/case$1/site.dump"
  echo "media" > "$T/case$1/media.tar.gz"
  DUMP="$T/case$1/site.dump" MEDIA="$T/case$1/media.tar.gz" LOGS="$T/case$1/logs"
}

pass=0 fail=0
OUT="" RC=0
run() {
  OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_DIR="$CO" OPENH2O_LOG_DIR="$LOGS" \
        RESTORE_WAIT_TRIES=2 RESTORE_WAIT_SECS=0 "$SH" scripts/restore.sh "$@" 2>&1)
  RC=$?
}
ok()  { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; echo "     exit $RC, output: $(printf '%s' "$OUT" | tail -c 700)"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
called()     { grep -qF -- "$1" "$S/calls.log"; }
not_called() { ! grep -qF -- "$1" "$S/calls.log"; }
says()       { case $OUT in *"$1"*) return 0 ;; esac; return 1; }
# line number of the first call containing the text (0 when absent)
at() { grep -nF -- "$1" "$S/calls.log" | head -1 | cut -d: -f1; }
no_marker() { [ ! -f "$CO/.restore-in-progress" ]; }

# (1) refusals before anything happens: exit 2, no docker call, no marker.
setup 1; run
check "1 no arguments: one-line usage, exit 2" '[ $RC = 2 ] && says "Usage: scripts/restore.sh" && [ ! -s "$S/calls.log" ] && no_marker'
setup 2; run "$T/case2/missing.dump" --yes
check "2 a missing dump file is refused" '[ $RC = 2 ] && says "cannot read the dump file" && [ ! -s "$S/calls.log" ] && no_marker'
setup 3; run "$DUMP"
check "3 without --yes is refused and says what it would do" '[ $RC = 2 ] && says "replaces every record" && [ ! -s "$S/calls.log" ] && no_marker'
setup 4; run "$DUMP" "$T/case4/missing.tar.gz" --yes
check "4 a missing media file is refused" '[ $RC = 2 ] && says "cannot read the media file" && [ ! -s "$S/calls.log" ] && no_marker'

# (5) a good restore with media: order, marker during, gone after.
setup 5; run "$DUMP" "$MEDIA" --yes
check "5 a good restore exits 0" '[ $RC = 0 ] && says "restore OK"'
check "5 the marker is gone after success" 'no_marker'
check "5 the safety backup runs first, with the marker bypass" 'grep -qF "marker=1 backup.sh ignore=1" "$S/calls.log" && [ "$(at backup.sh)" = 1 ]'
check "5 order: backup, stop web, recreate db, pg_restore, media, start web, health" '
  a=$(at "backup.sh"); b=$(at "compose stop web"); c=$(at "dropdb"); d=$(at "pg_restore"); e=$(at "compose run"); f=$(at "compose start web"); g=$(at "run_health_checks")
  [ "$a" -gt 0 ] && [ "$a" -lt "$b" ] && [ "$b" -lt "$c" ] && [ "$c" -lt "$d" ] && [ "$d" -lt "$e" ] && [ "$e" -lt "$f" ] && [ "$f" -lt "$g" ]'
check "5 the marker existed during every step up to the row counts, and is gone from them on" 'g=$(at "psql -At -F"); ! head -n $((g - 1)) "$S/calls.log" | grep -qF "marker=0" && sed -n "${g}p" "$S/calls.log" | grep -qF "marker=0"'
check "5 the database is recreated from template0 through the postgres database, with the container user and name" 'grep -F dropdb "$S/calls.log" | grep -qF -- "-d postgres" && grep -F createdb "$S/calls.log" | grep -qF -- "-T template0" && grep -F createdb "$S/calls.log" | grep -qF "\$POSTGRES_USER" && grep -F createdb "$S/calls.log" | grep -qF "\$POSTGRES_DB"'
check "5 pg_restore uses --no-owner --exit-on-error" 'grep -F "pg_restore" "$S/calls.log" | grep -qF -- "--no-owner --exit-on-error"'
check "5 the media unpack is a one-off with no dependencies and the sh entrypoint" 'grep -F "compose run" "$S/calls.log" | grep -qF -- "--rm --no-deps -T --entrypoint sh web"'
check "5 run_health_checks runs in the web container" 'grep -F run_health_checks "$S/calls.log" | grep -qF "compose exec -T web python manage.py run_health_checks"'
check "5 the row counts are printed" 'says "core_user 3"'
check "5 the counts come before the health checks, which write rows of their own" '[ "$(at "psql -At -F")" -lt "$(at run_health_checks)" ]'
check "5 no hard-coded database user or name in the script" '! grep -qE "(-U|-d) openh2o" "$REPO/scripts/restore.sh"'

# (6) no media file: no one-off run.
setup 6; run "$DUMP" --yes
check "6 without a media file the uploads are left alone" '[ $RC = 0 ] && not_called "compose run" && not_called "find /app/media"'

# (7) the safety backup fails: stop before touching anything.
setup 7; : > "$S/backup_fail"; run "$DUMP" "$MEDIA" --yes
check "7 a failed safety backup exits 1 and says nothing was changed" '[ $RC = 1 ] && says "Nothing was changed"'
check "7 no stop, no drop, no restore" 'not_called "compose stop" && not_called "dropdb" && not_called "pg_restore" && no_marker'

# (8) pg_restore fails: marker still removed, safety backup named, web not started.
setup 8; : > "$S/restore_fail"; run "$DUMP" "$MEDIA" --yes
check "8 a failed pg_restore exits 1" '[ $RC = 1 ] && says "RESTORE FAILED"'
check "8 the marker is gone after a failure" 'no_marker'
check "8 it names the safety backup and web is not started" 'says "backups/openh2o-SAFETY.dump" && not_called "compose start web" && says "docker compose start web"'

# (9) the website never gets healthy: failure, marker gone, log tail shown.
setup 9; : > "$S/unhealthy"; run "$DUMP" --yes
check "9 an unhealthy web exits 1, marker gone, log shown" '[ $RC = 1 ] && no_marker && says "web log line" && says "did not become healthy"'

# (10) the health checks report a problem: exit 1, marker gone, counts still printed.
setup 10; : > "$S/health_fail"; run "$DUMP" --yes
check "10 a failing run_health_checks exits 1 and still prints counts" '[ $RC = 1 ] && no_marker && says "core_user 3" && says "reported a problem"'

# (11) a marker already there: refuse and leave it alone.
setup 11; : > "$CO/.restore-in-progress"; run "$DUMP" --yes
check "11 an existing marker is refused and kept" '[ $RC = 1 ] && [ -f "$CO/.restore-in-progress" ] && [ ! -s "$S/calls.log" ]'

# run-sync.sh: skips while the marker exists, unchanged otherwise.
run_sync() {
  OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_DIR="$CO" OPENH2O_LOG_DIR="$LOGS" "$SH" scripts/run-sync.sh cdec usgs 2>&1)
  RC=$?
}
setup 12; : > "$CO/.restore-in-progress"; run_sync
check "12 run-sync exits 0 without syncing while the marker exists" '[ $RC = 0 ] && [ ! -s "$S/calls.log" ] && grep -q "restore in progress, sync skipped" "$LOGS/sync.log"'
setup 13; run_sync
EXPECT='marker=0 docker compose up -d
marker=0 docker compose exec -T web python manage.py sync_source cdec
marker=0 docker compose exec -T web python manage.py sync_source usgs'
check "13 with no marker run-sync makes exactly the calls it always made" '[ $RC = 0 ] && [ "$(sed "s/ *$//" "$S/calls.log")" = "$EXPECT" ]'

# backup.sh from the real repo agrees with the bypass restore.sh uses.
check "14 restore.sh sets the bypass backup.sh reads" 'grep -q "OPENH2O_IGNORE_RESTORE_MARKER=1" "$REPO/scripts/restore.sh" && grep -q "OPENH2O_IGNORE_RESTORE_MARKER" "$REPO/scripts/backup.sh"'

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
