"""Idempotently ensure an admin superuser exists, built from environment vars.

This runs on every container start (wired into the Dockerfile CMD, right after
``migrate``). It reads ``DJANGO_SUPERUSER_EMAIL`` and
``DJANGO_SUPERUSER_PASSWORD``; if either is missing it does nothing, so any
environment without those variables (local dev, CI) is left untouched.

Why this exists: the database lives in the ``db_data`` Docker volume. A normal
rebuild leaves it alone, but ``make fresh`` runs ``docker compose down -v``,
which deletes that volume and the entire database with it -- including the admin
account. Recreating it by hand every time is the bug behind "my login keeps
getting erased." With this command in the startup chain, the admin is restored
automatically from the saved email + password on the very next boot, even after
a full wipe.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the admin superuser from DJANGO_SUPERUSER_* env vars."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip() or email

        if not email or not password:
            self.stdout.write(
                "ensure_superuser: DJANGO_SUPERUSER_EMAIL / "
                "DJANGO_SUPERUSER_PASSWORD not set -- skipping."
            )
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username},
        )
        # The custom User model is an AbstractUser, so it still carries a unique
        # username field even though login is by email -- keep it populated.
        user.username = user.username or username or email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        # django-allauth authenticates by email via its EmailAddress table.
        # Guarantee a verified, primary row so the admin can log in by email
        # even when this user was just (re)created from scratch.
        try:
            from allauth.account.models import EmailAddress

            EmailAddress.objects.update_or_create(
                email=email,
                defaults={"user": user, "verified": True, "primary": True},
            )
        except Exception as exc:  # pragma: no cover - defensive, allauth optional
            self.stdout.write(
                self.style.WARNING(f"ensure_superuser: could not sync EmailAddress ({exc}).")
            )

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"ensure_superuser: {verb} admin {email}."))
