# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Production settings.
"""

from .base import *  # noqa: F401, F403
from .base import env

DEBUG = False

# -- Security ----------------------------------------------------------------

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# HTTPS-only behaviours. They default ON so a real (TLS) deployment is secure
# out of the box; a plain-HTTP deployment behind a trusted network — e.g. the
# Tailscale-only staging box on http://butler:8081 — sets these False in its
# .env so the browser will actually send the session/CSRF cookies (a Secure
# cookie is never sent over http, which otherwise 403s every login). Never set
# these False on a deployment reachable over the public internet.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# -- Fail-fast hardening -----------------------------------------------------
# The development default password is fine inside the Docker network (the db
# port is never published), but it must never reach a public deployment. Refuse
# to boot in production if the database password or ALLOWED_HOSTS were left at
# their insecure defaults, rather than silently running an exposed instance.
from django.core.exceptions import ImproperlyConfigured  # noqa: E402

_db_password = DATABASES["default"].get("PASSWORD", "")  # noqa: F405
if _db_password in ("", "openh2o", "postgres", "password", "changeme"):
    raise ImproperlyConfigured(
        "Insecure database password in production. Set a strong POSTGRES_PASSWORD "
        "(or DATABASE_URL) in your .env before deploying. See DEPLOY.md."
    )

if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS is empty in production. Set it to your domain in .env "
        "(e.g. ALLOWED_HOSTS=water.example.org). See DEPLOY.md."
    )

# -- Logging -----------------------------------------------------------------
# With DEBUG=False, Django renders the generic 500 page but writes the traceback
# nowhere by default — an unhandled exception in production leaves zero trace
# (the signup-500 incident left nothing in `docker compose logs web`). Route the
# django.request logger to console at ERROR so tracebacks reach container stdout
# (captured by `docker compose logs web`), plus a catch-all root logger at
# WARNING. This lives in production.py because local already surfaces tracebacks
# via DEBUG=True, so this is the minimal correct home.
#
# Logs go to stdout only and do NOT survive container restarts. A future
# follow-up could ship them to a durable volume or an aggregator — out of scope
# here, and no external logging dependency is added.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}

# -- Email -------------------------------------------------------------------

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
