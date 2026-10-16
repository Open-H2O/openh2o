# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sign-in pages' sentences Brent approved (150.1-02 screen 18, message
AB, 2026-10-15 20:58), and the code change with them: on a site with no mail
server the reset page said a link was sent while the email only reached the
server log, so it now says the site sends no email.
"""
import pytest
from django.test import Client, override_settings
from django.urls import reverse

CONSOLE = "django.core.mail.backends.console.EmailBackend"
SMTP = "django.core.mail.backends.smtp.EmailBackend"


def _get(name):
    return Client().get(reverse(name)).content.decode().replace("&#x27;", "'")


@pytest.mark.django_db
class TestResetPage:
    @override_settings(EMAIL_BACKEND=SMTP)
    def test_with_a_mail_server(self):
        body = _get("account_reset_password")
        assert (
            "Enter your email address, and OpenH2O will email you a link to reset "
            "your password."
        ) in body
        assert 'name="email"' in body
        assert "This site sends no email." not in body

    @override_settings(EMAIL_BACKEND=CONSOLE)
    def test_with_no_mail_server(self):
        body = _get("account_reset_password")
        assert "This site sends no email. Ask an administrator to reset your password." in body
        assert 'name="email"' not in body
        assert "Back to login" in body

    def test_reset_sent(self):
        body = _get("account_reset_password_done")
        assert (
            "OpenH2O emails a password reset link to the address you entered when it "
            "belongs to an account. If the email does not arrive, check your spam folder."
        ) in body
        assert "Back to login" in body and "Back to Login" not in body


@pytest.mark.django_db
def test_login_page_lines():
    body = _get("account_login")
    assert "Sign in to your water-data dashboard." not in body


@pytest.mark.django_db
def test_login_error_sentence():
    resp = Client().post(reverse("account_login"), {"login": "nobody@example.com", "password": "wrong"})
    assert "The email address and password do not match an account." in resp.content.decode()


@pytest.mark.django_db
def test_verification_sent():
    body = _get("account_email_verification_sent")
    assert "OpenH2O has emailed you a link to activate your account." in body
