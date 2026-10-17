# SPDX-License-Identifier: AGPL-3.0-or-later
"""allauth's password forms with OpenH2O's sentences (ISS-248).

The labels and blank-field sentences of Change password, and one sentence for
two new passwords that differ, on every page that sets a password. The checks are allauth's own; only the
words change. Wired through ``ACCOUNT_FORMS`` in config/settings/base.py.
"""
from allauth.account import forms as allauth_forms

# allauth's sentence, raised in two places with the same words.
_ALLAUTH_MISMATCH = "You must type the same password each time."
MISMATCH = "The two new passwords do not match."

BLANK_CURRENT = "Enter your current password."
BLANK_NEW = "Enter the new password."
BLANK_AGAIN = "Enter the new password again."


class _OneMismatchSentence:
    """Swap allauth's mismatch sentence for the approved one."""

    def clean(self):
        cleaned = super().clean()
        errors = self.errors.get("password2")
        if errors and _ALLAUTH_MISMATCH in errors:
            self.errors["password2"] = self.error_class(
                [MISMATCH if e == _ALLAUTH_MISMATCH else e for e in errors]
            )
        return cleaned


def _label(form, name, label, blank):
    field = form.fields[name]
    field.label = label
    field.error_messages["required"] = blank
    # The two password fields show allauth's placeholder ("New Password") and
    # Django's rules list as help; the page shows neither (message A row 7).
    field.widget.attrs.pop("placeholder", None)
    field.help_text = ""


class ChangePasswordForm(_OneMismatchSentence, allauth_forms.ChangePasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _label(self, "oldpassword", "Current password", BLANK_CURRENT)
        _label(self, "password1", "New password", BLANK_NEW)
        _label(self, "password2", "Confirm new password", BLANK_AGAIN)


class SetPasswordForm(_OneMismatchSentence, allauth_forms.SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _label(self, "password1", "New password", BLANK_NEW)
        _label(self, "password2", "Confirm new password", BLANK_AGAIN)


class ResetPasswordKeyForm(_OneMismatchSentence, allauth_forms.ResetPasswordKeyForm):
    pass


class SignupForm(_OneMismatchSentence, allauth_forms.SignupForm):
    pass
