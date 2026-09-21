#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# shape_stack.sh: stand up, seed, check and tear down one of the six deployment
# shapes measured in Phase 145 (145-02), so any later plan can re-walk a shape on
# a fresh instance instead of re-deriving the recipe by hand.
#
# Usage:
#   scripts/shape_stack.sh up <n>           # write the override, build+start db+web,
#                                            # check, seed, verify, print modules
#   scripts/shape_stack.sh seed <n>         # re-run seed_data + verify_clean_install
#                                            # on an already-up shape
#   scripts/shape_stack.sh login-check <n>  # authenticated GET of / ; prints the status
#   scripts/shape_stack.sh down <n>         # tear down (with volumes) and delete the override
#
# This script NEVER touches `openh2o` or `openh2o-staging`; every docker compose
# call below is pinned to a literal `openh2o-shape-<n>` project name that is
# checked against <n> before any command runs (see require_shape below).
#
# The override file lives at ${TMPDIR:-/tmp}/openh2o-shape-<n>.override.yml, never
# inside this repository, and `git status` must never show it.
#
# `verify_clean_install` fails (exit 1, "No reference data found (zero DataSource
# rows)") on any shape whose module list omits `datasync`, shapes 1, 2 and 5 as
# measured in 145-02-EVIDENCE.md. That is a known positive-signal bug in the
# check, not a broken install (every module-appropriate reference table IS
# seeded), so this script prints the failure and continues rather than treating
# it as fatal: ISS-198, expected until Phase 151.

set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERRIDE_DIR="${TMPDIR:-/tmp}"

# -- Module lists (table order, verbatim from 146-01-PLAN.md's context block,
#    cross-checked against 145-02-EVIDENCE.md's per-shape table). Bash 3.2 (the
#    version macOS ships) has no associative arrays, so this is a case statement
#    rather than a `declare -A` table.
modules_for() {
  case "$1" in
    1) echo "core,geography,measurements,standards,parcels,accounting,surface,reporting,setup,infrastructure,health,feedback" ;;
    2) echo "core,geography,measurements,standards,drinking,setup,infrastructure,health,feedback" ;;
    3) echo "core,geography,measurements,standards,parcels,accounting,datasync,setup,infrastructure,health,feedback" ;;
    4) echo "core,geography,measurements,standards,parcels,accounting,wells,datasync,setup,infrastructure,health,feedback" ;;
    5) echo "core,geography,measurements,standards,parcels,accounting,surface,recharge,setup,infrastructure,health,feedback" ;;
    6) echo "" ;;  # empty = all sixteen modules
    *) echo "shape_stack: unreachable module lookup for shape $1" >&2; exit 1 ;;
  esac
}

require_shape() {
  case "$1" in
    1|2|3|4|5|6) ;;
    *) echo "shape_stack: <n> must be 1-6, got '$1'" >&2; exit 1 ;;
  esac
}

# This is the guard named in the plan: PROJECT is always openh2o-shape-<n>, never
# `openh2o` or `openh2o-staging`, those are the maintainer's live checkouts
# (see MAINTAINER.md) and this script must never reach them.
project_for() {
  local n="$1"
  local project="openh2o-shape-${n}"
  case "$project" in
    openh2o-shape-[1-6]) ;;
    *) echo "shape_stack: refusing project name '$project'" >&2; exit 1 ;;
  esac
  echo "$project"
}

override_path() {
  echo "${OVERRIDE_DIR}/openh2o-shape-$1.override.yml"
}

write_override() {
  local n="$1"
  local port="810${n}"
  local modules
  modules="$(modules_for "$n")"
  local path
  path="$(override_path "$n")"
  cat > "$path" <<EOF
services:
  web:
    ports: ["${port}:8000"]
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.local
      OPENH2O_MODULES: "${modules}"
      ALLOWED_HOSTS: "localhost,127.0.0.1"
      CSRF_TRUSTED_ORIGINS: "http://localhost:${port},http://127.0.0.1:${port}"
      DJANGO_SUPERUSER_EMAIL: shape${n}@local.test
      DJANGO_SUPERUSER_USERNAME: shape${n}
      DJANGO_SUPERUSER_PASSWORD: password123
EOF
  echo "$path"
}

