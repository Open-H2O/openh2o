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
        from django.db.models.signals import post_migrate

        from .checks import check_development_settings_in_use, check_site_identity_is_set
        from .site_identity import apply_site_identity

        register(check_development_settings_in_use)
        register(check_site_identity_is_set)

        # Fill in the Site row once migrations have finished, never
        # here: ready() runs before the tables exist. sender=self keeps it to
        # one firing per `migrate`, not one per installed app.
        # The finalized-year lock reads a date-and-time column as the site's
        # day; each connection carries the site's TIME_ZONE for it.
        from django.db.backends.signals import connection_created

        from accounting.locks import set_session_time_zone

        connection_created.connect(
            set_session_time_zone, dispatch_uid="accounting.locks.set_session_time_zone"
        )

        post_migrate.connect(
            apply_site_identity,
            sender=self,
            dispatch_uid="core.apply_site_identity",
        )
