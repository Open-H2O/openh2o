# SPDX-License-Identifier: AGPL-3.0-or-later
"""
WSGI config for openh2o project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

application = get_wsgi_application()
