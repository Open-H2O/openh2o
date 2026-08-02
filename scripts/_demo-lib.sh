# SPDX-License-Identifier: AGPL-3.0-or-later
# shellcheck shell=bash
#
# Shared helpers for the demo snapshot/reset pair. Sourced, never executed —
# it defines functions and assumes the caller has already `cd`-ed into the
# OpenH2O checkout and set `-euo pipefail`.
#
# Why a shared lib: snapshot-demo.sh STAMPS the golden snapshot with a schema
# fingerprint, and reset-demo.sh COMPARES the live schema against that stamp
# before it wipes anything. Both sides must compute the fingerprint the exact
# same way, or every comparison would be a false mismatch. Keeping the one
# definition here guarantees they stay in lockstep.

# Optional: set OPENH2O_NTFY_URL to an ntfy topic URL to receive alerts
# (e.g. http://192.168.0.114:8080/vander-infra). Unset = alerting disabled.
#
# This reads the SHELL ENVIRONMENT ONLY, and nothing here should ever reach into
# .env for it. The Makefile already lifts the key out of .env and exports it for
# every recipe (see its OPENH2O_NTFY_URL note, added with the ISS-106 fix in
# 4ac401d), and the crontab lines set it inline. One mechanism, two callers.
# A .env fallback was added here on 2026-08-01 and removed the next morning: it
# was justified by a claim that the refused promotion of 2026-08-01 17:01 PDT
# had alerted nobody, and the ntfy topic's own message history disproves that —
# the alert arrived at 17:02. The measurement behind the claim was a bare
# `bash -c` sourcing this file, which of course sees no variable, because `make`
# is what exports it. Probing a mechanism outside the harness that drives it
# says nothing about the mechanism.
NTFY_URL="${OPENH2O_NTFY_URL:-}"

# Which compose project these helpers talk to. Defaults to the caller's own
# project (snapshot-demo.sh and reset-demo.sh, which run inside the deployment
# they are stamping or restoring). rebuild-golden.sh overrides it with a
# `-p <scratch>` project so the SAME fingerprint and row-count definitions
# describe the candidate it just built. Two callers already depend on these
# computing identically on both sides of the snapshot/reset pair — that is the
# whole reason this file exists — so the invocation is what varies, never the
# function.
DEMO_COMPOSE="${DEMO_COMPOSE:-docker compose}"

# How to run a one-off python process in the web image. The default targets the
# RUNNING web container, which is what a live deployment has. rebuild-golden.sh
# has no running web container ON PURPOSE — starting one runs the entrypoint's
# no-argument branch, which calls ensure_superuser and would bake a staging
# admin account into the candidate — so it passes `run --rm --no-deps web`,
# which execs and exits without ever booting a server.
DEMO_WEB="${DEMO_WEB:-exec -T web}"

