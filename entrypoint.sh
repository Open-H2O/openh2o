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

python manage.py collectstatic --noinput --clear
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py ensure_superuser

# Named volumes mounted over these paths are root-owned on first create (or from
# a prior root-run deployment); hand them to `app` so the non-root worker can
# still write user uploads and static output. Best-effort: a read-only mount
# would fail here and that is fine to ignore.
chown -R app:app /app/media /app/staticfiles 2>/dev/null || true

# Dynamic request concurrency. gthread lets each worker serve several requests
# while views wait on the DB or an external API (OpenET/CIMIS), so a press spike
# does not saturate a tiny fixed worker pool. Tune per host via .env; the default
# (3 workers x 4 threads = 12 concurrent) is safe on a 2-4GB VPS.
exec gosu app gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout "${GUNICORN_TIMEOUT:-60}"
