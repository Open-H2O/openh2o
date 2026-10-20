# SPDX-License-Identifier: AGPL-3.0-or-later
"""Temporary passwords and choosing your own (151-04, S3 A and S7 A).

Rows 9 to 20 of the approved account-sentences file. Addresses are fictional.
"""
import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from django.urls import reverse

from core.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-good-passw0rd"
TEMP = "temp-pass-4821"
CHOSEN = "my-own-pass-7733"
CHOOSE = "/profile/choose-password/"


@pytest.fixture(autouse=True)
def _enforced(settings):
    settings.ACCESS_CONTROL_ENFORCED = True


def _person(email, **extra):
    user = User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=True, **extra
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _body(response):
    return response.content.decode().replace("&#x27;", "'")


def _sign_in(email, password):
    client = Client()
    response = client.post(
        reverse("account_login"), {"login": email, "password": password}
    )
    return client, response


def _set_temp(jane, bob, password=TEMP):
    client = _client(jane)
    response = client.post(
        reverse("core:user_temp_password", args=[bob.pk]),
        {"password1": password, "password2": password},
    )
    return client, response


# -- The Set a temporary password page ----------------------------------------


def test_row_9_jane_sets_bobs_temporary_password():
    jane = _person("jane@example.com", agency_admin=True)
    bob = _person("bob@example.com")
    client, response = _set_temp(jane, bob)
    assert response.status_code == 302 and response.url == reverse("core:users_list")
    assert (
        "You set a temporary password for bob@example.com. OpenH2O will ask them "
        "to choose a new password the next time they sign in."
    ) in _body(client.get(reverse("core:users_list")))
    bob.refresh_from_db()
    assert bob.must_choose_password is True
    assert not bob.check_password(PASSWORD) and bob.check_password(TEMP)
    _client_, old = _sign_in("bob@example.com", PASSWORD)
    assert old.status_code == 200  # the sign-in form again: the old password fails
    _client_, new = _sign_in("bob@example.com", TEMP)
    assert new.status_code == 302


def test_rows_10_to_14_the_page_words():
    jane = _person("jane@example.com", agency_admin=True)
    bob = _person("bob@example.com")
    body = _body(_client(jane).get(reverse("core:user_temp_password", args=[bob.pk])))
    assert "<title>Set a temporary password - Open Water Accounting Platform</title>" in body
    assert body.count("Set a temporary password") >= 3  # title, heading, crumb
    assert (
        "This page sets a temporary password for bob@example.com. Their current "
        "password stops working when you click Set temporary password. OpenH2O "
        "will ask them to choose a new password the next time they sign in. "
        "OpenH2O does not email the person about the change."
    ) in body
    assert ">Temporary password</label>" in body
    assert ">Confirm temporary password</label>" in body
    assert ">Set temporary password</button>" in body
    assert "Back to Users" in body


def test_row_13_blank_boxes_and_the_mismatch_and_refusals():
    jane = _person("jane@example.com", agency_admin=True)
    bob = _person("bob@example.com")
    url = reverse("core:user_temp_password", args=[bob.pk])
    client = _client(jane)
    body = _body(client.post(url, {"password1": "", "password2": ""}))
    assert "Enter the temporary password." in body
    assert "Enter the temporary password again." in body
    body = _body(client.post(url, {"password1": TEMP, "password2": TEMP + "x"}))
    assert "The two new passwords do not match." in body
    body = _body(client.post(url, {"password1": "abc12", "password2": "abc12"}))
    assert "The password must have at least 8 characters." in body
    body = _body(client.post(url, {"password1": "bob@example.com", "password2": "bob@example.com"}))
    assert "The password is too similar to the email address." in body
    bob.refresh_from_db()
    assert bob.check_password(PASSWORD) and not bob.must_choose_password


def test_your_own_row_is_not_a_temporary_password_page():
    jane = _person("jane@example.com", agency_admin=True)
    url = reverse("core:user_temp_password", args=[jane.pk])
    assert _client(jane).get(url).status_code == 404


# -- Add user sets the flag ----------------------------------------------------


def test_a_user_added_with_add_user_must_choose_a_password():
    jane = _person("jane@example.com", agency_admin=True)
    _client(jane).post(reverse("core:user_create"), {
        "email": "added@example.com", "first_name": "", "last_name": "",
        "title": "", "password": "a-good-passw0rd", "role": "operator",
    })
    assert User.objects.get(email="added@example.com").must_choose_password is True


