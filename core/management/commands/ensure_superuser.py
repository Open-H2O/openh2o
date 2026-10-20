# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make the site's first host administrator from the settings file, once.

This runs on every container start (wired into the Dockerfile CMD, right after
``migrate``). It acts only when the site has no active host administrator
(``is_staff`` and ``is_active``): then it reads ``DJANGO_SUPERUSER_EMAIL`` and
``DJANGO_SUPERUSER_PASSWORD`` and creates that account. When a host
administrator exists it touches nothing, and it never changes an existing
account's password.

Why: the settings file's password used to be put back at every start, so a
password changed on the site was undone, and a changed address in the file made
a second host administrator (S1/S2 rulings, 2026-10-20).

Why this exists at all: the database lives in the ``db_data`` Docker volume. A
normal rebuild leaves it alone, but ``make fresh`` runs ``docker compose down
-v``, which deletes that volume and the account with it, and the demonstration's
nightly reset restores a golden database with zero accounts. This command then
makes the host administrator again.
"""

import os

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the first host administrator from .env when the site has none."

    def handle(self, *args, **options):
        User = get_user_model()

        if User.objects.filter(is_staff=True, is_active=True).exists():
            self.stdout.write(
                "ensure_superuser: skipped. This site already has a host administrator."
            )
            return

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()
        if not email or not password:
            self.stdout.write(
                "ensure_superuser: skipped. .env does not set both "
                "DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD."
            )
            return

        if (
            User.objects.filter(email__iexact=email).exists()
            or EmailAddress.objects.filter(email__iexact=email).exists()
        ):
            self.stdout.write(
                f"ensure_superuser: skipped. {email} already has an account. "
                "Set DJANGO_SUPERUSER_EMAIL in .env to a different address."
            )
            return

        # The custom User model is an AbstractUser, so it still carries a unique
        # username field even though login is by email.
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip() or email
        user = User(
            username=username,
            email=email,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        user.set_password(password)
        user.save()

        # allauth signs in by its EmailAddress table: a verified, primary row.
        EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"ensure_superuser: created the host administrator {email}."
            )
        )
