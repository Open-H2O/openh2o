# SPDX-License-Identifier: AGPL-3.0-or-later
"""allauth account adapter wired to the access-control master switch (ISS-021).

``ACCESS_CONTROL_ENFORCED`` defaults to True (since Phase 41), so public
self-registration is CLOSED by default. With the switch on, this adapter closes
signup at allauth's own gate -- the signup view stops serving the form and
refuses to create accounts -- so no separate template surgery is needed. The
open demo is the deployment that turns the switch OFF; a real agency leaves it
alone.

``ACCOUNT_EMAIL_VERIFICATION`` is a real setting as of ISS-015 (closed
2026-08-04, Phase 109-01) rather than the hardcoded ``"none"`` it used to be.
Unset, it derives from ``EMAIL_HOST``: "mandatory" where a mail server is
configured, "none" where there is not one, so an install that cannot send mail
can never lock its operator out. It governs the open-signup posture -- when the
switch above is ON, this adapter refuses the signup before verification is ever
reached. See ``config/settings/base.py`` under "-- Signup email verification".
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
