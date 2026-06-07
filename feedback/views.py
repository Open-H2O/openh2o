# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake endpoint for the in-app feedback widget.

Same-origin POST (multipart/form-data) from partials/_feedback_widget.html.
CSRF-protected (the widget sends the token in the X-CSRFToken header). Stores
the submission + any image attachments, then kicks off a best-effort forward to
the n8n pipeline. Returns small JSON the widget uses to show a confirmation.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .forwarder import forward_async
from .models import Feedback, FeedbackAttachment

logger = logging.getLogger("feedback")

# Defaults; overridable in settings so a deployment can tighten/loosen them.
MAX_ATTACHMENTS = getattr(settings, "FEEDBACK_MAX_ATTACHMENTS", 5)
MAX_ATTACHMENT_BYTES = getattr(settings, "FEEDBACK_MAX_ATTACHMENT_BYTES", 8 * 1024 * 1024)
MAX_MESSAGE_CHARS = getattr(settings, "FEEDBACK_MAX_MESSAGE_CHARS", 5000)
MAX_DIAGNOSTICS_BYTES = getattr(settings, "FEEDBACK_MAX_DIAGNOSTICS_BYTES", 64 * 1024)
RATE_LIMIT_PER_HOUR = getattr(settings, "FEEDBACK_RATE_LIMIT_PER_HOUR", 20)


def _client_ip(request):
    """Best-effort client IP. Trusts X-Forwarded-For's first hop only when set
    by our own reverse proxy (Caddy); falls back to REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@require_POST
def submit(request):
    if not settings.FEEDBACK_ENABLED:
        return JsonResponse({"ok": False, "error": "disabled"}, status=404)

    # Honeypot: a hidden field real users never see. If a bot fills it, accept
    # the request (so the bot sees success and moves on) but store nothing.
    if request.POST.get("website", "").strip():
        return JsonResponse({"ok": True, "ref": None})

    ip = _client_ip(request)

    # Light per-IP throttle. LocMemCache is per-process, so this is a soft brake
    # on abuse rather than a hard guarantee — adequate for a low-volume widget.
    if ip and RATE_LIMIT_PER_HOUR:
        key = f"feedback:rate:{ip}"
        count = cache.get(key, 0)
        if count >= RATE_LIMIT_PER_HOUR:
            return JsonResponse(
                {"ok": False, "error": "rate_limited"}, status=429
            )
        cache.set(key, count + 1, 3600)

    message = (request.POST.get("message") or "").strip()
    if not message:
        return JsonResponse(
            {"ok": False, "error": "Message is required."}, status=400
        )
    message = message[:MAX_MESSAGE_CHARS]

    category = (request.POST.get("category") or "").strip()
    if category not in Feedback.Category.values:
        category = Feedback.Category.BUG

    name = (request.POST.get("name") or "").strip()[:200]
    email = (request.POST.get("email") or "").strip()[:254]
    if email:
        try:
            validate_email(email)
        except ValidationError:
            email = ""  # drop a malformed email rather than reject the report

    page_url = (request.POST.get("page_url") or "").strip()[:2000]

    diagnostics = _parse_diagnostics(request.POST.get("diagnostics"))
    # Merge server-authoritative facts the client can't be trusted to report.
    diagnostics["server"] = {
        "remote_ip": ip,
        "user_id": request.user.id if request.user.is_authenticated else None,
        "user_email": request.user.email if request.user.is_authenticated else None,
        "is_staff": bool(getattr(request.user, "is_staff", False)),
        "agency_admin": bool(getattr(request.user, "agency_admin", False)),
    }

    fb = Feedback.objects.create(
        category=category,
        message=message,
        name=name,
        email=email,
        page_url=page_url,
        diagnostics=diagnostics,
        remote_ip=ip,
        user=request.user if request.user.is_authenticated else None,
    )

    _save_attachments(request, fb)

    # Best-effort, non-blocking hand-off to the triage pipeline.
    forward_async(fb.pk)

    return JsonResponse({"ok": True, "ref": fb.pk})


@require_GET
def attachment(request, pk):
    """Serve a feedback screenshot to staff only.

    Attachments are deliberately NOT on the public web (no /media/ route in
    production). This view streams the file through Django after checking the
    viewer is staff, so the admin's inline preview works without exposing
    user-submitted images to the world.
    """
    user = request.user
    if not (user.is_authenticated and user.is_staff):
        raise Http404
    att = get_object_or_404(FeedbackAttachment, pk=pk)
    return FileResponse(
        att.image.open("rb"),
        content_type=att.content_type or "application/octet-stream",
    )


def _parse_diagnostics(raw):
    """Parse the client diagnostics JSON, bounded in size, never raising."""
    if not raw:
        return {}
    if len(raw) > MAX_DIAGNOSTICS_BYTES:
        raw = raw[:MAX_DIAGNOSTICS_BYTES]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"_unparsed": True}
    return data if isinstance(data, dict) else {"_value": data}


def _save_attachments(request, fb):
    """Persist up to MAX_ATTACHMENTS image files; skip anything that isn't a
    sane-sized image rather than failing the whole submission."""
    saved = 0
    for upload in request.FILES.getlist("attachments"):
        if saved >= MAX_ATTACHMENTS:
            break
        ctype = (upload.content_type or "").lower()
        if not ctype.startswith("image/"):
            continue
        if upload.size and upload.size > MAX_ATTACHMENT_BYTES:
            continue
        try:
            FeedbackAttachment.objects.create(
                feedback=fb,
                image=upload,
                original_name=(upload.name or "")[:255],
                content_type=ctype[:100],
                size=upload.size or 0,
            )
            saved += 1
        except Exception as exc:
            # A corrupt image (ImageField/Pillow validation) shouldn't sink the
            # whole report — the text is the valuable part.
            logger.warning("feedback #%s attachment rejected: %s", fb.pk, exc)
    return saved
