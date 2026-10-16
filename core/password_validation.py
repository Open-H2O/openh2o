# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django's password checks with OpenH2O's sentences.

Brent, 150.1-02 screen 17 message A row 9 (2026-10-16 06:15). The checks are
Django's own; only the sentence each one shows changes, on every page that
sets a password (Add user, change password, reset password, create account).
"""
from django.contrib.auth import password_validation as django_pv


class MinimumLengthValidator(django_pv.MinimumLengthValidator):
    def get_error_message(self):
        return f"The password must have at least {self.min_length} characters."


class CommonPasswordValidator(django_pv.CommonPasswordValidator):
    def get_error_message(self):
        return "The password is one of about 20,000 common passwords that OpenH2O refuses."


class NumericPasswordValidator(django_pv.NumericPasswordValidator):
    def get_error_message(self):
        return "The password cannot be only digits."
