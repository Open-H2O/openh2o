#!/usr/bin/env bash
# Deploy openh2o.com: deploy.sh [<commit>] [--drill-smoke-missing-page]
#
# openh2o is NOT a static site and NOT on Cloudflare — it runs as Docker
# containers on the host named by OPENH2O_DEPLOY_HOST, an SSH host set in the
# maintainer's own shell environment (prod checkout: ~/openh2o). This wrapper
# runs scripts/release.sh there over SSH, read from origin/main (so the newest
# release script runs even when the checkout is older), which:
#   - runs `make deploy REF=<commit>`: it refuses first unless that commit's
#     `tests` run on GitHub passed, and refuses when GitHub cannot be asked
#     (`make ci-gate`; nothing is changed); then git reset --hard to the commit
#     it checked (so: PUSH your changes first), rebuilds the web container, and
#     RESETS the demo database to the golden snapshot it built and promoted
#   - then smoke-tests the live home page (its title and the new version), and
#     when that fails puts the previous code, web image and demo database back
#
# Before the ssh it asks for the deploy checks (scripts/regress-gate.sh and
# .github/workflows/deploy-checks.yml): the tests of the commit in the live page
# footer (https://openh2o.com/, or OPENH2O_SITE_URL) must pass on the candidate's code, and each fix's test must fail on the
# commit before the fix. A red check, or one that does not finish within the
# wait, refuses the release with nothing changed (exit 1); the run's log prints
# the Test-Change: or Fix-Test: lines that would excuse each failure. The
# candidate is resolved here, and that exact commit is what the server checks out
# and releases. Needs `gh` logged in with access to the repository's Actions.
# Before dispatching the deploy checks it runs scripts/test_reasons.py (read from origin/main) on the
# same pair: an old test the candidate changed with no Test-Change: line refuses in seconds, with the
# lines it needs, instead of after the 27-minute check; nothing else here changed with it.
#
# <commit> defaults to origin/main's commit. --drill-smoke-missing-page also
# asks for a page that does not exist, so the smoke test fails and the rollback
# runs: the drill that proves it. Exit codes are release.sh's (0 released,
# 1 refused with nothing changed, 2 bad arguments, 5 rolled back, 6 the
# rollback did not finish). `make deploy` alone still works and checks nothing
# after it ships. This has real production side effects.
set -euo pipefail

usage() { echo "usage: deploy.sh [<commit>] [--drill-smoke-missing-page]"; exit 2; }
host=${OPENH2O_DEPLOY_HOST:-}
if [ -z "$host" ]; then
  echo "deploy.sh: set OPENH2O_DEPLOY_HOST to the SSH host that runs openh2o.com." >&2
  exit 2
fi
ref="" drill=no-drill
for a in "$@"; do
  case $a in
    --drill-smoke-missing-page) drill=$a ;;
    -*|*[!A-Za-z0-9._/-]*) usage ;;
    *) [ -z "$ref" ] || usage; ref=$a ;;
  esac
done

# The deploy checks, before anything on the server changes.
here=$(cd "$(dirname "$0")" && pwd)
git -C "$here" fetch -q origin
cand=$(git -C "$here" rev-parse --verify "${ref:-origin/main}^{commit}") || { echo "deploy.sh: '${ref:-origin/main}' is not a commit here." >&2; exit 2; }
desc=$(curl -fsS --max-time 30 "${OPENH2O_SITE_URL:-https://openh2o.com/}" | sed -n 's/.*app-footer-version"[^>]*>\([^<]*\)<.*/\1/p' | head -1) || desc=""
desc=${desc%-dirty}
case $desc in *-g*) short=${desc##*-g} ;; *) short=$desc ;; esac
live=""
[ -n "$short" ] && live=$(git -C "$here" rev-parse --verify --quiet "$short^{commit}") || true
if [ -z "$live" ]; then
  base=last-checked
  echo "deploy.sh: no live commit read from the page footer ('$desc'); deploy checks from the last checked commit"
elif [ "$live" = "$cand" ] || git -C "$here" merge-base --is-ancestor "$cand" "$live"; then
  base=""
  echo "deploy.sh: $cand is live or older than live ${live:0:12}: no new tests or fixes to check"
else
  base=$(git -C "$here" merge-base "$live" "$cand")
  [ "$base" = "$live" ] || echo "deploy.sh: live ${live:0:12} is not on the candidate's line; deploy checks from the common ancestor ${base:0:12}"
fi
if [ -n "$base" ] && [ "$base" != last-checked ]; then
  # Old tests the candidate changes need their Test-Change: lines; asked of git alone, in seconds,
  # before the deploy checks are started. Read from origin/main so an older candidate is asked too.
  reasons=$(mktemp)
  if git -C "$here" show origin/main:scripts/test_reasons.py > "$reasons" 2>/dev/null; then
    rc=0
    (cd "$here" && python3 -I "$reasons" check --base "$base" --head "$cand") || rc=$?
    rm -f "$reasons"
    if [ "$rc" != 0 ]; then
      [ "$rc" = 1 ] || echo "deploy.sh: the old-test reasons could not be read (exit $rc)." >&2
      echo "deploy.sh: REFUSED: old tests changed without their lines; nothing on the server was changed." >&2
      exit 1
    fi
  else
    rm -f "$reasons"
  fi
elif [ "$base" = last-checked ]; then
  echo "deploy.sh: no live commit, so the old-test reasons are not asked here; the deploy checks still decide"
fi
if [ -n "$base" ]; then
  gate=$(mktemp)
  git -C "$here" show origin/main:scripts/regress-gate.sh > "$gate"
  rc=0
  bash "$gate" Open-H2O/openh2o "$cand" "$base" --wait 3600 || rc=$?
  rm -f "$gate"
  case $rc in
    0) ;;
    3) echo "deploy.sh: the deploy checks were asked wrongly (exit 3)." >&2; exit 2 ;;
    *) echo "deploy.sh: REFUSED by the deploy checks (exit $rc); nothing on the server was changed." >&2; exit 1 ;;
  esac
fi
ref=$cand

echo "About to release openh2o.com on $host (rebuild web + RESET demo DB to golden, then a smoke test)."
echo "This ships ${ref:-whatever is on origin/main}. Ctrl-C now if it isn't pushed."
# Both arguments always go over, as words ssh cannot drop or merge: the ref was
# checked above to hold no space or shell character.
ssh "$host" bash -s -- "${ref:-origin/main}" "$drill" <<'REMOTE'
set -euo pipefail
cd ~/openh2o
git fetch -q origin </dev/null
ref=$(git rev-parse --verify "$1^{commit}" </dev/null)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git show origin/main:scripts/release.sh > "$tmp/release.sh" </dev/null
git show origin/main:scripts/smoke.sh > "$tmp/smoke.sh" </dev/null
# The release script asks the site it released; it has no default address.
export RELEASE_SITE=https://openh2o.com
if [ "$2" = --drill-smoke-missing-page ]; then
  bash "$tmp/release.sh" REF="$ref" --drill-smoke-missing-page </dev/null
else
  bash "$tmp/release.sh" REF="$ref" </dev/null
fi
REMOTE
