# SPDX-License-Identifier: AGPL-3.0-or-later
"""Set the organization's name and the site's time zone from the command line.

Saves the ``SiteConfig`` row the admin's Site configs page edits, then runs
``apply_site_identity`` so the site's address follows without a ``migrate``.
The command also writes a given name onto the ``Site`` row, because its help
promises that every email starts with the organization's name, and
``apply_site_identity`` writes the name only over the ``example.com``
placeholder (a rename would otherwise never reach the emails).

``--name`` may be left out once the organization has a record, so the time
zone can be changed on its own.
"""
from zoneinfo import available_timezones

from django.conf import settings
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
            default=None,
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
        name = options["name"]
        zone = options["time_zone"]
        config = SiteConfig.objects.first()

        if name is not None:
            name = name.strip()
        if name == "" or (name is None and (config is None or zone is None)):
            raise CommandError("Give the organization's name after --name.")
        if zone is not None and zone not in available_timezones():
            raise CommandError(
                f"OpenH2O cannot use the time zone {zone}. "
                "Give a name such as America/Denver."
            )

        if config is None:
            config = SiteConfig(agency_name=name)
        elif name is not None:
            config.agency_name = name
        if zone is not None:
            config.timezone = zone
        config.save()

        apply_site_identity()
        if name is not None:
            # Site.name holds at most 50 characters.
            Site.objects.filter(pk=settings.SITE_ID).update(name=name[:50])
        Site.objects.clear_cache()
        site_name = Site.objects.get_current().name

        self.stdout.write(
            f"The organization's name is now {config.agency_name}. "
            f"The site's time zone is {config.timezone}. "
            f"Emails from this site start their subject line with {site_name}."
        )
