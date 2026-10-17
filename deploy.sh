#!/usr/bin/env bash
# Deploy openh2o.com: deploy.sh [<commit>] [--drill-smoke-missing-page]
#
# openh2o is NOT a static site and NOT on Cloudflare — it runs as Docker
# containers on Butler (prod checkout: ~/openh2o). This wrapper runs
# scripts/release.sh there over SSH, read from origin/main (so the newest
# release script runs even when the checkout is older), which:
#   - runs `make deploy REF=<commit>`: it refuses first unless that commit's
#     `tests` run on GitHub passed, and refuses when GitHub cannot be asked
#     (`make ci-gate`; nothing is changed); then git reset --hard to the commit
#     it checked (so: PUSH your changes first), rebuilds the web container, and
#     RESETS the demo database to the golden snapshot it built and promoted
#   - then smoke-tests the live home page (its title and the new version), and
#     when that fails puts the previous code, web image and demo database back
#
# <commit> defaults to origin/main's commit. --drill-smoke-missing-page also
# asks for a page that does not exist, so the smoke test fails and the rollback
# runs: the drill that proves it. Exit codes are release.sh's (0 released,
# 1 refused with nothing changed, 2 bad arguments, 5 rolled back, 6 the
# rollback did not finish). `make deploy` alone still works and checks nothing
# after it ships. This has real production side effects.
set -euo pipefail

usage() { echo "usage: deploy.sh [<commit>] [--drill-smoke-missing-page]"; exit 2; }
ref="" drill=no-drill
for a in "$@"; do
  case $a in
    --drill-smoke-missing-page) drill=$a ;;
    -*|*[!A-Za-z0-9._/-]*) usage ;;
    *) [ -z "$ref" ] || usage; ref=$a ;;
  esac
done

echo "About to release openh2o.com on Butler (rebuild web + RESET demo DB to golden, then a smoke test)."
echo "This ships ${ref:-whatever is on origin/main}. Ctrl-C now if it isn't pushed."
# Both arguments always go over, as words ssh cannot drop or merge: the ref was
# checked above to hold no space or shell character.
ssh butler bash -s -- "${ref:-origin/main}" "$drill" <<'REMOTE'
set -euo pipefail
cd ~/openh2o
git fetch -q origin </dev/null
ref=$(git rev-parse --verify "$1^{commit}" </dev/null)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git show origin/main:scripts/release.sh > "$tmp/release.sh" </dev/null
git show origin/main:scripts/smoke.sh > "$tmp/smoke.sh" </dev/null
if [ "$2" = --drill-smoke-missing-page ]; then
  bash "$tmp/release.sh" REF="$ref" --drill-smoke-missing-page </dev/null
else
  bash "$tmp/release.sh" REF="$ref" </dev/null
fi
REMOTE
