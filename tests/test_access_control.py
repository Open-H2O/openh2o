# SPDX-License-Identifier: AGPL-3.0-or-later
"""Switch-matrix tests for the two-tier access model (Phase 41-01, ISS-021).

These lock the contract that lets us ship the access machinery DARK and flip one
switch at go-live without a code change:

  - Switch OFF (default): the gate is a pass-through — any logged-in user reaches
    the Setup Wizard and the Methodology page, exactly as on the live demo today.
  - Switch ON: only an administrator (Django staff/superuser OR agency_admin)
    gets in; a plain operator is bounced; anonymous users go to login.

The two gated screens stand in for the whole class: Setup Wizard (setup:wizard,
guarded by @admin_required over @login_required) and Methodology
(accounting:methodology_settings, @login_required over @admin_required). Testing
both proves the decorator behaves the same regardless of stack order.

Pinned to config.settings.local via pyproject (prod settings 301-redirect the
test client). Runs in the web container (needs the DB + templates).
"""
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

User = get_user_model()

SETUP_URL = reverse("setup:wizard")
METHODOLOGY_URL = reverse("accounting:methodology_settings")
GATED_URLS = (SETUP_URL, METHODOLOGY_URL)


# --------------------------------------------------------------------------
# User factories (no UserFactory in tests/factories.py; build users directly,
# mirroring tests/test_methodology_settings.py)
# --------------------------------------------------------------------------


def _operator():
    """A plain logged-in user: not staff, not an agency admin."""
    return User.objects.create_user(
        username="operator", password="x", is_active=True,
        is_staff=False, agency_admin=False,
    )


def _agency_admin():
    """Elevated via agency_admin (the two-tier model's non-superuser admin)."""
    return User.objects.create_user(
        username="agencyadmin", password="x", is_active=True,
        is_staff=False, agency_admin=True,
    )


def _superuser():
    """Elevated via is_staff — the deployed superuser path (ensure_superuser)."""
    return User.objects.create_user(
        username="super", password="x", is_active=True,
        is_staff=True, is_superuser=True,
    )


def _client_for(user):
    c = Client()
    c.force_login(user)
    return c


# --------------------------------------------------------------------------
# User.is_administrator — the one rule
# --------------------------------------------------------------------------


def test_is_administrator_false_for_bare_user():
    assert _operator().is_administrator is False


def test_is_administrator_true_for_staff():
    assert _superuser().is_administrator is True


def test_is_administrator_true_for_agency_admin():
    assert _agency_admin().is_administrator is True


def test_is_administrator_false_for_inactive_staff():
    """Inactive trumps elevation — a disabled account is never an administrator."""
    u = User.objects.create_user(
        username="ghost", password="x", is_active=False, is_staff=True
    )
    assert u.is_administrator is False


# --------------------------------------------------------------------------
# Switch OFF (status quo): any logged-in user reaches both screens
# --------------------------------------------------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_switch_off_operator_reaches_both_screens():
    c = _client_for(_operator())
    for url in GATED_URLS:
        assert c.get(url).status_code == 200, f"operator blocked from {url} with switch OFF"


# --------------------------------------------------------------------------
# Switch ON: enforce the two-tier model
# --------------------------------------------------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_switch_on_operator_is_redirected_from_both():
    c = _client_for(_operator())
    for url in GATED_URLS:
        assert c.get(url).status_code == 302, f"operator NOT blocked from {url} with switch ON"


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_switch_on_agency_admin_reaches_both():
    c = _client_for(_agency_admin())
    for url in GATED_URLS:
        assert c.get(url).status_code == 200, f"agency_admin blocked from {url} with switch ON"


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_switch_on_superuser_reaches_both():
    c = _client_for(_superuser())
    for url in GATED_URLS:
        assert c.get(url).status_code == 200, f"superuser blocked from {url} with switch ON"


# --------------------------------------------------------------------------
# Anonymous: redirected to login regardless of the switch
# --------------------------------------------------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_anonymous_redirected_switch_off():
    c = Client()
    for url in GATED_URLS:
        assert c.get(url).status_code == 302, f"anonymous reached {url} (switch OFF)"


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_anonymous_redirected_switch_on():
    c = Client()
    for url in GATED_URLS:
        assert c.get(url).status_code == 302, f"anonymous reached {url} (switch ON)"
