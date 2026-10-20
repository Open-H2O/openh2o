# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host administrators on the Users page (151-04, ISS-260).

A host administrator is ``is_staff``. Only a host administrator changes a host
administrator's account, in the views as well as on the page. The sentences are
rows 1 to 8 of the approved account-sentences file. Addresses are fictional.
"""
import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from django.urls import reverse

from core.forms import role_of
from core.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-good-passw0rd"
ROW_4 = "Only a host administrator can change this account."
ROW_8 = "Only a host administrator can change a host administrator's account."
USERS = "core:users_list"


@pytest.fixture(autouse=True)
def _enforced(settings):
    settings.ACCESS_CONTROL_ENFORCED = True


def _person(email, **extra):
    user = User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=True, **extra
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _host(email="host@example.com"):
    return _person(email, is_staff=True, is_superuser=True)


def _agency_admin(email="agency@example.com"):
    return _person(email, agency_admin=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _body(response):
    return response.content.decode().replace("&#x27;", "'")


def _after(client, response):
    """The Users page the redirect lands on, so the messages show."""
    assert response.status_code == 302
    return _body(client.get(reverse(USERS)))


def _signs_in(email, password):
    response = Client().post(
        reverse("account_login"), {"login": email, "password": password}
    )
    return response.status_code == 302


# -- ISS-260 first: the request posted past the page -----------------------------


def test_iss_260_an_agency_administrator_cannot_deactivate_a_host_administrator():
    host = _host()
    client = _client(_agency_admin())
    response = client.post(reverse("core:user_toggle_active", args=[host.pk]))
    assert ROW_8 in _after(client, response)
    host.refresh_from_db()
    assert host.is_active is True


def test_a_non_host_administrator_is_refused_on_set_role():
    host = _host()
    client = _client(_agency_admin())
    response = client.post(
        reverse("core:user_set_role", args=[host.pk]), {"role": "viewer"}
    )
    assert ROW_8 in _after(client, response)
    host.refresh_from_db()
    assert (host.is_staff, host.is_superuser, host.read_only) == (True, True, False)


def test_a_non_host_administrator_is_refused_on_change_email_get_and_post():
    host = _host()
    client = _client(_agency_admin())
    url = reverse("core:user_email_edit", args=[host.pk])
    get = client.get(url)
    assert ROW_8 in _after(client, get)
    post = client.post(url, {"email": "new.host@example.org"})
    assert ROW_8 in _after(client, post)
    host.refresh_from_db()
    assert host.email == "host@example.com"


def test_a_non_host_administrator_is_refused_on_temporary_password():
    host = _host()
    client = _client(_agency_admin())
    url = reverse("core:user_temp_password", args=[host.pk])
    assert ROW_8 in _after(client, client.get(url))
    post = client.post(url, {"password1": "temp-pass-4821", "password2": "temp-pass-4821"})
    assert ROW_8 in _after(client, post)
    host.refresh_from_db()
    assert host.check_password(PASSWORD) and not host.must_choose_password


def test_a_non_host_administrator_cannot_set_the_host_role_on_anyone():
    operator = _person("operator@example.com")
    client = _client(_agency_admin())
    response = client.post(
        reverse("core:user_set_role", args=[operator.pk]),
        {"role": "host_administrator"},
    )
    assert ROW_8 in _after(client, response)
    operator.refresh_from_db()
    assert (operator.is_staff, operator.is_superuser) == (False, False)


# -- A host administrator acts on another host administrator ---------------------


def test_a_host_administrator_changes_another_hosts_email():
    other = _host("other.host@example.com")
    client = _client(_host())
    response = client.post(
        reverse("core:user_email_edit", args=[other.pk]),
        {"email": "other.new@example.org"},
    )
    assert response.status_code == 302
    other.refresh_from_db()
    assert other.email == "other.new@example.org"
    assert _signs_in("other.new@example.org", PASSWORD)
    assert not _signs_in("other.host@example.com", PASSWORD)


def test_a_host_administrator_deactivates_and_reactivates_another_host():
    other = _host("other.host@example.com")
    client = _client(_host())
    url = reverse("core:user_toggle_active", args=[other.pk])
    client.post(url)
    other.refresh_from_db()
    assert other.is_active is False
    client.post(url)
    other.refresh_from_db()
    assert other.is_active is True


def test_a_host_administrator_makes_an_operator_a_host_administrator_and_back():
    operator = _person("operator@example.com")
    client = _client(_host())
    url = reverse("core:user_set_role", args=[operator.pk])
    response = client.post(url, {"role": "host_administrator"})
    assert "operator@example.com is now a host administrator." in _after(client, response)
    operator.refresh_from_db()
    assert (operator.is_staff, operator.is_superuser) == (True, True)
    assert (operator.agency_admin, operator.read_only) == (False, False)
    assert role_of(operator) == "host_administrator"
    client.post(url, {"role": "operator"})
    operator.refresh_from_db()
    assert (operator.is_staff, operator.is_superuser) == (False, False)
    assert role_of(operator) == "operator"


def test_a_host_administrator_demoted_to_viewer_loses_the_host_rank():
    other = _host("other.host@example.com")
    _client(_host()).post(
        reverse("core:user_set_role", args=[other.pk]), {"role": "viewer"}
    )
    other.refresh_from_db()
    assert (other.is_staff, other.is_superuser, other.read_only) == (False, False, True)


# -- What the page shows ----------------------------------------------------------


def test_the_fourth_option_and_row_2_show_to_host_readers_only():
    _person("operator@example.com")
    host_body = _body(_client(_host()).get(reverse(USERS)))
    assert 'value="host_administrator"' in host_body
    assert ">Host administrator</option>" in host_body
    assert "You can also use the administration site at /admin/." in host_body
    admin_body = _body(_client(_agency_admin()).get(reverse(USERS)))
    assert 'value="host_administrator"' not in admin_body
    assert ">Host administrator</option>" not in admin_body
    assert "You can also use the administration site at /admin/." not in admin_body


def test_row_1_the_host_badge_shows_in_the_role_column():
    _host("badged.host@example.com")
    body = _body(_client(_agency_admin()).get(reverse(USERS)))
    assert '<span class="badge badge-pill badge-gold">Host administrator</span>' in body


def test_row_4_for_a_non_host_reader_and_no_controls_on_a_host_row():
    host = _host()
    body = _body(_client(_agency_admin()).get(reverse(USERS)))
    assert ROW_4 in body
    assert "managed outside this page" not in body
    assert reverse("core:user_toggle_active", args=[host.pk]) not in body
    assert reverse("core:user_email_edit", args=[host.pk]) not in body
    assert reverse("core:user_temp_password", args=[host.pk]) not in body


def test_row_5_on_a_host_readers_own_row_and_all_four_controls_on_another_host():
    me = _host()
    other = _host("other.host@example.com")
    body = _body(_client(me).get(reverse(USERS)))
    assert "You cannot change your own role, status or email address on this page." in body
    assert "Another administrator can." not in body
    assert reverse("core:user_toggle_active", args=[other.pk]) in body
    assert reverse("core:user_email_edit", args=[other.pk]) in body
    assert reverse("core:user_temp_password", args=[other.pk]) in body
    assert reverse("core:user_set_role", args=[other.pk]) in body
    assert body.count(">Set temporary password</a>") == 1


def test_a_non_host_administrators_own_row_keeps_the_approved_text():
    body = _body(_client(_agency_admin()).get(reverse(USERS)))
    assert (
        "You cannot change your own role, status or email address. Another "
        "administrator can."
    ) in body


def test_row_6_the_button_is_on_a_non_host_row_for_an_administrator():
    operator = _person("operator@example.com")
    body = _body(_client(_agency_admin()).get(reverse(USERS)))
    assert ">Set temporary password</a>" in body
    assert reverse("core:user_temp_password", args=[operator.pk]) in body


# -- Guards that stay --------------------------------------------------------------


def test_the_self_guards_still_hold_for_a_host_administrator():
    me = _host()
    client = _client(me)
    client.post(reverse("core:user_toggle_active", args=[me.pk]))
    client.post(reverse("core:user_set_role", args=[me.pk]), {"role": "viewer"})
    me.refresh_from_db()
    assert me.is_active and me.is_staff and not me.read_only


def test_the_last_administrator_guard_still_holds(settings):
    # With the switch off an operator reaches the endpoint, so only the guard
    # stands between the one administrator and a demotion.
    settings.ACCESS_CONTROL_ENFORCED = False
    only = _agency_admin()
    me = _person("operator@example.com")
    assert only.is_administrator
    client = _client(me)
    client.post(reverse("core:user_set_role", args=[only.pk]), {"role": "viewer"})
    only.refresh_from_db()
    assert only.agency_admin is True
