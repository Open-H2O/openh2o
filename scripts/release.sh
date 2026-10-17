#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# release.sh REF=<commit> [--drill-smoke-missing-page]
#
# The demonstration host's release: `make deploy REF=<commit>`, then a smoke test of the live home
# page, and when that fails, the previous release put back in the same run. Run it in the
# demonstration host's checkout (the one carrying .demo-host). deploy.sh runs it on the server
# from origin/main; `make release REF=<commit>` runs it from the checkout. `make deploy` alone
# still works, and checks nothing after it ships.
#
# Before anything changes it records the checkout's commit and `git describe`, the web
# container's image (read from `docker compose images web`), the sha256 of golden.dump and
# golden.meta, and the snapshot folder's backups. It checks that the live page shows the
# checkout's version, so the release it would go back to is one it can recognise, and tags the
# running image <repository>:previous.
#
# After `make deploy` the smoke test asks the live home page for its title and for the new
# `git describe`. With --drill-smoke-missing-page it also asks for a page that does not exist,
# which can only fail: that is the drill that proves the rollback.
#
# The rollback, when the smoke test fails or make deploy fails after its reset (git printed
# "HEAD is now at"; a refusal's own text may name the command, so the command is not read):
#   1. git reset --hard <the previous commit>
#   2. docker tag <repository>:previous <repository>:<tag>, then
#      APP_VERSION=<previous describe> docker compose up -d --no-build. The image carries its own
#      version; passing the same one keeps compose's build argument in step with it.
#   3. If this run replaced golden.dump, this run's backups of golden.dump and golden.meta (found
#      by their sha256) are copied back over them and FORCE=1 scripts/reset-demo.sh restores the
#      live database from them, keeping feedback as it does every night. If it did not, both are
#      left alone, because the live database was never replaced either.
#   4. The smoke test again, for the previous version.
#
# Exit codes:
#   0  released: the live page shows the new version
#   1  refused, nothing changed: not the demonstration host, no web container, the live page does
#      not show the checkout's version, or make deploy stopped before its reset
#   2  bad arguments, or no smoke.sh beside this script
#   5  the new release failed and the previous one is back, its smoke test passing
#   6  the rollback did not finish, or its smoke test failed: read the release log
#
# Settings: RELEASE_SITE (default https://openh2o.com), OPENH2O_SNAPSHOT_DIR (read as
# promote-golden.sh reads it), RELEASE_LOG_DIR (default $HOME), RELEASE_SMOKE_TRIES and
# RELEASE_SMOKE_WAIT (smoke.sh's --tries and --wait, default 20 and 3).
#
# The script copies itself and smoke.sh to a temporary folder and runs from there, because
# `git reset --hard` rewrites the checkout under it, and the previous commit may carry neither.
#
# Runs on bash 3.2 and bash 5.
set -u

usage() {
  echo "release: usage: release.sh REF=<commit> [--drill-smoke-missing-page]${1:+ ($1)}"
  exit 2
}

ref="" drill=0
for a in "$@"; do
  case $a in
    REF=?*) [ -z "$ref" ] || usage "one REF only"; ref=${a#REF=} ;;
    --drill-smoke-missing-page) drill=1 ;;
    *) usage "unknown argument '$a'" ;;
  esac
done
[ -n "$ref" ] || usage "REF=<commit> is required"

here=$(cd "$(dirname "$0")" && pwd)
[ -f "$here/smoke.sh" ] || usage "no smoke.sh beside $0"

if [ -z "${RELEASE_SH_RUNNING:-}" ]; then
  {
    RELEASE_SH_RUNNING=$(mktemp -d "${TMPDIR:-/tmp}/release.XXXXXX") || exit 2
    cp "$0" "$RELEASE_SH_RUNNING/release.sh" && cp "$here/smoke.sh" "$RELEASE_SH_RUNNING/smoke.sh" || exit 2
    export RELEASE_SH_RUNNING
    "${BASH:-bash}" "$RELEASE_SH_RUNNING/release.sh" "$@"
    rc=$?
    rm -rf "$RELEASE_SH_RUNNING"
    exit $rc
  }
