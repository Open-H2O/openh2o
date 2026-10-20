# SPDX-License-Identifier: AGPL-3.0-or-later
"""Change a person's email address from the server.

``python manage.py change_email <current address> <new address>``. It reuses
``UserEmailForm``, so the checks and the rewrite of ``User.email``, the
username and the one allauth ``EmailAddress`` row are the Users page's own.
The password is not touched. It is how the site's only host administrator
changes their address, since no one else can on the Users page.
"""

import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.forms import UserEmailForm


class Command(BaseCommand):
    help = "Change a person's email address."

    def add_arguments(self, parser):
        parser.add_argument("current_email")
        parser.add_argument("new_email")

    def handle(self, *args, **options):
        current = options["current_email"].strip()
        new = options["new_email"].strip()

        user = get_user_model().objects.filter(email__iexact=current).first()
        if user is None:
            self.stderr.write(
                f"change_email: {current} does not belong to any account."
            )
            sys.exit(1)

        form = UserEmailForm(data={"email": new}, target=user)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    self.stderr.write(f"change_email: {error}")
            sys.exit(1)

        old = user.email
        form.save()
        self.stdout.write(
            f"change_email: changed {old} to {user.email}. The password did not change."
        )
