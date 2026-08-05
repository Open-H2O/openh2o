# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Local development settings.

Two lines in this module used to discard what the operator configured, without
saying so. Both now read the environment and keep the old value as the default,
so no existing development workflow changes and nothing is silently overridden.
"""

from .base import *  # noqa: F401, F403
from .base import env

DEBUG = True

# WAS a hardcoded ["*"], which threw away whatever the operator set in .env and
# never said a word — the exact line a clean-room deployment landed on when its
# ALLOWED_HOSTS appeared to have no effect. Reading the environment with ["*"]
# as the default keeps development behaviour identical while letting a
# deliberately-set value survive.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# WAS a hardcoded console backend, which meant a correctly configured Postmark
# or SMTP account PRINTED password-reset mail into a log file and sent nothing —
# a mail account that looks configured, tests as configured, and delivers no
# mail. Console stays the default, so development still prints; an operator who
# sets EMAIL_BACKEND now actually gets it.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