fi
SMOKE=$here/smoke.sh

site=${RELEASE_SITE:-https://openh2o.com}
site=${site%/}
home="$site/"
missing="$site/smoke-drill-page-that-does-not-exist/"
title='<title>Home - Open Water Accounting Platform'
tries=${RELEASE_SMOKE_TRIES:-20}
wait=${RELEASE_SMOKE_WAIT:-3}
checkout=$(pwd)
snapdir=${OPENH2O_SNAPSHOT_DIR:-$HOME/$(basename "$checkout")-demo-snapshot}
golden=$snapdir/golden.dump
meta=$snapdir/golden.meta
logdir=${RELEASE_LOG_DIR:-$HOME}
mkdir -p "$logdir" || usage "cannot write to $logdir"
log=$logdir/openh2o-release-$(date '+%Y%m%d-%H%M%S').log
mkout=$RELEASE_SH_RUNNING/make-deploy.out

say() { echo "release: $*" | tee -a "$log"; }
finish() { say "exit=$1"; exit "$1"; }
sum() {
  if [ ! -f "$1" ]; then echo none
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1
  fi
}
web_field() {  # ID, Repository or Tag of the web container's image
  docker compose images web --format json 2>/dev/null | sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p" | head -1
}
smoke() {
  "${BASH:-bash}" "$SMOKE" --tries "$tries" --wait "$wait" "$@" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
# This run's backup of a file: a golden.*.bak-pre-* name that was not there before and whose
# sha256 is the file's sha256 before the run.
this_runs_backup() {  # <dump|meta> <sha256 before>
  local f
  for f in $(ls -1 "$snapdir" 2>/dev/null | grep "^golden\.$1\.bak-pre-"); do
    case "
$backups_before
" in *"
$f
"*) continue ;; esac
    [ "$(sum "$snapdir/$f")" = "$2" ] && { echo "$snapdir/$f"; return 0; }
  done
  return 1
}
put_back() {  # <backup> <target> <sha256 it must have>
  cp -p "$1" "$2.restore.$$" && mv "$2.restore.$$" "$2" && [ "$(sum "$2")" = "$3" ]
}

say "release of REF=$ref$( [ $drill = 1 ] && echo ', drill: the smoke test also asks for a page that does not exist') in $checkout; log $log"

# --- before anything changes -------------------------------------------------------------------
[ -f .demo-host ] || { say "REFUSING: $checkout has no .demo-host, so make deploy would refuse too. Nothing changed."; finish 1; }
prev_head=$(git rev-parse HEAD) || { say "REFUSING: cannot read HEAD. Nothing changed."; finish 1; }
prev_desc=$(git describe --tags --always --dirty 2>/dev/null)
img_id=$(web_field ID)
img_repo=$(web_field Repository)
img_tag=$(web_field Tag)
if [ -z "$img_id" ] || [ -z "$img_repo" ] || [ -z "$img_tag" ]; then
  say "REFUSING: no running web container to go back to (docker compose images web). Nothing changed."
  finish 1
fi
golden_before=$(sum "$golden")
meta_before=$(sum "$meta")
backups_before=$(ls -1 "$snapdir" 2>/dev/null | grep -E '^golden\.(dump|meta)\.bak-pre-')
say "before: HEAD $prev_head, version $prev_desc"
say "before: web image $img_repo:$img_tag $img_id"
say "before: golden.dump sha256 $golden_before, golden.meta sha256 $meta_before"
say "before: newest backup $(ls -1t "$snapdir" 2>/dev/null | grep -E '^golden\.dump\.bak-pre-' | head -1)"
say "before: the live page must show $prev_desc"
if ! smoke "$home" "$title" "$home" "$prev_desc"; then
  say "REFUSING: the live page does not show the checkout's version $prev_desc, so this run could not recognise the release it would put back. Nothing changed."
  finish 1
fi
docker tag "$img_id" "$img_repo:previous" || { say "REFUSING: could not tag $img_id as $img_repo:previous. Nothing changed."; finish 1; }
say "kept the running image as $img_repo:previous"

# --- the deploy --------------------------------------------------------------------------------
rollback() {
  local bad=0 now dump_bak meta_bak
  say "ROLLING BACK: $1. Putting back $prev_desc ($prev_head)."
  git reset --hard "$prev_head" 2>&1 | tee -a "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || { say "git reset --hard $prev_head failed"; bad=1; }
  docker tag "$img_repo:previous" "$img_repo:$img_tag" || { say "could not retag $img_repo:previous"; bad=1; }
  APP_VERSION=$prev_desc docker compose up -d --no-build 2>&1 | tee -a "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || { say "docker compose up -d --no-build failed"; bad=1; }
  now=$(web_field ID)
  if [ "$now" != "$img_id" ]; then
    say "the web container runs ${now:-nothing}, not $img_id; recreating it"
    APP_VERSION=$prev_desc docker compose up -d --no-build --force-recreate web 2>&1 | tee -a "$log"
    now=$(web_field ID)
    [ "$now" = "$img_id" ] || { say "the web container still runs ${now:-nothing}, not $img_id"; bad=1; }
  fi
  say "web image now $now"
  if [ "$(sum "$golden")" = "$golden_before" ] && [ "$(sum "$meta")" = "$meta_before" ]; then
    say "golden.dump was not replaced by this run, so it and the live database are left alone"
  else
    dump_bak=$(this_runs_backup dump "$golden_before")
    meta_bak=$(this_runs_backup meta "$meta_before")
    if [ -z "$dump_bak" ] || { [ "$meta_before" != none ] && [ -z "$meta_bak" ]; }; then
      say "golden.dump or golden.meta was replaced by this run and there is no backup of it from this run with the sha256 it had before; both are left as they are and the live database is not reset"
      bad=1
    elif put_back "$dump_bak" "$golden" "$golden_before" && { [ -z "$meta_bak" ] || put_back "$meta_bak" "$meta" "$meta_before"; }; then
      say "golden.dump and golden.meta put back from $(basename "$dump_bak")${meta_bak:+ and $(basename "$meta_bak")} (sha256 as before)"
      FORCE=1 bash scripts/reset-demo.sh 2>&1 | tee -a "$log"
      [ "${PIPESTATUS[0]}" = 0 ] || { say "reset-demo.sh failed"; bad=1; }
    else
      say "could not copy the backups back over golden.dump and golden.meta"
      bad=1
    fi
  fi
  say "smoke test of the previous release, $prev_desc"
  smoke "$home" "$title" "$home" "$prev_desc" || bad=1
  if [ $bad = 0 ]; then
    say "the previous release $prev_desc is back and its smoke test passed"
    finish 5
  fi
  say "THE ROLLBACK DID NOT FINISH. Read $log before anything else."
  finish 6
}

say "make deploy REF=$ref"
make deploy REF="$ref" </dev/null 2>&1 | tee "$mkout"
mk=${PIPESTATUS[0]}
cat "$mkout" >> "$log"
if [ "$mk" != 0 ]; then
  if grep -q '^HEAD is now at ' "$mkout"; then
    rollback "make deploy failed (exit $mk) after its reset"
  fi
  say "make deploy stopped (exit $mk) before its reset. Nothing changed."
  finish 1
fi

new_head=$(git rev-parse HEAD)
new_desc=$(git describe --tags --always --dirty 2>/dev/null)
say "deployed $new_desc ($new_head); smoke test"
if [ $drill = 1 ]; then
  smoke "$home" "$title" "$home" "$new_desc" "$missing" "$title"
else
  smoke "$home" "$title" "$home" "$new_desc"
fi
sm=$?
if [ $sm = 0 ]; then
  say "released $new_desc; the previous image stays tagged $img_repo:previous"
  finish 0
fi
rollback "the smoke test failed (smoke exit $sm)"
