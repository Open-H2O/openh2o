#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Build the ENTIRE demonstration database from the repository, in a disposable
# compose project that deletes itself afterwards, and leave the result on disk
# as a CANDIDATE.
#
# NOTHING IS PROMOTED HERE. golden.dump is not read, not written and not backed
# up by this script. What lands is `candidate.dump` + `candidate.meta`, an
# artifact a human (or the gates in 103-02) can compare against production
# before anyone decides it deserves to become the golden. A rebuild wired
# straight into promotion would be MORE dangerous than the status quo, not less.
#
# Why this exists: production only ever *restores* golden.dump, so a fix to
# demonstration CONTENT reaches staging automatically and production never. The
# golden has always been a photocopy of a live database rather than a build
# output, which is what made that possible. This is the build.
#
# THE ISOLATION IS THE PROJECT NAME. A compose project name IS the volume
# namespace, so the entire safety of this script rests on $REBUILD_PROJECT
# differing from the checkout's own project. That is checked first, loudly,
# before anything is built. It deliberately does NOT refuse on .production-lock:
# Phase 104 wires this into the production deploy, and a scratch project inside
# the production checkout is safe precisely because its volume is separate.
#
# Usage:  scripts/rebuild-golden.sh [CANDIDATE_PATH]
#   OPENH2O_DIR      checkout to build from   (default: this script's parent)
#   REBUILD_PROJECT  scratch compose project  (default: openh2o-rebuild)
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CANDIDATE="${1:-$HOME/openh2o-demo-snapshot/candidate.dump}"
META="${CANDIDATE%.dump}.meta"
REBUILD_PROJECT="${REBUILD_PROJECT:-openh2o-rebuild}"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

cd "$OPENH2O_DIR"

# ---------------------------------------------------------------------------
# Guard — the scratch project must not be able to name a real deployment.
# ---------------------------------------------------------------------------
own_project="$(basename "$OPENH2O_DIR")"
for reserved in "$own_project" openh2o openh2o-staging; do
  if [ "$REBUILD_PROJECT" = "$reserved" ]; then
    echo "" >&2
    echo "rebuild-golden: REFUSING — REBUILD_PROJECT is '$REBUILD_PROJECT'." >&2
    echo "  A compose project name IS the volume namespace. Building under a real" >&2
    echo "  deployment's project would tear down that deployment's stack and delete" >&2
    echo "  its database volume at the end of this script." >&2
    echo "  Reserved names: this checkout ('$own_project'), production" >&2
    echo "  ('openh2o') and staging ('openh2o-staging'). Pick any other name." >&2
    echo "" >&2
    exit 1
  fi
done

C="docker compose -p $REBUILD_PROJECT"
started=$(date +%s)

# Tear the scratch stack down on ANY exit path, so a failure halfway through
# never strands a stack or a volume for the next run to inherit.
cleanup() {
  # shellcheck disable=SC2086  # $C is a multi-word command and must word-split
  $C down -v --remove-orphans >/dev/null 2>&1 || true
}
fail() {
  cleanup
  # `low` on purpose: production is serving and untouched, and no golden was
  # read or written. A failed rebuild is something to look at in the morning,
  # not something to be woken for. (Same reasoning Brent directed at 102-02.)
  demo_ntfy low "OpenH2O golden rebuild failed" \
    "rebuild-golden on $(hostname) failed. No candidate was written and nothing was promoted; the live site is unaffected."
  echo "rebuild-golden: FAILED — scratch stack torn down, nothing promoted." >&2
  exit 1
}
trap fail ERR

version="$(git describe --tags --always --dirty 2>/dev/null || echo dev)"
commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

echo "rebuild-golden: building $version ($commit) in scratch project '$REBUILD_PROJECT'"
echo "rebuild-golden: candidate -> $CANDIDATE   (NOTHING is promoted by this script)"

# shellcheck disable=SC2086
$C build web
# ONLY db. Never `up web` (see run_step) and never `up caddy` — caddy binds host
# ports 80/443 and would collide with the live deployment on this same box.
# shellcheck disable=SC2086
$C up -d --wait db

# Every step runs as `run --rm`, never against a running web container.
#
#   entrypoint.sh branches on [ "$#" -gt 0 ]: WITH arguments it execs the
#   command and exits. WITHOUT them it runs collectstatic + migrate +
#   createcachetable + ensure_superuser, and that last one would create the
#   checkout's .env admin — on staging, admin@staging.local — and bake it into
#   the candidate. That is the exact mechanism by which staging admin rows once
#   reached production. THE CANDIDATE MUST CONTAIN ZERO USER ROWS.
#
#   -e OPENH2O_MODULES= is not noise. config/settings/base.py reads that
#   variable and falls back to the FULL module list when it is empty. The
#   checkout's .env may carry a reduced set (Plan 90-03 deliberately ran staging
#   on reduced configurations), and a golden built under a reduced config would
#   silently omit whole domains. Empty pins the build to the full default set
#   regardless of what this host happens to be running.
run_step() {
  echo ""
  echo "=== $* ==="
  # shellcheck disable=SC2086
  $C run --rm --no-deps -e OPENH2O_MODULES= web python manage.py "$@"
}

