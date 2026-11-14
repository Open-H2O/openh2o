# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class DatasyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "datasync"

    def ready(self):
        from datasync import signals  # noqa: F401
