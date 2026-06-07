# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app feedback intake: the durable record behind the Feedback button.

The widget (templates/partials/_feedback_widget.html) POSTs here same-origin,
so every report lands in the platform's own database FIRST — it survives even
if the optional downstream pipeline (n8n triage, set via FEEDBACK_ENDPOINT) is
unreachable. Screenshots ride along as FeedbackAttachment rows. A best-effort
forward to n8n happens after the row is committed (see feedback.forwarder); its
success is stamped on ``forwarded`` so a missed forward is visible, not silent.
"""
import uuid

from django.conf import settings
from django.db import models


def feedback_attachment_path(instance, filename):
    """Store attachments under media/feedback/<feedback_id>/<uuid>.<ext>.

    The client-supplied name is kept only as a label on the row (original_name);
    the on-disk name is a uuid so two users uploading "screenshot.png" never
    collide and a crafted filename can't escape the directory.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:8]
    return f"feedback/{instance.feedback_id}/{uuid.uuid4().hex}.{ext}"


class Feedback(models.Model):
    """One submission from the in-app Feedback button."""

    class Category(models.TextChoices):
        BUG = "bug", "Bug"
        IDEA = "idea", "Idea"
        QUESTION = "question", "Question"
        DATA = "data", "Data looks wrong"

    class Status(models.TextChoices):
        NEW = "new", "New"
        TRIAGED = "triaged", "Triaged"
        RESOLVED = "resolved", "Resolved"
        SPAM = "spam", "Spam"

    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.BUG
    )
    message = models.TextField()
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    page_url = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="feedback",
    )
    # Browser/runtime diagnostics gathered client-side at submit (JS errors,
    # failed requests, viewport/zoom, user-agent, build version, etc.) plus a
    # few server-authoritative fields merged in by the view.
    diagnostics = models.JSONField(default=dict, blank=True)
    remote_ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW
    )
    # True once the best-effort POST to FEEDBACK_ENDPOINT (n8n) succeeded.
    forwarded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "feedback"

    def __str__(self):
        return f"#{self.pk} {self.get_category_display()} — {self.message[:60]}"


class FeedbackAttachment(models.Model):
    """An image (usually a screenshot) attached to a Feedback submission."""

    feedback = models.ForeignKey(
        Feedback, on_delete=models.CASCADE, related_name="attachments"
    )
    image = models.ImageField(upload_to=feedback_attachment_path)
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name or self.image.name
