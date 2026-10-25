#!/usr/bin/env bash
# Copied verbatim from vanderoffice/testing-program deploy-gate/regress-gate.sh at 849082613d803eeb79caa760060f473fc5cc318f; change it there.
# regress-gate.sh <owner/repo> <40-character head> <40-character base | last-checked> [--wait <seconds>]
#
# Asks GitHub whether the repository's deploy checks (rules 6 and 8: old tests against new code,
# and each fix's test against the commit before the fix; regress/regress.py run by the
# repository's deploy-checks.yml) passed for exactly this pair, for a deploy script to call right
# after ci-gate.sh and before its first change to anything serving.
#
# The newest deploy-checks.yml run titled exactly `deploy checks <head> from <base>` decides. With
# none, it dispatches one (`gh workflow run deploy-checks.yml --ref main -f base -f head`) and
# waits for it, polling every 15 seconds up to --wait (default 1800). A run for the same head from
# another base is not accepted.
#
# `last-checked` in place of a base (for a path with no release mark) means the head of the
# newest green deploy-checks run whose head is an ancestor of <head>, asked through GitHub's
# compare API; if a green run already checked <head> itself, that run decides.
#
# Exit codes:
#   0  that run finished green: the deploy may go on
#   2  refused: it failed, was cancelled, did not finish within --wait, or no run appeared
#   3  bad input (not owner/repo, not a full 40-character lowercase hex commit, a bad --wait)
#   4  GitHub could not be asked (gh missing, not logged in, network, API error); refuse too
#
# Needs `gh` logged in with read access to the repository's Actions, and write access to dispatch
# (inside an Actions job: GH_TOKEN: ${{ github.token }} with `permissions: actions: write`).
# Never deploys anything.
#
# Source: vanderoffice/testing-program deploy-gate/regress-gate.sh. Application repositories carry
# a verbatim copy with one header line naming the commit it came from; change it there, not in
# a copy.
set -uo pipefail

say() { echo "regress-gate: $*"; }
usage() { say "usage: regress-gate.sh <owner/repo> <40-character head> <40-character base | last-checked> [--wait <seconds>] ($1)"; exit 3; }

repo=${1:-}
head=${2:-}
base=${3:-}
wait_s=1800
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || usage "got repo '$repo'"
[[ $head =~ ^[0-9a-f]{40}$ ]] || usage "got head '$head'"
[[ $base =~ ^[0-9a-f]{40}$ || $base == last-checked ]] || usage "got base '$base'"
shift 3
while [ $# -gt 0 ]; do
  case $1 in
    --wait) [[ ${2:-} =~ ^[0-9]+$ ]] || usage "got --wait '${2:-}'"; wait_s=$2; shift 2 ;;
    *) usage "got '$1'" ;;
  esac
done
poll=${REGRESS_GATE_POLL:-15}
WF=deploy-checks.yml
command -v gh >/dev/null 2>&1 || { say "REFUSED: could not ask GitHub (no gh on PATH)"; exit 4; }

err=$(mktemp "${TMPDIR:-/tmp}/regress-gate.XXXXXX") || { say "REFUSED: could not make a temporary file"; exit 4; }
trap 'rm -f "$err"' EXIT

# Lines of id|title|status|conclusion|url|headSha, newest first.
runs() {
  gh run list -R "$repo" --workflow "$WF" -L 100 \
    --json databaseId,displayTitle,status,conclusion,url,headSha \
    --jq '.[] | [(.databaseId|tostring), .displayTitle, .status, (.conclusion // ""), .url, .headSha] | join("|")' 2>"$err"
}
asked() {  # gh exit code
  say "REFUSED: could not ask GitHub (gh exit $1: $(head -1 "$err"))"
  exit 4
}

if [ "$base" = last-checked ]; then
  out=$(runs) || asked $?
  found="" n=0
  while IFS='|' read -r id title status conclusion url hsha; do
    [ -n "$id" ] || continue
    [ "$status" = completed ] && [ "$conclusion" = success ] || continue
    case $title in
      "deploy checks weekly") cand=$hsha; from="a week before" ;;
      "deploy checks "*" from "*) cand=${title#deploy checks }; from=${cand#* from }; cand=${cand%% from *} ;;
      *) continue ;;
    esac
    [[ $cand =~ ^[0-9a-f]{40}$ ]] || continue
    if [ "$cand" = "$head" ]; then
      say "green $repo $head: $WF run $id already checked this head (from $from) $url"
      exit 0
    fi
    n=$((n + 1))
    [ $n -le 20 ] || break
    st=$(gh api "repos/$repo/compare/$cand...$head" --jq .status 2>"$err") || { say "note: could not compare $cand with $head (gh: $(head -1 "$err")); skipped"; continue; }
    if [ "$st" = ahead ]; then found=$cand; break; fi
  done <<<"$out"
  [ -n "$found" ] || { say "REFUSED $repo $head: no green $WF run whose head is an ancestor of it, so there is no last-checked base"; exit 2; }
  say "base last-checked = $found (head of green run $id)"
  base=$found
fi

title="deploy checks $head from $base"
pick() {  # sets line to the newest run with exactly this title, or ""
  local out
  out=$(runs) || asked $?
  line=""
  while IFS= read -r l; do
    IFS='|' read -r _ t _ <<<"$l"
    if [ "$t" = "$title" ]; then line=$l; break; fi
  done <<<"$out"
}
judge() {
  local id t status conclusion url
  IFS='|' read -r id t status conclusion url _ <<<"$line"
  if [ "$status" = completed ] && [ "$conclusion" = success ]; then
    say "green $repo $head from $base: $WF run $id $url"
    exit 0
  fi
  if [ "$status" = completed ]; then
    say "REFUSED $repo $head from $base: $WF run $id is completed, ${conclusion:-no conclusion} ($url)"
    exit 2
  fi
}

pick
if [ -z "$line" ]; then
  say "no $WF run for '$title'; dispatching one"
  gh workflow run "$WF" -R "$repo" --ref main -f "base=$base" -f "head=$head" >/dev/null 2>"$err" || asked $?
  sleep "$poll"
  pick
fi
deadline=$((SECONDS + wait_s))
while :; do
  [ -n "$line" ] && judge
  if [ $SECONDS -ge $deadline ]; then
    if [ -n "$line" ]; then
      IFS='|' read -r id _ status _ url _ <<<"$line"
      say "REFUSED $repo $head from $base: $WF run $id is $status, not finished within $wait_s s ($url)"
    else
      say "REFUSED $repo $head from $base: no $WF run titled '$title' appeared within $wait_s s"
    fi
    exit 2
  fi
  sleep "$poll"
  pick
done
