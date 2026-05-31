#!/usr/bin/env bash
#
# Resilient external-data sync for OpenH2O cron jobs.
#
# Why this exists: the bare cron line `docker compose exec -T web ... sync_all`
# silently did nothing whenever the web container was down at run time (e.g.
# after an unattended-upgrade reboot), and it wrote its log to /var/log, which
# the unprivileged cron user could not write — so failures left no trace at all.
#
# This wrapper:
#   * ensures the web container is running (`up -d` is a no-op if it already is),
#   * runs one or more sources via `sync_source`,
#   * logs to a path the cron user can write,
#   * pings ntfy if any source fails, so a broken sync is visible.
#
# Usage:  run-sync.sh cdec usgs
#         run-sync.sh cimis cnrfc dwr_wdl dwr_sgma noaa openet
set -uo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-/home/butler/openh2o}"
LOG_DIR="${OPENH2O_LOG_DIR:-/home/butler/openh2o-logs}"
NTFY_URL="${OPENH2O_NTFY_URL:-http://localhost:8080/vander-infra}"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
alert() {
  curl -fsS -H "Title: OpenH2O data sync" -H "Priority: high" -H "Tags: warning" \
    -d "$1" "$NTFY_URL" >/dev/null 2>&1 || true
}

cd "$OPENH2O_DIR" 2>/dev/null || {
  echo "$(ts) FATAL: cannot cd to $OPENH2O_DIR" >>"$LOG"
  alert "OpenH2O sync FATAL: cannot cd to $OPENH2O_DIR"
  exit 1
}

# Guarantee the container is up. `up -d` without --build is near-instant when
# everything is already running, and revives it if a reboot left it stopped.
docker compose up -d >>"$LOG" 2>&1 || {
  echo "$(ts) FATAL: docker compose up -d failed" >>"$LOG"
  alert "OpenH2O sync FATAL: docker compose up -d failed on $(hostname)"
  exit 1
}

failed=()
for code in "$@"; do
  echo "$(ts) >>> sync_source $code" >>"$LOG"
  if docker compose exec -T web python manage.py sync_source "$code" >>"$LOG" 2>&1; then
    echo "$(ts) <<< $code OK" >>"$LOG"
  else
    echo "$(ts) <<< $code FAILED (exit $?)" >>"$LOG"
    failed+=("$code")
  fi
done

if [ "${#failed[@]}" -gt 0 ]; then
  alert "OpenH2O sync failed for: ${failed[*]} — see $LOG on $(hostname)"
  exit 1
fi
echo "$(ts) all sources OK: $*" >>"$LOG"
exit 0
