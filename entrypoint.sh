#!/bin/sh
# Container entrypoint. Runs the privileged boot steps as root, then drops
# privileges to the unprivileged `app` user to serve requests.
#
# Why the split: gunicorn is the process that handles untrusted input — feedback
# uploads (Pillow), spreadsheet/ZIP imports. If any of those has an RCE, we want
# it to land as `app`, not as root sitting next to the mounted secrets dir. The
# boot steps (collectstatic/migrate) need write access to the root-owned named
# volumes, so they stay root; then we chown the writable paths to `app` and exec
# gunicorn under it.
set -e

# One-off management commands (the CI clean-install steps, or any manual
# `docker compose run web python manage.py ...`) arrive here as arguments. Run
# that command as the app user and exit — do NOT fall through to the server boot.
# Without this the entrypoint ignored its arguments and always exec'd gunicorn,
# so every `docker compose run web <cmd>` silently started the web server and hung
# forever. That is what wedged the clean-install-guard CI (makemigrations --check
# never ran; the job just timed out). The no-argument path below is unchanged, so
# production `docker compose up` still boots and serves exactly as before.
if [ "$#" -gt 0 ]; then
    exec gosu app "$@"
fi

python manage.py collectstatic --noinput --clear
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py ensure_superuser

# Named volumes mounted over these paths are root-owned on first create (or from
# a prior root-run deployment); hand them to `app` so the non-root worker can
# still write user uploads and static output. Best-effort: a read-only mount
# would fail here and that is fine to ignore.
chown -R app:app /app/media /app/staticfiles /app/logs 2>/dev/null || true

# Dynamic request concurrency. gthread lets each worker serve several requests
# while views wait on the DB or an external API (OpenET/CIMIS), so a press spike
# does not saturate a tiny fixed worker pool. Tune per host via .env; the default
# (3 workers x 4 threads = 12 concurrent) is safe on a 2-4GB VPS.
#
# --access-logfile turns on the record of who asked for what (ISS-121). Before
# this flag a deployment built from this repository's own documentation logged
# not one request, on either shape, and "has anyone opened this page" had no
# answer. For a public agency that record is also what answers a records request
# about the agency's own system.
#
# Why `-` (stdout) and not a path. A file here would need its own rotation, and
# /app/logs already belongs to the Django rotating handler in
# config/settings/production.py — a second writer with no rotation of its own is
# the thing that fills a disk. stdout is what `docker compose logs web` reads,
# and it is also what makes this ONE flag correct on both deployment shapes: the
# systemd unit in docs/INSTALL-WITHOUT-DOCKER.md carries the same flag pointed at
# a real path, because that shape has no container log to read.
#
# The /health/live/ healthcheck (Dockerfile) probes every 15s and will be most of
# this log's volume. That is accepted: it is an in-container curl to 127.0.0.1,
# so Caddy never sees it, and the Caddy log below is the clean visitor record.
exec gosu app gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile -
