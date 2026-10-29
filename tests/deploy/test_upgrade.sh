#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Tests for scripts/upgrade.sh (`make upgrade`). No network, no Docker: stand-ins for git and
# docker go first on PATH and log each call to calls.log (docker calls with the APP_VERSION they
# were given), a stand-in backup.sh plays the backup, and a temporary folder plays the checkout.
# Files in the state folder steer the stand-ins:
#   status_out     what `git status --porcelain` prints (locally edited files)
#   incoming       the files the update changes (`git diff --name-only HEAD @{upstream}`)
#   caddy_changed  the Caddyfile differs between the old and new commit
#   ff_fail        git merge --ff-only fails
#   fetch_fail     git fetch fails
#   backup_fail    the backup exits 1
#   unhealthy      the web container never reports healthy
#   health_fail    run_health_checks exits 1
#   crontab        the installed schedule the stand-in `crontab` reads and writes (absent: none)
#
# Run: bash tests/deploy/test_upgrade.sh   (bash 3.2 on a Mac, bash 5 on Linux)
set -uo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
SH=${BASH:-bash}
T=$(mktemp -d "${TMPDIR:-/tmp}/test-upgrade.XXXXXX")
trap 'rm -rf "$T"' EXIT

OLD_V=v2.17-273-g1111111
NEW_V=v2.17-300-g2222222

mkdir -p "$T/bin"

cat > "$T/bin/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >> "$S/calls.log"
case $1 in
  fetch) [ -f "$S/fetch_fail" ] && exit 1 ;;
  rev-parse) if [ "$2" = --abbrev-ref ]; then echo origin/main; else cat "$S/head"; fi ;;
  status) cat "$S/status_out" ;;
  diff)
    case $2 in
      --name-only) cat "$S/incoming" ;;
      --quiet) [ -f "$S/caddy_changed" ] && exit 1; exit 0 ;;
    esac ;;
  describe) if [ "$(cat "$S/head")" = OLD ]; then echo "$OLD_V"; else echo "$NEW_V"; fi ;;
  merge)
    if [ -f "$S/ff_fail" ]; then echo "fatal: Not possible to fast-forward, aborting." >&2; exit 128; fi
    echo NEW > "$S/head" ;;
esac
exit 0
EOF

cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $(printf '%s ' "$@")APP_VERSION=${APP_VERSION-unset}" >> "$S/calls.log"
if [ "$1" = inspect ]; then
  if [ -f "$S/unhealthy" ]; then echo starting; else echo healthy; fi
  exit 0
fi
[ "$1" = compose ] || exit 0
shift
case $1 in
  ps) echo abc123 ;;
  logs) echo "web log line" ;;
  exec) echo "health: ok"; [ -f "$S/health_fail" ] && exit 1 ;;
esac
exit 0
EOF
# A stand-in crontab: `-l` prints the schedule file (exit 1 when there is none), `-` replaces it.
cat > "$T/bin/crontab" <<'EOF'
#!/usr/bin/env bash
echo "crontab $*" >> "$S/calls.log"
case $1 in
  -l) [ -f "$S/crontab" ] && cat "$S/crontab" || exit 1 ;;
  -) cat > "$S/crontab" ;;
esac
exit 0
EOF
chmod +x "$T/bin/"*

setup() {
  export S="$T/case$1/state" CO="$T/case$1/co" OLD_V NEW_V
  mkdir -p "$S" "$CO/scripts" "$CO/backups" "$T/case$1/logs"
  cp "$REPO/scripts/upgrade.sh" "$REPO/scripts/install-cron.sh" "$CO/scripts/"
  printf 'OPENH2O_DIR=/stale\n0 6 * * * cd $OPENH2O_DIR && fresh-job\n0 7 * * * new-job\n' > "$CO/crontab.txt"
  cat > "$CO/scripts/backup.sh" <<'EOS'
echo "backup.sh" >> "$S/calls.log"
[ -f "$S/backup_fail" ] && exit 1
echo '{ "dump_file": "openh2o-SAFETY.dump" }' > "$OPENH2O_DIR/backups/last-backup.json"
EOS
  : > "$S/calls.log"; : > "$S/status_out"; : > "$S/incoming"; echo OLD > "$S/head"
  LOGS="$T/case$1/logs"
}

