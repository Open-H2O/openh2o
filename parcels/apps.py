from django.apps import AppConfig


class ParcelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parcels"

    def ready(self):
        import parcels.signals  # noqa: F401
