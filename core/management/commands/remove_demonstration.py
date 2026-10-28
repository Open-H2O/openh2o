# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remove OpenH2O's demonstration data from this site.

Deletes every record the content tables hold and leaves the site as a clean
install: users, reference lists and the site settings stay, Demonstration mode
is turned off, and the site name is deleted only when it is the
demonstration's own. One transaction. Refuses when the demonstration is not
loaded.
"""

from django.core.management.base import BaseCommand

from core.management.commands.load_demonstration import run_command


class Command(BaseCommand):
    help = (
        "Remove the demonstration data from this site, leaving users, "
        "reference lists and the site settings."
    )

    def add_arguments(self, parser):
        parser.add_argument("--record", type=int, default=None,
                            help="The Site health record the Demonstration data page made for this run.")
        parser.add_argument("--user", type=int, default=None,
                            help="The person who pressed the button on the Demonstration data page.")

    def handle(self, *args, **options):
        run_command("remove", self, options)
