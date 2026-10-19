#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Tests for scripts/backup.sh. No Docker and no database: a stand-in for docker goes first on
# PATH and logs each call to calls.log, and a temporary folder plays the checkout. Files in the
# state folder steer the stand-in:
#   dump_fail      pg_dump exits 1
#   dump_empty     pg_dump succeeds and writes nothing
#   list_fail      pg_restore --list exits 1
#   media_fail     the tar in the web container exits 1
#   table_data     how many public TABLE DATA entries the dump lists (default 3)
#   base_tables    how many base tables the database has (default 3)
#   restore_marker not used here; restore.sh's own tests cover the marker
#
# Run: bash tests/deploy/test_backup.sh   (bash 3.2 on a Mac, bash 5 on Linux)
set -uo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
SH=${BASH:-bash}
T=$(mktemp -d "${TMPDIR:-/tmp}/test-backup.XXXXXX")
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/bin"

cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$S/calls.log"
[ "$1" = compose ] || exit 0
shift
[ "$1" = exec ] || exit 0
case " $* " in
  *" pg_dump "*)
    [ -f "$S/dump_fail" ] && { echo "pg_dump: error" >&2; exit 1; }
    [ -f "$S/dump_empty" ] && exit 0
    echo "PGDMP fake custom-format dump" ;;
  *" pg_restore --list "*)
    cat > /dev/null
    [ -f "$S/list_fail" ] && { echo "pg_restore: error: not a dump" >&2; exit 1; }
    n=$(cat "$S/table_data" 2>/dev/null || echo 3)
    echo "; Archive created"
    echo "1; 0 0 TABLE public some_table openh2o"
    i=0
    while [ "$i" -lt "$n" ]; do echo "$((100 + i)); 0 $((200 + i)) TABLE DATA public table_$i openh2o"; i=$((i + 1)); done
    echo "900; 0 901 TABLE DATA tiger geocode_settings openh2o"
    echo "901; 0 902 TABLE DATA topology layer openh2o" ;;
  *" psql "*)
    cat "$S/base_tables" 2>/dev/null || echo 3 ;;
  *" tar "*)
    [ -f "$S/media_fail" ] && { echo "tar: media: No such file" >&2; exit 1; }
    echo "fake media archive" ;;
esac
exit 0
EOF
chmod +x "$T/bin/docker"

# A fresh world per case: a checkout holding this repository's backup.sh, an empty state folder.
setup() {
  export S="$T/case$1/state" CO="$T/case$1/co"
  mkdir -p "$S" "$CO/scripts" "$T/case$1/logs"
  cp "$REPO/scripts/backup.sh" "$CO/scripts/"
  : > "$S/calls.log"
  LOGS="$T/case$1/logs"
}
# old <n>: n old backups, oldest first, stamps well before any real run.
old() {
  mkdir -p "$CO/backups"
  local i=1
  while [ "$i" -le "$1" ]; do
    printf -v st '2020010%d-120000' "$i"
    echo "old dump $i" > "$CO/backups/openh2o-$st.dump"
    echo "old media $i" > "$CO/backups/media-$st.tar.gz"
    i=$((i + 1))
  done
}

