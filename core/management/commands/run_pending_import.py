# SPDX-License-Identifier: AGPL-3.0-or-later
"""Commit one uploaded import file, in its own process.

    python manage.py run_pending_import --token 1c2d...

The Import button on a bulk import page starts this (core/pending_imports.py
``start_import``), the way the Calculate button starts ``run_accounting``: the
commit of a large file takes longer than a web request is allowed to. The only
argument is the upload's token, checked to be a UUID before anything else. The
command re-reads the stored file, writes through the page's own commit function
under the change-history context of the person who pressed Import, stores the
result block's context on the row, and deletes the file.
"""
import uuid

from django.core.management.base import BaseCommand, CommandError

from core import pending_imports


class Command(BaseCommand):
    help = "Commit one uploaded import file that is waiting, and store its result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--token",
            required=True,
            help="The token of the pending import (a UUID).",
        )

    def handle(self, *args, **options):
        try:
            token = uuid.UUID(options["token"])
        except ValueError:
            raise CommandError("--token must be a UUID, the token of a pending import.")
        pending_imports.run(str(token))
