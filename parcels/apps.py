# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class ParcelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parcels"

    def ready(self):
        import parcels.signals  # noqa: F401