pass=0 fail=0
OUT="" RC=0
run() {
  OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_DIR="$CO" OPENH2O_LOG_DIR="$LOGS" \
        UPGRADE_WAIT_TRIES=2 UPGRADE_WAIT_SECS=0 "$SH" scripts/upgrade.sh 2>&1)
  RC=$?
}
ok()  { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; echo "     exit $RC, output: $(printf '%s' "$OUT" | tail -c 700)"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
called()     { grep -qF -- "$1" "$S/calls.log"; }
not_called() { ! grep -qF -- "$1" "$S/calls.log"; }
says()       { case $OUT in *"$1"*) return 0 ;; esac; return 1; }
wrote_schedule() { grep -qx "crontab -" "$S/calls.log"; }
at() { grep -nF -- "$1" "$S/calls.log" | head -1 | cut -d: -f1; }

# (1) a good upgrade: order, version, summary.
setup 1; run
check "1 a good upgrade exits 0" '[ $RC = 0 ]'
check "1 order: fetch, backup, merge, build, health checks" '
  a=$(at "git fetch"); b=$(at backup.sh); c=$(at "git merge"); d=$(at "up -d --build"); e=$(at run_health_checks)
  [ "$a" -gt 0 ] && [ "$a" -lt "$b" ] && [ "$b" -lt "$c" ] && [ "$c" -lt "$d" ] && [ "$d" -lt "$e" ]'
check "1 the merge is a fast-forward only, to the fetched upstream" 'called "git merge --ff-only @{upstream}"'
check "1 up -d --build gets APP_VERSION set to the NEW describe (computed after the merge)" 'called "docker compose up -d --build APP_VERSION=$NEW_V"'
check "1 the describe has no --dirty" '! grep -qF -- "--dirty" "$S/calls.log" && ! grep -v "^ *#" "$REPO/scripts/upgrade.sh" | grep -q "describe.*--dirty"'
check "1 caddy is restarted after the build even when this update leaves the Caddyfile alone" 'called "docker compose restart caddy" && [ "$(at "up -d --build")" -lt "$(at "restart caddy")" ]'
check "1 it prints old version, new version and the backup file" 'says "Old version: $OLD_V" && says "New version: $NEW_V" && says "backups/openh2o-SAFETY.dump"'

# (2) a failed backup stops before the merge and the build.
setup 2; : > "$S/backup_fail"; run
check "2 a failed backup exits 1 with the plan's wording" '[ $RC = 1 ] && says "Upgrade stopped: the backup failed. Nothing was changed."'
check "2 no merge, no build" 'called backup.sh && not_called "git merge" && not_called "up -d --build"'

# (3a) a local edit to a file the update changes stops before the backup and names the file.
setup 3; printf ' M Caddyfile\n' > "$S/status_out"; printf 'Caddyfile\ncore/models.py\n' > "$S/incoming"; run
check "3a exits 1 and names the file, with the message shape" '[ $RC = 1 ] && says "Upgrade stopped: this update changes Caddyfile, which has local edits on this server. Nothing was changed." && says "git checkout -- Caddyfile" && says "then put your edits back"'
check "3a stops before the backup, the merge and the build" 'not_called backup.sh && not_called "git merge" && not_called "docker"'
setup 4; printf ' M crontab.txt\n' > "$S/status_out"; printf 'crontab.txt\n' > "$S/incoming"; run
check "3a crontab.txt gets the extra sentence" '[ $RC = 1 ] && says "The installed schedule is a copy, so crontab.txt'"'"'s edits are already in effect and can be discarded."'
setup 5; printf ' M Caddyfile\n' > "$S/status_out"; printf 'Caddyfile\n' > "$S/incoming"; run
check "3a a non-crontab file does not get the crontab sentence" '[ $RC = 1 ] && ! says "installed schedule"'

# (3b) a local edit to a file the update does not change is kept and the upgrade goes on.
setup 6; printf ' M Caddyfile\n M crontab.txt\n' > "$S/status_out"; printf 'core/models.py\n' > "$S/incoming"; run
check "3b the upgrade proceeds" '[ $RC = 0 ] && called backup.sh && called "git merge" && called "up -d --build"'
check "3b it says which edits it kept" 'says "Keeping your local edits to: Caddyfile crontab.txt"'
check "3b it never discards anything (no checkout, reset or stash)" 'not_called "git checkout" && not_called "git reset" && not_called "git stash"'

# (4) a branch that cannot fast-forward stops before the build.
setup 7; : > "$S/ff_fail"; run
check "4 a non-fast-forward exits 1, after the backup, before any build" '[ $RC = 1 ] && called backup.sh && called "git merge" && not_called "docker" && says "cannot fast-forward"'

