# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account pages after ISS-248's design pass (Brent, 2026-10-17).

Decisions: an administrator changes a person's email address on the Users
page (05:09); one address per person, so allauth's email page is removed
(05:12); Change password and Set a password are app pages like the profile
(05:20). Words: message A (05:31) and message B (05:47), each line below.

Addresses are fictional (example.com, example.org).
"""
from pathlib import Path

import pytest
from allauth.account.models import EmailAddress
from django.conf import settings
from django.test import Client
from django.urls import reverse

from core.account_forms import (
    MISMATCH,
    ResetPasswordKeyForm,
    SignupForm,
)
from core.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-good-passw0rd"
NEW_PASSWORD = "another-g00d-one"


def _person(email, password=PASSWORD, **extra):
    user = User.objects.create_user(
        username=email, email=email, password=password, is_active=True, **extra
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _body(response):
    return response.content.decode().replace("&#x27;", "'")


def _signs_in(email, password):
    response = Client().post(
        reverse("account_login"), {"login": email, "password": password}
    )
    return response.status_code == 302


# -- The profile (message A rows 1, 2 and 11) --------------------------------


def test_profile_card_for_a_person():
    body = _body(_client(_person("probe.op@example.com")).get(reverse("profile")))
    assert "Ask an administrator to change your email address." in body
    assert "Another administrator can change your email address" not in body
    assert "Manage email" not in body
    assert "managed on their own pages" not in body
    assert "Change password" in body


def test_profile_card_for_an_administrator():
    admin = _person("probe.admin@example.com", agency_admin=True)
    body = _body(_client(admin).get(reverse("profile")))
    assert "Another administrator can change your email address on the Users page." in body
    assert "Ask an administrator to change your email address." not in body


def test_profile_card_for_a_host_administrator():
    # Brent 2026-10-17 10:43 ("A"): neither line is true for the account the
    # server's settings create, so it shows only the Change password button.
    host = _person("probe.host@example.com", is_staff=True, is_superuser=True)
    body = _body(_client(host).get(reverse("profile")))
    assert "change your email address" not in body
    assert ">Change password</a>" in body


def test_saving_the_profile_shows_no_unapproved_sentence():
    client = _client(_person("probe.save@example.com"))
    response = client.post(
        reverse("profile"),
        {"first_name": "Probe", "last_name": "", "phone": "", "title": ""},
        follow=True,
    )
    assert "Profile updated." not in _body(response)


# -- The removed email page ---------------------------------------------------


def test_the_email_page_is_gone():
    client = _client(_person("probe.gone@example.com"))
    assert client.get("/accounts/email/").status_code == 404
    assert client.post("/accounts/email/", {"email": "x@example.org",
                                             "action_add": ""}).status_code == 404
    assert EmailAddress.objects.filter(email="x@example.org").count() == 0


def test_no_template_links_to_the_email_page():
    hits = []
    for path in Path(settings.BASE_DIR, "templates").rglob("*.html"):
        text = path.read_text()
        if "'account_email'" in text or '"account_email"' in text or "/accounts/email/" in text:
            hits.append(str(path))
    assert hits == []


def test_one_address_per_person():
    assert settings.ACCOUNT_MAX_EMAIL_ADDRESSES == 1


# -- Change password (message A rows 3 to 11) --------------------------------


def test_change_password_page_words():
    body = _body(_client(_person("probe.cp@example.com")).get(
        reverse("account_change_password")))
    assert "<title>Change password - Open Water Accounting Platform</title>" in body
    assert ">Your profile</a>" in body
    assert (
        "When you change your password, OpenH2O keeps you signed in here and "
        "signs you out of every other browser."
    ) in body
    for label in ("Current password", "New password", "Confirm new password"):
        assert f">{label}</label>" in body
    assert ">Change password</button>" in body
    assert ">Forgot password?</a>" in body
    # Row 7: Django's rules list and allauth's Title Case labels are gone.
    assert "Your password can't" not in body
    assert "Current Password" not in body
    assert "New Password (again)" not in body
    # It is an app page (decision 3): the sidebar is there.
    assert "sidebar" in body


def test_change_password_blank_fields():
    client = _client(_person("probe.blank@example.com"))
    body = _body(client.post(reverse("account_change_password"),
                             {"oldpassword": "", "password1": "", "password2": ""}))
    assert "Enter your current password." in body
    assert "Enter the new password." in body
    assert "Enter the new password again." in body
    assert "This field is required." not in body


def test_change_password_wrong_current_password():
    client = _client(_person("probe.wrong@example.com"))
    body = _body(client.post(reverse("account_change_password"), {
        "oldpassword": "not-it", "password1": NEW_PASSWORD, "password2": NEW_PASSWORD}))
    assert "The current password does not match your account." in body
    assert "Please type your current password." not in body


def test_change_password_mismatch():
    client = _client(_person("probe.mismatch@example.com"))
    body = _body(client.post(reverse("account_change_password"), {
        "oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD + "x"}))
    assert "The two new passwords do not match." in body
    assert "You must type the same password each time." not in body


def test_change_password_refusals_are_the_approved_ones():
    client = _client(_person("probe.short@example.com"))
    body = _body(client.post(reverse("account_change_password"), {
        "oldpassword": PASSWORD, "password1": "12345", "password2": "12345"}))
    assert "The password must have at least 8 characters." in body
    assert "The password cannot be only digits." in body


def test_change_password_returns_to_the_profile_with_the_sentence():
    user = _person("probe.done@example.com")
    client = Client()
    assert client.login(username=user.username, password=PASSWORD)
    other = Client()
    assert other.login(username=user.username, password=PASSWORD)
    response = client.post(reverse("account_change_password"), {
        "oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("profile")
    body = _body(client.get(reverse("profile")))
    assert "You changed your password." in body
    assert "Password successfully changed." not in body
    # Row 4: this browser stays signed in; the other is signed out.
    assert client.get(reverse("profile")).status_code == 200
    assert other.get(reverse("profile")).status_code == 302
    assert _signs_in(user.email, NEW_PASSWORD)


def test_the_mismatch_sentence_on_every_page_that_sets_a_password():
    form = ResetPasswordKeyForm(
        data={"password1": NEW_PASSWORD, "password2": NEW_PASSWORD + "x"},
        user=_person("probe.reset@example.com"), temp_key="k")
    assert not form.is_valid()
    assert form.errors["password2"] == [MISMATCH]
    form = SignupForm(data={"email": "probe.signup@example.com",
                            "password1": NEW_PASSWORD, "password2": NEW_PASSWORD + "x"})
    assert not form.is_valid()
    assert form.errors["password2"] == [MISMATCH]


# -- Set a password (message B rows 1 to 3) ----------------------------------


def _google_only_person():
    user = _person("probe.google@example.com")
    user.set_unusable_password()
    user.save()
    return user


def test_change_password_sends_a_google_only_person_to_set_a_password():
    client = _client(_google_only_person())
    response = client.get(reverse("account_change_password"))
    assert response.status_code == 302
    assert response.url == reverse("account_set_password")


def test_set_a_password_page_words():
    body = _body(_client(_google_only_person()).get(reverse("account_set_password")))
    assert "<title>Set a password - Open Water Accounting Platform</title>" in body
    assert (
        "You sign in with Google. Set a password to sign in with your email "
        "address as well."
    ) in body
    assert ">New password</label>" in body
    assert ">Confirm new password</label>" in body
    assert ">Set password</button>" in body


def test_set_a_password_returns_to_the_profile_with_the_sentence():
    user = _google_only_person()
    client = _client(user)
    response = client.post(reverse("account_set_password"),
                           {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert response.url == reverse("profile")
    body = _body(client.get(reverse("profile")))
    assert "You set a password." in body
    assert "Password successfully set." not in body


# -- The Users page and Change email (message B rows 4 to 10) ----------------


@pytest.fixture
def admin():
    return _person("probe.admin@example.com", agency_admin=True)


def test_users_page_offers_change_email_on_other_rows_only(admin):
    jane = _person("jane@example.com")
    User.objects.create_user(username="host@example.com", email="host@example.com",
                             password="x", is_staff=True)
    body = _body(_client(admin).get(reverse("core:users_list")))
    assert reverse("core:user_email_edit", args=[jane.pk]) in body
    assert body.count(">Change email</a>") == 1
    assert (
        "You cannot change your own role, status or email address. Another "
        "administrator can."
    ) in body


def test_change_email_page_words(admin):
    jane = _person("jane@example.com")
    body = _body(_client(admin).get(reverse("core:user_email_edit", args=[jane.pk])))
    assert "<title>Change email address - Open Water Accounting Platform</title>" in body
    assert (
        "This page changes the email address jane@example.com signs in with. The "
        "new address takes effect immediately, and the password does not change. "
        "OpenH2O does not email the person about the change."
    ) in body
    assert ">New email address</label>" in body
    assert 'placeholder="name@example.com"' in body
    assert "Back to Users" in body


@pytest.mark.parametrize("typed, sentence", [
    ("", "Enter the email address."),
    ("jane@example", "jane@example is not a complete email address."),
    ("jane@example.com", "jane@example.com is already this person's email address."),
    ("taken@example.com", "The email address taken@example.com already belongs to an account."),
])
def test_change_email_refusals(admin, typed, sentence):
    jane = _person("jane@example.com")
    _person("taken@example.com")
    body = _body(_client(admin).post(
        reverse("core:user_email_edit", args=[jane.pk]), {"email": typed}))
    assert sentence in body
    jane.refresh_from_db()
    assert jane.email == "jane@example.com"


def test_change_email_refuses_a_second_address_on_file(admin):
    jane = _person("jane@example.com")
    other = _person("other@example.com")
    EmailAddress.objects.create(user=other, email="second@example.com")
    body = _body(_client(admin).post(
        reverse("core:user_email_edit", args=[jane.pk]), {"email": "second@example.com"}))
    assert "The email address second@example.com already belongs to an account." in body


def test_change_email_moves_the_sign_in_name(admin):
    jane = _person("jane@example.com")
    EmailAddress.objects.create(user=jane, email="jane.old2@example.com")
    client = _client(admin)
    response = client.post(reverse("core:user_email_edit", args=[jane.pk]),
                           {"email": "Jane.Doe@Example.org"})
    assert response.url == reverse("core:users_list")
    body = _body(client.get(reverse("core:users_list")))
    assert (
        "You changed the email address from jane@example.com to "
        "jane.doe@example.org."
    ) in body
    jane.refresh_from_db()
    assert (jane.email, jane.username) == ("jane.doe@example.org", "jane.doe@example.org")
    assert list(EmailAddress.objects.filter(user=jane).values_list(
        "email", "primary", "verified")) == [("jane.doe@example.org", True, True)]
    assert _signs_in("jane.doe@example.org", PASSWORD)
    assert not _signs_in("jane@example.com", PASSWORD)
    assert not _signs_in("jane.old2@example.com", PASSWORD)


def test_change_email_is_not_for_your_own_or_a_host_account(admin):
    host = User.objects.create_user(username="host@example.com", email="host@example.com",
                                    password="x", is_staff=True)
    client = _client(admin)
    assert client.get(reverse("core:user_email_edit", args=[admin.pk])).status_code == 404
    assert client.get(reverse("core:user_email_edit", args=[host.pk])).status_code == 404


def test_change_email_is_for_administrators_only():
    jane = _person("jane@example.com")
    operator = _person("probe.op@example.com")
    response = _client(operator).post(
        reverse("core:user_email_edit", args=[jane.pk]), {"email": "x@example.org"})
    assert response.status_code in (302, 403)
    jane.refresh_from_db()
    assert jane.email == "jane@example.com"


# -- Add user (message B row 9 and the reworded row 2) ------------------------


def test_add_user_incomplete_address(admin):
    body = _body(_client(admin).post(reverse("core:user_create"), {
        "email": "jane@example", "password": PASSWORD, "role": "operator"}))
    assert "jane@example is not a complete email address." in body
    assert "Enter a valid email address." not in body
