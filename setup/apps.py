from django.apps import AppConfig


class SetupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "setup"
    label = "setup"
    verbose_name = "Setup Wizard"
