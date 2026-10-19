#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# An agency's upgrade: `make upgrade`. Backs up, updates the code, rebuilds, checks, and stamps the
# new version into the footer (ISS-173). It is NOT `make deploy`, which is the demonstration host's
# own target and replaces the database with a canned one.
#
# In order:
#   1. git fetch (changes nothing in the working tree). Local edits are normal on a real site: the
#      guide has an agency edit the top of crontab.txt and, on some installs, the Caddyfile. So a
#      locally edited file only stops the upgrade when this update ALSO changes that file; the
#      script names it and stops before the backup, before anything changes. Edited files the
#      update does not touch are kept, and listed.
#   2. scripts/backup.sh. If it fails: "Upgrade stopped: the backup failed. Nothing was changed."
#   3. git merge --ff-only @{upstream} (the commit step 1 fetched, so there is no second fetch
#      that could land a different commit). A branch that cannot fast-forward stops here, before
#      anything is rebuilt.
#   4. The new version is `git describe --tags --always`, worked out AFTER step 3 (the Makefile's
#      own APP_VERSION is fixed when make starts, before the update). No --dirty: a site whose
#      Caddyfile names its own domain is not running a different version. Then
#      APP_VERSION=<new> docker compose up -d --build for the whole stack, and
#      `docker compose restart caddy` when the Caddyfile differs between the old and new commit
#      (up --build does not reload it).
#   5. Waits for the web container to report healthy (bounded). On timeout it prints the last 50
#      log lines, names the backup to restore from, and exits 1.
#   6. run_health_checks, then prints the old version, the new version and the backup file name.
#
# Environment (all optional):
#   OPENH2O_DIR          the checkout (default: the folder above scripts/)
#   OPENH2O_LOG_DIR      where backup.log goes (default: backups/logs in the checkout)
#   UPGRADE_WAIT_TRIES   how many health polls to make (default 90)
#   UPGRADE_WAIT_SECS    seconds between polls (default 5)
set -uo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
export OPENH2O_DIR
export OPENH2O_LOG_DIR="${OPENH2O_LOG_DIR:-$OPENH2O_DIR/backups/logs}"
TRIES="${UPGRADE_WAIT_TRIES:-90}"
SECS="${UPGRADE_WAIT_SECS:-5}"

cd "$OPENH2O_DIR" 2>/dev/null || { echo "Upgrade stopped: cannot cd to $OPENH2O_DIR. Nothing was changed." >&2; exit 1; }

if [ -f .restore-in-progress ]; then
  echo "Upgrade stopped: a restore is in progress (.restore-in-progress exists). Nothing was changed." >&2
  exit 1
fi

# 1. Fetch, then look at what is edited here against what the update changes.
git fetch >/dev/null 2>&1 || { echo "Upgrade stopped: git fetch failed (is this server online?). Nothing was changed." >&2; exit 1; }
git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1 \
  || { echo "Upgrade stopped: this branch does not track a remote branch. Nothing was changed." >&2; exit 1; }

edited=$(git status --porcelain --untracked-files=no | cut -c4-)
incoming=$(git diff --name-only HEAD '@{upstream}')
clash="" kept=""
for f in $edited; do
  if printf '%s\n' "$incoming" | grep -qxF -- "$f"; then clash="$clash $f"; else kept="$kept $f"; fi
done
if [ -n "$clash" ]; then
  for f in $clash; do
    echo "Upgrade stopped: this update changes $f, which has local edits on this server. Nothing was changed. Save a copy of your edits, run \`git checkout -- $f\`, run \`make upgrade\` again, then put your edits back." >&2
    if [ "$f" = crontab.txt ]; then
      echo "The installed schedule is a copy, so crontab.txt's edits are already in effect and can be discarded." >&2
    fi
  done
  exit 1
fi
[ -z "$kept" ] || echo "Keeping your local edits to:$kept (this update does not change them)."

# 2. Back up first.
if ! bash "$OPENH2O_DIR/scripts/backup.sh"; then
  echo "Upgrade stopped: the backup failed. Nothing was changed." >&2
  exit 1
fi
backup_file=$(sed -n 's/.*"dump_file": *"\([^"]*\)".*/\1/p' backups/last-backup.json 2>/dev/null)
media_file=$(sed -n 's/.*"media_file": *"\([^"]*\)".*/\1/p' backups/last-backup.json 2>/dev/null)

# 3. Update the code.
old_sha=$(git rev-parse HEAD)
old_version=$(git describe --tags --always)
git merge --ff-only '@{upstream}' \
  || { echo "Upgrade stopped: this branch cannot fast-forward to the update (it has commits of its own). Nothing was rebuilt. The backup is backups/$backup_file." >&2; exit 1; }
new_sha=$(git rev-parse HEAD)

# 4. Rebuild the whole stack stamped with the new version.
new_version=$(git describe --tags --always)
APP_VERSION="$new_version" docker compose up -d --build \
  || { echo "Upgrade stopped: docker compose up --build failed. The backup is backups/$backup_file." >&2; exit 1; }
if ! git diff --quiet "$old_sha" "$new_sha" -- Caddyfile; then
  docker compose restart caddy
fi

# 5. Wait for the website to be healthy.
healthy=0 i=0
while [ "$i" -lt "$TRIES" ]; do
  cid=$(docker compose ps -q web 2>/dev/null)
  state=$([ -n "$cid" ] && docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null)
  if [ "$state" = healthy ]; then healthy=1; break; fi
  i=$((i + 1))
  sleep "$SECS"
done
if [ "$healthy" != 1 ]; then
  docker compose logs --tail 50 web
  echo "Upgrade failed: the web container did not become healthy. Its last 50 log lines are above." >&2
  echo "The version before the upgrade was $old_version ($old_sha)." >&2
  echo "The backup taken before anything changed: backups/$backup_file and backups/$media_file" >&2
  exit 1
fi

# 6. Health checks and the summary.
docker compose exec -T web python manage.py run_health_checks
health_rc=$?
echo ""
echo "Old version: $old_version"
echo "New version: $new_version"
echo "Backup:      backups/$backup_file"
if [ "$health_rc" != 0 ]; then
  echo "run_health_checks reported a problem (exit $health_rc). Read its output above." >&2
  exit 1
fi
exit 0