run_step migrate --noinput
run_step seed_data
# NOT part of the seed_data umbrella, deliberately — core/modules.py records why
# (listing it in the registry would change behaviour for anyone composing
# seed_data from it). But the umbrella's scope is not this build's scope: a
# rebuild that skips it produces a demonstration with an EMPTY SensorThings
# crosswalk — measured 2026-07-31, production carries 17 ObservedProperty and 26
# SourceParameter rows and the first candidate carried 0 of each. Nothing a
# visitor sees (standards ships no views or urls), but check_conformance and
# every adapter's PARAMETER_MAP resolve against it. Idempotent, so this neither
# changes seed_data nor double-seeds.
run_step seed_observed_properties
# The boundary must exist BEFORE the flowlines fixture: flowlines.json names it
# by natural key, and it is pk 1 on staging and pk 6 on production. seed_merced
# runs this same step again a moment later; it is idempotent.
run_step seed_merced_base
run_step loaddata data/merced/flowlines.json
# --allow-prod-clobber is belt-and-braces: the database is empty, so there is
# nothing to clobber and a first-time seed passes the guard unaided (ISS-095).
# Passed anyway so the sequence does not depend on that emptiness holding.
run_step seed_merced --skip-auto-populate --allow-prod-clobber
run_step load_openet_fixture
run_step seed_calculation_plan
run_step refresh_merced_accounting

# ---------------------------------------------------------------------------
# Dump the candidate.
# ---------------------------------------------------------------------------
echo ""
tmp="$(mktemp)"
# SC2016 is intentional and load-bearing: POSTGRES_USER/POSTGRES_DB must expand
# inside the db container, from its own env, not on this host. Same idiom as
# snapshot-demo.sh, which is how the dump adapts to prod and staging alike.
# shellcheck disable=SC2086,SC2016
$C exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$tmp"
if [ ! -s "$tmp" ]; then
  rm -f "$tmp"
  echo "rebuild-golden: ERROR dump was empty — keeping any previous candidate" >&2
  fail
fi
mkdir -p "$(dirname "$CANDIDATE")"
mv "$tmp" "$CANDIDATE"

# ---------------------------------------------------------------------------
# Stamp the manifest WHILE THE STACK IS STILL UP — these facts cannot be
# recovered once the volume is gone. Same key=value shape snapshot-demo.sh
# writes, so 103-02 can install it as golden.meta unchanged.
# ---------------------------------------------------------------------------
export DEMO_COMPOSE="$C"
export DEMO_WEB="run --rm --no-deps -e OPENH2O_MODULES= web"

fingerprint="$(demo_migration_fingerprint)"
if [ -z "$fingerprint" ]; then
  echo "rebuild-golden: ERROR could not read the candidate's schema fingerprint" >&2
  fail
fi

# Record what was BUILT, never what was intended: read the resolved list out of
# the container's own settings.
modules="$(
  # shellcheck disable=SC2086
  $C run --rm --no-deps -e OPENH2O_MODULES= web python manage.py shell \
    -c 'from django.conf import settings; print("MODS:" + ",".join(settings.OPENH2O_MODULES))' \
    2>/dev/null | sed -n 's/^MODS://p' | head -1
)"

counts="$(demo_row_counts)"
row_total="$(printf '%s\n' "$counts" | demo_row_total)"

metatmp="$(mktemp)"
{
  echo "# OpenH2O demo CANDIDATE manifest — written by rebuild-golden.sh"
  echo "# Built from the repository. NOT promoted: this is not a golden snapshot."
  echo "schema_version=$version"
  echo "source_commit=$commit"
  echo "migration_fingerprint=$fingerprint"
  echo "snapshot_timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "openh2o_modules=$modules"
  echo ""
  echo "# first-party row counts (app.Model=count) at build time"
  printf '%s\n' "$counts"
} > "$metatmp"
mv "$metatmp" "$META"

# ---------------------------------------------------------------------------
# Tear down and PROVE it. A teardown that silently left its volume behind would
# poison the next rebuild with this run's rows, and that run would still look
# clean — which is the whole failure class this milestone exists to end.
# ---------------------------------------------------------------------------
echo ""
# shellcheck disable=SC2086
$C down -v --remove-orphans
leftover="$(docker volume ls -q --filter name="^${REBUILD_PROJECT}_" || true)"
if [ -n "$leftover" ]; then
  echo "rebuild-golden: ERROR scratch volume(s) survived teardown:" >&2
  # shellcheck disable=SC2086  # word-split on purpose: one volume name per line
  printf '  %s\n' $leftover >&2
  exit 1
fi
trap - ERR

elapsed=$(( $(date +%s) - started ))
echo ""
echo "rebuild-golden: candidate  -> $CANDIDATE ($(du -h "$CANDIDATE" | cut -f1))"
echo "rebuild-golden: manifest   -> $META"
echo "rebuild-golden: version     $version   fingerprint ${fingerprint:0:12}…"
echo "rebuild-golden: modules     $modules"
echo "rebuild-golden: rows        $row_total across $(printf '%s\n' "$counts" | wc -l | tr -d ' ') models"
echo "rebuild-golden: scratch volume gone, stack removed"
echo "rebuild-golden: wall clock  $((elapsed / 60))m $((elapsed % 60))s"
echo ""
echo "NOTHING WAS PROMOTED. Compare this candidate against production before it"
echo "becomes anything. Promotion is Phase 103-02."
