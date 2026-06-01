# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app Users page + switch-aware public signup (Phase 41-02, ISS-021).

Two contracts are locked here:

  1. The Users area (core.urls) is admin-gated, lets an administrator add a user
     who can then sign in by email, and flips admin/active state -- with two
     lock-out guards: you can't change your OWN status, and the LAST administrator
     can't be demoted or deactivated. The last-admin guard genuinely matters while
     the master switch is OFF, because admin_required is then a pass-through: any
     logged-in user (even an operator) can reach these endpoints during the demo,
     so the guard stops them nuking the only admin.

  2. Public signup follows the master switch via the allauth adapter: OFF -> open
     (demo unchanged), ON -> closed at allauth's own gate.

Pinned to config.settings.local (prod settings 301-redirect the test client).
"""
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from core.forms import UserCreateForm

User = get_user_model()

USERS_URL = reverse("core:users_list")


# --------------------------------------------------------------------------
# Builders (no UserFactory; mirror tests/test_access_control.py)
# --------------------------------------------------------------------------


def _operator(username="operator", email="operator@example.com"):
    return User.objects.create_user(
        username=username, email=email, password="x",
        is_active=True, is_staff=False, agency_admin=False,
    )


def _agency_admin(username="agencyadmin", email="admin@example.com"):
    return User.objects.create_user(
        username=username, email=email, password="x",
        is_active=True, is_staff=False, agency_admin=True,
    )


def _superuser(username="super", email="super@example.com"):
    return User.objects.create_user(
        username=username, email=email, password="x",
        is_active=True, is_staff=True, is_superuser=True,
    )


def _client_for(user):
    c = Client()
    c.force_login(user)
    return c


# --------------------------------------------------------------------------
# Access: the Users area rides the same gate as the rest of Phase 41
# --------------------------------------------------------------------------


def test_anonymous_redirected_to_login():
    assert Client().get(USERS_URL).status_code == 302


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_switch_on_operator_blocked():
    assert _client_for(_operator()).get(USERS_URL).status_code == 302


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_switch_on_admin_reaches_page():
    assert _client_for(_agency_admin()).get(USERS_URL).status_code == 200


# --------------------------------------------------------------------------
# Adding a user (UserCreateForm) -- can then sign in by email
# --------------------------------------------------------------------------


def test_create_form_mints_login_ready_user():
    form = UserCreateForm(data={
        "email": "New.Person@District.Gov",
        "first_name": "New", "last_name": "Person", "title": "Clerk",
        "password": "a-good-passw0rd", "agency_admin": False,
    })
    assert form.is_valid(), form.errors
    user = form.save()
    # Email normalized; username kept in lockstep; password usable.
    assert user.email == "new.person@district.gov"
    assert user.username == "new.person@district.gov"
    assert user.is_active
    assert user.check_password("a-good-passw0rd")
    assert not user.agency_admin
    # allauth authenticates against EmailAddress -- a verified primary row exists.
    ea = EmailAddress.objects.get(email="new.person@district.gov")
    assert ea.verified and ea.primary and ea.user_id == user.id


def test_create_form_administrator_checkbox_writes_flag():
    form = UserCreateForm(data={
        "email": "boss@district.gov", "first_name": "Boss", "last_name": "Person",
        "title": "", "password": "a-good-passw0rd", "agency_admin": True,
    })
    assert form.is_valid(), form.errors
    assert form.save().is_administrator


def test_create_form_rejects_duplicate_email():
    _operator(email="dupe@district.gov")
    form = UserCreateForm(data={
        "email": "Dupe@District.gov", "first_name": "", "last_name": "",
        "title": "", "password": "a-good-passw0rd", "agency_admin": False,
    })
    assert not form.is_valid()
    assert "email" in form.errors


def test_create_view_adds_user():
    c = _client_for(_agency_admin())
    resp = c.post(reverse("core:user_create"), {
        "email": "added@district.gov", "first_name": "Add", "last_name": "Ed",
        "title": "", "password": "a-good-passw0rd", "agency_admin": False,
    })
    assert resp.status_code == 302
    assert User.objects.filter(email="added@district.gov").exists()


# --------------------------------------------------------------------------
# Toggles + lock-out guards
# --------------------------------------------------------------------------


def test_toggle_admin_grants_and_revokes():
    actor = _superuser()
    target = _operator()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_admin", args=[target.pk]))
    target.refresh_from_db()
    assert target.agency_admin is True
    c.post(reverse("core:user_toggle_admin", args=[target.pk]))
    target.refresh_from_db()
    assert target.agency_admin is False


def test_cannot_revoke_own_admin():
    actor = _agency_admin()
    # A second admin exists, so only the self-guard (not last-admin) can stop this.
    _superuser()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_admin", args=[actor.pk]))
    actor.refresh_from_db()
    assert actor.agency_admin is True  # unchanged


def test_cannot_demote_last_administrator():
    # Switch OFF: admin_required is a pass-through, so an operator can reach the
    # endpoint and would otherwise strip the only admin. The guard stops it.
    only_admin = _agency_admin()
    actor = _operator()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_admin", args=[only_admin.pk]))
    only_admin.refresh_from_db()
    assert only_admin.agency_admin is True  # last admin protected


def test_staff_admin_status_not_togglable_here():
    actor = _agency_admin()
    staff = _superuser()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_admin", args=[staff.pk]))
    staff.refresh_from_db()
    assert staff.is_staff is True and staff.agency_admin is False  # untouched


def test_toggle_active_deactivates_and_reactivates():
    actor = _superuser()
    target = _operator()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_active", args=[target.pk]))
    target.refresh_from_db()
    assert target.is_active is False
    c.post(reverse("core:user_toggle_active", args=[target.pk]))
    target.refresh_from_db()
    assert target.is_active is True


def test_cannot_deactivate_self():
    actor = _superuser()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_active", args=[actor.pk]))
    actor.refresh_from_db()
    assert actor.is_active is True  # unchanged


def test_cannot_deactivate_last_administrator():
    only_admin = _agency_admin()
    actor = _operator()
    c = _client_for(actor)
    c.post(reverse("core:user_toggle_active", args=[only_admin.pk]))
    only_admin.refresh_from_db()
    assert only_admin.is_active is True  # last admin protected


# --------------------------------------------------------------------------
# Public signup follows the master switch (allauth adapter)
# --------------------------------------------------------------------------

SIGNUP_URL = reverse("account_signup")


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_signup_open_when_switch_off():
    resp = Client().get(SIGNUP_URL)
    assert resp.status_code == 200
    assert b"password1" in resp.content  # the signup form is served


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_signup_closed_when_switch_on():
    resp = Client().get(SIGNUP_URL)
    # allauth serves signup_closed (no form) when is_open_for_signup is False.
    assert b"password1" not in resp.content
