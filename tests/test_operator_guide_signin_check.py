# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-389: the operator guide's "check sign-in without a browser" command works.

The guide tells an operator to paste a Python snippet into `manage.py shell -c`.
This test pulls that snippet out of `docs/AI-OPERATOR-GUIDE.md` itself, runs it
against a site configured the way production is (HTTPS redirect on, secure
cookies on, the proxy header trusted), and checks that it prints 302, the status
the guide promises for a working sign-in.

Test data is INVENTED: the user below exists only inside this test.
"""
import contextlib
import io
import re
from pathlib import Path

import pytest
from django.test import override_settings

from core.models import User

pytestmark = pytest.mark.django_db

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "AI-OPERATOR-GUIDE.md"

TEST_HOST = "signin-check.example.org"
TEST_EMAIL = "signin-check-admin@example.org"  # invented test data
TEST_PASSWORD = "invented-test-password-4471"  # invented test data


def _guide_snippet():
    """The Python inside the shell-quoted `shell -c "..."` block that builds a Client."""
    text = GUIDE.read_text()
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        if "from django.test import Client" in block:
            match = re.search(r'shell -c "\n(.*?)\n"', block, re.DOTALL)
            assert match, "the sign-in block no longer has a shell -c \"...\" body"
            return match.group(1)
    raise AssertionError("no block in the operator guide builds a django Client")


def test_the_guides_signin_command_prints_302_on_an_https_site():
    code = _guide_snippet()
    assert "water.example.org" in code
    code = (
        code.replace("water.example.org", TEST_HOST)
        .replace("ADMIN_EMAIL", TEST_EMAIL)
        .replace("ADMIN_PASSWORD", TEST_PASSWORD)
    )
    User.objects.create_superuser(
        username="signincheckadmin", email=TEST_EMAIL, password=TEST_PASSWORD
    )

    out = io.StringIO()
    with override_settings(
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_SSL_REDIRECT=True,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        ALLOWED_HOSTS=[TEST_HOST],
    ), contextlib.redirect_stdout(out):
        exec(code, {})

    assert out.getvalue().strip() == "302"


def test_the_guide_no_longer_tells_the_operator_to_pass_secure_true():
    assert "secure=True" not in GUIDE.read_text()
