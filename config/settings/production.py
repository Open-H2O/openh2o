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

# The Docker HEALTHCHECK curls the liveness probe on the loopback interface from
# INSIDE the container, so its Host header is 127.0.0.1 — allow it. Appended AFTER
# the guard above so an empty operator-supplied ALLOWED_HOSTS still fails fast;
# loopback is unreachable from outside the container, so this widens nothing real.
ALLOWED_HOSTS = ALLOWED_HOSTS + ["127.0.0.1", "localhost"]  # noqa: F405

# ...and exempt that probe from the HTTPS redirect. SECURE_SSL_REDIRECT would
# otherwise answer the plain-HTTP in-container probe with a 301, which a strict
# healthcheck reads as failure. Everything else still redirects to HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^health/live/?$"]

# -- Logging -----------------------------------------------------------------
# With DEBUG=False, Django renders the generic 500 page but writes the traceback
# nowhere by default — an unhandled exception in production leaves zero trace
# (the signup-500 incident left nothing in `docker compose logs web`). Route the
# django.request logger to console at ERROR so tracebacks reach container stdout
# (captured by `docker compose logs web`), plus a catch-all root logger at
# WARNING. This lives in production.py because local already surfaces tracebacks
# via DEBUG=True, so this is the minimal correct home.
#
# Tracebacks go to BOTH the container stdout (so `docker compose logs web` still
# works live) AND a rotating file on a mounted volume, so they survive a container
# recreate/redeploy — a launch-week incident stays debuggable instead of vanishing
# with the old container. LOG_DIR is a mounted volume (see docker-compose.yml); the
# entrypoint owns it to the non-root app user. No external logging dependency.
import os  # noqa: E402

LOG_DIR = env("LOG_DIR", default="/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

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
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "openh2o.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB per file
            "backupCount": 5,               # keep ~50 MB of history, bounded
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "WARNING",
    },
}

# -- Email -------------------------------------------------------------------

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
