#!/usr/bin/env bash
# smoke.sh [--tries N] [--wait S] [--max-time S] <url> <marker> [<url> <marker> ...]
#
# The check after a deploy: each URL must answer HTTP 200 and its body must hold its marker, a
# fixed string (not a pattern). A deploy writes its release mark (<40-character commit> <UTC
# stamp>) into what it ships and passes that line as a marker, so a pass means this release is
# the one answering, not merely that something answers. Redirects are not followed: a page that
# redirects is not the page.
#
# Each URL is tried up to --tries times, --wait seconds apart, each request bounded by
# --max-time seconds (defaults 10, 3 and 10). One line per URL: `smoke: PASS <url>` or
# `smoke: FAIL <url> <reason>`, with at most 200 bytes of the body; a failed try that will be
# retried prints `smoke: try <n> of <N> ...`. Nothing from any header is printed.
#
# Exit codes:
#   0  every URL answered 200 with its marker
#   1  at least one did not (every URL is still checked and reported)
#   3  bad input (odd arguments, an empty marker, a URL that is not http or https, a bad option),
#      or no curl; nothing was fetched
#
# Runs on bash 3.2 (macOS), bash 5 (the VPS) and a GitHub runner; needs only curl.
#
# Source: the maintainer's deploy-gate/smoke.sh at 8e0a972c577d9ff9c88d3229c42fb6c33701e5c7.
# This copy is verbatim but for this paragraph; change it there, not here.
set -u

say() { echo "smoke: $*"; }
usage() {
  say "usage: smoke.sh [--tries N] [--wait S] [--max-time S] <url> <marker> [<url> <marker> ...]${1:+ ($1)}"
  exit 3
}

tries=10 wait=3 maxtime=10
while [ $# -gt 0 ]; do
  case $1 in
    --tries)    [ $# -ge 2 ] || usage "--tries needs a value"; tries=$2; shift 2 ;;
    --wait)     [ $# -ge 2 ] || usage "--wait needs a value"; wait=$2; shift 2 ;;
    --max-time) [ $# -ge 2 ] || usage "--max-time needs a value"; maxtime=$2; shift 2 ;;
    --) shift; break ;;
    --*) usage "unknown option $1" ;;
    *) break ;;
  esac
done

is_count()  { case $1 in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ]; }
is_number() { case $1 in ''|.*|*.|*[!0-9.]*|*.*.*) return 1 ;; esac; }
is_count "$tries" || usage "--tries must be a whole number of 1 or more, got '$tries'"
is_number "$wait" || usage "--wait must be a number of seconds, got '$wait'"
is_number "$maxtime" || usage "--max-time must be a number of seconds, got '$maxtime'"

# Every pair is checked before anything is fetched.
check_pairs() {
  [ $# -gt 0 ] || usage "no URL given"
  [ $(($# % 2)) = 0 ] || usage "every URL needs a marker"
  while [ $# -gt 0 ]; do
    case $1 in
      http://?*|https://?*) ;;
      *) usage "not an http or https URL: '$1'" ;;
    esac
    [ -n "$2" ] || usage "empty marker for $1"
    shift 2
  done
}
check_pairs "$@"
command -v curl >/dev/null 2>&1 || { say "needs curl"; exit 3; }

body=$(mktemp "${TMPDIR:-/tmp}/smoke.XXXXXX") || { say "could not make a temporary file"; exit 3; }
errf=$(mktemp "${TMPDIR:-/tmp}/smoke.XXXXXX") || { rm -f "$body"; say "could not make a temporary file"; exit 3; }
trap 'rm -f "$body" "$errf"' EXIT

# The first 200 bytes of the last body, on one line, printable characters only.
excerpt() {
  local e
  e=$(head -c 200 "$body" | tr '\n\r\t' '   ' | LC_ALL=C tr -cd '[:print:]')
  [ -n "$e" ] && printf '; body starts: %s' "$e"
}

# One try at one URL. Sets $reason and returns 0 on a pass.
try_once() {
  local url=$1 marker=$2 code rc
  : > "$body"
  code=$(curl -sS --proto '=http,https' --max-time "$maxtime" -o "$body" -w '%{http_code}' -- "$url" 2>"$errf")
  rc=$?
  if [ $rc -ne 0 ] || [ "$code" = 000 ]; then
    reason="no answer (curl exit $rc: $(head -c 160 "$errf" | tr '\n\r' '  '))"
    return 1
  fi
  if [ "$code" != 200 ]; then
    reason="HTTP $code$(excerpt)"
    return 1
  fi
  if grep -qF -- "$marker" "$body"; then
    return 0
  fi
  reason="HTTP 200, marker missing$(excerpt)"
  return 1
}

failed=0
while [ $# -gt 0 ]; do
  url=$1 marker=$2
  shift 2
  n=1
  while :; do
    reason=""
    if try_once "$url" "$marker"; then
      say "PASS $url"
      break
    fi
    if [ "$n" -ge "$tries" ]; then
      say "FAIL $url $reason (after $n of $tries tries)"
      failed=1
      break
    fi
    say "try $n of $tries $url: $reason; trying again in $wait s"
    sleep "$wait"
    n=$((n + 1))
  done
done
exit $failed
