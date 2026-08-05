# SPDX-License-Identifier: AGPL-3.0-or-later
"""`config.settings.local` must not override the operator in silence.

Two lines in that module used to discard what the operator configured and say
nothing: ``ALLOWED_HOSTS = ["*"]`` threw away the ``.env`` value, and a
hardcoded console ``EMAIL_BACKEND`` printed password-reset mail into a log file
while a correctly configured mail account sent nothing.

**How these tests reach the real code path.** The lines under test are module-
level expressions evaluated at import. So each test patches the process
environment and *reloads the actual settings module*, then reads what that
module produced. Asserting against a re-implementation of the expression would
prove only that the test can copy a line of code.

The fourth pair covers ``openh2o.W001`` — the warning that exists because
Django's generic ``security.W018`` was read by a clean-room deployment and
dismissed as expected output. Both directions are asserted: a check that cannot
be silent is not a check.
"""

import importlib
import os
from unittest import mock

from django.test import override_settings

from core.checks import DEBUG_WARNING_ID, check_development_settings_in_use

SETTINGS_MODULE = "config.settings.local"
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"


def _reload_local_settings():
    """Re-execute config/settings/local.py against the current environment.

    ``config.settings.base`` is already imported and is not re-executed, so this
    is cheap: it re-evaluates exactly the two expressions under test.
    """
    return importlib.reload(importlib.import_module(SETTINGS_MODULE))


def _environment_without(*names):
    """Patch os.environ with the named keys removed, restoring them after."""
    cleared = {key: value for key, value in os.environ.items() if key not in names}
    return mock.patch.dict(os.environ, cleared, clear=True)


class TestTheOperatorsValuesSurvive:
    def test_an_operator_set_allowed_hosts_is_not_discarded(self):
        with mock.patch.dict(os.environ, {"ALLOWED_HOSTS": "water.example.org"}):
            local = _reload_local_settings()

        assert local.ALLOWED_HOSTS == ["water.example.org"], (
            "local settings threw away the operator's ALLOWED_HOSTS and "
            f"substituted its own value: {local.ALLOWED_HOSTS!r}"
        )

    def test_an_operator_set_email_backend_is_not_discarded(self):
        smtp = "django.core.mail.backends.smtp.EmailBackend"
        with mock.patch.dict(os.environ, {"EMAIL_BACKEND": smtp}):
            local = _reload_local_settings()

        assert local.EMAIL_BACKEND == smtp, (
            "local settings overrode a configured mail backend with the console "
            "one, which prints password-reset mail to a log file and sends "
            f"nothing: {local.EMAIL_BACKEND!r}"
        )


class TestTodaysDefaultsAreUnchanged:
    def test_allowed_hosts_still_defaults_to_everything(self):
        with _environment_without("ALLOWED_HOSTS"):
            local = _reload_local_settings()

        assert local.ALLOWED_HOSTS == ["*"], (
            "development settings must keep working with no configuration at "
            f"all; got {local.ALLOWED_HOSTS!r}"
        )

    def test_email_still_defaults_to_the_console(self):
        with _environment_without("EMAIL_BACKEND"):
            local = _reload_local_settings()

        assert local.EMAIL_BACKEND == CONSOLE_BACKEND, (
            "development must still print mail to the console when nothing is "
            f"configured; got {local.EMAIL_BACKEND!r}"
        )


class TestTheDevelopmentSettingsWarning:
    @override_settings(DEBUG=True)
    def test_it_fires_under_debug_and_points_at_the_supported_posture(self):
        warnings = check_development_settings_in_use(None)

        assert len(warnings) == 1, (
            f"expected exactly one warning under DEBUG=True, got {warnings!r}"
        )
        warning = warnings[0]
        assert warning.id == DEBUG_WARNING_ID
        assert "config.settings.production" in warning.hint, (
            "the warning must name the settings module that replaces this one"
        )
        assert "AI-OPERATOR-GUIDE.md" in warning.hint and "Phase 2" in warning.hint, (
            "the warning must point at the document that carries the posture "
            f"table; hint was: {warning.hint!r}"
        )

    @override_settings(DEBUG=False)
    def test_it_is_silent_under_production_settings(self):
        assert check_development_settings_in_use(None) == [], (
            "the warning fired with DEBUG=False, so it says nothing about "
            "which settings module is running and is not a measurement"
        )


def teardown_module(module):
    """Leave the imported settings module matching the real environment.

    Every test above reloads it under a patched environment. Without this the
    last patch's values would linger on the module object for anything that
    imports it later in the same session.
    """
    _reload_local_settings()
