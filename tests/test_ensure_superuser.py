# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the ``ensure_superuser`` startup command.

This command runs on EVERY container boot (Dockerfile CMD, after migrate). Since
151-04 it makes the first host administrator once and then leaves the site
alone: a rebuild is a no-op while an active host administrator exists, so the
password is never put back and the session-auth hash never moves (an unchanged
hash was the earlier fix for admins being logged out after every rebuild). The
rule's own cases are in ``test_first_account_151_04.py``.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

EMAIL = "admin@example.com"
PASSWORD = "S3cret-pass-word!"


def _set_env(monkeypatch, email=EMAIL, password=PASSWORD):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", email)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", password)


@pytest.mark.django_db
class TestEnsureSuperuser:
    def test_creates_admin_when_missing(self, monkeypatch):
        _set_env(monkeypatch)
        call_command("ensure_superuser")

        User = get_user_model()
        u = User.objects.get(email=EMAIL)
        assert u.is_superuser and u.is_staff and u.is_active
        assert u.check_password(PASSWORD)

    def test_rerun_does_not_rotate_session_auth_hash(self, monkeypatch):
        """A second run must NOT move the session-auth hash, or every rebuild
        logs the admin out."""
        _set_env(monkeypatch)
        call_command("ensure_superuser")  # create

        User = get_user_model()
        hash_after_create = User.objects.get(email=EMAIL).get_session_auth_hash()

        call_command("ensure_superuser")  # the "every boot" re-run
        hash_after_rerun = User.objects.get(email=EMAIL).get_session_auth_hash()

        assert hash_after_rerun == hash_after_create

    def test_changed_env_password_does_not_override_the_site(self, monkeypatch):
        """Rewritten in 151-04 (was test_changed_password_does_update): a
        changed DJANGO_SUPERUSER_PASSWORD no longer takes effect once a host
        administrator exists."""
        _set_env(monkeypatch)
        call_command("ensure_superuser")

        _set_env(monkeypatch, password="A-different-pass-9!")
        call_command("ensure_superuser")

        User = get_user_model()
        u = User.objects.get(email=EMAIL)
        assert u.check_password(PASSWORD)
        assert not u.check_password("A-different-pass-9!")

    def test_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("DJANGO_SUPERUSER_EMAIL", raising=False)
        monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)
        call_command("ensure_superuser")

        User = get_user_model()
        assert not User.objects.filter(is_superuser=True).exists()
