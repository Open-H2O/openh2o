# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Local development settings.
"""

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Console email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
