#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Tests for scripts/release.sh. No network and no Docker: stand-ins for make, docker, git and
# curl go first on PATH, each logging its arguments to calls.log, and a temporary folder plays
# the checkout, the snapshot folder and the live page. scripts/smoke.sh is the real one; only
# curl underneath it is a stand-in.
#
# The stand-ins model what matters to a rollback: `git reset --hard` moves HEAD and, when it goes
# back to the previous commit, deletes the checkout's release.sh and smoke.sh (that commit has
# neither); `make deploy` prints its reset line, backs up and replaces golden.dump and
# golden.meta the way promote-golden.sh does, and puts a new image on the web container; `docker
# compose up --no-build` runs whatever image the web tag names, and the page then shows that
# image's version.
#
# Run: bash tests/deploy/test_release.sh   (bash 3.2 on a Mac, bash 5 on Linux)
set -uo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
SH=${BASH:-bash}
T=$(mktemp -d "${TMPDIR:-/tmp}/test-release.XXXXXX")
trap 'rm -rf "$T"' EXIT

SITE=http://release-test.invalid
TITLE='<title>Home - Open Water Accounting Platform'
PREV=1111111111111111111111111111111111111111
NEW=2222222222222222222222222222222222222222
PREV_DESC=v2.17-273-g11111111
NEW_DESC=v2.17-300-g22222222
MISSING=$SITE/smoke-drill-page-that-does-not-exist/

mkdir -p "$T/bin"

cat > "$T/bin/make" <<'EOF'
#!/usr/bin/env bash
echo "make $*" >> "$S/calls.log"
mode=$(cat "$S/make_mode")
if [ "$mode" = refuse ]; then
  echo "  REFUSING to deploy: its tests run did not pass (ci_gate exit 1)."
  exit 2
fi
if [ "$mode" = guard_refuse ]; then
  echo "  If it had run here it would have thrown away every local change in this"
  echo "  checkout (git reset --hard), rebuilt the canned demonstration database, and"
  exit 2
fi
echo 'sha=$(cat .deploy-verified-sha) && test -n "$sha" && git reset --hard "$sha"'
git reset --hard "$(cat "$S/new_sha")"
if [ "$mode" = fail_before_promote ]; then
  echo "promote-golden: REFUSED: the candidate did not pass the promotion gates"
  exit 2
fi
if [ "$mode" != no_backup ]; then
  cp -p "$SNAP/golden.dump" "$SNAP/golden.dump.bak-pre-new-20261017"
  cp -p "$SNAP/golden.meta" "$SNAP/golden.meta.bak-pre-new-20261017"
fi
echo "new golden" > "$SNAP/golden.dump"
echo "migration_fingerprint=new" > "$SNAP/golden.meta"
if [ "$mode" = fail_after_promote ]; then
  echo "reset-demo: ERROR: drop/create failed"
  exit 2
fi
echo sha256:new > "$S/container_image"
echo sha256:new > "$S/tag_openh2o-web_latest"
if [ "$mode" = bad_page ] || [ "$mode" = no_backup ]; then
  printf '%s</title>\n<p>Server Error</p>\n' "$TITLE" > "$S/live.html"
else
  printf '%s</title>\n<footer>%s</footer>\n' "$TITLE" "$(cat "$S/describe_$(cat "$S/new_sha")")" > "$S/live.html"
fi
echo "Deployed $(cat "$S/describe_$(cat "$S/new_sha")")."
EOF

cat > "$T/bin/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >> "$S/calls.log"
case $1 in
  rev-parse) cat "$S/head" ;;
  describe) cat "$S/describe_$(cat "$S/head")" ;;
  reset)
    echo "$3" > "$S/head"
    echo "HEAD is now at $(printf '%s' "$3" | cut -c1-8)"
    # The previous commit carries neither script.
    [ "$3" = "$(cat "$S/prev_sha")" ] && rm -f "$CO/scripts/release.sh" "$CO/scripts/smoke.sh"
    ;;
esac
exit 0
EOF

cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $* APP_VERSION=${APP_VERSION-unset}" >> "$S/calls.log"
key() { printf '%s' "$1" | tr ':/' '__'; }
if [ "$1" = tag ]; then
  case $2 in sha256:*) img=$2 ;; *) img=$(cat "$S/tag_$(key "$2")") ;; esac
  echo "$img" > "$S/tag_$(key "$3")"
  exit 0
fi
[ "$1" = compose ] || exit 0
shift
case $1 in
  images)
    if [ -f "$S/web_down" ]; then echo '[]'; exit 0; fi
    printf '[{"ID":"%s","ContainerName":"openh2o-web-1","Repository":"openh2o-web","Tag":"latest","Platform":"linux/amd64"}]\n' "$(cat "$S/container_image")"
    ;;
  up)
    case " $* " in *" --build "*) exit 0 ;; esac
    img=$(cat "$S/tag_openh2o-web_latest")
    echo "$img" > "$S/container_image"
    if [ -f "$S/rollback_page_bad" ]; then
      printf '%s</title>\n' "$TITLE" > "$S/live.html"
    else
      printf '%s</title>\n<footer>%s</footer>\n' "$TITLE" "$(cat "$S/imgver_$(key "$img")")" > "$S/live.html"
    fi
    ;;