def test_rows_19_and_20_on_the_add_user_page():
    jane = _person("jane@example.com", agency_admin=True)
    body = _body(_client(jane).get(reverse("core:user_create")))
    assert "Add an account for each person who needs to sign in." in body
    assert "The person signs in with their email address and the starting password" in body
    assert "adds an account for one person" not in body


# -- The redirect --------------------------------------------------------------


@pytest.fixture
def flagged():
    jane = _person("jane@example.com", agency_admin=True)
    bob = _person("bob@example.com")
    _set_temp(jane, bob)
    client, response = _sign_in("bob@example.com", TEMP)
    assert response.status_code == 302
    return bob, client


@pytest.mark.parametrize("path", ["/", "/wells/", "/profile/", "/users/", "/changes/"])
def test_every_page_sends_a_flagged_person_to_the_choose_page(flagged, path):
    _bob, client = flagged
    response = client.get(path)
    assert response.status_code == 302 and response.url == CHOOSE


def test_a_flagged_host_administrator_goes_to_the_choose_page_before_admin():
    host = _person("host@example.com", is_staff=True, is_superuser=True)
    host.must_choose_password = True
    host.save(update_fields=["must_choose_password"])
    client = _client(host)
    response = client.get("/admin/")
    assert response.status_code == 302 and response.url == CHOOSE
    assert client.get(CHOOSE).status_code == 200  # no loop


def test_an_htmx_request_gets_hx_redirect(flagged):
    _bob, client = flagged
    response = client.get("/wells/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert response["HX-Redirect"] == CHOOSE


def test_the_choose_page_words_and_sign_out_signs_out(flagged):
    _bob, client = flagged
    body = _body(client.get(CHOOSE))
    assert "<title>Choose a new password - Open Water Accounting Platform</title>" in body
    assert "<h1 class=\"auth-title\">Choose a new password</h1>" in body
    assert (
        "An administrator set your current password. Choose a new password to continue."
    ) in body
    assert ">New password</label>" in body and ">Confirm new password</label>" in body
    assert ">Save password</button>" in body
    assert ">Sign out</button>" in body
    response = client.post(reverse("account_logout"))
    assert response.status_code == 302
    assert client.get("/profile/").url.startswith(reverse("account_login"))


def test_row_18_the_same_password_is_refused(flagged):
    bob, client = flagged
    body = _body(client.post(CHOOSE, {"password1": TEMP, "password2": TEMP}))
    assert "The new password must be different from your current password." in body
    bob.refresh_from_db()
    assert bob.must_choose_password is True


def test_the_choose_page_blanks_mismatch_and_refusals(flagged):
    _bob, client = flagged
    body = _body(client.post(CHOOSE, {"password1": "", "password2": ""}))
    assert "Enter the new password." in body and "Enter the new password again." in body
    body = _body(client.post(CHOOSE, {"password1": CHOSEN, "password2": CHOSEN + "x"}))
    assert "The two new passwords do not match." in body
    body = _body(client.post(CHOOSE, {"password1": "abc12", "password2": "abc12"}))
    assert "The password must have at least 8 characters." in body


def test_choosing_clears_the_flag_and_keeps_the_person_signed_in(flagged):
    bob, client = flagged
    response = client.post(CHOOSE, {"password1": CHOSEN, "password2": CHOSEN})
    assert response.status_code == 302 and response.url == "/"
    bob.refresh_from_db()
    assert bob.must_choose_password is False and bob.check_password(CHOSEN)
    assert client.get("/").status_code == 200
    # "/" shows no messages; the profile does, and keeps the sentence for it.
    assert "You changed your password." in _body(client.get("/profile/"))


def test_a_person_without_the_flag_who_opens_the_choose_page_goes_home():
    bob = _person("bob@example.com")
    response = _client(bob).get(CHOOSE)
    assert response.status_code == 302 and response.url == "/"


def test_a_flagged_viewer_can_post_the_choose_page():
    viewer = _person("viewer@example.com", read_only=True)
    viewer.must_choose_password = True
    viewer.save(update_fields=["must_choose_password"])
    client = _client(viewer)
    # A GET is not refused as a write page.
    assert client.get(CHOOSE).status_code == 200
    response = client.post(CHOOSE, {"password1": CHOSEN, "password2": CHOSEN})
    assert response.status_code == 302 and response.url == "/"
    viewer.refresh_from_db()
    assert viewer.must_choose_password is False


def test_static_files_and_health_are_not_redirected(flagged):
    _bob, client = flagged
    assert client.get("/static/css/tokens.css").status_code != 302
