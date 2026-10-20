# SPDX-License-Identifier: AGPL-3.0-or-later
"""151-04: the reset email, the reset page on a site with no mail server
(ISS-259), the inactive page, the closed-signup page and /accounts/.

Addresses are fictional (example.com, example.org).
"""
import pytest
from allauth.account.models import EmailAddress
from django.contrib.sites.models import Site
from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse

from core.models import User

SMTP = "django.core.mail.backends.smtp.EmailBackend"
PASSWORD = "a-good-passw0rd"


def _person(email, password=PASSWORD, **extra):
    user = User.objects.create_user(
        username=email, email=email, password=password, **extra
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _body(response):
    return response.content.decode().replace("&#x27;", "'")


@override_settings(EMAIL_BACKEND=SMTP, EMAIL_HOST="")
def test_iss259_reset_page_without_a_mail_host_and_a_direct_post():
    page = _body(Client().get(reverse("account_reset_password")))
    assert "This site does not send email. Ask an administrator to set a temporary password for you." in page
    assert 'name="email"' not in page
    _person("jane@example.com")
    response = Client().post(
        reverse("account_reset_password"), {"email": "jane@example.com"}
    )
    assert response.status_code == 302
    assert mail.outbox == []


@override_settings(EMAIL_HOST="mail.example.org")
def test_reset_email_subject_and_body():
    _person("jane@example.com")
    Client().post(reverse("account_reset_password"), {"email": "jane@example.com"})
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["jane@example.com"]
    assert message.subject.endswith("] Reset your password")
    assert message.subject.count("Reset your password") == 1
    lines = message.body.split("\n")
    domain = Site.objects.get_current().domain
    assert lines[0] == (
        f"Someone asked to reset the password for jane@example.com on {domain}. "
        "Open this link to choose a new password:"
    )
    assert lines[1] == ""
    assert "/accounts/password/reset/key/" in lines[2]
    assert lines[3] == ""
    assert lines[4] == (
        "The link works once and expires in three days. If you did not ask for "
        "this, you can ignore this email. Your password has not changed."
    )
    assert len(lines) == 5
    assert "Hello from" not in message.body
    assert "Thank you for using" not in message.body


@override_settings(EMAIL_HOST="mail.example.org")
def test_an_address_with_no_account_sends_no_email():
    response = Client().post(
        reverse("account_reset_password"), {"email": "nobody@example.com"}
    )
    assert response.status_code == 302
    assert mail.outbox == []


def test_inactive_page_words():
    _person("gone@example.com", is_active=False)
    response = Client().post(
        reverse("account_login"), {"login": "gone@example.com", "password": PASSWORD}, follow=True
    )
    body = _body(response)
    assert "<h1 class=\"auth-title\">Account inactive</h1>" in body
    assert (
        "An administrator has deactivated this account. Ask an administrator to "
        "reactivate it if you need it again."
    ) in body
    assert "Back to login" in body
    assert "This account is inactive." not in body


def test_inactive_page_direct():
    body = _body(Client().get(reverse("account_inactive")))
    assert "Account inactive" in body and "Account Inactive" not in body


def test_closed_signup_page_sentence():
    body = _body(Client().get(reverse("account_signup")))
    assert (
        "The administrator creates your account and gives you a starting password. "
        "You choose a new password the first time you sign in."
    ) in body
    assert "then gives you the password" not in body


def test_accounts_root_signed_in_goes_to_the_profile():
    client = Client()
    client.force_login(_person("jane@example.com"))
    response = client.get("/accounts/")
    assert response.status_code == 302
    assert response.url == reverse("profile")


def test_accounts_root_anonymous_goes_to_login():
    response = Client().get("/accounts/")
    assert response.status_code == 302
    assert response.url == reverse("account_login")
