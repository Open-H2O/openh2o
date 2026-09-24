# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finalize and reopen for administrators only, with a required reopen note
(147-02 Task 3).

``accounting.views.period_finalize`` now sits behind ``@admin_required`` as
well as login, and reopening a finalized period requires a reason (10-500
characters) that lands on the period's change-history event via
``core.history.change_note``. Finalizing takes the same note, optional.

Every assertion here is an exact value: the response status, whether the row
changed, and the literal error text on the page, never a direction.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from accounting.models import ReportingPeriod
from core.access import READ_ONLY_MESSAGE
from core.history import LABEL_BEFORE_UPDATE
from tests.factories import ReportingPeriodFactory

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
def administrator():
    return _user("finalize-administrator", agency_admin=True)


@pytest.fixture
def operator():
    return _user("finalize-operator")


@pytest.fixture
def viewer():
    return _user("finalize-viewer", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _finalize_url(period):
    return reverse("accounting:period_finalize", args=[period.pk])


def _open_period(**kwargs):
    kwargs.setdefault("start_date", "2023-10-01")
    kwargs.setdefault("end_date", "2024-09-30")
    return ReportingPeriodFactory(**kwargs)


def _finalized_period(finalized_by=None, **kwargs):
    kwargs.setdefault("start_date", "2024-10-01")
    kwargs.setdefault("end_date", "2025-09-30")
    period = ReportingPeriodFactory(**kwargs)
    period.is_finalized = True
    from django.utils import timezone

    period.finalized_at = timezone.now()
    period.finalized_by = finalized_by
    period.save(update_fields=["is_finalized", "finalized_at", "finalized_by"])
    return period


# ---------------------------------------------------------------------------
# Administrator-only gate
# ---------------------------------------------------------------------------


def test_an_operators_post_is_refused_and_the_period_is_unchanged(operator):
    period = _open_period()

    response = _client(operator).post(_finalize_url(period), {"note": ""})

    # admin_required's non-admin branch: a redirect back to the dashboard,
    # never a 403 or a 500.
    assert response.status_code == 302
    assert response.url == reverse("accounting:dashboard")
    period.refresh_from_db()
    assert period.is_finalized is False


def test_a_viewer_is_refused_403_by_the_read_only_middleware(viewer):
    period = _open_period()

    response = _client(viewer).post(_finalize_url(period), {"note": ""})

    assert response.status_code == 403
    assert READ_ONLY_MESSAGE in response.content.decode()
    period.refresh_from_db()
    assert period.is_finalized is False


def test_access_control_off_still_lets_an_operator_finalize(operator):
    """Documented behaviour, pinned rather than changed (147-02 Task 3): with
    the switch off, ``admin_required`` is a pass-through for any signed-in
    user by design (the hosted demo's posture) -- period_finalize does not
    special-case that switch, so an operator finalizing here is the same
    "authenticated user" path the demo has always allowed, not a new hole.
    """
    period = _open_period()

    with override_settings(ACCESS_CONTROL_ENFORCED=False):
        response = _client(operator).post(_finalize_url(period), {"note": ""})

    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized is True


# ---------------------------------------------------------------------------
# Finalize: optional note
# ---------------------------------------------------------------------------


def test_an_administrator_finalizes_with_no_note(administrator):
    period = _open_period()

    response = _client(administrator).post(_finalize_url(period), {"note": ""})

    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized is True
    assert period.finalized_by_id == administrator.pk
    assert period.finalized_at is not None
    after = period.events.get(pgh_label="update")
    assert "note" not in after.pgh_context.metadata


def test_an_administrator_finalizes_with_a_note_and_it_lands_on_the_event(administrator):
    period = _open_period()

    response = _client(administrator).post(
        _finalize_url(period), {"note": "Board approved the water year close"}
    )

    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized is True
    after = period.events.get(pgh_label="update")
    assert after.pgh_context.metadata["note"] == "Board approved the water year close"


# ---------------------------------------------------------------------------
# Reopen: required note, 10-500 characters
# ---------------------------------------------------------------------------


def test_reopen_without_a_note_is_refused_with_the_form_error(administrator):
    period = _finalized_period()

    response = _client(administrator).post(_finalize_url(period), {"note": ""})

    assert response.status_code == 200
    assert (
        "Reopening a finalized period needs a reason, at least 10 characters."
        in response.content.decode()
    )
    period.refresh_from_db()
    assert period.is_finalized is True


def test_reopen_with_a_9_character_note_is_refused_with_the_form_error(administrator):
    period = _finalized_period()

    response = _client(administrator).post(
        _finalize_url(period), {"note": "x" * 9}
    )

    assert response.status_code == 200
    assert (
        "Reopening a finalized period needs a reason, at least 10 characters."
        in response.content.decode()
    )
    period.refresh_from_db()
    assert period.is_finalized is True


def test_reopen_with_a_501_character_note_is_refused_with_the_form_error(administrator):
    period = _finalized_period()

    response = _client(administrator).post(
        _finalize_url(period), {"note": "x" * 501}
    )

    assert response.status_code == 200
    assert (
        "Keep the reason to 500 characters or fewer."
        in response.content.decode()
    )
    period.refresh_from_db()
    assert period.is_finalized is True


def test_reopen_with_a_valid_note_succeeds_and_nulls_the_finalizer(administrator):
    earlier_finalizer = _user("finalize-earlier-administrator", agency_admin=True)
    period = _finalized_period(finalized_by=earlier_finalizer)

    response = _client(administrator).post(
        _finalize_url(period), {"note": "Late diversion record corrected"}
    )

    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized is False
    assert period.finalized_by_id is None
    assert period.finalized_at is None

    # 147-01's history keeps the earlier finalizer: the row as it WAS still
    # names them, even though the live field is now null. Latest by pgh_id,
    # not .get(), because the fixture's own setup save (finalizing the period
    # before the test's reopen) already recorded one before/update pair.
    before = (
        period.events.filter(pgh_label=LABEL_BEFORE_UPDATE)
        .order_by("-pgh_id")
        .first()
    )
    assert before.finalized_by == earlier_finalizer.pk

    after = period.events.filter(pgh_label="update").order_by("-pgh_id").first()
    assert after.pgh_context.metadata["note"] == "Late diversion record corrected"


# ---------------------------------------------------------------------------
# The period page's control
# ---------------------------------------------------------------------------


def test_the_period_page_shows_the_control_to_an_administrator_and_not_an_operator(
    administrator, operator
):
    period = _open_period()
    detail_url = reverse("accounting:period_detail", args=[period.pk])

    admin_response = _client(administrator).get(detail_url)
    assert admin_response.status_code == 200
    assert "Finalize period" in admin_response.content.decode()

    operator_response = _client(operator).get(detail_url)
    assert operator_response.status_code == 200
    assert "Finalize period" not in operator_response.content.decode()
