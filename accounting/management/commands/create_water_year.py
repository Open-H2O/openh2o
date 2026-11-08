# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create a water year from the command line.

The command and the Water Years page call one function,
``accounting.services.create_water_year``, so they check the name and dates by
the same rules and attach the same records.
"""
from django.core.management.base import BaseCommand, CommandError

from accounting.services import create_water_year, water_year_created_sentence


class Command(BaseCommand):
    help = (
        "Create a water year. The command checks the name and dates by the same "
        "rules as the Water Years page. The command attaches each diversion "
        "record and ledger entry dated inside the new water year to that year."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            required=True,
            help='The water year\'s name, such as "2024 Water Year".',
        )
        parser.add_argument(
            "--start",
            required=True,
            help=(
                "The water year's first day in the form YYYY-MM-DD. "
                "It must be the first day of a month."
            ),
        )
        parser.add_argument(
            "--end",
            required=True,
            help=(
                "The water year's last day in the form YYYY-MM-DD. "
                "It must be the last day of a month."
            ),
        )
        parser.add_argument(
            "--notes",
            default="",
            help="A note kept with the water year.",
        )

    def handle(self, *args, **options):
        period, counts, form = create_water_year(
            {
                "name": options["name"],
                "start_date": options["start"],
                "end_date": options["end"],
                "notes": options["notes"],
            }
        )
        if period is None:
            lines = ["OpenH2O did not create the water year."]
            for errors in form.errors.values():
                lines.extend(errors)
            raise CommandError("\n".join(lines))

        self.stdout.write(water_year_created_sentence(counts))
