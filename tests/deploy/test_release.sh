#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Tests for scripts/release.sh. No network and no Docker: stand-ins for make, docker, git, curl
# and python3 go first on PATH, each logging its arguments to calls.log, and a temporary folder
# plays the checkout, the snapshot folder, the live page and GitHub's list of deploy-checks runs.
# scripts/smoke.sh and scripts/ci_gate.py are the real ones; only curl underneath smoke.sh is a
# stand-in, and python3 hands ci_gate.py the runs in runs.json instead of letting it ask GitHub.
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
OTHER=3333333333333333333333333333333333333333
FORK=4444444444444444444444444444444444444444
REAL_PY=$(command -v python3)

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
  rev-parse)
    if [ "$2" = --verify ]; then
      shift 2; [ "${1:-}" = --quiet ] && shift
      r=${1%"^{commit}"}
      case $r in ""|*[!0-9a-f]*) exit 1 ;; esac
      [ ${#r} = 40 ] || exit 1
      echo "$r"
    else
      cat "$S/head"
    fi
    ;;
  merge-base)
    # --is-ancestor <a> <b>: true when they are the same commit or the case says the candidate
    # is older than the live one; otherwise the common ancestor the case set.
    if [ "$2" = --is-ancestor ]; then [ "$3" = "$4" ] || [ -f "$S/older" ]; exit; fi
    cat "$S/merge_base"
    ;;
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
if [ "$1" = image ] && [ "$2" = inspect ]; then
  # The image's environment: the version it was built with, as the Dockerfile sets it.
  img=${*: -1}
  printf 'PATH=/usr/local/bin\nAPP_VERSION=%s\n' "$(cat "$S/imgver_$(key "$img")")"
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

# python3: a call of ci_gate.py --fetch gets the runs in runs.json on stdin instead of asking
# GitHub (or, with github_down, the refusal ci_gate prints when GitHub cannot be asked); every
# other call goes to the real python3.
printf '#!/usr/bin/env bash\nREAL=%s\n' "$REAL_PY" > "$T/bin/python3"
cat >> "$T/bin/python3" <<'EOF'
echo "python3 $*" >> "$S/calls.log"
case " $* " in
  *"/ci_gate.py "*" --fetch "*)
    if [ -f "$S/github_down" ]; then
      echo "ci_gate: REFUSED: could not ask GitHub (network error: no route to host)"
      exit 4
    fi
    args=() skip=0
    for a in "$@"; do
      if [ $skip = 1 ]; then skip=0; continue; fi
      case $a in --fetch) ;; --repo) skip=1 ;; *) args+=("$a") ;; esac
    done
    exec "$REAL" "${args[@]}" < "$S/runs.json"
    ;;
esac
exec "$REAL" "$@"
EOF
chmod +x "$T/bin/"*