pass=0 fail=0
OUT="" RC=0
run() {
  OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_DIR="$CO" OPENH2O_LOG_DIR="$LOGS" \
        "$SH" scripts/backup.sh "$@" 2>&1)
  RC=$?
}
ok()  { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; echo "     exit $RC, output: $(printf '%s' "$OUT" | tail -c 700)"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
called()     { grep -qF -- "$1" "$S/calls.log"; }
count() { ls -1 "$CO/backups" 2>/dev/null | grep -cE "$1" || true; }
json() { sed -n "s/.*\"$1\": *\"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}\$/\1/p" "$CO/backups/last-backup.json"; }

# (1) success: a dump, a media file, a record with the counts, no partial files, exit 0.
setup 1; echo 5 > "$S/table_data"; echo 5 > "$S/base_tables"; run
check "1 a good run exits 0" '[ $RC = 0 ]'
check "1 one dump and one media file" '[ "$(count "^openh2o-[0-9]{8}-[0-9]{6}\.dump$")" = 1 ] && [ "$(count "^media-[0-9]{8}-[0-9]{6}\.tar\.gz$")" = 1 ]'
check "1 no partial files" '[ "$(count "partial")" = 0 ]'
check "1 last-backup.json carries the counts" '[ "$(json table_data_entries)" = 5 ] && [ "$(json base_tables)" = 5 ]'
check "1 last-backup.json names the files and their bytes" '[ "$(json dump_file)" = "$(ls "$CO/backups" | grep "\.dump$")" ] && [ "$(json media_file)" = "$(ls "$CO/backups" | grep "\.tar\.gz$")" ] && [ "$(json dump_bytes)" -gt 0 ] && [ "$(json media_bytes)" -gt 0 ]'
check "1 last-backup.json has an offset timestamp" 'grep -qE "\"finished_at\": \"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}[+-][0-9]{2}:[0-9]{2}\"" "$CO/backups/last-backup.json"'
check "1 no failure file" '[ ! -f "$CO/backups/last-backup-failure.json" ]'
check "1 tiger and topology entries are not counted" '[ "$(json table_data_entries)" = 5 ]'
check "1 the database user is read in the container, not written" '! grep -q "openh2o -d\|-U openh2o" "$CO/scripts/backup.sh"'

# (2) a failed pg_dump: no .dump, a failure file, non-zero, old backups and record untouched.
setup 2; old 3; echo '{"old":"record"}' > "$CO/backups/last-backup.json"; : > "$S/dump_fail"; run
check "2 a failed pg_dump exits 1" '[ $RC = 1 ]'
check "2 no new dump, no partial" '[ "$(count "openh2o-[0-9]{8}-[0-9]{6}\.dump$")" = 3 ] && [ "$(count "partial")" = 0 ]'
check "2 the failure file names the step" 'grep -q "\"step\": \"dump\"" "$CO/backups/last-backup-failure.json" && grep -q "\"failed_at\"" "$CO/backups/last-backup-failure.json"'
check "2 the old record and old backups are untouched" 'grep -q old "$CO/backups/last-backup.json" && [ "$(count "^media-")" = 3 ]'

# (3) an empty dump is a failure.
setup 3; : > "$S/dump_empty"; run
check "3 an empty dump exits 1 and leaves no dump" '[ $RC = 1 ] && [ "$(count "\.dump")" = 0 ] && [ -f "$CO/backups/last-backup-failure.json" ]'

# (4) a dump that cannot be listed fails.
setup 4; : > "$S/list_fail"; run
check "4 an unreadable dump exits 1" '[ $RC = 1 ]'
check "4 it leaves no dump and says read-back" '[ "$(count "\.dump")" = 0 ] && grep -q "\"step\": \"read-back\"" "$CO/backups/last-backup-failure.json"'

# (5) a dump listing fewer tables than the database has fails.
setup 5; old 2; echo 2 > "$S/table_data"; echo 4 > "$S/base_tables"; run
check "5 fewer entries than tables exits 1" '[ $RC = 1 ]'
check "5 no new dump, no media file, nothing old deleted" '[ "$(count "\.dump")" = 2 ] && [ "$(count "^media-")" = 2 ]'
check "5 the failure file says how many" 'grep -q "lists 2 tables with data but the database has 4" "$CO/backups/last-backup-failure.json"'

# (6) a media error fails and removes this run's dump too, so the record never points at half a pair.
setup 6; old 1; : > "$S/media_fail"; run
check "6 a tar error exits 1" '[ $RC = 1 ]'
check "6 this run left no dump or media file, the old pair stays" '[ "$(count "\.dump")" = 1 ] && [ "$(count "^media-")" = 1 ] && grep -q "\"step\": \"media\"" "$CO/backups/last-backup-failure.json"'

# (7) retention keeps exactly OPENH2O_BACKUP_KEEP of each, newest first.
setup 7; old 5; export OPENH2O_BACKUP_KEEP=3; run
unset OPENH2O_BACKUP_KEEP
check "7 exits 0" '[ $RC = 0 ]'
check "7 keeps exactly 3 dumps and 3 media files" '[ "$(count "^openh2o-.*\.dump$")" = 3 ] && [ "$(count "^media-.*\.tar\.gz$")" = 3 ]'
check "7 the new files and the two newest old ones stay" '[ -f "$CO/backups/openh2o-20200105-120000.dump" ] && [ -f "$CO/backups/openh2o-20200104-120000.dump" ] && [ ! -f "$CO/backups/openh2o-20200103-120000.dump" ] && [ ! -f "$CO/backups/openh2o-20200101-120000.dump" ]'
check "7 last-backup.json is never pruned" '[ -f "$CO/backups/last-backup.json" ]'

# (8) a good run removes an earlier failure file.
setup 8; mkdir -p "$CO/backups"; echo '{"failed_at":"x"}' > "$CO/backups/last-backup-failure.json"; run
check "8 a good run deletes the failure file" '[ $RC = 0 ] && [ ! -f "$CO/backups/last-backup-failure.json" ]'

# (9) a restore in progress: skipped, exit 0, nothing run; restore.sh's own backup bypasses it.
setup 9; : > "$CO/.restore-in-progress"; run
check "9 skipped while a restore runs" '[ $RC = 0 ] && [ ! -s "$S/calls.log" ] && [ "$(count "\.dump")" = 0 ] && grep -q "restore in progress, backup skipped" "$LOGS/backup.log"'
OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_DIR="$CO" OPENH2O_LOG_DIR="$LOGS" OPENH2O_IGNORE_RESTORE_MARKER=1 "$SH" scripts/backup.sh 2>&1); RC=$?
check "9 restore.sh's own safety backup still runs" '[ $RC = 0 ] && [ "$(count "\.dump")" = 1 ]'

# (10) the folder is ignored by git and by the image build. The image carries neither ignore
# file (nor .git), and the suite runs inside the image, so there the check is on the effect:
# the image holds no backups folder and no restore marker.
if [ -f "$REPO/.dockerignore" ]; then
  check "10 .gitignore keeps the dumps out, .dockerignore keeps backups/ out of the image" 'grep -qx "backups/\*" "$REPO/.gitignore" && grep -qx "backups/" "$REPO/.dockerignore"'
  check "10 the backups folder itself ships, so Docker never creates it owned by root" 'grep -qx "!backups/.gitkeep" "$REPO/.gitignore" && git -C "$REPO" ls-files --error-unmatch backups/.gitkeep >/dev/null 2>&1'
  check "10 the restore marker is in both too" 'grep -qx ".restore-in-progress" "$REPO/.gitignore" && grep -qx ".restore-in-progress" "$REPO/.dockerignore"'
else
  check "10 (inside the image) no backups folder and no restore marker were built in" '[ ! -e "$REPO/backups" ] && [ ! -e "$REPO/.restore-in-progress" ]'
fi
check "10 the shipped schedule has the backup line" 'grep -qE "^25 1 \* \* \* \\\$OPENH2O_DIR/scripts/backup\.sh\$" "$REPO/crontab.txt"'
check "10 the website gets the folder read-only" 'grep -qF -- "- ./backups:/backups:ro" "$REPO/docker-compose.yml"'

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
