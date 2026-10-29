#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# guard-demo-target.sh <name> [checkout]
#
# The demonstration targets (make demo, remove-demo, reset-demo, snapshot-demo, calc-rebuild) and
# the scripts behind them load, remove or restore demonstration data, and a restore replaces the
# live database. They refuse in a protected checkout (one carrying .production-lock), unless the
# checkout is also the demonstration host (one carrying .demo-host): the public demonstration is
# protected from the commands that would stop or rebuild it, and its nightly reset, which runs
# `bash scripts/reset-demo.sh` from cron, still has to work there. A checkout with neither
# marker is not guarded, as before.
#
# Exit 0 and no output when the target may run; exit 1 and a sentence when it may not.
# Runs on bash 3.2 and bash 5.
set -u

name=${1:-this command}
checkout=${2:-$(cd "$(dirname "$0")/.." && pwd)}

if [ -f "$checkout/.production-lock" ] && [ ! -f "$checkout/.demo-host" ]; then
  cat >&2 <<MSG

  REFUSING: this checkout is protected (it carries .production-lock) and is not the demonstration host.
  '$name' loads, removes or restores demonstration data, and a restore replaces this site's records.
  To see the demonstration, use a separate checkout that has no .production-lock.
  To run it here on purpose: rm .production-lock  (then recreate it after).

MSG
  exit 1
fi
exit 0