# Block until the db container actually accepts queries, or fail after a timeout.
#
# `docker compose up -d --wait db` is NOT sufficient on its own, and the reason
# is worth knowing. The postgres entrypoint starts a TEMPORARY server to run
# initdb, then shuts it down and starts the real one. A healthcheck can pass
# against that temporary server, so `--wait` returns and the next command hits
# "FATAL: the database system is shutting down".
#
# Measured 2026-07-31 in Plan 103-02: this never fired on an idle box and fired
# every time with the test suite running beside it, because load widens the
# window. Phase 104 wires these scripts into an automated deploy, where a
# transient race that only appears under load is exactly the failure that will
# appear in production and nowhere else.
#
# **AND IT DID. 2026-08-01 17:01 PDT, the v2.9 production deploy refused with
# exactly that FATAL, from inside this function's own caller** — with the
# staging test suite running beside it, precisely as the paragraph above
# predicted. The guard was right about the disease and wrong about the cure: it
# probed over the UNIX SOCKET, which is the one transport the temporary server
# does answer, so its first success could be that server and the race simply
# moved one step later. Staging had passed the identical script minutes earlier
# on a quieter box.
#
# **The discriminator is TCP, and it is exact rather than probabilistic.** The
# postgres image's `docker_temp_server_start` appends `-c listen_addresses=''`,
# so the initdb server listens on the socket and CANNOT accept a TCP connection
# at all. A query answered on 127.0.0.1 is therefore the real server by
# construction — not "probably ready", not "ready long enough". No amount of
# extra polling on the socket could have given that guarantee, which is why
# this is a transport change and not a longer timeout.
#
#   demo_wait_for_db [seconds]      (default 90)
demo_wait_for_db() {
  local deadline
  deadline=$(( $(date +%s) + ${1:-90} ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    # shellcheck disable=SC2086,SC2016
    # SC2086: DEMO_COMPOSE is a multi-word command and must word-split.
    # SC2016: POSTGRES_USER must expand inside the db container, from its own
    # env, not on this host — the same idiom snapshot-demo.sh uses.
    # -h 127.0.0.1 is load-bearing, NOT tidiness. See the note above: without
    # it this function can return while the temporary initdb server is still
    # up, and the caller's next statement dies on "the database system is
    # shutting down".
    if $DEMO_COMPOSE exec -T db sh -c \
         'psql -h 127.0.0.1 -tAqc "SELECT 1" -U "$POSTGRES_USER" -d postgres' \
         >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# Pipe data in, get its sha256 hex digest out. Works on Linux (sha256sum) and
# macOS (shasum), so the same lib runs on the server and a dev's laptop.
_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

# Fingerprint of the live database's migration state: the ordered, applied
# migration plan, hashed. Two databases with the same fingerprint are at the
# same schema; a different fingerprint means a migration ran (or hasn't) that
# the other side doesn't know about. Prints the hex digest, or nothing if the
# web container can't answer (caller must treat empty as "unknown — don't trust").
demo_migration_fingerprint() {
  local plan
  # shellcheck disable=SC2086  # DEMO_COMPOSE/DEMO_WEB are multi-word commands
  # ("docker compose -p x", "run --rm --no-deps web") and MUST word-split.
  plan="$($DEMO_COMPOSE $DEMO_WEB python manage.py showmigrations --plan 2>/dev/null)"
  [ -n "$plan" ] || return 0
  printf '%s' "$plan" | _sha256
}

# Row counts for every first-party (project-owned) model, one `app.Model=count`
# line per model, sorted. Skips Django/allauth internals (sessions, admin log,
# etc.) whose counts churn on their own and would just be noise. The `RC:` tag +
# sed strips any stray shell banner so only clean `label=count` lines come back.
demo_row_counts() {
  # shellcheck disable=SC2086  # see demo_migration_fingerprint — must word-split
  $DEMO_COMPOSE $DEMO_WEB python manage.py shell -c '
from django.apps import apps
rows = []
for m in apps.get_models():
    pkg = m._meta.app_config.name
    if pkg.startswith("django.") or pkg.startswith("allauth"):
        continue
    rows.append((m._meta.label, m.objects.count()))
for label, n in sorted(rows):
    print("RC:%s=%d" % (label, n))
' 2>/dev/null | sed -n 's/^RC:\(.*\)/\1/p'
}

# Sum the counts coming out of demo_row_counts (stdin) into a single total.
demo_row_total() {
  awk -F= '{s += $2} END {print s + 0}'
}

# Fire an ntfy notification if OPENH2O_NTFY_URL is set; a no-op otherwise, so the
# scripts run fine on a box with no alerting configured. Never fails the caller.
#   demo_ntfy <priority> <title> <message>
demo_ntfy() {
  local priority="$1" title="$2" msg="$3"
  [ -n "$NTFY_URL" ] || return 0
  curl -fsS -H "Title: $title" -H "Priority: $priority" -H "Tags: droplet" \
    -d "$msg" "$NTFY_URL" >/dev/null 2>&1 || true
}
