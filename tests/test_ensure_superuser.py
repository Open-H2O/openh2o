# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the ``ensure_superuser`` startup command.

This command runs on EVERY container boot (Dockerfile CMD, after migrate). The
critical property: a normal rebuild must be a no-op for an unchanged admin
password. It previously called ``set_password`` unconditionally, which re-hashed
the same password with a fresh salt every boot, rotating the user's
``get_session_auth_hash()`` and silently logging the admin out after every prod
rebuild (Django ties session validity to that hash). These tests pin the fix.
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
        """The regression: a second run on an unchanged password must NOT move
        the session-auth hash — otherwise every rebuild logs the admin out."""
        _set_env(monkeypatch)
        call_command("ensure_superuser")  # create

        User = get_user_model()
        hash_after_create = User.objects.get(email=EMAIL).get_session_auth_hash()

        call_command("ensure_superuser")  # the "every boot" re-run
        hash_after_rerun = User.objects.get(email=EMAIL).get_session_auth_hash()

        assert hash_after_rerun == hash_after_create

    def test_changed_password_does_update(self, monkeypatch):
        """A genuinely changed DJANGO_SUPERUSER_PASSWORD still takes effect (and
        rotating the hash then is correct — a real password change ends old
        sessions)."""
        _set_env(monkeypatch)
        call_command("ensure_superuser")

        _set_env(monkeypatch, password="A-different-pass-9!")
        call_command("ensure_superuser")

        User = get_user_model()
        u = User.objects.get(email=EMAIL)
        assert u.check_password("A-different-pass-9!")
        assert not u.check_password(PASSWORD)

    def test_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("DJANGO_SUPERUSER_EMAIL", raising=False)
        monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)
        call_command("ensure_superuser")

        User = get_user_model()
        assert not User.objects.filter(is_superuser=True).exists()
