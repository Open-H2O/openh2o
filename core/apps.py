# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Registered here rather than at import time so the check is bound once,
        # after the app registry is populated. Imported inside ready() because
        # core/checks.py reads settings.
        from django.core.checks import register

        from .checks import check_development_settings_in_use

        register(check_development_settings_in_use)
