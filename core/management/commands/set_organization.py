# SPDX-License-Identifier: AGPL-3.0-or-later
"""Set the organization's name and the site's time zone from the command line.

Saves the ``SiteConfig`` row the admin's Site configs page edits, then runs
``apply_site_identity`` so the site's name follows without a ``migrate``.
"""
from zoneinfo import available_timezones

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError

from core.models import SiteConfig
from core.site_identity import apply_site_identity


class Command(BaseCommand):
    help = (
        "Set the organization's name and the site's time zone. Every email the "
        "site sends starts its subject line with the organization's name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            required=True,
            help="The organization's name.",
        )
        parser.add_argument(
            "--time-zone",
            dest="time_zone",
            default=None,
            help=(
                "The site's time zone, such as America/Denver. Leave the option "
                "out to keep the site's time zone. The time zone of a new site "
                "is America/Los_Angeles."
            ),
        )

    def handle(self, *args, **options):
        name = (options["name"] or "").strip()
        zone = options["time_zone"]

        if not name:
            raise CommandError("Give the organization's name after --name.")
        if zone is not None and zone not in available_timezones():
            raise CommandError(
                f"OpenH2O cannot use the time zone {zone}. "
                "Give a name such as America/Denver."
            )

        config = SiteConfig.objects.first()
        if config is None:
            config = SiteConfig(agency_name=name)
            if zone is not None:
                config.timezone = zone
        else:
            config.agency_name = name
            if zone is not None:
                config.timezone = zone
        config.save()

        apply_site_identity()
        Site.objects.clear_cache()
        site_name = Site.objects.get_current().name

        self.stdout.write(
            f"The organization's name is now {config.agency_name}. "
            f"The site's time zone is {config.timezone}. "
            f"Emails from this site start their subject line with {site_name}."
        )
