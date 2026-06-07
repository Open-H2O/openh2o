# SPDX-License-Identifier: AGPL-3.0-or-later
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import feedback.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Feedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("bug", "Bug"),
                            ("idea", "Idea"),
                            ("question", "Question"),
                            ("data", "Data looks wrong"),
                        ],
                        default="bug",
                        max_length=20,
                    ),
                ),
                ("message", models.TextField()),
                ("name", models.CharField(blank=True, max_length=200)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("page_url", models.TextField(blank=True)),
                ("diagnostics", models.JSONField(blank=True, default=dict)),
                ("remote_ip", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("triaged", "Triaged"),
                            ("resolved", "Resolved"),
                            ("spam", "Spam"),
                        ],
                        default="new",
                        max_length=20,
                    ),
                ),
                ("forwarded", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "feedback",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="FeedbackAttachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        upload_to=feedback.models.feedback_attachment_path
                    ),
                ),
                ("original_name", models.CharField(blank=True, max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=100)),
                ("size", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "feedback",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="feedback.feedback",
                    ),
                ),
            ],
        ),
    ]