# (5) caddy restarts when the Caddyfile changed (as it does every time; see case 1).
setup 8; : > "$S/caddy_changed"; run
check "5 a changed Caddyfile restarts caddy after the build" '[ $RC = 0 ] && called "docker compose restart caddy" && [ "$(at "up -d --build")" -lt "$(at "restart caddy")" ]'

# (6) a health timeout exits non-zero, shows the log and names the backup.
setup 9; : > "$S/unhealthy"; run
check "6 a health timeout exits 1" '[ $RC = 1 ] && says "did not become healthy"'
check "6 it shows the web log and names the old version and the backup" 'says "web log line" && says "before the upgrade was v2.17-273-g1111111" && says "backups/openh2o-SAFETY.dump"'
check "6 it does not go on to the health checks" 'not_called run_health_checks'

# (7) run_health_checks failing is an error too.
setup 10; : > "$S/health_fail"; run
check "7 a failing run_health_checks exits 1 but still prints the versions" '[ $RC = 1 ] && says "New version: $NEW_V"'

# (8) fetch failure and a restore in progress stop at once.
setup 11; : > "$S/fetch_fail"; run
check "8 a failed fetch stops before the backup" '[ $RC = 1 ] && not_called backup.sh && says "Nothing was changed"'
setup 12; : > "$CO/.restore-in-progress"; run
check "8 a restore in progress stops everything" '[ $RC = 1 ] && [ ! -s "$S/calls.log" ]'

# (10) the installed schedule is refreshed after a good upgrade.
BEGIN='# BEGIN OpenH2O schedule (written by make install-cron, replaced each time it runs)'
END='# END OpenH2O schedule'
setup 13
printf 'MAILTO=me@example.org\n%s\nOPENH2O_DIR=/old/path\nOPENH2O_LOG_DIR=%s/custom-logs\n0 6 * * * old-job\n%s\n' \
  "$BEGIN" "$T" "$END" > "$S/crontab"
run
check "10 a schedule with the marker is rewritten from crontab.txt after a good upgrade" '[ $RC = 0 ] && grep -qF "new-job" "$S/crontab" && ! grep -qF "old-job" "$S/crontab"'
check "10 it keeps the operator log folder and the lines outside the block" 'grep -qxF "OPENH2O_LOG_DIR=$T/custom-logs" "$S/crontab" && grep -qxF "MAILTO=me@example.org" "$S/crontab" && grep -qxF "OPENH2O_DIR=$(cd "$CO" && pwd)" "$S/crontab"'
check "10 it runs after the health checks" '[ "$(at run_health_checks)" -lt "$(grep -nx "crontab -" "$S/calls.log" | head -1 | cut -d: -f1)" ]'
check "10 the block appears once" '[ "$(grep -cF "# BEGIN OpenH2O schedule" "$S/crontab")" = 1 ]'

setup 14
printf '0 6 * * * old-job\n' > "$S/crontab"
run
check "10 a schedule with no marker is left alone and the output says to run make install-cron" '[ $RC = 0 ] && says "make install-cron" && ! wrote_schedule && grep -qF "old-job" "$S/crontab"'

setup 15
printf '%s\nOPENH2O_DIR=/old/path\nOPENH2O_LOG_DIR=%s/custom-logs\n0 6 * * * old-job\n%s\n' "$BEGIN" "$T" "$END" > "$S/crontab"
: > "$S/unhealthy"; run
check "10 a failed upgrade does not touch the schedule" '[ $RC = 1 ] && grep -qF "old-job" "$S/crontab" && ! wrote_schedule'

# (9) make upgrade runs the script under a .production-lock, and make deploy is untouched.
if command -v make >/dev/null 2>&1; then
  P="$T/lock"; mkdir -p "$P"; cp "$REPO/Makefile" "$P/"; : > "$P/.production-lock"
  OUT=$(cd "$P" && make -n upgrade 2>&1); RC=$?
  check "9 make -n upgrade under .production-lock runs the script" '[ $RC = 0 ] && says "bash scripts/upgrade.sh" && ! says "REFUSING"'
  check "9 make deploy is still guarded by the demo-host check and is not make upgrade" 'grep -q "^deploy: guard-demo-host" "$REPO/Makefile" && ! grep -A3 "^upgrade:" "$REPO/Makefile" | grep -q "guard-"'
fi

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
