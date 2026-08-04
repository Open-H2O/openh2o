# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for signup email verification (Phase 109-01, ISS-015).

Until 2026-08-04 ``ACCOUNT_EMAIL_VERIFICATION`` was a hardcoded ``"none"`` in
config/settings/base.py with no environment variable behind it: nobody got
verification and no operator could turn it on without editing Python. These
tests lock the contract that replaced it.

What is being locked:

  1. The three values django-allauth understands are accepted, and an
     unrecognised one is refused at boot with a named error rather than
     silently falling back -- a silent fallback to "none" would read to the
     operator as "verification is on" while sending nothing at all.
  2. The DERIVATION. Unset, the value keys on EMAIL_HOST: "mandatory" where a
     mail server is configured, "none" where there is not one. That is the
     platform's core value -- where OpenH2O runs must not matter -- so an
     office computer with no mail server can never lock its own operator out.
  3. What a signup ACTUALLY does with verification on and no real mail server.
     docs/AI-OPERATOR-GUIDE.md carried an unmeasured claim that this 500s; the
     assertion below is the measurement, not a restatement.
  4. The interaction with ACCESS_CONTROL_ENFORCED: the adapter's gate
     supersedes verification entirely, so a future change to one cannot
     silently open the other.

Pinned to config.settings.local via pyproject (prod settings 301-redirect the
test client). Runs in the web container (needs the DB + templates).
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from django.urls import reverse

from config.settings.base import (
    ACCOUNT_EMAIL_VERIFICATION_CHOICES,
    resolve_email_verification,
)

User = get_user_model()

SIGNUP_URL = reverse("account_signup")

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"


def _signup_payload(email):
    """The three fields ACCOUNT_SIGNUP_FIELDS declares."""
    return {
        "email": email,
        "password1": "a-very-long-passphrase-42",
        "password2": "a-very-long-passphrase-42",
    }


# --------------------------------------------------------------------------
# The three legal values are accepted and land unchanged
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["none", "optional", "mandatory"])
def test_each_legal_value_is_accepted(value):
    """An explicit legal value passes through untouched, mail server or not."""
    assert resolve_email_verification(value, "smtp.postmarkapp.com") == value
    assert resolve_email_verification(value, "") == value


def test_legal_values_are_exactly_allauths_three():
    assert ACCOUNT_EMAIL_VERIFICATION_CHOICES == ("none", "optional", "mandatory")


def test_value_is_case_and_whitespace_tolerant():
    """Operators type into a .env by hand; 'Mandatory ' is not a misconfiguration."""
    assert resolve_email_verification(" Mandatory ", "") == "mandatory"


# --------------------------------------------------------------------------
# An illegal value fails closed and loud
# --------------------------------------------------------------------------


def test_illegal_value_raises_improperly_configured():
    with pytest.raises(ImproperlyConfigured) as excinfo:
        resolve_email_verification("yes-please", "smtp.postmarkapp.com")

    message = str(excinfo.value)
    assert "yes-please" in message, "the error must name the bad value"
    for legal in ACCOUNT_EMAIL_VERIFICATION_CHOICES:
        assert legal in message, f"the error must name the legal value {legal!r}"


def test_illegal_value_never_silently_falls_back():
    """The failure mode this guards: a bad value resolving to a working default.

    If the guard is ever deleted, this returns 'none' or 'mandatory' instead of
    raising, and the operator believes verification is on while nothing sends.
    """
    with pytest.raises(ImproperlyConfigured):
        resolve_email_verification("true", "")


# --------------------------------------------------------------------------
# The derivation (this is the chosen default: derived from EMAIL_HOST)
# --------------------------------------------------------------------------


def test_derives_mandatory_when_a_mail_server_is_configured():
    assert resolve_email_verification("", "smtp.postmarkapp.com") == "mandatory"


def test_derives_none_when_there_is_no_mail_server():
    """The single-office-computer case: never lock the operator out."""
    assert resolve_email_verification("", "") == "none"