esac
exit 0
EOF

cat > "$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/null url=""
while [ $# -gt 0 ]; do
  case $1 in
    -o) out=$2; shift 2 ;;
    -w|--max-time|--proto) shift 2 ;;
    --) url=$2; shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
echo "curl $url" >> "$S/calls.log"
if [ "$url" = "$SITE/" ]; then
  cat "$S/live.html" > "$out"; printf 200
else
  printf 'Not Found' > "$out"; printf 404
fi
EOF
chmod +x "$T/bin/"*

# A fresh world per case: the checkout at PREV with this repository's release.sh and smoke.sh,
# the old golden and one older backup, the old image on the web container, the old page live.
setup() {
  export S="$T/case$1/state" CO="$T/case$1/co" SNAP="$T/case$1/snap" SITE TITLE
  mkdir -p "$S" "$CO/scripts" "$SNAP" "$T/case$1/logs"
  cp "$REPO/scripts/release.sh" "$REPO/scripts/smoke.sh" "$CO/scripts/" 2>/dev/null
  : > "$CO/.demo-host"
  cat > "$CO/scripts/reset-demo.sh" <<'EOF'
echo "reset-demo FORCE=${FORCE:-0} golden=$(cat "$SNAP/golden.dump") meta=$(cat "$SNAP/golden.meta")" >> "$S/calls.log"
EOF
  : > "$S/calls.log"
  echo ok > "$S/make_mode"
  echo "$PREV" > "$S/head"; echo "$PREV" > "$S/prev_sha"; echo "$NEW" > "$S/new_sha"
  echo "$PREV_DESC" > "$S/describe_$PREV"; echo "$NEW_DESC" > "$S/describe_$NEW"
  echo sha256:old > "$S/container_image"; echo sha256:old > "$S/tag_openh2o-web_latest"
  echo "$PREV_DESC" > "$S/imgver_sha256_old"; echo "$NEW_DESC" > "$S/imgver_sha256_new"
  printf '%s</title>\n<footer>%s</footer>\n' "$TITLE" "$PREV_DESC" > "$S/live.html"
  echo "old golden" > "$SNAP/golden.dump"
  echo "migration_fingerprint=old" > "$SNAP/golden.meta"
  echo "older golden" > "$SNAP/golden.dump.bak-pre-older-20261012"
  echo "migration_fingerprint=older" > "$SNAP/golden.meta.bak-pre-older-20261012"
  LOGS="$T/case$1/logs"
}

pass=0 fail=0
OUT="" RC=0
run() {
  OUT=$(cd "$CO" && PATH="$T/bin:$PATH" OPENH2O_SNAPSHOT_DIR="$SNAP" RELEASE_SITE="$SITE" \
        RELEASE_LOG_DIR="$LOGS" RELEASE_SMOKE_TRIES=1 RELEASE_SMOKE_WAIT=0 \
        "$SH" scripts/release.sh "$@" 2>&1)
  RC=$?
}
ok()  { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; echo "     exit $RC, output: $(printf '%s' "$OUT" | tail -c 700)"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
called()     { grep -qF -- "$1" "$S/calls.log"; }
not_called() { ! grep -qF -- "$1" "$S/calls.log"; }
says()       { case $OUT in *"$1"*) return 0 ;; esac; return 1; }
is() { [ "$(cat "$1")" = "$2" ]; }

# Each check that reads the end state also asks that make deploy ran, so none passes when
# release.sh is missing or stops early.

# (1) make deploy refuses before its reset: release.sh exits 1 and nothing else changes.
setup 1; echo refuse > "$S/make_mode"; run REF=$NEW
check "1 a refusal before the reset exits 1" '[ $RC = 1 ]'
check "1 no reset, no retag, no up" 'called "make deploy REF=$NEW" && not_called "git reset" && not_called "openh2o-web:previous openh2o-web:latest" && not_called "compose up"'
check "1 golden untouched" 'called "make deploy REF=$NEW" && is "$SNAP/golden.dump" "old golden"'

# (2) a good deploy: exit 0 and no rollback.
setup 2; run REF=$NEW
check "2 a good deploy exits 0" '[ $RC = 0 ]'
check "2 the running image is kept as :previous first" 'called "docker tag sha256:old openh2o-web:previous"'
check "2 make deploy gets the ref" 'called "make deploy REF=$NEW"'
check "2 no rollback" 'called "make deploy REF=$NEW" && not_called "git reset --hard $PREV" && not_called "openh2o-web:previous openh2o-web:latest" && not_called "reset-demo"'
check "2 the new golden stays" 'is "$SNAP/golden.dump" "new golden"'
check "2 the release log records exit=0" 'grep -q "exit=0" "$LOGS"/openh2o-release-*.log'