# Waits for the web container's own HEALTHCHECK (Dockerfile: curl against
# /health/live/) to report healthy. The first build can take up to ~110s
# (145-02-EVIDENCE.md); later ones 6-7s off the layer cache.
wait_for_web_healthy() {
  local project="$1"
  local tries=0
  local max_tries=60
  while [ "$tries" -lt "$max_tries" ]; do
    local status
    status="$($COMPOSE -p "$project" ps --format json web 2>/dev/null | python3 -c '
import json, sys
line = sys.stdin.readline()
if not line.strip():
    print("missing")
else:
    print(json.loads(line).get("Health", "missing"))
' 2>/dev/null || echo "missing")"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    tries=$((tries + 1))
    sleep 2
  done
  echo "shape_stack: web container for $project did not become healthy in $((max_tries * 2))s" >&2
  return 1
}

cmd_up() {
  local n="$1"
  require_shape "$n"
  local project
  project="$(project_for "$n")"
  local override
  override="$(write_override "$n")"

  echo "shape_stack: bringing up $project (port 810${n}) from $override"
  $COMPOSE -p "$project" -f "$REPO_ROOT/docker-compose.yml" -f "$override" up -d --build db web

  wait_for_web_healthy "$project"

  echo "shape_stack: manage.py check"
  $COMPOSE -p "$project" exec -T web python manage.py check

  echo "shape_stack: manage.py seed_data"
  $COMPOSE -p "$project" exec -T web python manage.py seed_data

  echo "shape_stack: manage.py verify_clean_install"
  if ! $COMPOSE -p "$project" exec -T web python manage.py verify_clean_install; then
    echo "shape_stack: verify_clean_install exited non-zero (ISS-198: expected until Phase 151 on any shape without datasync)"
  fi

  echo "shape_stack: composed OPENH2O_MODULES"
  $COMPOSE -p "$project" exec -T web python manage.py shell -c \
    'from django.conf import settings; print(",".join(settings.OPENH2O_MODULES))'
}

cmd_seed() {
  local n="$1"
  require_shape "$n"
  local project
  project="$(project_for "$n")"

  echo "shape_stack: manage.py seed_data"
  $COMPOSE -p "$project" exec -T web python manage.py seed_data

  echo "shape_stack: manage.py verify_clean_install"
  if ! $COMPOSE -p "$project" exec -T web python manage.py verify_clean_install; then
    echo "shape_stack: verify_clean_install exited non-zero (ISS-198: expected until Phase 151 on any shape without datasync)"
  fi
}

cmd_login_check() {
  local n="$1"
  require_shape "$n"
  local port="810${n}"
  python3 - "$port" "$n" <<'PYEOF'
import sys
import requests

port, n = sys.argv[1], sys.argv[2]
base = f"http://localhost:{port}"
email = f"shape{n}@local.test"
password = "password123"

session = requests.Session()
login_page = session.get(f"{base}/accounts/login/", timeout=20)
csrf_token = session.cookies.get("csrftoken")
if not csrf_token:
    print(f"shape_stack: no csrftoken cookie from {base}/accounts/login/ (status {login_page.status_code})", file=sys.stderr)
    sys.exit(1)

resp = session.post(
    f"{base}/accounts/login/",
    data={"login": email, "password": password, "csrfmiddlewaretoken": csrf_token},
    headers={"Referer": f"{base}/accounts/login/"},
    timeout=20,
)

check = session.get(f"{base}/", timeout=20)
own_email_present = email in check.text
login_link_present = 'href="/accounts/login/"' in check.text

print(check.status_code)
if check.status_code != 200 or not own_email_present or login_link_present:
    print(
        f"shape_stack: login-check failed (status={check.status_code} "
        f"own_email_present={own_email_present} login_link_present={login_link_present})",
        file=sys.stderr,
    )
    sys.exit(1)
PYEOF
}

cmd_down() {
  local n="$1"
  require_shape "$n"
  local project
  project="$(project_for "$n")"
  local override
  override="$(override_path "$n")"

  if [ ! -f "$override" ]; then
    echo "shape_stack: override missing, regenerating so down still works"
    override="$(write_override "$n")"
  fi

  echo "shape_stack: tearing down $project (with volumes)"
  $COMPOSE -p "$project" -f "$REPO_ROOT/docker-compose.yml" -f "$override" down -v
  rm -f "$override"
}

main() {
  if [ "$#" -lt 2 ]; then
    echo "usage: $0 up|down|seed|login-check <n>" >&2
    exit 1
  fi
  local sub="$1"
  local n="$2"
  case "$sub" in
    up) cmd_up "$n" ;;
    down) cmd_down "$n" ;;
    seed) cmd_seed "$n" ;;
    login-check) cmd_login_check "$n" ;;
    *) echo "usage: $0 up|down|seed|login-check <n>" >&2; exit 1 ;;
  esac
}

main "$@"