def test_derivation_treats_whitespace_only_email_host_as_unconfigured():
    assert resolve_email_verification("", "   ") == "none"


def test_unset_is_none_and_empty_string_alike():
    assert resolve_email_verification(None, "") == "none"
    assert resolve_email_verification(None, "smtp.example.org") == "mandatory"


def test_explicit_value_beats_the_derivation_in_both_directions():
    """openh2o.com pins 'none' WITH mail configured; this is why that works."""
    assert resolve_email_verification("none", "smtp.postmarkapp.com") == "none"
    assert resolve_email_verification("mandatory", "") == "mandatory"


# --------------------------------------------------------------------------
# What a real signup does with verification on and no real mail server
#
# This is the measurement behind docs/AI-OPERATOR-GUIDE.md. Console backend
# (what an operator with no SMTP gets), signup open, verification mandatory.
# --------------------------------------------------------------------------


@override_settings(
    ACCESS_CONTROL_ENFORCED=False,
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
    EMAIL_BACKEND=CONSOLE_BACKEND,
    ACCOUNT_RATE_LIMITS={},
)
def test_mandatory_verification_with_console_backend_does_not_500():
    """MEASURED 2026-08-04: signup succeeds and redirects; it does NOT 500.

    The console email backend writes the confirmation to stdout instead of
    sending it, which is a successful send as far as Django is concerned. The
    operator guide's warning that this would 500 was written from the ISS-015
    era, when the backend was SMTP against an empty EMAIL_HOST -- a different
    configuration with a different failure. It does not describe this one.
    """
    response = Client().post(SIGNUP_URL, _signup_payload("verify-me@example.org"))

    assert response.status_code != 500, (
        f"signup 500'd with the console backend "
        f"(status {response.status_code}) -- the operator guide's warning holds"
    )
    assert response.status_code == 302
    assert User.objects.filter(email="verify-me@example.org").exists(), (
        "the account should be created; it is login that verification blocks"
    )


@override_settings(
    ACCESS_CONTROL_ENFORCED=False,
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_RATE_LIMITS={},
)
def test_mandatory_verification_actually_sends_a_confirmation():
    """Verification on means a confirmation message is genuinely emitted."""
    from django.core import mail

    mail.outbox = []
    Client().post(SIGNUP_URL, _signup_payload("confirm-me@example.org"))

    assert len(mail.outbox) == 1, (
        f"expected exactly one confirmation email, got {len(mail.outbox)}"
    )


@override_settings(
    ACCESS_CONTROL_ENFORCED=False,
    ACCOUNT_EMAIL_VERIFICATION="none",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_RATE_LIMITS={},
)
def test_verification_none_sends_nothing():
    """The contrast case: 'none' is genuinely silent, not merely unenforced."""
    from django.core import mail

    mail.outbox = []
    Client().post(SIGNUP_URL, _signup_payload("quiet@example.org"))

    assert mail.outbox == []


# --------------------------------------------------------------------------
# The interaction: the access-control gate supersedes verification
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verification", ["none", "optional", "mandatory"])
def test_signup_is_refused_when_access_control_is_enforced(verification):
    """The shipped gated default closes signup at allauth's own gate.

    Whatever verification is set to, no account is created -- so a future change
    to one switch cannot silently open the other.
    """
    with override_settings(
        ACCESS_CONTROL_ENFORCED=True,
        ACCOUNT_EMAIL_VERIFICATION=verification,
        EMAIL_BACKEND=CONSOLE_BACKEND,
        ACCOUNT_RATE_LIMITS={},
    ):
        email = f"blocked-{verification}@example.org"
        response = Client().post(SIGNUP_URL, _signup_payload(email))

        assert response.status_code != 500
        assert not User.objects.filter(email=email).exists(), (
            f"an account was created with the access gate ON "
            f"(verification={verification!r})"
        )
