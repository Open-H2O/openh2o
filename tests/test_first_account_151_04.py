# SPDX-License-Identifier: AGPL-3.0-or-later
"""151-04: the settings file makes the first host administrator once, and
``change_email`` moves an address from the server.

Addresses are fictional (example.com, example.org).
"""
import pytest
from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.contrib.auth import get_user_model

User = get_user_model()

EMAIL = "jane@example.com"
PASSWORD = "S3cret-pass-word!"

SKIP_HAVE = "ensure_superuser: skipped. This site already has a host administrator."
SKIP_ENV = (
    "ensure_superuser: skipped. .env does not set both "
    "DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD."
)


def _env(monkeypatch, email=EMAIL, password=PASSWORD):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", email)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", password)


def _run(capsys):
    call_command("ensure_superuser")
    return capsys.readouterr().out.strip()


def _person(email, password="a-good-passw0rd", **extra):
    user = User.objects.create_user(
        username=email, email=email, password=password, **extra
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def test_empty_database_gets_the_account(monkeypatch, capsys):
    _env(monkeypatch)
    out = _run(capsys)
    assert out == f"ensure_superuser: created the host administrator {EMAIL}."
    user = User.objects.get(email=EMAIL)
    assert user.is_staff and user.is_superuser and user.is_active
    assert user.check_password(PASSWORD)
    row = EmailAddress.objects.get(user=user)
    assert row.email == EMAIL and row.verified and row.primary


def test_changed_password_survives_a_second_run(monkeypatch, capsys):
    _env(monkeypatch)
    _run(capsys)
    user = User.objects.get(email=EMAIL)
    user.set_password("Changed-on-the-site-9!")
    user.save()
    out = _run(capsys)
    assert out == SKIP_HAVE
    user.refresh_from_db()
    assert user.check_password("Changed-on-the-site-9!")
    assert not user.check_password(PASSWORD)


def test_changed_env_address_makes_no_second_account(monkeypatch, capsys):
    _env(monkeypatch)
    _run(capsys)
    _env(monkeypatch, email="other@example.org")
    out = _run(capsys)
    assert out == SKIP_HAVE
    assert User.objects.count() == 1
    assert not User.objects.filter(email="other@example.org").exists()


@pytest.mark.parametrize("missing", ["DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD"])
def test_missing_lines_print_the_skip(monkeypatch, capsys, missing):
    _env(monkeypatch)
    monkeypatch.delenv(missing)
    assert _run(capsys) == SKIP_ENV
    assert User.objects.count() == 0


def test_address_on_file_is_left_alone(monkeypatch, capsys):
    person = _person(EMAIL, password="their-own-passw0rd")
    _env(monkeypatch, email=EMAIL.upper())
    out = _run(capsys)
    assert out == (
        f"ensure_superuser: skipped. {EMAIL.upper()} already has an account. "
        "Set DJANGO_SUPERUSER_EMAIL in .env to a different address."
    )
    person.refresh_from_db()
    assert person.check_password("their-own-passw0rd")
    assert not person.check_password(PASSWORD)
    assert not person.is_staff and not person.is_superuser
    assert User.objects.count() == 1


def test_address_only_in_the_allauth_table_counts_as_on_file(monkeypatch, capsys):
    holder = _person("holder@example.org")
    EmailAddress.objects.create(user=holder, email=EMAIL, verified=True)
    _env(monkeypatch)
    assert "already has an account" in _run(capsys)
    assert User.objects.count() == 1


def test_only_an_inactive_host_administrator_present_creates_the_new_one(monkeypatch, capsys):
    _person("gone@example.org", is_staff=True, is_superuser=True, is_active=False)
    _env(monkeypatch)
    out = _run(capsys)
    assert out == f"ensure_superuser: created the host administrator {EMAIL}."
    assert User.objects.get(email=EMAIL).is_staff


# -- change_email ------------------------------------------------------------


def test_change_email_moves_every_copy_and_keeps_the_password(capsys):
    user = _person(EMAIL, password="keep-this-passw0rd")
    call_command("change_email", EMAIL, "jane.doe@example.org")
    assert capsys.readouterr().out.strip() == (
        f"change_email: changed {EMAIL} to jane.doe@example.org. "
        "The password did not change."
    )
    user.refresh_from_db()
    assert user.email == "jane.doe@example.org"
    assert user.username == "jane.doe@example.org"
    assert user.check_password("keep-this-passw0rd")
    row = EmailAddress.objects.get(user=user)
    assert row.email == "jane.doe@example.org" and row.verified and row.primary


def test_change_email_finds_the_account_ignoring_case(capsys):
    user = _person(EMAIL)
    call_command("change_email", EMAIL.upper(), "new@example.org")
    user.refresh_from_db()
    assert user.email == "new@example.org"


def test_change_email_refuses_an_address_on_file(capsys):
    _person(EMAIL)
    _person("taken@example.org")
    with pytest.raises(SystemExit) as exc:
        call_command("change_email", EMAIL, "taken@example.org")
    assert exc.value.code != 0
    assert capsys.readouterr().err.strip() == (
        "change_email: The email address taken@example.org already belongs to an account."
    )
    assert User.objects.get(username=EMAIL).email == EMAIL


def test_change_email_unknown_address(capsys):
    with pytest.raises(SystemExit) as exc:
        call_command("change_email", EMAIL, "new@example.org")
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert captured.err.strip() == (
        f"change_email: {EMAIL} does not belong to any account."
    )
    assert captured.out == ""
