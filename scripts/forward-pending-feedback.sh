#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Retry the best-effort forward for any in-app feedback that has not reached the
# triage pipeline yet, then alert if any remain stuck. Meant to run on a cron.
#
# Context: a feedback report is saved to THIS platform's DB first and only
# best-effort forwarded to the central triage pipeline (Gmail approval queue,
# feedback.vanderdev.net). Reports now survive the nightly demo reset (see
# reset-demo.sh), so a failed forward is no longer data loss — but without this,
# a report could sit in the DB forever and silently never reach the queue. This
# re-fires the forward (idempotent: a row flips forwarded=true once it lands) and
# makes a persistent failure LOUD instead of invisible.
#
# Reuses the already-deployed feedback.forwarder code via `manage.py shell` — no
# image rebuild needed. Set OPENH2O_NTFY_URL to enable the alert.
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$OPENH2O_DIR"
NTFY_URL="${OPENH2O_NTFY_URL:-}"

out="$(docker compose exec -T web python manage.py shell -c '
from feedback.models import Feedback
from feedback import forwarder
ids = list(Feedback.objects.filter(forwarded=False).values_list("id", flat=True))
for fid in ids:
    try:
        forwarder._forward(fid)   # synchronous; sets forwarded=True on success
    except Exception:
        pass
stuck = Feedback.objects.filter(forwarded=False).count()
print("RESULT retried=%d stuck=%d" % (len(ids), stuck))
' 2>/dev/null | sed -n 's/^RESULT //p')"

echo "[$(date '+%F %T')] forward-pending-feedback: ${out:-no-result}"

stuck="$(printf '%s' "$out" | sed -n 's/.*stuck=\([0-9]\{1,\}\).*/\1/p')"
if [ -n "$NTFY_URL" ] && [ "${stuck:-0}" -gt 0 ] 2>/dev/null; then
  curl -fsS -H "Title: OpenH2O feedback not reaching triage" -H "Priority: high" -H "Tags: warning" \
    -d "$stuck feedback report(s) on $(hostname) are saved in the platform DB but did NOT reach the triage pipeline after a retry. They are safe (durable in the DB) but need a look: feedback.vanderdev.net health + Django /admin/feedback/." \
    "$NTFY_URL" >/dev/null 2>&1 || true
fi
