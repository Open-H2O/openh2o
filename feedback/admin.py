# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin surface for triaging feedback by hand when needed.

The primary triage path is the n8n/Gmail pipeline, but the Django admin is the
always-available fallback and the canonical record. Diagnostics render as
pretty-printed JSON; attachments show inline with a thumbnail preview.
"""
import json

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Feedback, FeedbackAttachment


class FeedbackAttachmentInline(admin.TabularInline):
    model = FeedbackAttachment
    extra = 0
    readonly_fields = ("preview", "original_name", "content_type", "size", "created_at")
    fields = ("preview", "original_name", "content_type", "size", "created_at")

    def preview(self, obj):
        if obj.pk and obj.image:
            # Staff-only serving view, not the public media URL (no /media/ route
            # in production; attachments are kept off the public web).
            url = reverse("feedback:attachment", args=[obj.pk])
            return format_html(
                '<img src="{}" style="max-height:120px;border-radius:6px;" />', url
            )
        return "—"

    preview.short_description = "Screenshot"


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "category",
        "status",
        "short_message",
        "name",
        "email",
        "forwarded",
    )
    list_filter = ("category", "status", "forwarded", "created_at")
    search_fields = ("message", "name", "email", "page_url")
    list_editable = ("status",)
    readonly_fields = (
        "created_at",
        "user",
        "remote_ip",
        "page_url",
        "forwarded",
        "diagnostics_pretty",
    )
    exclude = ("diagnostics",)
    inlines = (FeedbackAttachmentInline,)
    date_hierarchy = "created_at"

    def short_message(self, obj):
        return (obj.message or "")[:80]

    short_message.short_description = "Message"

    def diagnostics_pretty(self, obj):
        try:
            blob = json.dumps(obj.diagnostics or {}, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            blob = str(obj.diagnostics)
        # diagnostics is fully attacker-controlled (raw client POST), and
        # json.dumps does NOT escape <, >, or / — so an unescaped value like
        # "</pre><img src=x onerror=...>" would break out of the <pre> and run
        # script in the admin's authenticated session (stored XSS). format_html
        # escapes the {} argument, neutralizing the payload while keeping the
        # <pre> wrapper literal.
        return format_html(
            '<pre style="white-space:pre-wrap;max-height:480px;overflow:auto;">{}</pre>',
            blob,
        )

    diagnostics_pretty.short_description = "Diagnostics"
