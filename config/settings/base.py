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
    "accounting",
    "surface",
    "recharge",
    "datasync",
    "reporting",
    "health",
    "setup",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

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
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# -- Media files (user-uploaded / generated reports) -------------------------

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -- Default primary key field type ------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -- django-allauth ----------------------------------------------------------

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
SOCIALACCOUNT_PROVIDERS = {}

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

DATASYNC_MOCK_MODE = env.bool("DATASYNC_MOCK_MODE", default=True)
OPENET_CACHE_DAYS = int(os.environ.get("OPENET_CACHE_DAYS", "30"))
OPENET_MONTHLY_BUDGET = int(os.environ.get("OPENET_MONTHLY_BUDGET", "400"))

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
