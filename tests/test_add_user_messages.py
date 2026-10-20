# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add user's sentences (150.1-02), and the code changes with them: an email address on file
as any account's address (a second address included) is refused instead of
moved onto the new account; Django's check against the email and names runs
(no user was passed, so it never did); each password refusal prints on its
own line (two ran together).

Addresses and names are fictional (example.com, Probe ...).
"""
import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from core.forms import ROLE_CHOICES, ROLE_HELP, UserCreateForm
from core.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    admin = User.objects.create(
        username="probe-admin@example.com", email="probe-admin@example.com",
        is_active=True, agency_admin=True,
    )
    client = Client()
    client.force_login(admin)
    return client


def _form(**data):
    base = {"email": "probe.new@example.com", "first_name": "", "last_name": "",
            "title": "", "password": "a-good-passw0rd", "role": "operator"}
    base.update(data)
    return UserCreateForm(data=base)


def test_page_words(admin_client):
    body = admin_client.get(reverse("core:user_create")).content.decode().replace("&#x27;", "'")
    assert "Add an account for each person who needs to sign in." in body
    assert (
        # 151-04 rows 19 and 20.
        "The person signs in with their email address and the starting password "
        "you set here. OpenH2O will ask them to choose a new password the first "
        "time they sign in. OpenH2O does not email them."
    ) in body
    assert "Sign-in &amp; Security" not in body and "Sign-in & Security" not in body
    assert 'placeholder="name@example.com"' in body
    assert "<span>Viewer</span>" in body
    assert ROLE_HELP in body
    assert "&mdash;" not in body.split("Details", 1)[1]


def test_role_words():
    assert dict(ROLE_CHOICES)["viewer"] == "Viewer"
    assert ROLE_HELP == (
        "Viewers read every record and change none. Operators also add, change "
        "and remove records. Administrators also manage users, set up the site, "
        "change the site's settings and finalize or reopen a water year."
    )


def test_blank_fields():
    form = _form(email="", password="")
    assert not form.is_valid()
    assert form.errors["email"] == ["Enter the email address."]
    assert form.errors["password"] == ["Enter the starting password."]


def test_an_address_on_file_is_refused():
    User.objects.create(username="probe.one@example.com", email="probe.one@example.com")
    form = _form(email="Probe.One@example.com")
    assert not form.is_valid()
    assert form.errors["email"] == [
        "The email address probe.one@example.com already belongs to an account."
    ]


def test_a_second_address_is_refused_and_stays_with_its_account():
    owner = User.objects.create(username="probe.owner@example.com", email="probe.owner@example.com")
    EmailAddress.objects.create(user=owner, email="probe.second@example.com", verified=True, primary=False)
    form = _form(email="probe.second@example.com")
    assert not form.is_valid()
    assert form.errors["email"] == [
        "The email address probe.second@example.com already belongs to an account."
    ]
    assert EmailAddress.objects.get(email="probe.second@example.com").user == owner


@pytest.mark.parametrize("password, sentence", [
    ("abc12", "The password must have at least 8 characters."),
    ("password123", "The password is one of about 20,000 common passwords that OpenH2O refuses."),
    ("83920174659", "The password cannot be only digits."),
])
def test_password_sentences(password, sentence):
    with pytest.raises(ValidationError) as caught:
        validate_password(password)
    assert sentence in caught.value.messages


def test_the_similarity_check_runs():
    form = _form(email="probe.marigold@example.com", password="probe.marigold")
    assert not form.is_valid()
    assert form.errors["password"] == ["The password is too similar to the email address."]
    form = _form(first_name="Bartholomew", password="bartholomew1")
    assert not form.is_valid()
    assert form.errors["password"] == ["The password is too similar to the first name."]


def test_each_refusal_on_its_own_line(admin_client):
    resp = admin_client.post(reverse("core:user_create"), {
        "email": "probe.short@example.com", "password": "abc", "role": "operator",
    })
    body = resp.content.decode()
    assert '<p class="form-error-text">The password must have at least 8 characters.</p>' in body
    assert (
        '<p class="form-error-text">The password is one of about 20,000 common '
        "passwords that OpenH2O refuses.</p>"
    ) in body
    assert not User.objects.filter(email="probe.short@example.com").exists()
