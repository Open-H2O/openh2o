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


# allauth message templates we don't want surfaced. allauth pushes a Django
# message on every login/logout, but the app's base.html renders feedback via
# HTMX toasts and never drains the message framework -- so those piled up unseen
# for the life of the demo. The new Users page (templates/partials/_messages.html)
# is the first thing to render messages, which would otherwise dump that whole
# backlog of "Successfully signed in as ..." lines. Swallow them at the source so
# only deliberate action feedback (user added, admin granted, etc.) ever shows.
_SUPPRESSED_MESSAGES = {
    "account/messages/logged_in.txt",
    "account/messages/logged_out.txt",
}


class AccessControlledAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return not settings.ACCESS_CONTROL_ENFORCED

    def add_message(self, request, level, message_template=None, *args, **kwargs):
        if message_template in _SUPPRESSED_MESSAGES:
            return
        return super().add_message(
            request, level, message_template, *args, **kwargs
        )
