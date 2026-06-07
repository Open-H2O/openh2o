# SPDX-License-Identifier: AGPL-3.0-or-later
"""Best-effort forward of a stored Feedback row to the n8n triage pipeline.

The platform's database is the system of record; this forward is the optional
bridge to the central feedback-triage workflow (Gmail Approval-Queue, GitHub
issues). It only runs when FEEDBACK_ENDPOINT is set, runs in a daemon thread so
the user's request returns immediately, and swallows every error: a down n8n
must never cost a user their feedback or surface an error to them. Whether it
landed is recorded on Feedback.forwarded so a silent miss is still auditable.

Attachments are sent as the actual image bytes (multipart), not links, so the
files never have to be exposed on the public web for n8n to reach them.
"""
import logging
import threading

import requests
from django.conf import settings

logger = logging.getLogger("feedback")

FORWARD_TIMEOUT = 20  # seconds


def forward_async(feedback_id):
    """Fire the forward in a background daemon thread (non-blocking)."""
    if not settings.FEEDBACK_ENDPOINT:
        return
    threading.Thread(
        target=_forward, args=(feedback_id,), daemon=True
    ).start()


def _forward(feedback_id):
    from .models import Feedback

    try:
        fb = Feedback.objects.prefetch_related("attachments").get(pk=feedback_id)
    except Feedback.DoesNotExist:
        return

    payload = {
        "product": "openh2o",
        "id": fb.pk,
        "category": fb.category,
        "message": fb.message,
        "name": fb.name or "",
        "email": fb.email or "",
        "page_url": fb.page_url or "",
        "created_at": fb.created_at.isoformat(),
        # n8n receives diagnostics as a JSON string field (simplest to parse in
        # a Set/Code node) alongside the multipart parts.
        "diagnostics": _json(fb.diagnostics),
    }

    files = []
    opened = []
    ok = False
    try:
        for att in fb.attachments.all():
            handle = att.image.open("rb")
            opened.append(handle)
            label = att.original_name or att.image.name.rsplit("/", 1)[-1]
            files.append(
                ("attachments", (label, handle, att.content_type or "image/jpeg"))
            )
        resp = requests.post(
            settings.FEEDBACK_ENDPOINT,
            data=payload,
            files=files or None,
            timeout=FORWARD_TIMEOUT,
        )
        ok = resp.ok
        if not ok:
            logger.warning(
                "feedback #%s forward returned HTTP %s", fb.pk, resp.status_code
            )
    except Exception as exc:  # never let a forward failure escape
        logger.warning("feedback #%s forward failed: %s", feedback_id, exc)
    finally:
        for handle in opened:
            try:
                handle.close()
            except Exception:
                pass

    Feedback.objects.filter(pk=feedback_id).update(forwarded=ok)


def _json(value):
    import json

    try:
        return json.dumps(value or {})
    except (TypeError, ValueError):
        return "{}"
