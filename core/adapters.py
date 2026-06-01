# SPDX-License-Identifier: AGPL-3.0-or-later
"""allauth account adapter wired to the access-control master switch (ISS-021).

Public self-registration is open by default because the live demo wants it. At
go-live we flip ``ACCESS_CONTROL_ENFORCED`` to True and this adapter closes
signup at allauth's own gate -- the signup view stops serving the form and
refuses to create accounts -- so no separate template surgery is needed.

We leave ``ACCOUNT_EMAIL_VERIFICATION`` as-is: closing signup entirely
supersedes the missing-verification gap for this single-tenant tool. Re-enabling
verification for any future open-signup mode is tracked under ISS-015.
"""
from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings


class AccessControlledAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return not settings.ACCESS_CONTROL_ENFORCED