# runs.json holds one deploy-checks run per argument triple <title> <status> <conclusion>,
# oldest first, with the field names GitHub's REST API uses.
runs() {
  local n=0 sep="" body="" c
  while [ $# -ge 3 ]; do
    n=$((n + 1))
    if [ -n "$3" ]; then c="\"$3\""; else c=null; fi
    body="$body$sep{\"id\":$n,\"display_title\":\"$1\",\"status\":\"$2\",\"conclusion\":$c,\"run_attempt\":1,\"created_at\":\"2026-11-22T10:0$n:00Z\",\"html_url\":\"https://example.invalid/runs/$n\",\"head_sha\":\"$FORK\"}"
    sep=,
    shift 3
  done
  printf '{"workflow_runs":[%s]}\n' "$body" > "$S/runs.json"
}

# A fresh world per case: the checkout at PREV with this repository's release.sh and smoke.sh,
# the old golden and one older backup, the old image on the web container, the old page live.
setup() {
  export S="$T/case$1/state" CO="$T/case$1/co" SNAP="$T/case$1/snap" SITE TITLE
  mkdir -p "$S" "$CO/scripts" "$SNAP" "$T/case$1/logs"
  cp "$REPO/scripts/release.sh" "$REPO/scripts/smoke.sh" "$REPO/scripts/ci_gate.py" "$CO/scripts/" 2>/dev/null
  : > "$CO/.demo-host"
  cat > "$CO/scripts/reset-demo.sh" <<'EOF'
echo "reset-demo FORCE=${FORCE:-0} golden=$(cat "$SNAP/golden.dump") meta=$(cat "$SNAP/golden.meta")" >> "$S/calls.log"
EOF
  : > "$S/calls.log"
  echo ok > "$S/make_mode"
  echo "$PREV" > "$S/head"; echo "$PREV" > "$S/prev_sha"; echo "$NEW" > "$S/new_sha"
  echo "$PREV" > "$S/merge_base"
  # The deploy checks passed for exactly this release: the candidate against the live commit.
  runs "deploy checks $NEW from $PREV" completed success
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

# (14) a tag added after the running image was built (v3.0 on 9797dd60, 2026-11-10): git describe
# names the commit by the tag while the image, and so the page, carry the version it was built
# with. The run recognises the release by the image's version and goes back to it with that version.
setup 14; echo v3.0 > "$S/describe_$PREV"; echo bad_page > "$S/make_mode"; run REF=$NEW
check "14 a later tag on the same commit still releases, and rolls back" '[ $RC = 5 ] && called "make deploy REF=$NEW"'
check "14 the rollback starts the image with the version it carries" 'called "docker compose up -d --no-build APP_VERSION=$PREV_DESC"'
check "14 says which version it went by" 'says "the running image carries $PREV_DESC"'
setup 14; echo v3.0 > "$S/describe_$PREV"; run REF=$NEW
check "14 and a good deploy exits 0" '[ $RC = 0 ]'

# (15) the running image carries the version of another commit: there is no release to recognise.
setup 15; echo v3.0 > "$S/describe_$PREV"; echo v2.17-1-g99999999 > "$S/imgver_sha256_old"
printf '%s</title>\n<footer>v2.17-1-g99999999</footer>\n' "$TITLE" > "$S/live.html"; run REF=$NEW
check "15 an image built from another commit exits 1" '[ $RC = 1 ] && not_called "make " && not_called "docker tag"'

# (16) to (25): before anything changes, the release asks GitHub for the newest deploy-checks run
# titled `deploy checks <candidate> from <live>` (from the common ancestor when the live commit is
# not on the candidate's line) and refuses unless it finished green. Nothing changed means make
# deploy never ran and the running image was not retagged.
nothing() { not_called "make " && not_called "docker tag" && is "$S/container_image" sha256:old; }

# (16) no run for the pair: refused, and it says how to start one.
setup 16; runs; run REF=$NEW
check "16 no deploy-checks run exits 1 with nothing changed" '[ $RC = 1 ] && called "python3 " && nothing'
check "16 says deploy.sh starts the missing run" 'says "deploy.sh"'

# (17) the run for the pair failed.
setup 17; runs "deploy checks $NEW from $PREV" completed failure; run REF=$NEW
check "17 a red deploy-checks run exits 1 with nothing changed" '[ $RC = 1 ] && called "python3 " && nothing'

# (18) the run for the pair is still running.
setup 18; runs "deploy checks $NEW from $PREV" in_progress ""; run REF=$NEW
check "18 a running deploy-checks run exits 1 with nothing changed" '[ $RC = 1 ] && called "python3 " && nothing'

# (19) GitHub cannot be asked: refused, never waved through.
setup 19; : > "$S/github_down"; run REF=$NEW
check "19 GitHub unreachable exits 1 with nothing changed" '[ $RC = 1 ] && called "python3 " && nothing'
check "19 says GitHub could not be asked" 'says "could not ask GitHub"'

# (20) a green run for exactly (candidate, live): the release goes on.
setup 20; run REF=$NEW
check "20 a green run for the pair releases" '[ $RC = 0 ] && called "make deploy REF=$NEW"'
check "20 it asked for exactly this pair" 'called "deploy checks $NEW from $PREV"'

# (21) a green run for the candidate from another base does not count.
setup 21; runs "deploy checks $NEW from $OTHER" completed success; run REF=$NEW
check "21 a green run from another base exits 1 with nothing changed" '[ $RC = 1 ] && called "python3 " && nothing'

# (22) the newest run for the pair decides: a red rerun after a green one refuses.
setup 22; runs "deploy checks $NEW from $PREV" completed success "deploy checks $NEW from $PREV" completed failure; run REF=$NEW
check "22 the newest run decides" '[ $RC = 1 ] && called "python3 " && nothing'

# (23) the live commit is not on the candidate's line: the pair is the candidate and the common
# ancestor, as deploy.sh asks it.
setup 23; echo "$FORK" > "$S/merge_base"; runs "deploy checks $NEW from $FORK" completed success; run REF=$NEW
check "23 the common ancestor is the base" '[ $RC = 0 ] && called "deploy checks $NEW from $FORK"'

# (24) the candidate is older than the live commit (going back): nothing new to check, as in
# deploy.sh, so GitHub is not asked.
setup 24; : > "$S/older"; runs; run REF=$NEW
check "24 an older candidate is not asked about" '[ $RC = 0 ] && called "make deploy REF=$NEW" && not_called "python3 "'

# (25) a REF that is not a commit here is refused before anything.
setup 25; run REF=no-such-commit
check "25 an unknown REF exits 1 with nothing changed" '[ $RC = 1 ] && nothing'

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