# (3) the page lacks the new version: the rollback puts back code, image, golden and database.
setup 3; echo bad_page > "$S/make_mode"; run REF=$NEW
check "3 a missing version exits 5" '[ $RC = 5 ]'
check "3 the checkout goes back" 'called "git reset --hard $PREV"'
check "3 the previous image is retagged" 'called "docker tag openh2o-web:previous openh2o-web:latest"'
check "3 up --no-build with the previous version" 'called "docker compose up -d --no-build APP_VERSION=$PREV_DESC"'
check "3 the web container runs the previous image" 'called "make deploy REF=$NEW" && is "$S/container_image" sha256:old'
check "3 golden.dump and golden.meta are this run's backups" 'called "make deploy REF=$NEW" && is "$SNAP/golden.dump" "old golden" && is "$SNAP/golden.meta" "migration_fingerprint=old"'
check "3 the database is reset from the restored golden" 'called "reset-demo FORCE=1 golden=old golden meta=migration_fingerprint=old"'
check "3 every backup is kept" '[ -f "$SNAP/golden.dump.bak-pre-new-20261017" ] && is "$SNAP/golden.dump.bak-pre-older-20261012" "older golden"'
check "3 the previous version is smoke-tested after" 'says "smoke: PASS $SITE/" && says "$PREV_DESC"'
check "3 the release log records exit=5" 'grep -q "exit=5" "$LOGS"/openh2o-release-*.log'

# (4) as 3, but the page is still wrong after the rollback: exit 6.
setup 4; echo bad_page > "$S/make_mode"; : > "$S/rollback_page_bad"; run REF=$NEW
check "4 a failed rollback smoke exits 6" '[ $RC = 6 ]'
check "4 the rollback still ran" 'called "docker tag openh2o-web:previous openh2o-web:latest"'

# (5) the drill flag adds the missing page, so a right page still rolls back.
setup 5; run REF=$NEW --drill-smoke-missing-page
check "5 the drill exits 5" '[ $RC = 5 ]'
check "5 the missing page is fetched" 'called "curl $MISSING"'
check "5 the smoke failure names it" 'says "smoke: FAIL $MISSING HTTP 404"'
check "5 the previous release is back" 'called "make deploy REF=$NEW" && is "$S/container_image" sha256:old && is "$SNAP/golden.dump" "old golden"'

# (6) make deploy fails after its reset (here after the promotion): the rollback runs.
setup 6; echo fail_after_promote > "$S/make_mode"; run REF=$NEW
check "6 a failure after the reset exits 5" '[ $RC = 5 ]'
check "6 the checkout and golden go back" 'called "git reset --hard $PREV" && is "$SNAP/golden.dump" "old golden"'

# (7) no promotion this run: golden.dump is left alone and the output says so.
setup 7; echo fail_before_promote > "$S/make_mode"; run REF=$NEW
check "7 exits 5" '[ $RC = 5 ]'
check "7 golden untouched and the database not reset" 'called "make deploy REF=$NEW" && is "$SNAP/golden.dump" "old golden" && not_called "reset-demo"'
check "7 says the golden was not replaced" 'says "golden.dump was not replaced by this run"'

# (8) bad arguments: exit 2 and make is never called.
for a in "" "REF=" "REF=$NEW REF=$PREV" "REF=$NEW --bogus" "$NEW"; do
  setup 8; run $a
  check "8 bad arguments '$a' exit 2" '[ $RC = 2 ] && not_called "make "'
done

# (9) not the demonstration host: exit 1 before anything.
setup 9; rm "$CO/.demo-host"; run REF=$NEW
check "9 no .demo-host exits 1" '[ $RC = 1 ] && not_called "make " && not_called "docker tag"'

# (10) the live page does not show the checkout's version, so there is no release to go back to.
setup 10; printf '%s</title>\n<footer>v0-other</footer>\n' "$TITLE" > "$S/live.html"; run REF=$NEW
check "10 an unverifiable live release exits 1" '[ $RC = 1 ] && not_called "make " && not_called "docker tag"'

# (11) the web container is not running: exit 1 before anything.
setup 11; : > "$S/web_down"; run REF=$NEW
check "11 no web container exits 1" '[ $RC = 1 ] && not_called "make " && not_called "docker tag"'

# (12) golden.dump changed but no backup from this run exists: the rollback cannot finish, exit 6.
setup 12; echo no_backup > "$S/make_mode"; run REF=$NEW
check "12 a replaced golden with no backup exits 6" '[ $RC = 6 ]'
check "12 says so" 'says "no backup of it from this run"'
check "12 the code and image still go back" 'called "git reset --hard $PREV" && is "$S/container_image" sha256:old'

# (13) a refusal whose text mentions git reset --hard (guard-demo-host's does) is still a refusal:
# only git's own "HEAD is now at" line means the reset ran.
setup 13; echo guard_refuse > "$S/make_mode"; run REF=$NEW
check "13 a refusal that names git reset --hard exits 1" '[ $RC = 1 ] && called "make deploy REF=$NEW"'
check "13 no rollback" 'called "make deploy REF=$NEW" && not_called "git reset" && not_called "compose up"'

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
