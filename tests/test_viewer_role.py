# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Viewer (read-only) role (147-02 Task 1).

A viewer signs in and reads every page; every unsafe request it makes is
refused by ``core.access.ReadOnlyMiddleware`` with a 403 and one sentence in
plain words, on every route, whatever ACCESS_CONTROL_ENFORCED says. An
operator's identical request still goes through. The allowlist (the viewer's
own sign-in and account, the feedback button, the sidebar switch and their
own contact details) is pinned here by name.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.http import urlencode

from parcels.models import ParcelLedger
from core.access import (
    READ_ONLY_MESSAGE,
    VIEWER_ALLOWED_URL_NAME_PREFIX,
    VIEWER_ALLOWED_URL_NAMES,
    viewer_may_post,
)
from tests.factories import ParcelFactory

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


@pytest.fixture
def operator():
    return _user("operator")


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _ledger_post(client, parcel):
    return client.post(
        reverse("accounting:ledger_create"),
        {
            "parcel": parcel.pk,
            "transaction_date": "2026-03-01",
            "effective_date": "2026-03-01",
            "amount_acre_feet": "-1.2500",
            "source_type": "manual_entry",
            "description": "viewer test",
        },
    )


def _area_patch(client, parcel, value):
    return client.patch(
        reverse("parcels:edit_field", args=[parcel.pk]),
        data=urlencode({"field": "area_acres", "value": value}),
        content_type="application/x-www-form-urlencoded",
    )


def _refused(response):
    return (response.status_code, READ_ONLY_MESSAGE in response.content.decode())


# -- The model -------------------------------------------------------------------


def test_a_viewer_cannot_also_be_an_administrator():
    for flags in ({"agency_admin": True}, {"is_staff": True}):
        user = User(username="both", read_only=True, **flags)
        with pytest.raises(ValidationError) as exc:
            user.clean()
        assert exc.value.messages == [
            "A viewer cannot also be an administrator. Choose one role."
        ]


def test_can_write_is_false_only_for_an_active_viewer():
    assert User(read_only=True, is_active=True).can_write is False
    assert User(read_only=False, is_active=True).can_write is True
    assert User(read_only=False, is_active=False).can_write is False


def test_role_label_reads_the_flags():
    assert User(agency_admin=True).role_label == "Administrator"
    assert User(is_staff=True).role_label == "Administrator"
    assert User(read_only=True).role_label == "Viewer"
    assert User().role_label == "Operator"


# -- Refused on every route --------------------------------------------------------


@pytest.mark.parametrize("enforced", [True, False])
def test_a_viewer_ledger_entry_is_refused_and_an_operators_is_not(viewer, operator, enforced):
    parcel = ParcelFactory(parcel_number="VIEW-001")
    with override_settings(ACCESS_CONTROL_ENFORCED=enforced):
        assert _refused(_ledger_post(_client(viewer), parcel)) == (403, True)
        assert ParcelLedger.objects.filter(parcel=parcel).count() == 0

        response = _ledger_post(_client(operator), parcel)
        assert response.status_code == 302
        entry = ParcelLedger.objects.get(parcel=parcel)
        assert entry.amount_acre_feet == Decimal("-1.2500")
        assert entry.effective_date == dt.date(2026, 3, 1)


@pytest.mark.parametrize("enforced", [True, False])
def test_a_viewer_area_patch_is_refused_and_an_operators_is_not(viewer, operator, enforced):
    parcel = ParcelFactory(parcel_number="VIEW-002", area_acres="12.50")
    with override_settings(ACCESS_CONTROL_ENFORCED=enforced):
        assert _refused(_area_patch(_client(viewer), parcel, "99.00")) == (403, True)
        parcel.refresh_from_db()
        assert parcel.area_acres == Decimal("12.50")

        assert _area_patch(_client(operator), parcel, "12.75").status_code == 200
        parcel.refresh_from_db()
        assert parcel.area_acres == Decimal("12.75")


def test_a_viewer_post_to_the_django_admin_is_refused(viewer):
    response = _client(viewer).post("/admin/accounting/parcelledger/add/", {})
    assert _refused(response) == (403, True)


def test_a_viewer_post_to_an_unknown_address_is_refused(viewer):
    assert _client(viewer).post("/no-such-page/", {}).status_code == 403


def test_a_viewer_put_and_delete_are_refused(viewer):
    parcel = ParcelFactory(parcel_number="VIEW-003")
    url = reverse("parcels:edit_field", args=[parcel.pk])
    client = _client(viewer)
    assert client.put(url, data="").status_code == 403
    assert client.delete(url).status_code == 403


def test_a_viewer_still_reads_pages(viewer):
    parcel = ParcelFactory(parcel_number="VIEW-004")
    client = _client(viewer)
    for url in (
        reverse("accounting:dashboard"),
        reverse("accounting:ledger_list"),
        reverse("parcels:detail", args=[parcel.pk]),
        reverse("change_history"),
    ):
        assert client.get(url).status_code == 200, url


def test_an_inactive_viewer_is_not_special_cased(viewer):
    """Sign-in refuses an inactive account already; the middleware keys on active."""
    viewer.is_active = False
    viewer.save()
    from core.access import is_viewer

    assert is_viewer(viewer) is False


# -- The allowlist -----------------------------------------------------------------


def test_the_allowlist_is_exactly_this():
    assert VIEWER_ALLOWED_URL_NAMES == frozenset({"feedback:submit", "set_nav_mode", "profile"})
    assert VIEWER_ALLOWED_URL_NAME_PREFIX == "account_"
    assert viewer_may_post("account_logout") is True
    assert viewer_may_post("account_change_password") is True
    assert viewer_may_post("accounting:ledger_create") is False
    assert viewer_may_post("core:user_set_role") is False
    assert viewer_may_post("") is False


def test_a_viewer_can_sign_out(viewer):
    client = _client(viewer)
    response = client.post(reverse("account_logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_a_viewer_can_change_their_own_password(viewer):
    client = _client(viewer)
    response = client.post(
        reverse("account_change_password"),
        {
            "oldpassword": "a-good-passw0rd",
            "password1": "another-good-passw0rd",
            "password2": "another-good-passw0rd",
        },
    )
    assert response.status_code == 302
    viewer.refresh_from_db()
    assert viewer.check_password("another-good-passw0rd") is True


def test_a_viewer_can_edit_their_own_contact_details(viewer):
    response = _client(viewer).post(
        reverse("profile"),
        {"first_name": "Robin", "last_name": "Vale", "phone": "", "title": ""},
    )
    assert response.status_code == 302
    viewer.refresh_from_db()
    assert (viewer.first_name, viewer.last_name) == ("Robin", "Vale")


def test_a_viewer_reaches_the_feedback_intake(viewer):
    # The honeypot answer is the view's own ({"ok": true, "ref": null}) and
    # stores nothing, so it proves the request reached the view.
    response = _client(viewer).post(reverse("feedback:submit"), {"website": "x"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "ref": None}


def test_a_viewer_can_flip_the_sidebar(viewer):
    response = _client(viewer).get(reverse("set_nav_mode"), {"mode": "admin"})
    assert response.status_code == 302
    assert response.cookies["nav_mode"].value == "admin"


def test_the_template_flag_is_false_only_for_a_viewer(viewer, operator):
    url = reverse("accounting:dashboard")
    assert _client(viewer).get(url).context["user_can_write"] is False
    assert _client(operator).get(url).context["user_can_write"] is True
    assert Client().get(reverse("about")).context["user_can_write"] is True
