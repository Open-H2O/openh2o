# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Base settings for Open Water Accounting Platform.

All secrets loaded from environment via django-environ.
"""

import os
from pathlib import Path

import environ

# -- Paths -------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()

# Read .env file if it exists (local development)
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

# -- Security ----------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# -- Application definition -------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.sites",
    # Third-party
    "django_extensions",
    "django_htmx",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    # Local
    "core",
    "geography",
    "parcels",
    "wells",
    "measurements",
    "standards",
    "accounting",
    "surface",
    "recharge",
    "datasync",
    "reporting",
    "health",
    "setup",
    "infrastructure",
    "feedback",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_config",
                "core.context_processors.analytics",
                "core.context_processors.feedback",
                "core.context_processors.access_flags",
                "core.context_processors.setup_status",
                "core.context_processors.app_version",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Build version stamp (git describe), baked into the image at build time by the
# Dockerfile ARG/ENV. Surfaced in the footer so any bug report can name the exact
# build. "dev" on an un-stamped local build.
APP_VERSION = os.environ.get("APP_VERSION", "dev")

# -- Database ----------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgis://openh2o:openh2o@db:5432/openh2o",
        engine="django.contrib.gis.db.backends.postgis",
    )
}

# -- Auth --------------------------------------------------------------------

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="America/Los_Angeles")
USE_I18N = True
USE_TZ = True

# -- Static files ------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    # Default file storage for user uploads (feedback screenshots, SiteConfig
    # logo). Overriding STORAGES replaces it wholesale — Django does NOT backfill
    # the "default" key, so it must be declared explicitly or every FileField/
    # ImageField save raises "Could not find config for 'default'".
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# -- Media files (user-uploaded / generated reports) -------------------------

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -- Upload limits -----------------------------------------------------------
# Bound request bodies so a multi-GB or zip-bomb upload can't exhaust the small
# target VPS (2-4GB). DATA_UPLOAD_MAX_MEMORY_SIZE caps non-file POST bodies (the
# bulk-import "commit" step re-posts parsed rows as JSON — 10 MB is generous for
# the 500-row cap while still bounding it). FILE_UPLOAD_MAX_MEMORY_SIZE is the
# threshold above which an uploaded file spools to a temp file instead of RAM.
# These do NOT cap the uploaded FILE size itself — that hard ceiling lives in
# infrastructure.importer (MAX_UPLOAD_BYTES / MAX_EXTRACTED_BYTES).
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB

# -- Default primary key field type ------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -- django-allauth ----------------------------------------------------------

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
# Closes public signup when ACCESS_CONTROL_ENFORCED is ON (the default); set it
# OFF only on an open demo where self-registration should stay open. See
# core.adapters / ISS-021.
ACCOUNT_ADAPTER = "core.adapters.AccessControlledAccountAdapter"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
SOCIALACCOUNT_PROVIDERS = {}

# -- Access control (two-tier model, ISS-021) --------------------------------
# Master switch for the Administrator vs Operator access model.
#   ON (default) = secure posture for a real agency: enforce admin_required
#       gates (Setup Wizard, Methodology) and close public self-signup, so a
#       district that just stands the platform up isn't left open to the world.
#       A superuser (createsuperuser) is already an administrator, so the
#       deployer is never locked out — see core.access.is_administrator.
#   OFF = open-demo posture: any logged-in user reaches every screen and public
#       self-registration is open. Set ACCESS_CONTROL_ENFORCED=False only on a
#       demo/eval deployment (our hosted demo does exactly this).
# See core.access for the switch-aware decorator.
ACCESS_CONTROL_ENFORCED = env.bool("ACCESS_CONTROL_ENFORCED", default=True)

# -- Email -------------------------------------------------------------------

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@openh2o.com")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")

# -- Google OAuth (optional) -------------------------------------------------

_google_client_id = env("GOOGLE_OAUTH_CLIENT_ID", default="")
_google_client_secret = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")

# -- Datasync ----------------------------------------------------------------

DATASYNC_MOCK_MODE = env.bool("DATASYNC_MOCK_MODE", default=False)
OPENET_CACHE_DAYS = int(os.environ.get("OPENET_CACHE_DAYS", "30"))
OPENET_MONTHLY_BUDGET = int(os.environ.get("OPENET_MONTHLY_BUDGET", "400"))

# OpenET source selection: "api" = OpenET REST API (default, the live path);
# "gee" = pull the same OpenET Ensemble collection directly from Google Earth
# Engine (opt-in, for large districts). See docs/earth-engine-tier-setup.md.
OPENET_MODE = env("OPENET_MODE", default="api")
GEE_PROJECT = env("GEE_PROJECT", default="")
GEE_SERVICE_ACCOUNT_EMAIL = env("GEE_SERVICE_ACCOUNT_EMAIL", default="")

# -- Analytics ---------------------------------------------------------------
# Umami is opt-in and deployment-specific. UMAMI_WEBSITE_ID is blank by default
# so a self-hosted copy reports traffic to no one; the tracking <script> only
# renders when this is set (see core.context_processors.analytics and the
# base templates). Set it in the environment on your own deployment only.
UMAMI_WEBSITE_ID = env("UMAMI_WEBSITE_ID", default="")
UMAMI_SCRIPT_URL = env("UMAMI_SCRIPT_URL", default="https://analytics.vanderdev.net/script.js")

# -- In-app feedback widget --------------------------------------------------
# The widget now POSTs to the platform's OWN intake endpoint (feedback.views.
# submit), so every report is stored locally first — durable on any deployment,
# including a self-hosted clone. FEEDBACK_ENABLED renders the button (OFF by
# default — a fresh district isn't asked to run a feedback inbox it has no one to
# read; set FEEDBACK_ENABLED=True to turn it on, e.g. on our demo and managed
# deployments). FEEDBACK_ENDPOINT is an OPTIONAL downstream forward target: when
# set, each stored submission is also POSTed (best-effort, with image bytes) to
# that URL — our n8n triage pipeline. Blank = store-only, phone home to no one.
FEEDBACK_ENABLED = env.bool("FEEDBACK_ENABLED", default=False)
FEEDBACK_ENDPOINT = env("FEEDBACK_ENDPOINT", default="")
FEEDBACK_MAX_ATTACHMENTS = env.int("FEEDBACK_MAX_ATTACHMENTS", default=5)
FEEDBACK_MAX_ATTACHMENT_BYTES = env.int(
    "FEEDBACK_MAX_ATTACHMENT_BYTES", default=8 * 1024 * 1024
)
FEEDBACK_MAX_MESSAGE_CHARS = env.int("FEEDBACK_MAX_MESSAGE_CHARS", default=5000)
FEEDBACK_MAX_DIAGNOSTICS_BYTES = env.int(
    "FEEDBACK_MAX_DIAGNOSTICS_BYTES", default=64 * 1024
)
FEEDBACK_RATE_LIMIT_PER_HOUR = env.int("FEEDBACK_RATE_LIMIT_PER_HOUR", default=20)
GEE_SERVICE_ACCOUNT_KEY_FILE = env("GEE_SERVICE_ACCOUNT_KEY_FILE", default="")

if _google_client_id and _google_client_secret:
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APP": {
                "client_id": _google_client_id,
                "secret": _google_client_secret,
            },
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
        }
    }

# One-click Google sign-in: skip allauth intermediate confirm page
SOCIALACCOUNT_LOGIN_ON_GET = True

# When Google vouches for a verified email that matches an existing account,
# sign into that account and link the social login (instead of erroring on the
# email collision). Safe because the provider verifies the email.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
