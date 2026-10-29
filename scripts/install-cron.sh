#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# install-cron.sh: put crontab.txt into the installed schedule (`make install-cron`).
#
# It writes one block, between two marker lines, and nothing else in the schedule:
#   OPENH2O_DIR      this checkout, worked out from where this script lives
#   OPENH2O_LOG_DIR  $OPENH2O_LOG_DIR from the environment, else $HOME/openh2o-logs
#   OPENH2O_NTFY_URL only when that is set in the environment (the Makefile reads it from .env)
#   ...followed by the jobs in crontab.txt.
# Run again, it replaces its own block, so a changed crontab.txt takes effect and the jobs never
# run twice. Lines outside the block are kept as they are.
#
# A schedule installed by an older version of this command holds the same jobs without the
# markers. Adding the block beside them would run every job twice, so it stops and says what to
# delete. Nothing is changed in that case.
#
# CRONTAB names the command that reads and writes the schedule (default: crontab), so a test
# can stand in for it.
#
# Runs on bash 3.2 and bash 5.
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
logdir=${OPENH2O_LOG_DIR:-$HOME/openh2o-logs}
crontab_cmd=${CRONTAB:-crontab}
begin='# BEGIN OpenH2O schedule (written by make install-cron, replaced each time it runs)'
end='# END OpenH2O schedule'

[ -f "$here/crontab.txt" ] || { echo "install-cron: no crontab.txt in $here. Nothing changed." >&2; exit 1; }

current=$("$crontab_cmd" -l 2>/dev/null || true)

# What is in the schedule outside our block.
outside=$(printf '%s\n' "$current" | awk -v b="$begin" -v e="$end" '
  $0 == b { skip = 1; next }
  $0 == e { skip = 0; next }
  !skip { print }
')

if printf '%s\n' "$outside" | grep -Eq 'run-sync\.sh|scripts/backup\.sh|run_health_checks|^OPENH2O_LOG_DIR='; then
  cat >&2 <<MSG

  REFUSING: the installed schedule already holds OpenH2O jobs that this command did not write.
  Adding its own would run every job twice.

  Open the schedule with 'crontab -e' and delete the OpenH2O lines: the OPENH2O_DIR and
  OPENH2O_LOG_DIR lines and every job that runs a script in $here/scripts or runs
  'docker compose exec'. Keep any lines of your own. Then run 'make install-cron' again.
  Nothing was changed.

MSG
  exit 1
fi

mkdir -p "$logdir"

{
  # Our own lines, minus the blank lines that trail the operator's.
  printf '%s\n' "$outside" | sed -e :a -e '/^[[:space:]]*$/{$d;N;ba' -e '}'
  printf '%s\n' "$begin"
  printf 'OPENH2O_DIR=%s\n' "$here"
  printf 'OPENH2O_LOG_DIR=%s\n' "$logdir"
  if [ -n "${OPENH2O_NTFY_URL:-}" ]; then
    printf 'OPENH2O_NTFY_URL=%s\n' "$OPENH2O_NTFY_URL"
  fi
  grep -Ev '^OPENH2O_(DIR|LOG_DIR|NTFY_URL)=' "$here/crontab.txt"
  printf '%s\n' "$end"
} | "$crontab_cmd" -

echo "Cron entries installed for $here, with logs in $logdir. Run 'make show-cron' to verify."
